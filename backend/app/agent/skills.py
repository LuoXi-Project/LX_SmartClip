"""Agent 技能包（skills）：目录 + SKILL.md，渐进式披露注入执行器。

- 内置技能：app/agent/skills_builtin/<slug>/SKILL.md（随代码分发）
- 用户技能：<data>/skills/<slug>/SKILL.md（本地内容，不进 git；同 slug 覆盖内置）
- 启用状态：config 表 agent_skills_enabled（JSON 数组，存「启用清单」；
  缺省 = 内置技能全部启用，用户新建技能默认启用）

渐进式披露：系统提示只注入 name + description 清单（几十 token），
模型命中后调 load_skill 工具载入全文（正文限 4K 字符）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.db.database import get_db_conn

logger = logging.getLogger(__name__)

SKILL_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
ENABLED_CONFIG_KEY = "agent_skills_enabled"
BODY_CHAR_LIMIT = 4000
REFERENCES_CHAR_LIMIT = 2000

_BUILTIN_DIR = Path(__file__).parent / "skills_builtin"


def _user_skills_dir() -> Path:
    from app.utils.paths import get_data_dir

    d = Path(get_data_dir()) / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 `---` frontmatter（仅 key: value 行）与正文。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[0][3:].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip().lower()] = val.strip()
    body = parts[1].lstrip("\n") if len(parts) >= 2 else ""
    # split("\n---", 2) 会把正文里第一个 \n--- 之前的内容留在 parts[1]，正常够用
    return meta, body


def _load_skill_dir(slug: str) -> dict[str, Any] | None:
    """从内置/用户目录读取单个技能（用户目录优先）。"""
    for source, base in (("user", _user_skills_dir()), ("builtin", _BUILTIN_DIR)):
        path = base / slug / "SKILL.md"
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("读取技能失败: %s", path)
            return None
        meta, body = _parse_frontmatter(raw)
        refs = base / slug / "references.md"
        return {
            "slug": slug,
            "name": meta.get("name") or slug,
            "description": meta.get("description") or "",
            "source": source,
            "body_chars": len(body),
            "body": body,
            "has_references": refs.is_file(),
            "dir": str(base / slug),
        }
    return None


# ── 启用状态（config 表）───────────────────────────────────────────────────


async def _read_enabled_set() -> set[str] | None:
    """返回启用 slug 集合；None = 未配置（默认：内置全启用 + 用户全启用）。"""
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT value FROM config WHERE key = ?", (ENABLED_CONFIG_KEY,)
        )
        row = await cur.fetchone()
        if not row or not row["value"]:
            return None
        try:
            data = json.loads(row["value"])
            return {str(x) for x in data} if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None
    finally:
        await db.close()


async def _write_enabled_set(enabled: set[str]) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, type, label, options) "
            "VALUES (?, ?, 'json', 'Agent 技能启用清单', NULL)",
            (ENABLED_CONFIG_KEY, json.dumps(sorted(enabled), ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


# ── 对外能力 ───────────────────────────────────────────────────────────────


async def list_skills() -> list[dict[str, Any]]:
    """全部技能（内置 + 用户），附启用状态；不含正文。"""
    slugs: dict[str, str] = {}   # slug -> source（user 覆盖 builtin）
    for base, source in ((_user_skills_dir(), "user"), (_BUILTIN_DIR, "builtin")):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                slugs[child.name] = source
    enabled_cfg = await _read_enabled_set()
    items = []
    for slug, source in slugs.items():
        info = _load_skill_dir(slug)
        if not info:
            continue
        if enabled_cfg is None:
            enabled = True   # 缺省：全部启用
        else:
            enabled = slug in enabled_cfg
        items.append({
            "slug": slug,
            "name": info["name"],
            "description": info["description"],
            "source": source,
            "body_chars": info["body_chars"],
            "has_references": info["has_references"],
            "enabled": enabled,
        })
    items.sort(key=lambda x: (x["source"] != "builtin", x["slug"]))
    return items


async def get_enabled_skills() -> list[dict[str, Any]]:
    return [s for s in await list_skills() if s["enabled"]]


def load_skill_content(slug: str) -> str | None:
    """技能全文（正文 + 可选 references），供 load_skill 工具注入模型上下文。"""
    info = _load_skill_dir(slug)
    if not info:
        return None
    parts = [f"# 技能：{info['name']}（{slug}）\n\n{info['body']}"]
    refs = Path(info["dir"]) / "references.md"
    if refs.is_file():
        try:
            ref_text = refs.read_text(encoding="utf-8")[:REFERENCES_CHAR_LIMIT]
            parts.append(f"\n\n# 参考资料\n\n{ref_text}")
        except OSError:
            pass
    content = "\n".join(parts)
    if len(content) > BODY_CHAR_LIMIT + REFERENCES_CHAR_LIMIT:
        content = content[: BODY_CHAR_LIMIT + REFERENCES_CHAR_LIMIT] + "\n…（内容过长已截断）"
    return content


async def build_skill_catalog_prompt() -> str:
    """渐进式披露第一步：仅注入 name+description 清单（拼在 EXECUTOR_SYSTEM 后）。"""
    skills = await get_enabled_skills()
    if not skills:
        return ""
    lines = [
        "\n\n## 可用技能（当用户诉求命中某技能描述时，先调用 load_skill 加载全文，再按其指导执行）"
    ]
    for s in skills:
        desc = s["description"][:120]
        lines.append(f"- {s['slug']}：{s['name']}。{desc}" if desc else f"- {s['slug']}：{s['name']}")
    return "\n".join(lines) + "\n"


async def set_skill_enabled(slug: str, enabled: bool) -> bool:
    info = _load_skill_dir(slug)
    if not info:
        return False
    current = await _read_enabled_set()
    if current is None:
        # 缺省全启用：固化当前全量后增删
        all_slugs = {s["slug"] for s in await list_skills()}
        current = all_slugs
    if enabled:
        current.add(slug)
    else:
        current.discard(slug)
    await _write_enabled_set(current)
    return True


async def create_skill(
    *,
    name: str,
    description: str,
    body: str,
    slug: str | None = None,
    references: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """新建用户技能（slug 可省略：名称为 ASCII 时转 kebab，否则随机后缀）。

    references：可选参考资料正文（落 references.md）。
    enabled：False 时安装后停用（远端导入技能的防注入默认）。
    """
    slug = (slug or "").strip().lower().replace("_", "-")
    if not slug:
        ascii_name = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
        slug = ascii_name or f"skill-{__import__('uuid').uuid4().hex[:6]}"
    if not SKILL_SLUG_RE.match(slug):
        raise ValueError(
            "技能标识需为小写字母开头的 slug（字母/数字/-/_，2~64 位），如 douyin-ecommerce"
        )
    if (_BUILTIN_DIR / slug / "SKILL.md").is_file() and (_user_skills_dir() / slug / "SKILL.md").is_file():
        raise ValueError(f"技能 {slug} 已存在")
    if not name.strip():
        raise ValueError("技能名称不能为空")
    skill_dir = _user_skills_dir() / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name.strip()}\ndescription: {description.strip()}\n---\n\n"
    (skill_dir / "SKILL.md").write_text(front + body.strip() + "\n", encoding="utf-8")
    if references and references.strip():
        (skill_dir / "references.md").write_text(references.strip() + "\n", encoding="utf-8")
    # 启用清单：固化后按 enabled 增删新 slug（未配置时先固化为当前全量）
    current = await _read_enabled_set()
    if current is None:
        current = {s["slug"] for s in await list_skills()}
    if enabled:
        current.add(slug)
    else:
        current.discard(slug)
    await _write_enabled_set(current)
    return {"slug": slug, "name": name.strip()}


async def delete_skill(slug: str) -> bool:
    """删除用户技能（内置技能不可删）。"""
    import shutil

    target = _user_skills_dir() / slug
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    current = await _read_enabled_set()
    if current is not None:
        current.discard(slug)
        await _write_enabled_set(current)
    return True


# ── 从外部来源安装技能（URL / GitHub / 本地路径）────────────────────────────

SKILL_FETCH_TIMEOUT_SEC = 20
SKILL_SOURCE_CHAR_LIMIT = 200_000   # 单文件拉取体积上限（字符）
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GITHUB_PATH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")
GITHUB_BRANCHES = ("main", "master")


async def _fetch_remote_text(url: str, *, optional: bool = False) -> str | None:
    """拉取远端文本（限时 + 限体积）；optional=True 时 404 返回 None。"""
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=SKILL_FETCH_TIMEOUT_SEC, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            if optional and resp.status_code == 404:
                return None
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPStatusError as e:
        raise ValueError(f"拉取失败：HTTP {e.response.status_code} {url}") from e
    except httpx.HTTPError as e:
        raise ValueError(f"网络错误：{str(e)[:200]}（{url}）") from e
    if len(text) > SKILL_SOURCE_CHAR_LIMIT:
        raise ValueError(f"来源内容超过 {SKILL_SOURCE_CHAR_LIMIT} 字符上限：{url}")
    return text


def _split_skill_source(raw: str) -> tuple[dict[str, str], str]:
    """校验 SKILL.md：必须有 frontmatter name/description，返回 (meta, body)。"""
    meta, body = _parse_frontmatter(raw)
    if not meta.get("name") or not meta.get("description"):
        raise ValueError(
            "来源不是有效的技能文件：frontmatter 缺少 name / description（需要 `---\\nname: …\\ndescription: …\\n---` 格式）"
        )
    if not body.strip():
        raise ValueError("技能正文为空")
    return meta, body


async def install_skill_from_source(
    *,
    source_type: str,
    url: str = "",
    repo: str = "",
    path: str = "",
    local_path: str = "",
    slug: str | None = None,
    enable: bool | None = None,
) -> dict[str, Any]:
    """从 URL / GitHub / 本地路径安装技能到用户技能目录。

    - url：SKILL.md 的直链（raw 地址）
    - repo + path：GitHub 仓库与技能目录（或 SKILL.md 相对路径），自动尝试 main/master
    - local_path：本地技能目录（含 SKILL.md）或 SKILL.md 文件路径
    - enable 缺省：远端来源（url/github）停用待审，本地来源启用
    """
    from pathlib import Path as _Path

    references: str | None = None
    if source_type == "url":
        u = (url or "").strip()
        if not u.startswith(("http://", "https://")):
            raise ValueError("url 来源需要 http(s) 直链")
        raw = await _fetch_remote_text(u)
        assert raw is not None
        meta, body = _split_skill_source(raw)
        origin = u
    elif source_type == "github":
        r = (repo or "").strip().strip("/")
        if not GITHUB_REPO_RE.match(r):
            raise ValueError("repo 需为 owner/name 形式，如 anthropics/skills")
        p = (path or "").strip().strip("/")
        if not p or not _GITHUB_PATH_RE.match(p):
            raise ValueError("path 需为仓库内相对路径（仅字母/数字/._-/），如 skills/my-skill")
        skill_path = p if p.endswith(".md") else f"{p}/SKILL.md"
        refs_path = skill_path.rsplit("/", 1)[0] + "/references.md"
        raw = None
        hit_branch = ""
        last_err: ValueError | None = None
        for branch in GITHUB_BRANCHES:
            base = f"https://raw.githubusercontent.com/{r}/{branch}/"
            try:
                raw = await _fetch_remote_text(base + skill_path)
                if raw is not None:
                    hit_branch = branch
                    break
            except ValueError as e:
                last_err = e
        if raw is None:
            raise last_err or ValueError(f"GitHub 仓库 {r} 未找到 {skill_path}（main/master 均尝试）")
        # 参考资料拉取失败不影响安装（404/网络错误都跳过）
        try:
            references = await _fetch_remote_text(
                f"https://raw.githubusercontent.com/{r}/{hit_branch}/{refs_path}", optional=True
            )
        except ValueError:
            references = None
        if raw is None:
            raise last_err or ValueError(f"GitHub 仓库 {r} 未找到 {skill_path}（main/master 均尝试）")
        meta, body = _split_skill_source(raw)
        origin = f"github:{r}/{p}"
    elif source_type == "local":
        lp = (local_path or "").strip()
        p = _Path(lp)
        if not p.is_absolute():
            p = _Path.cwd() / p
        skill_file = p if p.is_file() else p / "SKILL.md"
        if not skill_file.is_file():
            raise ValueError(f"本地路径未找到 SKILL.md：{skill_file}")
        raw = skill_file.read_text(encoding="utf-8", errors="replace")
        if len(raw) > SKILL_SOURCE_CHAR_LIMIT:
            raise ValueError(f"本地文件超过 {SKILL_SOURCE_CHAR_LIMIT} 字符上限")
        meta, body = _split_skill_source(raw)
        refs_file = skill_file.parent / "references.md"
        if refs_file.is_file():
            references = refs_file.read_text(encoding="utf-8", errors="replace")[:SKILL_SOURCE_CHAR_LIMIT]
        origin = str(skill_file)
    else:
        raise ValueError("source_type 只支持 url / github / local")

    if enable is None:
        enable = source_type == "local"
    created = await create_skill(
        name=meta["name"],
        description=meta["description"],
        body=body,
        slug=slug,
        references=references,
        enabled=enable,
    )
    return {
        **created,
        "enabled": enable,
        "source_kind": "local" if source_type == "local" else "remote",
        "origin": origin,
        "has_references": bool(references),
        "body_chars": len(body),
    }
