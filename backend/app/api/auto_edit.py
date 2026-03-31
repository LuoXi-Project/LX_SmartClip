"""auto_edit.py — 自动一键成片 · Plan 规划接口

Phase 1：仅生成结构化 Plan，不负责实际成片渲染。
"""
from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.db.database import DB_PATH
from app.core.llm import LLMClient, LLMConfig
from app.api.copy_gen import _build_video_context
from app.api.subtitle import (
    SubtitleSegmentInput,
    SubtitleStyle,
    GenerateSRTRequest,
    BurnSubtitleRequest,
    ExportOriginalRequest,
)
from app.api.tts import SynthesizeRequest, SynthesizeResponse, synthesize as tts_synthesize

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])


class PlanKeepFlags(BaseModel):
    clips: bool = False
    subtitles: bool = False
    transitions: bool = False
    bgm: bool = False


class TimingHint(BaseModel):
    start: float
    end: float


class SubtitlePlan(BaseModel):
    strategy: Literal["auto", "asr", "rewrite", "none"] = "auto"
    text: str
    source: Literal["asr", "llm", "user"] = "llm"
    timing_hint: Optional[TimingHint] = None


class TransitionPlan(BaseModel):
    type: Literal["hard_cut", "cross_dissolve", "fade_in", "fade_out"] = "hard_cut"
    duration_sec: float = 0.3


class ClipRef(BaseModel):
    clip_id: str
    video_id: str
    weight: float = 1.0


class SegmentPlan(BaseModel):
    id: str
    chapter_id: Optional[str] = None
    order: int
    clip_group: List[ClipRef]
    selected_clip_ids: List[str]
    start_time_sec: float
    end_time_sec: float
    audio_mode: Literal["original", "tts", "mute"] = "original"
    subtitle: SubtitlePlan
    transition: Optional[TransitionPlan] = None


class BGMPlan(BaseModel):
    enabled: bool = False
    source: Literal["library", "user", "ai"] = "library"
    track_id: Optional[str] = None
    volume_db: float = -12.0
    loop: bool = True
    fade_in_sec: float = 0.8
    fade_out_sec: float = 1.0


class Constraints(BaseModel):
    max_clip_per_segment: int = 3
    match_strategy: Literal["asr+vlm", "asr_only", "vlm_only"] = "asr+vlm"
    respect_user_video_order: bool = False


class Plan(BaseModel):
    plan_id: str
    title: str
    summary: str
    mode: Literal["auto", "voiceover", "original"] = "auto"
    target_duration_sec: Optional[float] = None
    estimated_duration_sec: Optional[float] = None
    chapters: Optional[List[dict]] = None
    segments: List[SegmentPlan]
    bgm: Optional[BGMPlan] = None
    constraints: Optional[Constraints] = None
    keep_flags: Optional[PlanKeepFlags] = None


class AutoEditPlanRequest(BaseModel):
    video_ids: List[str] = Field(..., description="选中视频 ID 列表")
    user_prompt: str = Field(..., min_length=1, description="用户提示词/需求")
    mode: Literal["auto", "voiceover", "original"] = "auto"
    target_duration_sec: Optional[int] = Field(
        None, ge=10, le=600, description="目标时长（秒）"
    )
    num_plans: int = Field(3, ge=1, le=5, description="候选方案数量")
    allow_cross_video: bool = True
    subtitle_policy: Literal["auto", "asr", "rewrite"] = "auto"
    transition_policy: Literal["auto", "hard_cut", "soft"] = "auto"
    bgm_policy: Literal["auto", "none", "user", "ai"] = "auto"
    plan_keep_flags: Optional[PlanKeepFlags] = None
    prev_plan_id: Optional[str] = None
    prev_plan: Optional[Plan] = None


class AutoEditPlanResponse(BaseModel):
    plans: List[Plan]


SYSTEM_PROMPT = """你是一位专业的视频剪辑规划师。
现在需要你基于给定的视频素材（已包含 ASR 台词和 VLM 画面描述），
结合用户的创作诉求，生成「自动一键成片」的结构化剪辑方案（Plan）。

重要约束（必须严格遵守）：
- 上文素材列表中，每一行都包含形如 [clip_id=XXXXX] 的片段 ID。
- 你在 Plan.clip_group[*].clip_id 和 Plan.selected_clip_ids 中使用的 clip_id
  必须从这些已有的 clip_id 中“原样拷贝”，绝对禁止凭空创造新的 clip_id，
  比如 "clip_001"、"seg_1" 之类都不允许。

其它要求：
- 你只输出 JSON，不要任何解释或多余文字。
- JSON 顶层结构为 {"plans": [Plan, ...]}，其中 Plan 结构严格遵循下面 schema。
- 所有时间单位均为秒（float）。
- 请确保 segments 能首尾相接，整体时长尽量接近 target_duration_sec。
- 如果信息不足，可以适度补全文案，但要与已有 ASR/VLM 内容风格一致。
"""


