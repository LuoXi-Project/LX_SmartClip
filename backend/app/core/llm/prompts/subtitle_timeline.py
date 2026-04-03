from __future__ import annotations

_LLM_SYS_PROMPT = (
    "你是专业的视频字幕时间轴生成器。根据文案和时长生成字幕时间轴，时间全局连续累加。\n"
    "规则: 1.不超出片段时长 2.超20字拆多条每条<=20字 3.每条0.3-6秒条间0.05秒 "
    '4.输出JSON:{"entries":[{"clip_id":"...","start":0.0,"end":2.5,"text":"..."}]} 5.只输出JSON'
)

