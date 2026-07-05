"""发布文案智能生成（一键发布的「发布内容」AI 生成）。

策略：**ASR 优先 + VLM 兜底**，结果缓存到 renders 表。
1. 取成片记录（含 material_title / plan_json / asr_text / vlm_summary）。
2. ASR（缓存优先）：asr_text 为空则抽音频转写，写回 renders。
3. VLM（缓存优先 + 兜底）：仅当 ASR 文本过短（< 阈值）且 vlm_summary 为空时，
   等间隔抽 4-6 帧，调 VLM 描述，写回 renders。ASR 足够丰富则跳过 VLM（省钱）。
4. LLM：拼上下文（material_title + plan 快照 + asr_text + 可选 vlm_summary），
   按目标平台风格生成 {title, description, tags}。

复用：LLMClient + LLMConfig、OpenAIVLM、WhisperASR/OpenAIASR/BailianASR、
extract_audio_for_asr、ffmpeg 等间隔抽帧（仿 splitter.extract_frames）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Any

import aiosqlite

from app.core.asr.openai_asr import OpenAIASR
from app.core.asr.whisper_asr import WhisperASR
from app.core.llm import LLMClient, LLMConfig
from app.core.vlm.openai_vlm import OpenAIVLM
from app.db.database import DB_PATH
from app.utils.bin_paths import ffmpeg_bin
from app.utils.ffmpeg_utils import extract_audio_for_asr
from app.utils.paths import resolve_stored_path

from app.api import renders_db

logger = logging.getLogger(__name__)

# ASR 文本短于此字数则触发 VLM 兜底（中文字符数）
_ASR_MIN_CHARS = 30
# VLM 兜底抽帧数
_VLM_FRAME_COUNT = 5
# VLM 单帧长边像素（控制 token）
_VLM_FRAME_TARGET_PX = 768

# ── 平台风格 + 硬约束 ─────────────────────────────────────────────────────
# 各平台字数上限（综合平台规则与创作者经验，标题/描述以"汉字数"近似计，英文平台以"字符数"计）。
# tags 限制：国内平台普遍 10 个以内、每个 ≤ 30 字符；海外平台 hashtag 数量略多。
# 注：平台规则会更新，这些是生成时的「硬上限」，避免 LLM 超长被截断；可在前端提示用户复核。
#
# 字段：title_max / desc_max / tags_max / tags_each_max / lang（默认输出语言）/ style（调性）
_PLATFORM_SPECS: dict[str, dict] = {
    "douyin": {
        "lang": "zh-CN",
        "title_max": 55, "desc_max": 500, "tags_max": 8, "tags_each_max": 20,
        "style": (
            "抖音风格：标题口语化、有悬念或情绪钩子（手机端通常只显示前 1-2 行，前 15 字最关键）；"
            "描述简短带 1-2 行正文，结尾引导互动（如「你怎么看？」）；"
            "标签覆盖大词 + 长尾词，含 1-2 个泛流量 tag。"
        ),
    },
    "xhs": {
        "lang": "zh-CN",
        "title_max": 20, "desc_max": 1000, "tags_max": 10, "tags_each_max": 20,
        "style": (
            "小红书风格：标题带 1-2 个 emoji、种草/分享口吻；"
            "描述分段、要点清晰、语气亲切、适当 emoji，结尾可带话题引导；"
            "标签偏生活化/细分场景词。"
        ),
    },
    "bilibili": {
        "lang": "zh-CN",
        "title_max": 80, "desc_max": 2000, "tags_max": 10, "tags_each_max": 30,
        "style": (
            "B 站风格：标题信息量足、可适度玩梗；"
            "描述可稍长、交代内容亮点或分 P 简介；"
            "标签偏内容主题与品类。"
        ),
    },
    "wxchannels": {
        "lang": "zh-CN",
        "title_max": 1000, "desc_max": 1000, "tags_max": 6, "tags_each_max": 20,
        "style": (
            "视频号风格：标题/文案简洁、正能量/生活化；"
            "描述平实自然、可带轻微引导关注；"
            "标签偏大众话题。"
        ),
    },
    "kuaishou": {
        "lang": "zh-CN",
        "title_max": 100, "desc_max": 500, "tags_max": 8, "tags_each_max": 20,
        "style": (
            "快手风格：标题接地气、口语化；"
            "描述简短直接；标签偏生活/接地气词。"
        ),
    },
    "tiktok": {
        "lang": "en",
        "title_max": 150, "desc_max": 4000, "tags_max": 6, "tags_each_max": 30,
        "style": (
            "TikTok 风格：标题英文、短促有钩子；描述精简；"
            "标签用英文 trending tag。如成片内容明显是中文，可中英混排。"
        ),
    },
    "youtube": {
        "lang": "en",
        "title_max": 100, "desc_max": 5000, "tags_max": 15, "tags_each_max": 30,
        "style": (
            "YouTube 风格：标题英文、信息量足、SEO 友好（搜索结果只显示约前 60-70 字符，关键词前置）；"
            "描述可详尽，含简介 + 关键时间点 + 关键词；"
            "标签英文，覆盖核心搜索词。"
        ),
    },
}

DEFAULT_SPEC: dict = {
    "lang": "zh-CN",
    "title_max": 55, "desc_max": 500, "tags_max": 8, "tags_each_max": 20,
    "style": "通用风格：标题精炼抓眼球；描述简明扼要点出内容价值；标签覆盖核心主题。",
}


def get_platform_spec(platform: str) -> dict:
    """获取平台规格（字数硬上限 + 默认语言 + 风格调性）。未知平台用 DEFAULT_SPEC。"""
    return _PLATFORM_SPECS.get(platform, DEFAULT_SPEC)


def _char_len(s: str, lang: str) -> int:
    """按平台语言估字数：中文按汉字数（近似），英文按字符数。"""
    if not s:
        return 0
    if lang.startswith("en"):
        return len(s)
    # 中文：去掉空白后按字符数计（汉字=1，标点=1）
    return len(re.sub(r"\s+", "", s))


def _trim_to_limit(s: str, limit: int, lang: str) -> tuple[str, bool]:
    """按字数上限截断字符串。返回 (截断后文本, 是否触发截断)。

    中文按汉字数计（去空白后），英文按字符数计。截断时尽量保留完整结尾（不补省略号以免再超长）。
    """
    if not s:
        return s, False
    if lang.startswith("en"):
        if len(s) <= limit:
            return s, False
        return s[:limit].rstrip(), True
    # 中文：按"非空白字符数"截断
    result_chars: list[str] = []
    count = 0
    for ch in s:
        if not ch.isspace():
            count += 1
            if count > limit:
                break
        result_chars.append(ch)
    out = "".join(result_chars).rstrip()
    return out, (_char_len(s, lang) > limit)


def _trim_tags(tags: list[str], each_max: int) -> tuple[list[str], bool]:
    """截断每个 tag 的长度（去掉 # 前缀）。返回 (处理后的 tags, 是否触发截断)。"""
    trimmed_any = False
    out: list[str] = []
    for t in tags:
        t = t.lstrip("#").strip()
        if len(t) > each_max:
            t = t[:each_max].rstrip()
            trimmed_any = True
        if t:
            out.append(t)
    return out, trimmed_any

