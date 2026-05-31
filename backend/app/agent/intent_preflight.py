from __future__ import annotations

import re
from typing import Any

import aiosqlite

from app.db.database import DB_PATH

# 用户话里像「素材指代」的片段（产品名/主题），用于搜视频名
_QUERY_STOP = frozenset(
    "的了个和与及或把将给用选要做一个段条秒分钟口播方案成片剪辑视频素材库列表".split()
)

# 不宜当作文件名关键词的泛化词（抽象需求 ≠ 素材名）
_GENERIC_KEYWORDS = frozenset(
    [
        "电影",
        "影视",
        "影片",
        "视频",
        "素材",
        "剪辑",
        "口播",
        "成片",
        "方案",
        "推荐",
        "适合",
        "查找",
        "帮我",
        "找",
        "有哪些",
        "什么",
    ]
)

# 探索性/推荐类请求：交给 Agent ReAct 推理，不做规则预填
_EXPLORATORY_PATTERNS = (
    re.compile(r"(找|搜|推荐|适合|哪些|有没有|帮我).{0,8}(视频|素材|片子)"),
    re.compile(r"(视频|素材).{0,8}(推荐|适合|哪些|有没有)"),
    re.compile(r"^帮我.{0,12}(找|选|推荐)"),
)


def _is_exploratory_query(message: str) -> bool:
    """用户在做探索/推荐，而非指定具体素材名。"""
    text = (message or "").strip()
    if not text:
        return False
    if any(p.search(text) for p in _EXPLORATORY_PATTERNS):
        return True
    # 「适合做 X 剪辑」类：X 多为风格而非文件名
    if re.search(r"适合.{0,12}剪辑", text):
        return True
    return False


def _meaningful_remainder(term: str) -> str:
    t = term.strip()
    for g in sorted(_GENERIC_KEYWORDS, key=len, reverse=True):
        t = t.replace(g, "")
    return re.sub(r"[\s的了一个与及把将给用选要做]", "", t)


def _is_usable_keyword(term: str) -> bool:
    t = term.strip()
    if len(t) < 2:
        return False
    if t in _GENERIC_KEYWORDS:
        return False
    return len(_meaningful_remainder(t)) >= 2


def _extract_search_terms(message: str) -> list[str]:
    """从用户句子里抽出可能对应视频文件名的检索词。"""
    text = (message or "").strip()
    if not text or _is_exploratory_query(text):
        return []

    terms: list[str] = []

    # 「洁柔面巾纸的3个视频」→ 洁柔面巾纸
    m = re.search(r"([^\s，,。.!！?？]{2,30}?)的\s*\d*\s*个?\s*视频", text)
    if m:
        terms.append(m.group(1).strip())

    # 「选/用 XXX 视频」
    m2 = re.search(r"(?:选|用|选中|选择)\s*([^\s，,。.!！?？]{2,40}?)\s*(?:的)?\s*\d*\s*个?\s*视频", text)
    if m2:
        terms.append(m2.group(1).strip())

    # 去掉尾部「视频」
    cleaned = re.sub(r"\d+\s*个?\s*视频$", "", text).strip()
    cleaned = re.sub(r"视频$", "", cleaned).strip()
    if len(cleaned) >= 2 and cleaned not in terms:
        # 过滤纯指令句
        if not re.fullmatch(r"^(列出|列表|生成|制作|导出|开始).+", cleaned):
            noise = sum(1 for c in cleaned if c in "列出方案成片秒")
            if noise < len(cleaned) * 0.6:
                terms.append(cleaned)

    # 去重、去停用
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        t = t.strip("的 ")
        t = re.sub(r"^(?:选|用|选中|选择)\s*", "", t)
        if len(t) < 2 or t in seen or not _is_usable_keyword(t):
            continue
        seen.add(t)
        out.append(t)
    return out[:3]


def _extract_limit(message: str, default: int = 3) -> int:
    m = re.search(r"(\d+)\s*个?\s*视频", message)
    if m:
        return max(1, min(int(m.group(1)), 10))
    m2 = re.search(r"(\d+)\s*秒", message)
    if m2:
        return default
    return default


def _extract_duration_sec(message: str) -> int | None:
    m = re.search(r"(\d+)\s*秒", message)
    if m:
        return max(10, min(int(m.group(1)), 600))
    return None


async def search_videos_by_name(keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
    q = keyword.strip().lower()
    if not q:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, name, status, duration, total_clips
            FROM videos
            WHERE LOWER(name) LIKE ?
            ORDER BY upload_at DESC
            LIMIT ?
            """,
            (f"%{q}%", limit),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


def should_force_execute(message: str, *, selected_count: int) -> bool:
    """有明确剪辑意图时不应走 clarify 早退。"""
    msg = message or ""
    if selected_count > 0:
        return True
    signals = (
        "视频",
        "方案",
        "口播",
        "成片",
        "剪辑",
        "秒",
        "分钟",
        "素材",
        "洁柔",
        "选中",
        "选",
    )
    return any(s in msg for s in signals)


async def run_intent_preflight(
    message: str,
    *,
    selected_video_ids: list[str],
) -> dict[str, Any] | None:
    """
    规则层：根据用户话自动搜视频并生成 workspace_patch。
    返回 None 表示无需预填。
    """
    if _is_exploratory_query(message):
        return None

    patch: dict[str, Any] = {}
    terms = _extract_search_terms(message)
    if not terms:
        return None
    limit = _extract_limit(message, default=3)
    duration = _extract_duration_sec(message)

    prefs_patch: dict[str, Any] = {}
    if duration is not None:
        prefs_patch["target_duration_sec"] = duration
    if "口播" in message:
        prefs_patch.setdefault("content_style", "voiceover")

    matched: list[dict[str, Any]] = []
    for term in terms:
        rows = await search_videos_by_name(term, limit=limit)
        for r in rows:
            if r["id"] not in {x["id"] for x in matched}:
                matched.append(r)
        if len(matched) >= limit:
            break

    if matched and not selected_video_ids:
        ids = [str(r["id"]) for r in matched[:limit]]
        patch["selected_video_ids"] = ids
        patch["pipeline_phase"] = "ingest"
        names = "、".join(str(r["name"]) for r in matched[:limit])
        patch["_preflight_note"] = (
            f"已根据「{terms[0]}」自动选中 {len(ids)} 个视频：{names}"
        )

    if prefs_patch:
        patch["user_preferences"] = prefs_patch

    note: str | None = None
    if "_preflight_note" in patch:
        note = str(patch.pop("_preflight_note"))

    if not patch:
        return None
    out: dict[str, Any] = {"workspace_patch": patch}
    if note:
        out["note"] = note
    return out
