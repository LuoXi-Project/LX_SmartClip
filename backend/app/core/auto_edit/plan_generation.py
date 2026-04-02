from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.models.auto_edit import AutoEditPlanRequest, AutoEditPlanResponse

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一位专业的视频剪辑规划师。
现在需要你基于给定的视频素材（可能包含 ASR 台词与/或 VLM 画面描述；有些素材可能没有 ASR），
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
- 当某些片段缺少 ASR 时，你必须主要依赖 VLM 画面描述进行语义匹配与剪辑（必要时在 constraints.match_strategy 选择 vlm）。
- 如果信息不足，可以适度补全文案，但要与已有 ASR/VLM 内容风格一致。
"""


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
            "source": "asr | asr+vlm | llm | vlm | user",
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
        "match_strategy": "asr+vlm | asr | vlm",
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


async def call_llm_for_plans(cfg: dict[str, Any], context: str, req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=3600,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(context, req) + "\n\n" + SCHEMA_HINT,
        },
    ]

    raw = await llm.chat(messages)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回内容为空")
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