_SYSTEM_PROMPT = (
    "你是一位资深的短视频运营，擅长根据视频内容为不同平台撰写高传播度的标题、描述和标签。\n"
    "严格基于提供的视频上下文（原素材标题、生成方案、ASR 台词、画面描述）生成，"
    "禁止编造视频中不存在的内容；可用概括性语言提炼，但不得与内容明显冲突。\n\n"
    "默认输出语言遵循「目标平台」的语言设定（中文平台用简体中文，海外平台用英文），"
    "除非用户在「额外要求」中明确指定其他语言。\n\n"
    "⚠️ 重要：ASR 台词由语音识别自动生成，常有错误，你必须在理解和复用时先做纠错：\n"
    "  - 繁体字误识别 → 转为对应简体规范用字（如「潔柔」→「洁柔」、「臺灣」→「台湾」）；\n"
    "  - 品牌/产品/人名/专有名词 → 修正为正确写法（如「洁肉/洁揉」→「洁柔」、「可口可樂」→「可口可乐」）；\n"
    "  - 明显的同音/形近/口音错字 → 按上下文还原（如「纸巾」被识别成「只斤」）；\n"
    "  - 不确定专名时，倾向与「原素材标题/方案」中的写法保持一致。\n"
    "纠错只用于你生成的标题/描述/标签，不要输出纠正后的台词原文。\n\n"
    "⚠️ 字数硬约束：必须严格遵守「目标平台」给出的 title/description/tags 字数上限与数量上限，"
    "超长会被平台截断或拒收。标签不要带 # 前缀。\n\n"
    "用户的「额外要求」优先级最高，可覆盖默认风格/语言/用词，但不得突破字数硬约束。\n\n"
    "必须返回严格的 JSON，字段：title (字符串)、description (字符串)、tags (字符串数组)。\n"
    "不要输出任何多余文字、不要用 markdown 代码块包裹。"
)


