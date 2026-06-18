"""混剪无标注 tier：音量活动切分单元测试。"""
from __future__ import annotations

from unittest.mock import patch

from app.core.auto_edit.mix_edit import (
    _append_none_tier_segments,
    _extract_audio_activity_segments,
    build_mix_edit_plan,
)


def _none_row(
    *,
    rid: str = "clip-1",
    vid: str = "vid-1",
    start: float = 0.0,
    dur: float = 10.0,
) -> dict:
    return {
        "id": rid,
        "video_id": vid,
        "clip_path": "storage/vid-1/clips/c1.mp4",
        "start_time": start,
        "duration": dur,
        "asr_text": None,
        "asr_segments": None,
        "vlm_description": None,
    }


@patch("app.core.auto_edit.mix_edit.detect_voice_ranges_by_silencedetect")
@patch("app.core.auto_edit.mix_edit.resolve_stored_path")
def test_extract_audio_activity_segments(mock_resolve, mock_detect):
    mock_resolve.return_value = "/tmp/c1.mp4"
    mock_detect.return_value = [(0.5, 2.0), (3.0, 5.5)]
    row = _none_row()
    out = _extract_audio_activity_segments(row)
    assert out == [(0.5, 2.0), (3.0, 5.5)]
    mock_detect.assert_called_once()
    kwargs = mock_detect.call_args.kwargs
    assert kwargs["noise_db"] == -36.0
    assert kwargs["min_silence_sec"] == 0.25


@patch("app.core.auto_edit.mix_edit.detect_voice_ranges_by_silencedetect")
@patch("app.core.auto_edit.mix_edit.resolve_stored_path")
def test_keep_original_none_tier_splits_on_voice(mock_resolve, mock_detect):
    mock_resolve.return_value = "/tmp/c1.mp4"
    mock_detect.return_value = [(0.0, 4.0), (5.0, 9.0)]
    row = _none_row()
    segments: list = []
    order = _append_none_tier_segments(
        row=row,
        order=0,
        segments=segments,
        mix_audio_mode="keep_original",
    )
    assert order == 2
    assert len(segments) == 2
    assert segments[0].audio_mode == "original"
    assert segments[0].override_duration_sec == 4.0
    assert segments[1].start_time_sec == 5.0
    assert segments[1].override_duration_sec == 4.0


@patch("app.core.auto_edit.mix_edit.detect_voice_ranges_by_silencedetect")
@patch("app.core.auto_edit.mix_edit.resolve_stored_path")
def test_build_mix_plan_none_tier_no_shuffle(mock_resolve, mock_detect):
    mock_resolve.return_value = "/tmp/c1.mp4"
    mock_detect.return_value = [(0.0, 3.0)]
    rows = [
        _none_row(rid="c-b", start=20.0, dur=5.0),
        _none_row(rid="c-a", start=0.0, dur=5.0),
    ]
    plan = build_mix_edit_plan(
        clip_rows=rows,
        mix_audio_mode="keep_original",
    )
    assert len(plan.segments) == 2
    assert plan.segments[0].selected_clip_ids == ["c-a"]
    assert plan.segments[1].selected_clip_ids == ["c-b"]
    assert "音量活动" in plan.summary or plan.segments[0].audio_mode == "original"

@patch("app.core.auto_edit.mix_edit.detect_voice_ranges_by_silencedetect")
@patch("app.core.auto_edit.mix_edit.resolve_stored_path")
def test_build_mix_plan_respects_target_duration(mock_resolve, mock_detect):
    mock_resolve.return_value = "/tmp/c1.mp4"
    # 5 段各 4s，共 20s；目标 10s 应只保留约 2.5 段
    mock_detect.return_value = [
        (0.0, 4.0),
        (4.5, 8.5),
        (9.0, 13.0),
        (13.5, 17.5),
        (18.0, 22.0),
    ]
    row = {
        "id": "raw_vid-1",
        "video_id": "vid-1",
        "clip_path": "storage/vid-1/video.mp4",
        "start_time": 0.0,
        "duration": 30.0,
        "asr_text": None,
        "asr_segments": None,
        "vlm_description": None,
    }
    plan = build_mix_edit_plan(
        clip_rows=[row],
        mix_audio_mode="keep_original",
        target_duration_sec=10.0,
    )
    assert plan.estimated_duration_sec is not None
    assert plan.estimated_duration_sec <= 10.0 + 1e-6
    assert len(plan.segments) <= 3
    assert "目标时长" in plan.summary
