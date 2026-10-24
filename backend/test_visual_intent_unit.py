# -*- coding: utf-8 -*-
"""画面意图改写（visual_intent）单元测试：解析、对齐、降级与批量改写。"""

from app.core.auto_edit.visual_intent import (
    expand_visual_intent_sync,
    expand_visual_intents_sync,
    parse_intents_payload,
)


def test_parse_valid_payload():
    res = parse_intents_payload('{"intents":["特写：年轻人深夜伏案工作，神情疲惫","远景：城市夜晚车流霓虹"]}', 2)
    assert res[0] and "伏案" in res[0]
    assert res[1] and "霓虹" in res[1]


def test_parse_len_mismatch_pads_none():
    # LLM 少输出一条：不足补 None，保持与输入逐条对应
    res = parse_intents_payload('{"intents":["只有一条"]}', 3)
    assert res[0] == "只有一条"
    assert res[1] is None and res[2] is None


def test_parse_invalid_json_all_none():
    assert parse_intents_payload("这不是JSON", 2) == [None, None]
    assert parse_intents_payload("", 2) == [None, None]


def test_expand_batch_with_fake_chat():
    def fake_chat(messages):
        # 校验输入确实是两句旁白
        user = messages[-1]["content"]
        assert "绝望" in user and "城市" in user
        return '{"intents":["人物特写：垂头、闭眼、握拳，情绪低落","城市夜景航拍：高楼灯火与车流"]}'

    res = expand_visual_intents_sync(
        {"base_url": "x", "api_key": "k", "model": "m"},
        ["他感到无比绝望", "镜头转向繁华的城市"],
        chat_fn=fake_chat,
    )
    assert res[0] and "特写" in res[0]
    assert res[1] and "航拍" in res[1]


def test_expand_skips_short_text():
    # 过短文案不改写（收益低且易失真）
    res = expand_visual_intents_sync(
        {"base_url": "x", "api_key": "k", "model": "m"},
        ["好", "这一刻他终于释怀了"],
        chat_fn=lambda m: '{"intents":["人物释然微笑的特写"]}',
    )
    assert res[0] is None
    assert res[1] and "释然" in res[1]


def test_expand_failure_returns_none():
    def boom(messages):
        raise RuntimeError("network down")

    res = expand_visual_intents_sync(
        {"base_url": "x", "api_key": "k", "model": "m"},
        ["一段足够长的旁白文案"],
        chat_fn=boom,
    )
    assert res == [None]
    # 单句接口同样降级
    single = expand_visual_intent_sync(
        {"base_url": "x", "api_key": "k", "model": "m"},
        "一段足够长的旁白文案",
        chat_fn=boom,
    )
    assert single is None