# ── 配置读取 ─────────────────────────────────────────────────────────────
async def _read_config(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as c:
        row = await c.fetchone()
    return row[0] if row else default


# ── ASR ─────────────────────────────────────────────────────────────────
def _build_asr(provider: str, *, model_size: str, base_url: str, api_key: str,
               model: str, language: str):
    """按 provider 构造 ASR 实例（与 api/asr.py 的 get_asr 等价，但每次新建避免缓存干扰）。"""
    if provider == "openai":
        return OpenAIASR(base_url=base_url, api_key=api_key, model=model, language=language)
    if provider == "bailian":
        from app.core.asr.bailian_asr import BailianASR
        return BailianASR(base_url=base_url, api_key=api_key, model=model, language=language)
    return WhisperASR(model_size=model_size, language=language or None)


async def _ensure_asr(video_abs: str, cached: str | None, cfg: dict) -> tuple[str | None, bool, str | None]:
    """转写成片音频。返回 (text, ok, error)。

    缓存命中直接返回；否则抽音频 → 转写。失败返回 (None, False, err)。
    """
    if cached and cached.strip():
        return cached.strip(), True, None
    if not cfg.get("asr_ready"):
        return None, False, "ASR 未配置（缺 provider/key）"
    audio_out = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            audio_out = tf.name
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: extract_audio_for_asr(video_abs, audio_out, overwrite=True,
                                          sample_rate=16000, channels=1),
        )
        asr = _build_asr(
            cfg["asr_provider"], model_size=cfg["asr_model_size"],
            base_url=cfg["asr_base_url"], api_key=cfg["asr_api_key"],
            model=cfg["asr_model"], language=cfg["asr_language"],
        )
        tr = await loop.run_in_executor(None, asr.transcribe_detailed, audio_out)
        return (tr.text or "").strip(), True, None
    except Exception as e:
        logger.warning("成片 ASR 失败: %s", e)
        return None, False, str(e)
    finally:
        if audio_out and os.path.isfile(audio_out):
            try:
                os.remove(audio_out)
            except Exception:
                pass


