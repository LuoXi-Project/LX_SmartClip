# -*- coding: utf-8 -*-
"""VLM 画面相关性校验单元测试：帧定位、打分解析与重排。"""

import os

from app.core.vlm.relevance import (
    apply_vlm_rerank,
    find_clip_frames,
    score_candidates_sync,
)


def _make_frames(root, clip_stem, count):
    d = os.path.join(root, "frames", clip_stem)
    os.makedirs(d, exist_ok=True)
    for i in range(count):
        with open(os.path.join(d, f"frame_{i:03d}.jpg"), "wb") as f:
            f.write(b"\xff\xd8fake")


def test_find_clip_frames_strips_material_prefix(tmp_path):
    # 抽帧目录名会剥掉文件名开头的素材 id 前缀（与 splitter 行为一致）
    vid = "abc123"
    clips_dir = tmp_path / vid / "clips"
    clips_dir.mkdir(parents=True)
    clip_path = str(clips_dir / f"{vid}_hybrid_0000.mp4")
    _make_frames(str(tmp_path / vid), "hybrid_0000", 5)

    frames = find_clip_frames({"clip_path": clip_path, "video_id": vid}, max_frames=2)
    assert len(frames) == 2
    assert all(os.path.isfile(p) for p in frames)
    # 等间隔采样自 stripped 目录
    assert os.path.normcase(frames[0]).endswith("frame_000.jpg")


def test_find_clip_frames_plain_stem(tmp_path):
    vid = "v1"
    clips_dir = tmp_path / vid / "clips"
    clips_dir.mkdir(parents=True)
    clip_path = str(clips_dir / "scene_07.mp4")
    _make_frames(str(tmp_path / vid), "scene_07", 3)

    frames = find_clip_frames({"clip_path": clip_path, "video_id": vid}, max_frames=2)
    assert len(frames) == 2


def test_find_clip_frames_missing_returns_empty(tmp_path):
    clip_path = str(tmp_path / "novid" / "clips" / "x.mp4")
    assert find_clip_frames({"clip_path": clip_path, "video_id": "novid"}) == []
    assert find_clip_frames({"clip_path": "", "video_id": "v"}) == []


def test_score_candidates_sync_with_fake_call(tmp_path):
    vid = "v"
    clips_dir = tmp_path / vid / "clips"
    clips_dir.mkdir(parents=True)
    c1 = {"clip_id": "c1", "clip_path": str(clips_dir / "a.mp4"), "video_id": vid}
    c2 = {"clip_id": "c2", "clip_path": str(clips_dir / "b.mp4"), "video_id": vid}
    _make_frames(str(tmp_path / vid), "a", 1)
    _make_frames(str(tmp_path / vid), "b", 1)

    def fake_call(content):
        assert any("旁白文案" in str(p) for p in content)
        assert any("候选1" in str(p) for p in content)
        return '{"scores":[{"idx":1,"score":8.5,"reason":"画面呈现主体动作"},{"idx":2,"score":11,"reason":"非法分应被丢弃"}]}'

    res = score_candidates_sync(
        {"base_url": "x", "api_key": "k", "model": "m"}, "他在奔跑", [c1, c2], call_fn=fake_call
    )
    assert "c1" in res and res["c1"]["vlm_score"] == 8.5
    # 超出 0~10 的非法分数被丢弃（宁缺毋滥）
    assert "c2" not in res


def test_score_candidates_no_frames_skips_vlm(tmp_path):
    c1 = {"clip_id": "c1", "clip_path": str(tmp_path / "none.mp4"), "video_id": "v"}
    res = score_candidates_sync(
        {"base_url": "x", "api_key": "k", "model": "m"}, "文案", [c1], call_fn=lambda c: "{}"
    )
    assert res == {}


def test_apply_vlm_rerank_reorders_and_annotates():
    a = {"clip_id": "a", "score": 9.0, "reason": "LLM精排"}
    b = {"clip_id": "b", "score": 7.0, "reason": "LLM精排"}
    c = {"clip_id": "c", "score": 8.0, "reason": "LLM精排"}  # 无 VLM 分
    out = apply_vlm_rerank(
        [a, b, c],
        {"b": {"vlm_score": 9.0, "vlm_reason": "画面直接支撑旁白"}},
    )
    # b：0.55*0.7 + 0.45*0.9 = 0.79 > a：0.55*0.9 = 0.495 > c：0.55*0.8
    assert [x["clip_id"] for x in out] == ["b", "a", "c"]
    assert out[0]["vlm_score"] == 9.0
    assert "VLM画面相关度 9.0/10" in out[0]["reason"]
    assert "vlm_score" not in out[1]


def test_apply_vlm_rerank_noop_without_results():
    a = {"clip_id": "a", "score": 9.0, "reason": "r"}
    out = apply_vlm_rerank([a], {})
    assert out == [a]
