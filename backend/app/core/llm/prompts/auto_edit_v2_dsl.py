from __future__ import annotations

_DSL_SYS_PROMPT = """你是一位专业的视频剪辑策略规划师。
你需要把用户需求抽象成“可编译的剪辑策略 DSL”。

要求（必须遵守）：
- 只输出 JSON，不要解释文字，不要 Markdown。
- 输出必须能被 Pydantic StrategyDSL 校验通过。
- 字段尽量短且受控：不要发散到剪辑方案/Plan，不要输出 clip_id。
"""

_DSL_SCHEMA_HINT = """
输出 JSON 结构示例（仅示例，不要照抄文本）：
{
  "dsl_version": "1",
  "goal": "string",
  "mode_hint": "auto|voiceover|original",
  "target_duration_sec": 60,
  "style": {"pace":"fast|medium|slow","tone":"energetic|neutral|calm","structure":["hook","context","highlight","cta"]},
  "preferences": {"prefer_asr": true, "prefer_vlm_when_no_asr": true, "avoid_repetition": true},
  "constraints": {"respect_user_video_order": false, "max_events_per_clip": 6, "tier_budget_ratio": {"tier1":0.7,"tier2":0.25,"tier3":0.05}}
}
"""

