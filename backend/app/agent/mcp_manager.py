"""MCP（Model Context Protocol）客户端管理：外部工具桥接进 Agent 工具注册表。

- 服务端配置存 config 表 agent_mcp_servers（JSON 数组，见 _DEFAULT_ENTRY）
- 连接懒建立 + 进程内缓存；断线重连一次，再失败跳过该 server（不影响内置工具）
- 工具桥接：REGISTRY 注册 mcp__<server_id>__<tool>，description 前缀 [MCP·<名称>]
- 风险：默认 L2（执行前确认，与权限三档联动）；server 配置 trusted 才进免确认集
- 防膨胀：每 server ≤20 个工具、全局 MCP ≤40
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from app.agent.tool_registry import REGISTRY, ToolSpec
from app.db.database import get_db_conn

logger = logging.getLogger(__name__)

MCP_CONFIG_KEY = "agent_mcp_servers"
SERVER_ID_RE_MIN = 3
MAX_TOOLS_PER_SERVER = 20
MAX_MCP_TOOLS_TOTAL = 40
DEFAULT_TIMEOUT_SEC = 60
CONNECT_TIMEOUT_SEC = 20
MCP_TOOL_PREFIX = "mcp__"


def tool_name(server_id: str, tool: str) -> str:
    return f"{MCP_TOOL_PREFIX}{server_id}__{tool}"


# ── 配置存取 ───────────────────────────────────────────────────────────────


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    transport = str(entry.get("transport") or "stdio")
    if transport not in ("stdio", "http"):
        raise ValueError(f"transport 只支持 stdio / http，收到 {transport!r}")
    sid = str(entry.get("id") or "").strip().lower()
    if not sid or len(sid) < SERVER_ID_RE_MIN or len(sid) > 32:
        raise ValueError("id 需要 3~32 位标识（小写字母/数字/-/_）")
    if transport == "stdio" and not str(entry.get("command") or "").strip():
        raise ValueError("stdio 传输需要 command")
    if transport == "http" and not str(entry.get("url") or "").strip():
        raise ValueError("http 传输需要 url")
    return {
        "id": sid,
        "name": str(entry.get("name") or sid).strip()[:40],
        "transport": transport,
        "command": str(entry.get("command") or "").strip(),
        "args": [str(a) for a in (entry.get("args") or [])][:32],
        "env": {str(k): str(v) for k, v in (entry.get("env") or {}).items()} if isinstance(entry.get("env"), dict) else {},
        "url": str(entry.get("url") or "").strip(),
        "headers": {str(k): str(v) for k, v in (entry.get("headers") or {}).items()} if isinstance(entry.get("headers"), dict) else {},
        "enabled": bool(entry.get("enabled", True)),
        "trusted": bool(entry.get("trusted", False)),
        "timeout_sec": max(5, min(int(entry.get("timeout_sec") or DEFAULT_TIMEOUT_SEC), 600)),
    }


async def list_servers() -> list[dict[str, Any]]:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT value FROM config WHERE key = ?", (MCP_CONFIG_KEY,))
        row = await cur.fetchone()
        if not row or not row["value"]:
            return []
        try:
            data = json.loads(row["value"])
        except json.JSONDecodeError:
            return []
        return [_normalize_entry(e) for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except ValueError:
        return []
    finally:
        await db.close()


async def _save_servers(servers: list[dict[str, Any]]) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, type, label, options) "
            "VALUES (?, ?, 'json', 'Agent MCP 服务配置', NULL)",
            (MCP_CONFIG_KEY, json.dumps(servers, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()


async def upsert_server(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_entry(entry)
    if not normalized["id"]:
        normalized["id"] = f"srv-{uuid.uuid4().hex[:6]}"
    servers = [s for s in await list_servers() if s["id"] != normalized["id"]]
    servers.append(normalized)
    await _save_servers(servers)
    await _manager.drop(normalized["id"])   # 配置变更后旧连接失效
    return normalized


async def delete_server(server_id: str) -> bool:
    servers = await list_servers()
    remaining = [s for s in servers if s["id"] != server_id]
    if len(remaining) == len(servers):
        return False
    await _save_servers(remaining)
    await _manager.drop(server_id)
    return True


# ── 连接管理 ───────────────────────────────────────────────────────────────


class _Connection:
    """一个 MCP server 的持久会话（async context manager 手动持有）。"""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.session = None
        self._cm_stack: list[Any] = []
        self.lock = asyncio.Lock()

    async def _open(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        if self.cfg["transport"] == "stdio":
            params = StdioServerParameters(
                command=self.cfg["command"], args=self.cfg["args"], env=self.cfg["env"] or None
            )
            cm = stdio_client(params)
            read, write = await cm.__aenter__()
            self._cm_stack.append(cm)
        else:
            headers = self.cfg.get("headers") or None
            http_client = create_mcp_http_client(headers=headers) if headers else None
            cm = streamable_http_client(self.cfg["url"], http_client=http_client)
            streams = await cm.__aenter__()
            read, write = streams[0], streams[1]
            self._cm_stack.append(cm)
        session_cm = ClientSession(read, write)
        self.session = await session_cm.__aenter__()
        self._cm_stack.append(session_cm)
        await asyncio.wait_for(self.session.initialize(), timeout=CONNECT_TIMEOUT_SEC)

    async def close(self) -> None:
        session, self.session = self.session, None
        stack, self._cm_stack = list(reversed(self._cm_stack)), []
        for cm in stack:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCP 连接清理异常（忽略）", exc_info=True)
        del session

    async def ensure(self) -> "_Connection":
        """取可用会话；无则建，断则重连一次。"""
        if self.session is not None:
            return self
        async with self.lock:
            if self.session is not None:
                return self
            try:
                await self._open()
            except Exception:
                logger.warning("MCP server %s 连接失败：%s", self.cfg["id"], self.cfg["name"], exc_info=True)
                raise
            return self


class _Manager:
    def __init__(self) -> None:
        self._conns: dict[str, _Connection] = {}
        # server_id -> 已注册工具列表 [{name, description, input_schema}]
        self._tools_cache: dict[str, list[dict[str, Any]]] = {}

    async def drop(self, server_id: str) -> None:
        conn = self._conns.pop(server_id, None)
        self._tools_cache.pop(server_id, None)
        if conn:
            await conn.close()

    async def close_all(self) -> None:
        for sid in list(self._conns):
            await self.drop(sid)

    def _conn(self, cfg: dict[str, Any]) -> _Connection:
        conn = self._conns.get(cfg["id"])
        if conn is None or conn.cfg != cfg:
            if conn is not None:
                # 配置变化：旧连接异步关闭，不阻塞
                asyncio.create_task(conn.close())
            conn = _Connection(cfg)
            self._conns[cfg["id"]] = conn
        return conn

    async def list_tools(self, cfg: dict[str, Any], *, use_cache: bool = True) -> list[dict[str, Any]]:
        """连接并列出工具（测试连接也走这里）。"""
        if use_cache and cfg["id"] in self._tools_cache:
            return self._tools_cache[cfg["id"]]
        conn = self._conn(cfg)
        # 连接失败时重连一次（drop 缓存连接后重试）
        try:
            c = await conn.ensure()
        except Exception:
            await self.drop(cfg["id"])
            conn = self._conn(cfg)
            c = await conn.ensure()
        result = await asyncio.wait_for(c.session.list_tools(), timeout=CONNECT_TIMEOUT_SEC)
        tools = []
        for t in (result.tools or [])[:MAX_TOOLS_PER_SERVER]:
            # mcp 1.x 属性名 inputSchema / isError；2.x 为 input_schema / is_error
            schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
            tools.append(
                {
                    "name": t.name,
                    "description": (getattr(t, "description", None) or "")[:300],
                    "input_schema": schema or {"type": "object", "properties": {}},
                }
            )
        self._tools_cache[cfg["id"]] = tools
        return tools

    async def call(self, cfg: dict[str, Any], tool: str, args: dict[str, Any]) -> str:
        """调用工具并把返回内容收敛为文本摘要（供 ToolResult.summary）。"""
        conn = self._conn(cfg)
        c = await conn.ensure()
        result = await asyncio.wait_for(
            c.session.call_tool(tool, arguments=args), timeout=cfg["timeout_sec"]
        )
        parts: list[str] = []
        for block in getattr(result, "content", None) or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                parts.append(str(getattr(block, "text", "")))
            else:
                # 图片/资源等非文本：给出类型说明，不塞二进制
                preview = ""
                if btype == "resource":
                    preview = str(getattr(getattr(block, "resource", None), "uri", ""))
                parts.append(f"（{btype} 内容{': ' + preview if preview else ''}，已省略展示）")
        summary = "\n".join(p for p in parts if p).strip()
        # mcp 1.x isError / 2.x is_error
        err = getattr(result, "is_error", None)
        if err is None:
            err = getattr(result, "isError", False)
        if err:
            raise RuntimeError(summary or "MCP 工具返回错误（无详情）")
        return summary or "（工具执行成功，无文本返回）"


_manager = _Manager()


# ── 桥接进工具注册表 ──────────────────────────────────────────────────────


async def sync_registry() -> dict[str, int]:
    """把启用 server 的工具 upsert 进 REGISTRY（移除失效的 mcp__* 项）。

    返回 {"servers": n, "tools": m}；单个 server 失败只跳过该 server。
    """
    # 清掉旧桥接项（内置工具不带 mcp__ 前缀，不受影响）
    for name in [n for n in REGISTRY if n.startswith(MCP_TOOL_PREFIX)]:
        REGISTRY.pop(name, None)

    servers = [s for s in await list_servers() if s["enabled"]]
    total = 0
    ok_servers = 0
    for cfg in servers:
        if total >= MAX_MCP_TOOLS_TOTAL:
            logger.warning("MCP 工具总数已达上限 %d，跳过剩余 server", MAX_MCP_TOOLS_TOTAL)
            break
        try:
            tools = await _manager.list_tools(cfg)
        except Exception:
            logger.warning("MCP server %s 工具列举失败，已跳过", cfg["id"], exc_info=True)
            continue
        ok_servers += 1
        prefix = f"[MCP·{cfg['name']}] "
        for t in tools:
            if total >= MAX_MCP_TOOLS_TOTAL:
                break
            full = tool_name(cfg["id"], t["name"])
            if full in REGISTRY:
                continue
            REGISTRY[full] = ToolSpec(
                name=full,
                description=prefix + (t["description"] or t["name"]),
                parameters=t["input_schema"],
                risk="L2",
                handler=_make_handler(cfg, t["name"]),
            )
            total += 1
    return {"servers": ok_servers, "tools": total}


def _make_handler(cfg: dict[str, Any], remote_tool: str):
    async def _handler(_ctx, args: dict[str, Any]):
        from app.models.agent import ToolResult

        try:
            summary = await _manager.call(cfg, remote_tool, args)
            return ToolResult(ok=True, summary=summary)
        except asyncio.TimeoutError:
            return ToolResult(
                ok=False, summary="", error=f"MCP 工具执行超时（>{cfg['timeout_sec']}s）"
            )
        except Exception as e:
            logger.warning("MCP 调用失败 %s/%s", cfg["id"], remote_tool, exc_info=True)
            return ToolResult(ok=False, summary="", error=f"MCP 调用失败：{str(e)[:300]}")

    return _handler


async def trusted_tool_names_async() -> set[str]:
    """受信任 server 的全部已注册工具名（供 AgentContext.external_trusted；
    需在 sync_registry 之后调用，工具清单已在 _tools_cache）。"""
    names: set[str] = set()
    for cfg in await list_servers():
        if not (cfg["enabled"] and cfg["trusted"]):
            continue
        tools = _manager._tools_cache.get(cfg["id"]) or []
        names.update(tool_name(cfg["id"], t["name"]) for t in tools)
    return names


async def test_server(cfg: dict[str, Any]) -> dict[str, Any]:
    """测试连接：列举工具并返回清单（不写配置）。"""
    normalized = _normalize_entry(cfg)
    # 临时连接（不复用缓存，测的就是「从零连得上」）
    tmp = _Connection(normalized)
    try:
        await tmp.ensure()
        result = await asyncio.wait_for(tmp.session.list_tools(), timeout=CONNECT_TIMEOUT_SEC)
        tools = [
            {"name": t.name, "description": (t.description or "")[:120]}
            for t in (result.tools or [])[:MAX_TOOLS_PER_SERVER]
        ]
        return {"ok": True, "tool_count": len(tools), "tools": tools}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    finally:
        await tmp.close()


async def shutdown() -> None:
    await _manager.close_all()