def _build_user_message(context: str, req: AutoEditPlanRequest) -> str:
    parts: list[str] = []
    parts.append("【用户需求】")
    parts.append(req.user_prompt.strip())
    parts.append("")
    parts.append("【生成要求】")
    parts.append(f"- 模式：{req.mode}")
    if req.target_duration_sec:
        parts.append(f"- 目标时长：约 {req.target_duration_sec} 秒")
    parts.append(f"- 方案数量：{req.num_plans} 个")
    parts.append(f"- 允许跨视频重排：{req.allow_cross_video}")
    parts.append(f"- 字幕策略：{req.subtitle_policy}")
    parts.append(f"- 转场策略：{req.transition_policy}")
    parts.append(f"- BGM 策略：{req.bgm_policy}")
    parts.append("")
    parts.append("【可用素材简要信息】")
    parts.append(context)
    return "\n".join(parts)


SCHEMA_HINT = """
请严格生成符合下述结构的 JSON：

{
  "plans": [
    {
      "plan_id": "string",
      "title": "string",
      "summary": "string",
      "mode": "auto | voiceover | original",
      "target_duration_sec": 60,
      "estimated_duration_sec": 61.2,
      "chapters": [],
      "segments": [
        {
          "id": "seg_1",
          "chapter_id": null,
          "order": 1,
          "clip_group": [
            { "clip_id": "xxx", "video_id": "v1", "weight": 0.8 }
          ],
          "selected_clip_ids": ["xxx"],
          "start_time_sec": 0.0,
          "end_time_sec": 3.2,
          "audio_mode": "original | tts | mute",
          "subtitle": {
            "strategy": "auto | asr | rewrite | none",
            "text": "本段对应的文案",
            "source": "asr | llm | user",
            "timing_hint": { "start": 0.0, "end": 3.2 }
          },
          "transition": {
            "type": "hard_cut | cross_dissolve | fade_in | fade_out",
            "duration_sec": 0.3
          }
        }
      ],
      "bgm": {
        "enabled": true,
        "source": "library | user | ai",
        "track_id": "bgm_001",
        "volume_db": -12.0,
        "loop": true,
        "fade_in_sec": 0.8,
        "fade_out_sec": 1.0
      },
      "constraints": {
        "max_clip_per_segment": 3,
        "match_strategy": "asr+vlm | asr_only | vlm_only",
        "respect_user_video_order": false
      },
      "keep_flags": {
        "clips": false,
        "subtitles": false,
        "transitions": false,
        "bgm": false
      }
    }
  ]
}
"""


def _extract_json_array(raw: str) -> str:
    """从可能含有思维链/Markdown 的返回中，提取 JSON 文本。"""
    import re

    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    if "```" in raw:
        parts = raw.split("```")
        # 取中间部分作为代码块
        if len(parts) > 1:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
            raw = candidate.strip() or raw
    # 兜底：从第一个 { 到最后一个 } 的范围
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


async def _call_llm_for_plans(
    cfg: dict,
    context: str,
    req: AutoEditPlanRequest,
) -> AutoEditPlanResponse:
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=90,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(context, req) + "\n\n" + SCHEMA_HINT,
        },
    ]

    raw = await llm.chat(messages)
    logger.debug("auto_edit raw LLM output: %s", raw[:500])
    cleaned = _extract_json_array(raw)

    # 尝试直接解析 JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试使用 json_repair 做一次修复
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
            logger.warning("auto_edit LLM JSON 修复成功")
        except Exception as e:
            logger.error("auto_edit JSON 解析失败: %s", e)
            raise HTTPException(status_code=502, detail="LLM 返回的 JSON 无法解析")

    try:
        return AutoEditPlanResponse(**data)
    except ValidationError as e:
        logger.error("auto_edit Plan 验证失败: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回的 Plan 结构不符合预期")


