"""Agent 技能包（skills）单元测试：frontmatter 解析、发现、启用态、创建/删除。

涉及 config 表读写的用例直接使用运行库（agent_skills_enabled 键），
结束时还原为未配置状态，避免污染其他测试。
"""

from __future__ import annotations

import pytest

from app.agent import skills
from app.db.database import get_db_conn


def test_parse_frontmatter():
    text = "---\nname: 测试技能\ndescription: 一个测试\n---\n\n正文内容"
    meta, body = skills._parse_frontmatter(text)
    assert meta["name"] == "测试技能"
    assert meta["description"] == "一个测试"
    assert body.strip() == "正文内容"


def test_parse_frontmatter_missing():
    meta, body = skills._parse_frontmatter("没有 frontmatter 的文本")
    assert meta == {}
    assert "没有" in body


def test_builtin_skills_shipped():
    """三个内置技能包随代码分发且可解析。"""
    items = [s for s in __import__("asyncio").run(skills.list_skills()) if s["source"] == "builtin"]
    slugs = {s["slug"] for s in items}
    assert {"douyin-ecommerce", "film-commentary", "knowledge-voiceover"} <= slugs
    for s in items:
        assert s["name"] and s["description"] and s["body_chars"] > 100


def test_load_skill_content_truncates():
    content = skills.load_skill_content("douyin-ecommerce")
    assert content and "黄金" in content
    assert len(content) <= skills.BODY_CHAR_LIMIT + skills.REFERENCES_CHAR_LIMIT + 50


@pytest.mark.asyncio
async def test_enable_disable_roundtrip():
    """停用→列表反映→启用→还原未配置状态。"""
    # 确保起始未配置（缺省全启用）
    db = await get_db_conn()
    await db.execute("DELETE FROM config WHERE key = ?", (skills.ENABLED_CONFIG_KEY,))
    await db.commit()
    await db.close()

    items = await skills.list_skills()
    assert all(s["enabled"] for s in items)

    ok = await skills.set_skill_enabled("douyin-ecommerce", False)
    assert ok
    items = await skills.list_skills()
    by_slug = {s["slug"]: s for s in items}
    assert by_slug["douyin-ecommerce"]["enabled"] is False
    assert by_slug["film-commentary"]["enabled"] is True

    # 目录注入排除停用项
    catalog = await skills.build_skill_catalog_prompt()
    assert "douyin-ecommerce" not in catalog
    assert "film-commentary" in catalog

    await skills.set_skill_enabled("douyin-ecommerce", True)
    catalog = await skills.build_skill_catalog_prompt()
    assert "douyin-ecommerce" in catalog

    # 清理：还原为未配置
    db = await get_db_conn()
    await db.execute("DELETE FROM config WHERE key = ?", (skills.ENABLED_CONFIG_KEY,))
    await db.commit()
    await db.close()


@pytest.mark.asyncio
async def test_create_and_delete_user_skill():
    created = await skills.create_skill(
        name="测试用户技能", description="临时测试", body="# 指导内容\n\n按此执行"
    )
    slug = created["slug"]
    try:
        content = skills.load_skill_content(slug)
        assert content and "按此执行" in content
        items = await skills.list_skills()
        mine = next(s for s in items if s["slug"] == slug)
        assert mine["source"] == "user"
        assert mine["enabled"] is True   # 新建默认启用
    finally:
        assert await skills.delete_skill(slug) is True
        assert skills.load_skill_content(slug) is None
