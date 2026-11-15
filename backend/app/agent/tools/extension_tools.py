"""动作：Agent 自扩展工具——安装/卸载技能包与 MCP 外部服务。

对标 AI IDE（Codex/ZCode）的自扩展能力：Agent 可在对话中按用户指令
安装社区技能或接入 MCP 工具服务，安装动作走权限三档确认门。

- install_skill（L2）：URL / GitHub / 本地路径安装技能；远端来源默认停用待审（防提示注入）
- uninstall_skill（L2）：卸载用户技能（内置不可卸）
- install_mcp_server（L3）：先测试连接再落库；stdio = 本机命令执行，任何档位都必须确认
- remove_mcp_server（L2）：移除已配置的 MCP 服务
- search_extension_registry（L0）：检索随代码维护的精选目录（extension_catalog.json）
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.agent import mcp_manager, skills
from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ToolResult

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "extension_catalog.json"
_CATALOG_MAX_HITS = 8


def load_extension_catalog() -> dict[str, Any]:
    try:
        return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("精选扩展目录读取失败: %s", _CATALOG_PATH, exc_info=True)
        return {"mcp_servers": [], "skills": []}


# ── 技能安装 / 卸载 ────────────────────────────────────────────────────────


async def _install_skill(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    enable_raw = args.get("enable")
    try:
        info = await skills.install_skill_from_source(
            source_type=str(args.get("source_type") or ""),
            url=str(args.get("url") or ""),
            repo=str(args.get("repo") or ""),
            path=str(args.get("path") or ""),
            local_path=str(args.get("local_path") or ""),
            slug=(str(args["slug"]) if args.get("slug") else None),
            enable=(bool(enable_raw) if isinstance(enable_raw, bool) else None),
        )
    except ValueError as e:
        return ToolResult(ok=False, summary="", error=str(e))

    lines = [
        f"已安装技能 {info['slug']}（{info['name']}）",
        f"来源：{info['origin']}；正文 {info['body_chars']} 字符"
        + ("；含参考资料 references.md" if info["has_references"] else ""),
    ]
    suggestions: list[str] = []
    if info["enabled"]:
        lines.append("状态：已启用（目录已注入系统提示，可 load_skill 使用）")
    else:
        lines.append(
            "状态：默认停用（远端来源防提示注入）。请在设置页「Agent 技能」审阅内容后启用；"
            "确认内容安全后也可以直接让我启用。"
        )
        suggestions.append(f"技能 {info['slug']} 已安装但默认停用，需要我启用时请告知")
    return ToolResult(ok=True, summary="\n".join(lines), next_suggestions=suggestions)


async def _uninstall_skill(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    slug = str(args.get("slug") or "").strip()
    if not slug:
        return ToolResult(ok=False, summary="", error="uninstall_skill 需要 slug 参数")
    items = await skills.list_skills()
    matches = [s for s in items if s["slug"] == slug]
    if not matches:
        return ToolResult(ok=False, summary="", error=f"技能 {slug} 不存在")
    if all(s["source"] == "builtin" for s in matches):
        return ToolResult(
            ok=False, summary="", error=f"技能 {slug} 是内置技能，不可卸载（可停用）"
        )
    ok = await skills.delete_skill(slug)
    if not ok:
        return ToolResult(ok=False, summary="", error=f"技能 {slug} 卸载失败")
    return ToolResult(ok=True, summary=f"已卸载技能 {slug}（如为同名内置技能，将回退到内置版本）")


# ── MCP 服务安装 / 移除 ────────────────────────────────────────────────────


def _sanitize_entry_args(args: dict[str, Any]) -> dict[str, Any] | str:
    """从工具参数提取 MCP server 配置；类型不符返回错误文本。"""
    entry: dict[str, Any] = {
        k: args.get(k)
        for k in ("id", "name", "transport", "command", "url", "env", "headers")
    }
    raw_args = args.get("args")
    if raw_args is None:
        entry["args"] = []
    elif isinstance(raw_args, list) and all(isinstance(a, (str, int, float)) for a in raw_args):
        entry["args"] = [str(a) for a in raw_args]
    else:
        return "args 需为字符串数组，如 [\"-y\", \"@modelcontextprotocol/server-fetch\"]"
    for key in ("env", "headers"):
        v = entry.get(key)
        if v is not None and not isinstance(v, dict):
            return f"{key} 需为对象（键值均为字符串）"
        if isinstance(v, dict):
            entry[key] = {str(k): str(val) for k, val in v.items()}
    return entry


async def _install_mcp_server(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    entry = _sanitize_entry_args(args)
    if isinstance(entry, str):
        return ToolResult(ok=False, summary="", error=entry)
    # 安装一律不可信（trusted=false）：免确认集只允许用户在设置页手动授予
    entry["trusted"] = False
    try:
        normalized = mcp_manager._normalize_entry(entry)
    except ValueError as e:
        return ToolResult(ok=False, summary="", error=str(e))
    # 先测连接（确认已在权限门放行后才走到这里），失败不落库
    try:
        test = await mcp_manager.test_server(normalized)
    except Exception as e:  # noqa: BLE001 —— 测试连接的任意异常都收敛为错误结果
        return ToolResult(ok=False, summary="", error=f"MCP 连接测试失败：{str(e)[:300]}")
    if not test.get("ok"):
        return ToolResult(
            ok=False,
            summary="",
            error=f"MCP 连接测试失败：{str(test.get('error') or '未知错误')[:300]}（未保存配置）",
        )
    saved = await mcp_manager.upsert_server({**normalized, "enabled": True, "trusted": False})
    # 立即同步注册表，让新工具在下一轮工具清单中立即可见
    try:
        await mcp_manager.sync_registry()
    except Exception:  # noqa: BLE001
        logger.warning("安装 MCP 后注册表同步失败（下轮对话会重试）", exc_info=True)
    tool_names = [t["name"] for t in test.get("tools") or []]
    lines = [
        f"已接入 MCP 服务 {saved['id']}（{saved['name']}，{saved['transport']}），"
        f"发现 {test.get('tool_count', len(tool_names))} 个工具：",
        "、".join(tool_names[:10]) + ("…" if len(tool_names) > 10 else ""),
        "已同步进工具注册表（调用前按权限档位确认；信任该服务可在设置页开启）。",
    ]
    return ToolResult(ok=True, summary="\n".join(lines))


async def _remove_mcp_server(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    server_id = str(args.get("server_id") or "").strip()
    if not server_id:
        return ToolResult(ok=False, summary="", error="remove_mcp_server 需要 server_id 参数")
    servers = await mcp_manager.list_servers()
    match = next((s for s in servers if s["id"] == server_id), None)
    if not match:
        return ToolResult(ok=False, summary="", error=f"MCP 服务 {server_id} 不存在")
    await mcp_manager.delete_server(server_id)
    # 移除后立即同步注册表，避免残留不可用的 mcp__* 工具
    try:
        await mcp_manager.sync_registry()
    except Exception:  # noqa: BLE001
        logger.warning("移除 MCP 后注册表同步失败（下轮对话会重试）", exc_info=True)
    return ToolResult(ok=True, summary=f"已移除 MCP 服务 {server_id}（{match['name']}）及其桥接工具")


# ── 精选目录检索 ───────────────────────────────────────────────────────────


async def _search_extension_registry(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip().lower()
    catalog = load_extension_catalog()
    lines: list[str] = []
    mcp_hits = 0
    for item in catalog.get("mcp_servers") or []:
        if mcp_hits >= _CATALOG_MAX_HITS:
            break
        hay = " ".join(
            [str(item.get("id") or ""), str(item.get("name") or ""),
             str(item.get("description") or ""), " ".join(item.get("tags") or [])]
        ).lower()
        if query and query not in hay:
            continue
        mcp_hits += 1
        install = item.get("install") or {}
        cmd = install.get("command", "")
        cmd_args = " ".join(install.get("args") or [])
        lines.append(
            f"[MCP] {item.get('id')}｜{item.get('name')}：{item.get('description')}"
            f"｜安装参数 transport={install.get('transport')} command={cmd} args=[{cmd_args}]"
        )
        if item.get("notes"):
            lines.append(f"       注意：{item['notes']}")
    skill_hits = 0
    for item in catalog.get("skills") or []:
        if skill_hits >= _CATALOG_MAX_HITS:
            break
        hay = " ".join(
            [str(item.get("slug") or ""), str(item.get("name") or ""),
             str(item.get("description") or ""), " ".join(item.get("tags") or [])]
        ).lower()
        if query and query not in hay:
            continue
        skill_hits += 1
        install = item.get("install") or {}
        lines.append(
            f"[技能] {item.get('slug')}｜{item.get('name')}：{item.get('description')}"
            f"｜安装参数 source_type={install.get('source_type')} repo={install.get('repo')} path={install.get('path')}"
        )
    if not lines:
        return ToolResult(
            ok=True,
            summary="精选目录中没有匹配项。也可以直接让用户提供技能 URL/GitHub 仓库路径或 MCP 服务参数，我可代为安装。",
        )
    return ToolResult(
        ok=True,
        summary=f"精选目录匹配 {mcp_hits} 个 MCP 服务、{skill_hits} 个技能：\n" + "\n".join(lines)
        + "\n（安装前会弹确认卡，用户同意后才会写入）",
    )


def register_extension_tools() -> None:
    register(
        ToolSpec(
            name="install_skill",
            description=(
                "从外部来源安装一个 Agent 技能包（对标 AI IDE 的技能安装）。来源三选一："
                "url（SKILL.md 直链）、github（owner/name 仓库 + 技能目录路径）、"
                "local（本机含 SKILL.md 的目录）。远端来源默认安装为停用态，"
                "需用户在设置页审阅启用。当用户说「装一下这个技能/从这个仓库导入技能」时使用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source_type": {
                        "type": "string",
                        "enum": ["url", "github", "local"],
                        "description": "来源类型",
                    },
                    "url": {"type": "string", "description": "source_type=url 时：SKILL.md 的直链"},
                    "repo": {"type": "string", "description": "source_type=github 时：owner/name"},
                    "path": {"type": "string", "description": "source_type=github 时：仓库内技能目录（如 skills/foo）"},
                    "local_path": {"type": "string", "description": "source_type=local 时：本机技能目录或 SKILL.md 路径"},
                    "slug": {"type": "string", "description": "可选：安装后的技能标识（缺省由名称推导）"},
                    "enable": {"type": "boolean", "description": "可选：是否安装后立即启用（远端来源建议留空=默认停用待审）"},
                },
                "required": ["source_type"],
            },
            risk="L2",
            handler=_install_skill,
        )
    )
    register(
        ToolSpec(
            name="uninstall_skill",
            description="卸载一个已安装的用户技能（内置技能不可卸载，只能停用）。",
            parameters={
                "type": "object",
                "properties": {"slug": {"type": "string", "description": "技能标识"}},
                "required": ["slug"],
            },
            risk="L2",
            handler=_uninstall_skill,
        )
    )
    register(
        ToolSpec(
            name="install_mcp_server",
            description=(
                "接入一个 MCP 外部工具服务（先测试连接，成功才保存）。stdio 类型（command+args，"
                "如 npx -y @modelcontextprotocol/server-fetch）会在本机执行命令，安装前必须经用户确认；"
                "http 类型填 url。可先用 search_extension_registry 查精选目录拿推荐参数。"
                "当用户说「接一下这个 MCP/给我加个抓取工具」时使用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "服务标识（3~32 位小写字母/数字/-/_）"},
                    "name": {"type": "string", "description": "显示名称"},
                    "transport": {"type": "string", "enum": ["stdio", "http"], "description": "传输方式"},
                    "command": {"type": "string", "description": "stdio：要执行的命令（如 npx/uvx/node）"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "stdio：命令参数（如 ['-y', '@modelcontextprotocol/server-fetch']）",
                    },
                    "env": {"type": "object", "description": "stdio：环境变量（如 token）"},
                    "url": {"type": "string", "description": "http：服务端点 URL"},
                    "headers": {"type": "object", "description": "http：自定义请求头"},
                },
                "required": ["id", "transport"],
            },
            risk="L3",
            handler=_install_mcp_server,
        )
    )
    register(
        ToolSpec(
            name="remove_mcp_server",
            description="移除一个已配置的 MCP 服务及其桥接工具。",
            parameters={
                "type": "object",
                "properties": {"server_id": {"type": "string", "description": "服务标识"}},
                "required": ["server_id"],
            },
            risk="L2",
            handler=_remove_mcp_server,
        )
    )
    register(
        ToolSpec(
            name="search_extension_registry",
            description=(
                "检索精选扩展目录（常用 MCP 服务与技能的安装元数据）。"
                "用户想扩展能力但没给具体来源时先查这里，把推荐的安装参数给用户看。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "关键词（如 抓取/浏览器/文档/记忆），留空列全部",
                    }
                },
                "required": [],
            },
            risk="L0",
            handler=_search_extension_registry,
        )
    )