# ── VLM（抽帧 + 描述） ─────────────────────────────────────────────────
def _extract_frames_evenly(video_abs: str, n_frames: int, target_px: int, out_dir: str) -> list[str]:
    """等间隔抽 n_frames 帧（仿 splitter.extract_frames 的 ffmpeg 命令）。返回帧路径列表。"""
    from app.utils.ffprobe_utils import probe_duration
    duration = probe_duration(video_abs)
    if duration <= 0:
        return []
    n = max(1, int(n_frames))
    interval = duration / (n + 1)
    paths: list[str] = []
    for i in range(n):
        ts = (i + 1) * interval
        out_path = os.path.join(out_dir, f"frame_{i:03d}.jpg")
        cmd = [ffmpeg_bin(), "-ss", f"{ts:.2f}", "-i", video_abs,
               "-map", "0:v:0", "-vframes", "1", "-q:v", "3"]
        if target_px and target_px > 0:
            p = target_px
            vf = (f"scale='if(gt(iw,ih),min({p},iw),trunc(oh*a/2)*2)':"
                  f"'if(gt(iw,ih),trunc(ow*a/2)*2,min({p},ih))':flags=lanczos")
            cmd += ["-vf", vf]
        cmd += ["-y", out_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            if os.path.isfile(out_path):
                paths.append(out_path)
        except Exception as e:
            logger.debug("抽帧失败 ts=%.2f: %s", ts, e)
    return paths


async def _ensure_vlm(video_abs: str, cached: str | None, cfg: dict) -> tuple[str | None, bool, str | None]:
    """VLM 描述成片画面。返回 (summary, ok, error)。缓存命中直接返回。"""
    if cached and cached.strip():
        return cached.strip(), True, None
    if not cfg.get("vlm_ready"):
        return None, False, "VLM 未配置（缺 base_url/model/key）"
    # 先确认成片有视频流
    try:
        from app.utils.ffprobe_utils import probe_video_dimensions
        probe_video_dimensions(video_abs)
    except Exception:
        return None, False, "成片无视频流，跳过 VLM"
    tmp_dir = tempfile.mkdtemp(prefix="render_vlm_")
    frame_paths: list[str] = []
    try:
        loop = asyncio.get_running_loop()
        frame_paths = await loop.run_in_executor(
            None, _extract_frames_evenly,
            video_abs, _VLM_FRAME_COUNT, _VLM_FRAME_TARGET_PX, tmp_dir,
        )
        if not frame_paths:
            return None, False, "抽帧失败"
        vlm = OpenAIVLM(base_url=cfg["vlm_base_url"], model=cfg["vlm_model"],
                        api_key=cfg["vlm_api_key"])
        # 复用既有 generate_description，得到结构化画面描述（含时间线）
        desc = await loop.run_in_executor(
            None, lambda: vlm.generate_description(frame_paths)
        )
        return (desc or "").strip(), True, None
    except Exception as e:
        logger.warning("成片 VLM 失败: %s", e)
        return None, False, str(e)
    finally:
        for p in frame_paths:
            try:
                os.remove(p)
            except Exception:
                pass
        try:
            os.rmdir(tmp_dir)
        except Exception:
            pass


# ── LLM 生成文案 ───────────────────────────────────────────────────────
def _build_context(material_title: str | None, plan_snapshot: dict | None,
                   asr_text: str | None, vlm_summary: str | None) -> str:
    parts: list[str] = []
    if material_title:
        parts.append(f"【原素材标题】{material_title}")
    if plan_snapshot:
        # 平铺关键方案字段
        keys = ("mode", "style", "audio_mode", "target_duration", "duration",
                "user_prompt", "tone", "voice", "script_text", "sentences", "storyline",
                "script_segments", "script_lines")
        kv = []
        for k in keys:
            v = plan_snapshot.get(k)
            if v in (None, "", [], {}):
                continue
            if isinstance(v, list):
                v = "；".join(str(x) for x in v)
            kv.append(f"{k}: {v}")
        if kv:
            parts.append("【生成方案】" + " | ".join(kv))
    if asr_text:
        # 显式提示 LLM：这是 ASR 识别结果，可能含繁简/同音/专名错字，需在复用时纠错
        # 若有 material_title，作为专名纠错的权威锚点
        anchor = f"（专名写法请以「{material_title}」为准）" if material_title else "（可能含繁体/同音/专名错字，需纠错后再用）"
        parts.append(f"【ASR 台词·自动识别{anchor}】{asr_text[:3000]}")
    if vlm_summary:
        parts.append(f"【画面描述】{vlm_summary[:3000]}")
    return "\n".join(parts) if parts else "（无可用上下文，请基于通用短视频运营经验生成）"


def _parse_copy_json(raw: str) -> dict:
    """从 LLM 返回里解析 {title, description, tags}，兼容代码块包裹与 <think>。"""
    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw or "", flags=re.IGNORECASE).strip()
    if "```" in raw:
        segs = raw.split("```")
        raw = segs[1] if len(segs) > 1 else segs[0]
        if raw.lstrip().lower().startswith("json"):
            raw = raw.lstrip()[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            obj = json.loads(repair_json(raw))
        except Exception as e:
            raise ValueError(f"无法解析 LLM 输出为 JSON: {e}")
    title = str(obj.get("title") or "").strip()
    desc = str(obj.get("description") or "").strip()
    tags = obj.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,，\s]+", tags) if t.strip()]
    elif isinstance(tags, list):
        tags = [str(t).strip().lstrip("#") for t in tags if str(t).strip()]
    else:
        tags = []
    return {"title": title, "description": desc, "tags": tags}


