"""动作：Agent 技能包工具（渐进式披露第二步——按需加载技能全文）。"""

from __future__ import annotations

from typing import Any

from app.agent import skills
from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ToolResult


async def _load_skill(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    slug = str(args.get("slug") or "").strip()
    if not slug:
        return ToolResult(ok=False, summary="", error="load_skill 需要 slug 参数")
    content = skills.load_skill_content(slug)
    if content is None:
        available = [s["slug"] for s in await skills.get_enabled_skills()]
        return ToolResult(
            ok=False,
            summary="",
            error=f"技能 {slug} 不存在或未启用（可用：{', '.join(available) or '无'}）",
        )
    return ToolResult(ok=True, summary=content)


def register_skill_tools() -> None:
    register(
        ToolSpec(
            name="load_skill",
            description=(
                "加载一个剪辑技能包的完整指导内容。当用户诉求命中系统提示「可用技能」"
                "清单中某项的描述时（如带货口播、影视解说、知识科普），先调用本工具"
                "加载该技能，再按技能内容生成方案/剪辑。只需加载一次，不要重复加载。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "技能标识（见系统提示的可用技能清单，如 douyin-ecommerce）",
                    }
                },
                "required": ["slug"],
            },
            risk="L1",
            handler=_load_skill,
        )
    )
