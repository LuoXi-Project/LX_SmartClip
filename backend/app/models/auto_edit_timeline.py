"""auto_edit 事件级时间轴（低侵入升级）的数据模型定义。

说明：
- 这些模型用于“DSL→Events→Timeline→Plan”的中间产物承载。
- V0 阶段它们不要求出现在对外 API 的 response_model 中（避免破坏兼容性）。
- 未来若要把事件层提升为 Plan 的一等公民，可复用这些模型并逐步迁移。
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class StrategyStyle(BaseModel):
    pace: Literal["slow", "medium", "fast"] = "medium"
    tone: Literal["calm", "neutral", "energetic"] = "neutral"
    structure: List[Literal["hook", "context", "highlight", "cta"]] = Field(
        default_factory=lambda: ["hook", "context", "highlight", "cta"]
    )


class StrategyPreferences(BaseModel):
    prefer_asr: bool = True
    prefer_vlm_when_no_asr: bool = True
    avoid_repetition: bool = True


class TierBudgetRatio(BaseModel):
    tier1: float = 0.7
    tier2: float = 0.25
    tier3: float = 0.05


class StrategyConstraints(BaseModel):
    respect_user_video_order: bool = False
    max_events_per_clip: int = Field(6, ge=1, le=50)
    tier_budget_ratio: TierBudgetRatio = Field(default_factory=TierBudgetRatio)


class StrategyDSL(BaseModel):
    dsl_version: str = "1"
    goal: str
    mode_hint: Optional[Literal["auto", "voiceover", "original"]] = None
    # 模板剪辑预设（当不为 None 时，编排器按 slot role 顺序强制取事件）
    template_preset: Optional[Literal["ecommerce", "marketing", "tech_review"]] = None
    target_duration_sec: Optional[int] = Field(None, ge=10, le=600)
    style: StrategyStyle = Field(default_factory=StrategyStyle)
    preferences: StrategyPreferences = Field(default_factory=StrategyPreferences)
    constraints: StrategyConstraints = Field(default_factory=StrategyConstraints)


class EventTimeRange(BaseModel):
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., gt=0)


class EventScores(BaseModel):
    local_score: float = Field(0.0, ge=0.0, le=1.0)
    relevance: Optional[float] = Field(None, ge=0.0, le=1.0)
    clarity: Optional[float] = Field(None, ge=0.0, le=1.0)
    emotion: Optional[float] = Field(None, ge=0.0, le=1.0)


EventRole = Literal["hook", "context", "highlight", "cta", "broll", "transition"]
EventBeat = Literal["setup", "turn", "payoff", "montage", "explain", "demo"]
EventSource = Literal["asr", "vlm", "asr+vlm", "llm", "user"]


class ClipEvent(BaseModel):
    event_id: str
    clip_id: str
    time_range: Optional[EventTimeRange] = None
    text: str = ""
    source: EventSource = "llm"
    role: EventRole = "highlight"
    beat: EventBeat = "explain"
    scores: EventScores = Field(default_factory=EventScores)
    tags: List[str] = Field(default_factory=list)
    evidence: Optional[str] = None

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, v: object) -> object:
        """
        LLM 常见问题：
        - 把 beat 值（如 turn/setup/payoff）写进 role
        - role 大小写/空格不一致
        这里做纠错，避免整批 events 因枚举不匹配直接失败。
        """
        if not isinstance(v, str):
            return v
        s = v.strip().lower().replace(" ", "")
        if not s:
            return s

        # 允许的 role
        if s in ("hook", "context", "highlight", "cta", "broll", "transition"):
            return s

        # 常见：把 beat 写进 role
        beat_to_role = {
            "setup": "hook",
            "turn": "context",
            "payoff": "highlight",
            "montage": "broll",
            "explain": "context",
            "demo": "highlight",
        }
        if s in beat_to_role:
            return beat_to_role[s]

        # 中文/同义词兜底（尽量少做、但能救回来）
        alias = {
            "开场": "hook",
            "引子": "hook",
            "背景": "context",
            "铺垫": "context",
            "亮点": "highlight",
            "高光": "highlight",
            "卖点": "highlight",
            "结尾": "cta",
            "关注": "cta",
            "转场": "transition",
            "过渡": "transition",
            "补镜": "broll",
            "空镜": "broll",
        }
        if s in alias:
            return alias[s]

        # 最终兜底：不让校验失败，回退 highlight
        return "highlight"

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_source(cls, v: object) -> object:
        """
        LLM 可能输出组合来源（例如 `vlm+asr`、`asr+vlm`）。
        这里做归一化，避免因为枚举不匹配导致整批 events 失败。
        """
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return s
        s_lower = s.lower().replace(" ", "")
        # 允许输入里出现 asr/vlm 的任意组合顺序
        if "+" in s_lower:
            parts = [p for p in s_lower.split("+") if p]
            parts_set = set(parts)
            if "asr" in parts_set and "vlm" in parts_set:
                return "asr+vlm"
            # 兜底：取第一个可识别 token
            for p in parts:
                if p in ("asr", "vlm", "llm", "user"):
                    return p
            return parts[0] if parts else s_lower
        # 兜底：直接映射常见大小写
        if s_lower in ("asr", "vlm", "asr+vlm", "llm", "user"):
            return s_lower
        return s_lower

    @field_validator("beat", mode="before")
    @classmethod
    def _normalize_beat(cls, v: object) -> object:
        """
        LLM 常见问题：
        - 把 role 值（如 highlight/hook）写进 beat
        - beat 大小写/空格不一致
        """
        if not isinstance(v, str):
            return v
        s = v.strip().lower().replace(" ", "")
        if not s:
            return s

        if s in ("setup", "turn", "payoff", "montage", "explain", "demo"):
            return s

        # 常见：把 role 写进 beat
        role_to_beat = {
            "hook": "setup",
            "context": "explain",
            "highlight": "payoff",
            "cta": "payoff",
            "broll": "montage",
            "transition": "turn",
        }
        if s in role_to_beat:
            return role_to_beat[s]

        # 中文/同义词兜底
        alias = {
            "铺垫": "setup",
            "反转": "turn",
            "转折": "turn",
            "高潮": "payoff",
            "高光": "payoff",
            "讲解": "explain",
            "说明": "explain",
            "演示": "demo",
            "展示": "demo",
            "蒙太奇": "montage",
        }
        if s in alias:
            return alias[s]

        return "explain"


class ClipEventsBatch(BaseModel):
    batch_id: str
    events: List[ClipEvent]
    batch_stats: Optional[Dict[str, object]] = None


class PooledEvent(ClipEvent):
    tier: Optional[Literal[1, 2, 3]] = None
    global_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    global_rank: Optional[int] = Field(None, ge=1)


class MergedEventPool(BaseModel):
    pool_version: str = "1"
    events: List[PooledEvent]


class TimelineItem(BaseModel):
    event_id: str
    clip_id: str
    subtitle_text: str = ""
    audio_mode: Literal["original", "tts", "mute"] = "original"
    duration_budget_sec: Optional[float] = Field(None, gt=0)


class FinalTimeline(BaseModel):
    timeline_version: str = "1"
    items: List[TimelineItem]
    total_duration_sec_est: Optional[float] = Field(None, gt=0)