async def _llm_generate(context: str, platform: str, spec: dict, user_prompt: str | None,
                        cfg: dict) -> dict:
    style_hint = spec["style"]
    lang = spec["lang"]
    # 字数硬约束（写入 prompt，强制 LLM 遵守；并在生成后由 _trim_to_limit 兜底截断）
    limit_block = (
        f"字数硬约束（不得突破）："
        f"title ≤ {spec['title_max']}（{'字符' if lang.startswith('en') else '字'}）；"
        f"description ≤ {spec['desc_max']}；"
        f"tags 最多 {spec['tags_max']} 个，每个 ≤ {spec['tags_each_max']} 字符且不带 #。"
    )
    lang_block = f"默认语言：{lang}（中文平台用简体中文，英文平台用英文）。"
    extra_line = (
        f"\n【额外要求（用户输入，优先级最高，可覆盖默认风格/语言/用词，但不得突破字数硬约束）】{user_prompt.strip()}"
        if user_prompt and user_prompt.strip() else ""
    )
    user_msg = (
        f"目标平台：{platform}\n"
        f"{lang_block}\n"
        f"风格要求：{style_hint}\n"
        f"{limit_block}{extra_line}\n\n"
        f"视频上下文：\n{context}\n\n"
        "请生成适合该平台的标题、描述和标签，严格输出 JSON："
        '{"title":"...","description":"...","tags":["..."]}'
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    llm = LLMClient(
        base_url=cfg["llm_base_url"], api_key=cfg["llm_api_key"], model=cfg["llm_model"],
        temperature=0.85, max_tokens=1500, timeout=120,
    )
    content = await llm.chat(messages)
    return _parse_copy_json(content)


# ── 主入口 ─────────────────────────────────────────────────────────────
async def generate_publish_copy(
    render_id: str,
    platform: str = "douyin",
    user_prompt: str | None = None,
    tone: str | None = None,
) -> dict:
    """为指定成片生成发布文案。

    Args:
        user_prompt: 用户自定义提示词（语言/特定指引/修正/特定要求等），优先级最高，覆盖默认风格。
        tone: 兼容旧参数；若同时传入，拼接到 user_prompt 之后。
    Returns:
        {title, description, tags, source: {asr, vlm, plan, material_title}, cached: {asr, vlm}}
    失败时 raise ValueError（配置缺失）或 RuntimeError（生成失败）。
    """
    rec = await renders_db.get_render(render_id)
    if not rec:
        raise ValueError("成片不存在")
    try:
        video_abs = resolve_stored_path(rec["file_path"])
    except Exception as e:
        raise ValueError(f"成片文件路径无法解析: {e}")
    if not os.path.isfile(video_abs):
        raise ValueError("成片文件不存在")

    # 读全部配置（ASR / VLM / LLM）
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        asr_provider = await _read_config(db, "asr_provider", "whisper")
        asr_model_size = await _read_config(db, "asr_model", "small")
        asr_base_url = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key = await _read_config(db, "asr_api_key", "")
        asr_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language = (await _read_config(db, "asr_language", "zh") or "").strip()
        vlm_base_url = await _read_config(db, "vlm_base_url", "https://api.openai.com/v1")
        vlm_model = await _read_config(db, "vlm_model", "gpt-4o")
        vlm_api_key = await _read_config(db, "vlm_api_key", "")
        llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)

    asr_ready = bool(
        (asr_provider == "whisper") or (asr_api_key and asr_model)
    )
    vlm_ready = bool(vlm_base_url and vlm_model and vlm_api_key)

    cfg = {
        "asr_ready": asr_ready, "asr_provider": asr_provider,
        "asr_model_size": asr_model_size, "asr_base_url": asr_base_url,
        "asr_api_key": asr_api_key, "asr_model": asr_model, "asr_language": asr_language,
        "vlm_ready": vlm_ready, "vlm_base_url": vlm_base_url,
        "vlm_model": vlm_model, "vlm_api_key": vlm_api_key,
        "llm_base_url": llm_cfg["base_url"], "llm_api_key": llm_cfg["api_key"],
        "llm_model": llm_cfg["model"],
    }

    material_title = rec.get("material_title")
    plan_snapshot: dict | None = None
    if rec.get("plan_json"):
        try:
            plan_snapshot = json.loads(rec["plan_json"])
        except Exception:
            plan_snapshot = None

    cached_asr = (rec.get("asr_text") or "").strip()
    cached_vlm = (rec.get("vlm_summary") or "").strip()

    # 1) ASR（缓存优先）
    asr_text, asr_ok, asr_err = await _ensure_asr(video_abs, cached_asr, cfg)
    used_asr = asr_ok and bool(asr_text)
    asr_cached = bool(cached_asr) and asr_ok
    if used_asr and asr_text != cached_asr:
        await renders_db.update_ai_context(render_id, asr_text=asr_text)

    # 2) VLM 兜底：仅当 ASR 不足时
    used_vlm = False
    vlm_cached = False
    vlm_text: str | None = None
    asr_too_short = (not used_asr) or (len(asr_text or "") < _ASR_MIN_CHARS)
    if asr_too_short:
        vlm_text, vlm_ok, _vlm_err = await _ensure_vlm(video_abs, cached_vlm, cfg)
        used_vlm = vlm_ok and bool(vlm_text)
        vlm_cached = bool(cached_vlm) and vlm_ok
        if used_vlm and vlm_text != cached_vlm:
            await renders_db.update_ai_context(render_id, vlm_summary=vlm_text)

    # 3) LLM 生成（合并 user_prompt + 兼容旧 tone）
    context = _build_context(material_title, plan_snapshot, asr_text, vlm_text)
    merged_prompt = (user_prompt or "").strip()
    if tone:
        merged_prompt = (merged_prompt + ("\n" if merged_prompt else "") + f"语气：{tone.strip()}").strip()
    spec = get_platform_spec(platform)
    try:
        copy = await _llm_generate(context, platform, spec, merged_prompt or None, cfg)
    except Exception as e:
        logger.error("发布文案 LLM 生成失败: %s", e)
        raise RuntimeError(f"LLM 生成失败: {e}")

    # 3.5) 字数硬兜底：LLM 偶尔会超长，按 spec 截断（记录是否触发）
    title, title_truncated = _trim_to_limit(copy["title"], spec["title_max"], spec["lang"])
    desc, desc_truncated = _trim_to_limit(copy["description"], spec["desc_max"], spec["lang"])
    tags = [t for t in copy["tags"]][:spec["tags_max"]]
    tags_truncated = len(copy["tags"]) > len(tags)
    tags, tags_each_truncated = _trim_tags(tags, spec["tags_each_max"])

    lang = spec["lang"]
    return {
        "title": title,
        "description": desc,
        "tags": tags,
        "source": {
            "material_title": bool(material_title),
            "plan": bool(plan_snapshot),
            "asr": used_asr,
            "vlm": used_vlm,
            "asr_note": (asr_err or None) if not used_asr else None,
        },
        "cached": {"asr": asr_cached, "vlm": vlm_cached},
        # 平台字数硬约束（供前端展示「x/上限」+ 用户复核）
        "limits": {
            "title_max": spec["title_max"],
            "desc_max": spec["desc_max"],
            "tags_max": spec["tags_max"],
            "lang": lang,
        },
        # 实际字数 + 是否触发兜底截断
        "lengths": {
            "title": _char_len(title, lang),
            "description": _char_len(desc, lang),
            "tags": len(tags),
        },
        "trimmed": title_truncated or desc_truncated or tags_truncated or tags_each_truncated,
    }