@router.post("/plan", response_model=AutoEditPlanResponse)
async def generate_auto_edit_plan(req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    """
    基于已处理完成的视频素材（clips + ASR + VLM），生成自动成片的结构化方案（Plan）。

    当前阶段：
    - 不做转场与 BGM 的真实渲染，仅在 Plan 中占位。
    - 不支持复杂的 keep_flags/prev_plan 逻辑，只做最简单的全量新方案。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.7,
                default_max_tokens=20480,
            )
            context = await _build_video_context(db, req.video_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("auto_edit 读取上下文失败: %s", e)
        raise HTTPException(status_code=500, detail="读取素材上下文失败")

    return await _call_llm_for_plans(cfg, context, req)


# ────────────────────────────────────────────────────────────
# Plan 实现：转换为字幕成片管线
# ────────────────────────────────────────────────────────────


class AutoEditRealizeRequest(BaseModel):
    plan: Plan
    project_name: Optional[str] = None


class AutoEditRealizeResponse(BaseModel):
    mode: Literal["voiceover", "original"]
    filename: str
    url: str


async def _segments_from_plan(plan: Plan) -> List[SubtitleSegmentInput]:
    """
    将 Plan.segments 转换为现有 SubtitleSegmentInput 列表。
    规则（Phase 2 最小版）：
    - 只取每个 segment.selected_clip_ids 的第一个 clip 作为主 clip_id
    - 如果为空，则回退到 clip_group[0].clip_id
    - 若 audio_mode == 'tts'，直接用段落文案调用一次 TTS 合成
    """
    seg_inputs: List[SubtitleSegmentInput] = []
    for seg in plan.segments:
        primary_clip = (seg.selected_clip_ids[0] if seg.selected_clip_ids else None) or (
            seg.clip_group[0].clip_id if seg.clip_group else None
        )
        if not primary_clip:
            logger.warning("segment %s 缺少可用 clip，跳过", seg.id)
            continue

        tts_filename: Optional[str] = None
        if seg.audio_mode == "tts" and seg.subtitle and seg.subtitle.text:
            # 直接调用 TTS 接口生成语音文件
            tts_req = SynthesizeRequest(text=seg.subtitle.text)
            tts_res: SynthesizeResponse = await tts_synthesize(tts_req)
            tts_filename = tts_res.filename

        seg_inputs.append(
            SubtitleSegmentInput(
                copy_text=seg.subtitle.text if seg.subtitle and seg.subtitle.text else "",
                clip_id=primary_clip,
                clip_ids=seg.selected_clip_ids or [primary_clip],
                tts_filename=tts_filename,
            )
        )
    return seg_inputs


@router.post("/realize", response_model=AutoEditRealizeResponse)
async def realize_auto_edit_plan(req: AutoEditRealizeRequest) -> AutoEditRealizeResponse:
    """
    将一个 Plan 实际转为成片：
    - voiceover 模式：TTS + 字幕 + burn 管线
    - original 模式：保留原声，按段落平均切字幕，调用 export_original

    当前版本：
    - 忽略 Plan.keep_flags / BGM / transition，仅打通基础链路。
    """
    plan = req.plan
    if not plan.segments:
        raise HTTPException(status_code=400, detail="Plan 中没有任何 segments")

    seg_inputs = await _segments_from_plan(plan)
    if not seg_inputs:
        raise HTTPException(status_code=400, detail="Plan 转换后没有有效片段")

    project_name = req.project_name or f"auto_edit_{plan.plan_id}"

    # 统一使用默认字幕样式，后续可根据前端传参自定义
    style = SubtitleStyle()

    # voiceover / auto -> 统一走配音管线（若某段未生成 TTS，会回落到 clip 时长）
    if plan.mode in ("auto", "voiceover"):
        # 先生成 SRT 时间轴（用 TTS 时长优先）
        srt_req = GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=True)
        from app.api.subtitle import generate_srt as generate_srt_route, burn_subtitle as burn_route

        srt_res = await generate_srt_route(srt_req)
        burn_req = BurnSubtitleRequest(
            segments=seg_inputs,
            srt_content=srt_res.srt_content,
            style=style,
            project_name=project_name,
        )
        burn_res = await burn_route(burn_req)
        return AutoEditRealizeResponse(mode="voiceover", filename=burn_res["filename"], url=burn_res["url"])

    # original 模式：走原声导出
    from app.api.subtitle import export_original as export_original_route

    export_req = ExportOriginalRequest(
        segments=seg_inputs,
        style=style,
        project_name=project_name,
        include_subtitle=True,
        normalize_audio=True,
    )
    res = await export_original_route(export_req)
    return AutoEditRealizeResponse(mode="original", filename=res.filename, url=res.url)

