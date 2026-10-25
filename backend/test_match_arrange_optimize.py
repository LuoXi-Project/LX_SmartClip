# -*- coding: utf-8 -*-
"""Matcher 跨段降权 + auto_edit_v2 编排多样性/节奏约束 单元测试。"""

import sqlite3

from app.core.matcher import Matcher
from app.core.auto_edit_v2.arrange import arrange_timeline, arrange_timeline_variants, _shot_bounds
from app.core.auto_edit_v2.merge_rank import assign_tiers_and_rank, merge_batches
from app.models.auto_edit_timeline import ClipEvent, ClipEventsBatch, StrategyDSL


def _mk_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE clips (
            id TEXT PRIMARY KEY, video_id TEXT, clip_path TEXT,
            start_time REAL, end_time REAL, duration REAL,
            asr_text TEXT, vlm_description TEXT, abstract_summary TEXT,
            keywords TEXT, emotion_tags TEXT
        )
        """
    )
    rows = [
        ("clipA", "v1", "a.mp4", 0, 5, 5, "他在深夜里奔跑训练，汗水淋漓", "", "", "[]", "[]"),
        ("clipB", "v1", "b.mp4", 5, 10, 5, "城市夜晚车流与霓虹灯", "", "", "[]", "[]"),
        ("clipC", "v1", "c.mp4", 10, 15, 5, "奔跑后的疲惫特写", "", "", "[]", "[]"),
    ]
    conn.executemany("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    return conn


def test_match_without_penalize_prefers_best_text_hit():
    conn = _mk_db()
    m = Matcher(embedder=None, vector_db=None, llm=None)
    res = m.match(query="深夜奔跑", db_conn=conn, top_k=3, top_n=3, mode="text")
    assert res["recommended"][0]["clip_id"] == "clipA"


def test_match_penalize_sinks_used_clip():
    conn = _mk_db()
    m = Matcher(embedder=None, vector_db=None, llm=None)
    res = m.match(
        query="深夜奔跑",
        db_conn=conn,
        top_k=3,
        top_n=3,
        mode="text",
        penalize_clip_ids=["clipA"],
    )
    top = res["recommended"]
    # 最佳命中被降权后不应再占据推荐首位，但仍保留在候选中
    assert top[0]["clip_id"] != "clipA"
    assert any(c["clip_id"] == "clipA" for c in res["candidates"])
    penalized = next(c for c in res["candidates"] if c["clip_id"] == "clipA")
    assert "已降权" in penalized["reason"]
    assert penalized["score"] < res["recommended"][0]["score"]


# ---------------- auto_edit_v2 编排 ----------------


def _mk_pool(clip_sequence, scores=None):
    events = []
    for i, cid in enumerate(clip_sequence):
        events.append(
            ClipEvent(
                event_id=f"e{i}",
                clip_id=cid,
                text=f"第{i}句旁白内容，用于撑起一定时长" + "长" * (i % 3),
                source="llm",
                role="highlight",
                scores={"local_score": 0.6 + 0.3 * ((len(clip_sequence) - i) / len(clip_sequence))},
            )
        )
    if scores:
        for e, s in zip(events, scores):
            e.scores.local_score = s
    # 与生产链路一致：先 merge_batches（计算 global_score/转 PooledEvent），再分层
    merged = merge_batches([ClipEventsBatch(batch_id="b1", events=events)])
    return assign_tiers_and_rank(merged)


def test_arrange_avoids_adjacent_same_clip():
    # 池中 A 的事件分数碾压，若无邻接约束会连选 A
    pool = _mk_pool(["A", "A", "A", "B", "B", "C"], scores=[0.95, 0.9, 0.85, 0.6, 0.5, 0.4])
    dsl = StrategyDSL(goal="g", target_duration_sec=40, style={"pace": "medium"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=40)

    assert len(tl.items) >= 2
    clip_ids = [it.clip_id for it in tl.items]
    for i in range(1, len(clip_ids)):
        assert clip_ids[i] != clip_ids[i - 1], f"相邻镜头复用了同一素材: {clip_ids}"


def test_arrange_relaxes_adjacency_when_pool_exhausted():
    # 只有同一素材的事件：邻接约束应自动放宽，保证出片
    pool = _mk_pool(["A", "A", "A"])
    dsl = StrategyDSL(goal="g", target_duration_sec=30, style={"pace": "medium"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=30)
    assert len(tl.items) >= 1


def test_arrange_shot_duration_bounds():
    pool = _mk_pool(["A", "B", "A", "C", "B", "A"], scores=[0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    dsl = StrategyDSL(goal="g", target_duration_sec=30, style={"pace": "fast"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=30)
    lo, hi = _shot_bounds(dsl)
    for it in tl.items:
        assert lo <= float(it.duration_budget_sec) <= hi, (
            f"镜头时长 {it.duration_budget_sec} 超出节奏区间 [{lo},{hi}]"
        )


def test_arrange_explicit_constraints_override_pace():
    dsl = StrategyDSL(
        goal="g",
        target_duration_sec=30,
        style={"pace": "fast"},
        constraints={"min_shot_sec": 4.0, "max_shot_sec": 9.0},
    )
    assert _shot_bounds(dsl) == (4.0, 9.0)
    pool = _mk_pool(["A", "B", "A", "C", "B", "A"], scores=[0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=30)
    # 尾镜允许吸收目标时长的余量而短于下限，其余镜头必须落在约束区间
    for it in tl.items[:-1]:
        assert 4.0 <= float(it.duration_budget_sec) <= 9.0
    assert float(tl.items[-1].duration_budget_sec) > 0


def test_variants_keep_adjacent_diversity():
    pool = _mk_pool(["A", "A", "B", "A", "B", "C"], scores=[0.9, 0.85, 0.8, 0.7, 0.6, 0.5])
    dsl = StrategyDSL(goal="g", target_duration_sec=40, style={"pace": "medium"})
    tls = arrange_timeline_variants(
        pool=pool, dsl=dsl, mode="original", target_duration_sec=40, num_plans=3
    )
    assert tls
    for tl in tls:
        clip_ids = [it.clip_id for it in tl.items]
        for i in range(1, len(clip_ids)):
            assert clip_ids[i] != clip_ids[i - 1], f"方案内相邻镜头复用同一素材: {clip_ids}"


# ---------------- 钩子结构（hook first） ----------------


def test_arrange_promotes_hook_first():
    # tier1 全是 highlight 且分数更高，hook 事件分数较低：编排后首镜头仍应为钩子
    events = [
        ClipEvent(event_id="e1", clip_id="A", text="高信息密度的正文第一句", role="highlight", scores={"local_score": 0.95}),
        ClipEvent(event_id="e2", clip_id="B", text="高信息密度的正文第二句", role="highlight", scores={"local_score": 0.9}),
        ClipEvent(event_id="e3", clip_id="C", text="你绝对想不到结局竟然是这样", role="hook", scores={"local_score": 0.6}),
        ClipEvent(event_id="e4", clip_id="D", text="补充背景的正文内容", role="context", scores={"local_score": 0.5}),
    ]
    pool = assign_tiers_and_rank(merge_batches([ClipEventsBatch(batch_id="b1", events=events)]))
    dsl = StrategyDSL(goal="g", target_duration_sec=30, style={"pace": "medium"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=30)
    assert tl.items, "时间轴不应为空"
    first = tl.items[0].event_id.split("#", 1)[0]
    assert first == "e3", f"首镜头应为钩子事件 e3，实际 {first}"


def test_hook_shot_uses_shorter_bounds():
    events = [
        ClipEvent(event_id="e1", clip_id="A", text="你绝对想不到结果竟然是这样反转", role="hook", scores={"local_score": 0.9}),
        ClipEvent(event_id="e2", clip_id="B", text="正文内容第二句比较长一些", role="highlight", scores={"local_score": 0.8}),
        ClipEvent(event_id="e3", clip_id="C", text="正文内容第三句也很长", role="context", scores={"local_score": 0.7}),
    ]
    pool = assign_tiers_and_rank(merge_batches([ClipEventsBatch(batch_id="b1", events=events)]))
    dsl = StrategyDSL(goal="g", target_duration_sec=30, style={"pace": "medium"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=30)
    hook_item = next(it for it in tl.items if (it.event_id or "").split("#", 1)[0] == "e1")
    # medium 全局区间 1.8~6 → 钩子收紧为 1.08~3.0（短促快切）
    assert 0.9 <= float(hook_item.duration_budget_sec) <= 3.0, (
        f"钩子镜头时长 {hook_item.duration_budget_sec} 未落在短促区间"
    )


def test_no_hook_keeps_original_order():
    events = [
        ClipEvent(event_id="e1", clip_id="A", text="正文第一句内容", role="highlight", scores={"local_score": 0.9}),
        ClipEvent(event_id="e2", clip_id="B", text="正文第二句内容", role="context", scores={"local_score": 0.8}),
    ]
    pool = assign_tiers_and_rank(merge_batches([ClipEventsBatch(batch_id="b1", events=events)]))
    dsl = StrategyDSL(goal="g", target_duration_sec=20, style={"pace": "medium"})
    tl = arrange_timeline(pool=pool, dsl=dsl, mode="original", target_duration_sec=20)
    ids = [(it.event_id or "").split("#", 1)[0] for it in tl.items]
    assert ids[0] == "e1", "无钩子事件时保持评分顺序"


# ---------------- /api/match/batch 集成（无 LLM/VLM 配置的纯文本链路） ----------------


def test_match_batch_sync_end_to_end(tmp_path, monkeypatch):
    import sqlite3

    db_path = str(tmp_path / "t.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        """
        CREATE TABLE clips (
            id TEXT PRIMARY KEY, video_id TEXT, clip_path TEXT,
            start_time REAL, end_time REAL, duration REAL,
            asr_text TEXT, vlm_description TEXT, abstract_summary TEXT,
            keywords TEXT, emotion_tags TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("clipA", "v1", "a.mp4", 0, 5, 5, "他在深夜里奔跑训练，汗水淋漓", "", "", "[]", "[]"),
            ("clipB", "v1", "b.mp4", 5, 10, 5, "城市夜晚车流与霓虹灯", "", "", "[]", "[]"),
            ("clipC", "v1", "c.mp4", 10, 15, 5, "奔跑后的疲惫特写", "", "", "[]", "[]"),
        ],
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr("app.api.match.DB_PATH", db_path)
    from app.api.match import _match_batch_sync
    from app.models.match import MatchBatchRequest

    resp = _match_batch_sync(
        MatchBatchRequest(
            segments=["深夜里奔跑训练的画面", "城市夜晚的车流霓虹", "再回到奔跑训练的镜头"],
            top_k=3,
            top_n=2,
        ),
        "",
    )
    assert len(resp.items) == 3
    # 未配置 LLM：不走画面意图改写
    assert all(it.visual_intent_query is None for it in resp.items)
    top_ids = [it.recommended[0].clip_id for it in resp.items if it.recommended]
    assert len(top_ids) == 3
    # 跨段去重生效：三段不会全部锁定同一段素材
    assert len(set(top_ids)) >= 2, f"三段全部选用同一片段: {top_ids}"
