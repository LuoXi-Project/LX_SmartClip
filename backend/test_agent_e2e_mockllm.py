"""Agent 全链路 e2e（mock LLM）：真实 orchestrator → 确认门 → 工具执行 → 产物落盘。

不依赖真实模型：本地起 OpenAI 兼容 mock 服务（aiohttp），
第一轮 executor 返回 preview_composition 工具调用，第二轮返回总结文本。
验证：路由 → ReAct 执行 → L1 工具直接放行 → 合成落盘 → artifact SSE → 消息持久化。

真实 LLM（13000 代理）联调仍需用户开启代理后另行验证。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
from aiohttp import web
import pytest
import pytest_asyncio

from app.core.motion import runtime
from app.db.database import get_db_conn
from app.models.agent import ChatRequest
from app.agent.orchestrator import run_chat_turn
from app.agent import session_store

_MOCK_HTML = (
    '<!doctype html><html><head><meta charset="UTF-8"/></head><body>'
    '<div id="root" data-composition-id="main" data-start="0" data-duration="3" '
    'data-width="1080" data-height="1920">'
    '<h1 id="t" class="clip" data-start="0" data-duration="3" data-track-index="0">标题卡</h1>'
    '</div>'
    '<script>window.__timelines=window.__timelines||{};'
    'window.__timelines["main"]={seek(){}};</script></body></html>'
)

_TOOL_ARGS = json.dumps({"html": _MOCK_HTML, "title": "e2e标题卡"}, ensure_ascii=False)


def _chunk(delta: dict[str, Any], finish: str | None = None, call_id: str = "c1") -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "model": "mock",
        "created": 1,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class _MockLLM:
    """OpenAI 兼容 mock：/v1/chat/completions（stream + 非流式路由调用）。"""

    def __init__(self) -> None:
        self.executor_calls = 0
        self.router_calls = 0
        self.runner: web.AppRunner | None = None
        self.port = 0

    async def start(self) -> None:
        async def handler(request: web.Request) -> web.StreamResponse | web.Response:
            body = await request.json()
            if body.get("stream"):
                self.executor_calls += 1
                resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
                await resp.prepare(request)
                if self.executor_calls == 1:
                    chunks = [
                        _chunk({"role": "assistant", "content": ""}),
                        _chunk(
                            {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-preview-1",
                                        "type": "function",
                                        "function": {"name": "preview_composition", "arguments": _TOOL_ARGS},
                                    }
                                ]
                            }
                        ),
                        _chunk({}, finish="tool_calls"),
                    ]
                else:
                    chunks = [
                        _chunk({"role": "assistant", "content": "标题卡合成已生成，请在画布预览确认效果。"}),
                        _chunk({}, finish="stop"),
                    ]
                for c in chunks:
                    await resp.write(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode())
                await resp.write(b"data: [DONE]\n\n")
                return resp
            # 非流式（router）：固定 execute 路由
            self.router_calls += 1
            return web.json_response(
                {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "model": "mock",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"route": "execute", "reason": "mock router"}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        app = web.Application()
        app.router.add_post("/v1/chat/completions", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


@pytest_asyncio.fixture()
async def mock_llm():
    from app.agent.tools import register_all_tools

    register_all_tools()
    mock = _MockLLM()
    await mock.start()

    # 改 DB 里的 llm_base_url 指向 mock（结束还原）
    db = await get_db_conn()
    cur = await db.execute("SELECT value FROM config WHERE key = 'llm_base_url'")
    row = await cur.fetchone()
    original: str | None = row["value"] if row else None
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value, type, label, options) "
        "VALUES ('llm_base_url', ?, 'text', 'LLM Base URL', NULL)",
        (f"http://127.0.0.1:{mock.port}/v1",),
    )
    await db.commit()
    await db.close()

    yield mock

    db = await get_db_conn()
    if original is None:
        await db.execute("DELETE FROM config WHERE key = 'llm_base_url'")
    else:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, type, label, options) "
            "VALUES ('llm_base_url', ?, 'text', 'LLM Base URL', NULL)",
            (original,),
        )
    await db.commit()
    await db.close()
    await mock.stop()


def _parse_sse_events(raw: list[bytes]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    buf = b"".join(raw)
    for block in buf.split(b"\n\n"):
        lines = block.decode("utf-8", errors="replace").strip().splitlines()
        name, data = "", ""
        for line in lines:
            if line.startswith("event: "):
                name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data += line[len("data: "):]
        if name and data:
            try:
                events.append((name, json.loads(data)))
            except json.JSONDecodeError:
                events.append((name, {}))
    return events


@pytest.mark.asyncio
async def test_agent_full_loop_mock_llm(mock_llm: _MockLLM):
    if not runtime.runtime_status()["ready"]:
        pytest.skip("动效运行时不就绪（无 Node/依赖），e2e 需要 workspace 依赖")
    ws = await session_store.create_session(title="e2e mock llm")
    session_id = ws.session_id
    comp_id = ""
    try:
        raw_chunks: list[bytes] = []
        async for chunk in run_chat_turn(session_id, ChatRequest(message="帮我做一个3秒竖屏标题卡")):
            raw_chunks.append(chunk)

        events = _parse_sse_events(raw_chunks)
        names = [e for e, _ in events]

        assert "route" in names, names
        assert mock_llm.router_calls == 1
        assert mock_llm.executor_calls == 2

        # L1 工具无需确认 → 直接 tool_start/tool_end + artifact
        assert "confirm_required" not in names
        assert "tool_start" in names and "tool_end" in names
        tool_events = [(n, d) for n, d in events if n == "tool_end"]
        assert any(d.get("ok") for _, d in tool_events)

        artifacts = [d for n, d in events if n == "artifact"]
        assert artifacts and artifacts[0]["payload"]["preview_url"].startswith(
            "/api/motion/compositions/"
        )
        comp_id = artifacts[0]["id"]
        assert (runtime.compositions_dir() / comp_id / "index.html").is_file()

        # 最终 assistant 文案 + done
        assert any("标题卡" in (d.get("content") or "") for n, d in events if n == "message_delta")
        assert names[-1] == "done"

        # 消息已持久化（user/assistant/tool/artifact；studio_type 在 content 内）
        msgs = await session_store.list_messages(session_id)
        types = {(m.get("content") or {}).get("studio_type") for m in msgs}
        assert {"user", "assistant", "tool", "artifact"} <= types
    finally:
        await session_store.delete_session(session_id)
        import shutil

        if comp_id:
            shutil.rmtree(runtime.compositions_dir() / comp_id, ignore_errors=True)


@pytest.mark.asyncio
async def test_agent_full_loop_render_requires_confirm(mock_llm: _MockLLM):
    """render_composition 为 L2：ask 档必须弹确认卡并终止本轮（pending_confirm）。"""
    if not runtime.runtime_status()["ready"]:
        pytest.skip("动效运行时不就绪")
    # 把 mock 的第一个工具调用换成 render_composition
    mock_llm.executor_calls = 0

    async def _patch_handler(request: web.Request) -> web.StreamResponse | web.Response:
        body = await request.json()
        if body.get("stream"):
            mock_llm.executor_calls += 1
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            args = json.dumps({"html": _MOCK_HTML, "title": "e2e渲染"}, ensure_ascii=False)
            chunks = [
                _chunk({"role": "assistant", "content": ""}),
                _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-render-1",
                                "type": "function",
                                "function": {"name": "render_composition", "arguments": args},
                            }
                        ]
                    }
                ),
                _chunk({}, finish="tool_calls"),
            ]
            for c in chunks:
                await resp.write(f"data: {json.dumps(c, ensure_ascii=False)}\n\n".encode())
            await resp.write(b"data: [DONE]\n\n")
            return resp
        mock_llm.router_calls += 1
        return web.json_response(
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"route": "execute", "reason": "mock router"}',
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    # 替换 mock 服务器的 handler（aiohttp 允许 add_routes 后追加，旧路由仍在前——改用独立 mock 实例更稳）
    mock2 = _MockLLM()

    async def _start_with(patch_handler) -> None:
        from aiohttp import web as _web

        app = _web.Application()
        app.router.add_post("/v1/chat/completions", patch_handler)
        mock2.runner = _web.AppRunner(app)
        await mock2.runner.setup()
        site = _web.TCPSite(mock2.runner, "127.0.0.1", 0)
        await site.start()
        mock2.port = site._server.sockets[0].getsockname()[1]  # type: ignore[attr-defined]

    await _start_with(_patch_handler)
    db = await get_db_conn()
    await db.execute(
        "INSERT OR REPLACE INTO config (key, value, type, label, options) "
        "VALUES ('llm_base_url', ?, 'text', 'LLM Base URL', NULL)",
        (f"http://127.0.0.1:{mock2.port}/v1",),
    )
    await db.commit()
    await db.close()

    ws = await session_store.create_session(title="e2e mock llm confirm")
    session_id = ws.session_id
    try:
        raw_chunks: list[bytes] = []
        async for chunk in run_chat_turn(session_id, ChatRequest(message="直接渲染一个标题卡")):
            raw_chunks.append(chunk)
        events = _parse_sse_events(raw_chunks)
        names = [e for e, _ in events]

        assert "confirm_required" in names
        assert names[-1] == "done"
        cid = events[-1][1].get("pending_confirm")
        assert cid
        pending = await session_store.pop_pending_confirm(cid)
        assert pending and pending["tool_name"] == "render_composition"
        # 未获确认不得执行
        assert "tool_start" not in names
    finally:
        await session_store.delete_session(session_id)
        await mock2.stop()
