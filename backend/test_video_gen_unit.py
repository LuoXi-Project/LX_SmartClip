# -*- coding: utf-8 -*-
"""生成式空镜兜底单元测试：入库注册、触发条件与批量预算。"""

import sqlite3

import pytest

from app.core.material.video_gen import register_generated_clip


def _mk_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE videos (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, file_path TEXT NOT NULL,
            thumbnail_path TEXT, duration REAL, total_clips INTEGER DEFAULT 0,
            split_mode TEXT DEFAULT 'scene', status TEXT DEFAULT 'pending',
            is_replica_ref INTEGER DEFAULT 0, upload_at TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE clips (
            id TEXT PRIMARY KEY, video_id TEXT NOT NULL, clip_path TEXT,
            start_time REAL, end_time REAL, duration REAL,
            asr_text TEXT, asr_segments TEXT, vlm_description TEXT, tags TEXT,
            abstract_summary TEXT, keywords TEXT, emotion_tags TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    return conn


def test_register_generated_clip_inserts_rows():
    conn = _mk_db()
    clip = register_generated_clip(conn, "storage/generated/gen_x.mp4", "雨夜城市霓虹空镜", 5.0)
    assert clip["clip_id"].startswith("genclip-")
    assert clip["vlm_description"] == "雨夜城市霓虹空镜"
    assert clip["keywords"] == ["AI生成", "空镜"]

    row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip["clip_id"],)).fetchone()
    assert row["video_id"] == clip["video_id"]
    assert float(row["duration"]) == 5.0
    vid = conn.execute("SELECT * FROM videos WHERE id = ?", (clip["video_id"],)).fetchone()
    assert vid is not None and vid["status"] == "done"


def _rt(min_score=5.5):
    return {
        "generate_cfg": {"base_url": "x", "api_key": "key", "model": "m"},
        "gen_min_score": min_score,
        "gen_duration_sec": 5.0,
        "gen_timeout_sec": 1.0,
        "gen_max_per_batch": 2,
    }


def _result(top_score):
    if top_score is None:
        return {"recommended": [], "candidates": []}
    return {
        "recommended": [{"clip_id": "c1", "score": top_score, "reason": "r"}],
        "candidates": [{"clip_id": "c1", "score": top_score, "reason": "r"}],
    }


@pytest.fixture()
def fake_generate(monkeypatch):
    calls = []

    def _fake(db_conn, cfg, prompt, *, duration_sec=5.0, timeout_sec=600.0):
        calls.append(prompt)
        return {
            "clip_id": f"genclip-{len(calls)}",
            "video_id": f"gen-{len(calls)}",
            "clip_path": f"storage/generated/gen_{len(calls)}.mp4",
            "start_time": 0.0,
            "end_time": 5.0,
            "duration": 5.0,
            "asr_text": "",
            "vlm_description": prompt,
            "abstract_summary": "",
            "keywords": ["AI生成"],
            "emotion_tags": [],
        }

    monkeypatch.setattr("app.core.material.video_gen.generate_broll_sync", _fake)
    return calls


def test_generate_disabled_by_flag():
    from app.api.match import _maybe_generate_fallback

    conn = _mk_db()
    # 请求/全局均为关 → 不生成
    assert _maybe_generate_fallback(_rt(), conn, False, _result(0.0), "画面", None) is False


def test_generate_triggers_on_low_score(fake_generate):
    from app.api.match import _maybe_generate_fallback

    conn = _mk_db()
    result = _result(3.0)  # 最佳 3.0 < 阈值 5.5
    ok = _maybe_generate_fallback(_rt(), conn, True, result, "雨夜霓虹空镜", None)
    assert ok is True and len(fake_generate) == 1
    top = result["recommended"][0]
    assert top["is_generated"] is True
    assert top["clip_id"].startswith("genclip-")
    assert "AI 生成空镜" in top["reason"]
    # 原推荐保留在后面
    assert result["recommended"][1]["clip_id"] == "c1"


def test_generate_skipped_when_score_good(fake_generate):
    from app.api.match import _maybe_generate_fallback

    conn = _mk_db()
    # 最佳 8.0 ≥ 阈值 → 不生成
    assert _maybe_generate_fallback(_rt(), conn, True, _result(8.0), "画面", None) is False
    assert fake_generate == []


def test_generate_respects_budget(fake_generate):
    from app.api.match import _maybe_generate_fallback

    conn = _mk_db()
    budget = [2]
    assert _maybe_generate_fallback(_rt(), conn, True, _result(0.0), "a", budget) is True
    assert budget == [1]
    assert _maybe_generate_fallback(_rt(), conn, True, _result(0.0), "b", budget) is True
    assert budget == [0]
    # 预算耗尽后不再生成
    assert _maybe_generate_fallback(_rt(), conn, True, _result(0.0), "c", budget) is False
    assert len(fake_generate) == 2


def test_generate_failure_falls_back_silently(monkeypatch):
    from app.api.match import _maybe_generate_fallback

    conn = _mk_db()

    def _boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr("app.core.material.video_gen.generate_broll_sync", _boom)
    result = _result(1.0)
    assert _maybe_generate_fallback(_rt(), conn, True, result, "x", None) is False
    assert result["recommended"][0]["clip_id"] == "c1"  # 原推荐不受影响
