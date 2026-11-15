"""Agent 自扩展工具单元测试：技能安装（本地/远端默认停用）、MCP 安装（L3 确认门）、
精选目录检索、卸载保护。

远端拉取用 monkeypatch 替换 skills._fetch_remote_text，避免真实网络依赖；
MCP 安装走本地 stdio 测试服务器（_mcp_test_server.py）全链路。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app.agent import mcp_manager, skills
from app.agent.tools import register_all_tools
from app.agent.tool_registry import REGISTRY, AgentContext, invoke, needs_confirm
from app.agent.tools.extension_tools import load_extension_catalog
from app.models.agent import WorkspaceState

_TEST_SERVER = Path(__file__).parent / "_mcp_test_server.py"

_VALID_REMOTE_SKILL = (
    "---\nname: 远端测试技能\ndescription: 从 URL 安装的测试技能\n---\n\n"
    "# 远端技能\n\n按此指导执行测试。"
)

_CTX = AgentContext(session_id="s", workspace=WorkspaceState(session_id="s"))


@pytest_asyncio.fixture(autouse=True)
async def _setup_cleanup():
    register_all_tools()
    yield
    # 清理可能落盘的测试技能与启用清单（还原未配置状态，避免污染其他测试）
    await skills.delete_skill("remote-test")
    await skills.delete_skill("local-test")
    from app.db.database import get_db_conn

    db = await get_db_conn()
    await db.execute("DELETE FROM config WHERE key = ?", (skills.ENABLED_CONFIG_KEY,))
    await db.commit()
    await db.close()
    await mcp_manager.delete_server("ext-test")
    await mcp_manager.delete_server("broken")
    await mcp_manager.shutdown()


def _make_local_skill(tmp_path: Path) -> Path:
    d = tmp_path / "local-test"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: 本地测试技能\ndescription: 本地导入测试\n---\n\n本地技能正文", encoding="utf-8"
    )
    (d / "references.md").write_text("参考资料内容", encoding="utf-8")
    return d


# ── install_skill ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_skill_local_enabled(tmp_path):
    src = _make_local_skill(tmp_path)
    result = await invoke(
        "install_skill",
        {"source_type": "local", "local_path": str(src), "slug": "local-test"},
        _CTX,
    )
    assert result.ok, result.error
    assert "已安装技能 local-test" in result.summary
    content = skills.load_skill_content("local-test")
    assert content and "本地技能正文" in content and "参考资料内容" in content
    items = await skills.list_skills()
    mine = next(s for s in items if s["slug"] == "local-test")
    assert mine["source"] == "user" and mine["enabled"] is True   # 本地来源默认启用
    catalog = await skills.build_skill_catalog_prompt()
    assert "local-test" in catalog


@pytest.mark.asyncio
async def test_install_skill_remote_defaults_disabled(monkeypatch):
    async def _fake_fetch(url: str, *, optional: bool = False):
        return _VALID_REMOTE_SKILL

    monkeypatch.setattr(skills, "_fetch_remote_text", _fake_fetch)
    result = await invoke(
        "install_skill",
        {"source_type": "url", "url": "https://example.com/SKILL.md", "slug": "remote-test"},
        _CTX,
    )
    assert result.ok, result.error
    assert "默认停用" in result.summary
    items = await skills.list_skills()
    mine = next(s for s in items if s["slug"] == "remote-test")
    assert mine["enabled"] is False
    catalog = await skills.build_skill_catalog_prompt()
    assert "remote-test" not in catalog          # 停用不进系统提示
    # 用户审阅后启用 → 进目录
    await skills.set_skill_enabled("remote-test", True)
    assert "remote-test" in await skills.build_skill_catalog_prompt()


@pytest.mark.asyncio
async def test_install_skill_remote_invalid_content(monkeypatch):
    async def _fake_fetch(url: str, *, optional: bool = False):
        return "# 没有 frontmatter 的普通文档"

    monkeypatch.setattr(skills, "_fetch_remote_text", _fake_fetch)
    result = await invoke(
        "install_skill",
        {"source_type": "url", "url": "https://example.com/SKILL.md", "slug": "remote-test"},
        _CTX,
    )
    assert not result.ok
    assert "frontmatter" in result.error
    assert skills.load_skill_content("remote-test") is None       # 未落盘


@pytest.mark.asyncio
async def test_install_skill_github_arg_validation():
    result = await invoke(
        "install_skill",
        {"source_type": "github", "repo": "bad repo!", "path": "skills/x", "slug": "remote-test"},
        _CTX,
    )
    assert not result.ok and "owner/name" in result.error


@pytest.mark.asyncio
async def test_uninstall_skill_builtin_rejected():
    result = await invoke("uninstall_skill", {"slug": "douyin-ecommerce"}, _CTX)
    assert not result.ok and "内置" in result.error


@pytest.mark.asyncio
async def test_uninstall_user_skill_roundtrip(tmp_path):
    src = _make_local_skill(tmp_path)
    assert (
        await invoke(
            "install_skill",
            {"source_type": "local", "local_path": str(src), "slug": "local-test"},
            _CTX,
        )
    ).ok
    result = await invoke("uninstall_skill", {"slug": "local-test"}, _CTX)
    assert result.ok, result.error
    assert skills.load_skill_content("local-test") is None


# ── install_mcp_server / remove_mcp_server ─────────────────────────────────


@pytest.mark.asyncio
async def test_install_mcp_server_risk_l3():
    spec = REGISTRY["install_mcp_server"]
    assert spec.risk == "L3"
    # L3：任何档位都必须确认（含完全访问）
    ws = WorkspaceState(session_id="s")
    ws.permissions.mode = "full"
    assert needs_confirm(spec, AgentContext(session_id="s", workspace=ws)) is True


@pytest.mark.asyncio
async def test_install_mcp_server_full_flow():
    result = await invoke(
        "install_mcp_server",
        {
            "id": "ext-test",
            "name": "扩展测试服务",
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(_TEST_SERVER)],
        },
        _CTX,
    )
    assert result.ok, result.error
    assert "add" in result.summary                      # 发现的工具列表
    servers = {s["id"]: s for s in await mcp_manager.list_servers()}
    assert "ext-test" in servers
    assert servers["ext-test"]["trusted"] is False      # 安装一律不可信
    assert "mcp__ext-test__add" in REGISTRY             # 已同步桥接

    removed = await invoke("remove_mcp_server", {"server_id": "ext-test"}, _CTX)
    assert removed.ok, removed.error
    assert "mcp__ext-test__add" not in REGISTRY


@pytest.mark.asyncio
async def test_install_mcp_server_bad_command_not_saved():
    result = await invoke(
        "install_mcp_server",
        {
            "id": "broken",
            "name": "坏服务",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", "import sys; sys.exit(1)"],
        },
        _CTX,
    )
    assert not result.ok
    ids = {s["id"] for s in await mcp_manager.list_servers()}
    assert "broken" not in ids                          # 测试失败不落库


@pytest.mark.asyncio
async def test_install_mcp_server_arg_type_guard():
    result = await invoke(
        "install_mcp_server",
        {"id": "ext-test", "transport": "stdio", "command": "npx", "args": "-y foo"},
        _CTX,
    )
    assert not result.ok and "args" in result.error


# ── search_extension_registry ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_extension_registry_filters():
    result = await invoke("search_extension_registry", {"query": "抓取"}, _CTX)
    assert result.ok
    assert "[MCP] fetch" in result.summary
    assert "[MCP] github" not in result.summary

    all_hits = await invoke("search_extension_registry", {"query": ""}, _CTX)
    assert all_hits.ok and "[技能]" in all_hits.summary


def test_catalog_file_loads():
    catalog = load_extension_catalog()
    assert len(catalog.get("mcp_servers") or []) >= 5
    assert len(catalog.get("skills") or []) >= 1
    for item in catalog["mcp_servers"]:
        install = item["install"]
        assert install["transport"] in ("stdio", "http")
        assert install.get("command") or install.get("url")
