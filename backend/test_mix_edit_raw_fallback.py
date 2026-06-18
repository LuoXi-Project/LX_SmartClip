"""混剪：未预处理视频 raw_ 回退加载。"""
from __future__ import annotations

import asyncio
from typing import Any

from app.api.auto_edit import _load_mix_edit_clips
from app.core.auto_edit.mix_edit import build_mix_edit_plan


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchall_result: list[Any] | None = None,
        fetchone_result: Any | None = None,
    ):
        self._fetchall = fetchall_result or []
        self._fetchone = fetchone_result

    async def fetchall(self) -> list[Any]:
        return self._fetchall

    async def fetchone(self) -> Any | None:
        return self._fetchone

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeDb:
    def __init__(
        self,
        *,
        clip_rows: list[Any] | None = None,
        video_row: dict[str, Any] | None = None,
    ):
        self.clip_rows = clip_rows or []
        self.video_row = video_row

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        if "FROM clips" in sql:
            return _FakeCursor(fetchall_result=self.clip_rows)
        if "FROM videos" in sql:
            return _FakeCursor(fetchone_result=self.video_row)
        return _FakeCursor()


def test_load_mix_edit_clips_raw_fallback_when_no_clips():
    async def _run() -> None:
        db = _FakeDb(
            clip_rows=[],
            video_row={
                "id": "vid-1",
                "file_path": "storage/vid-1/video.mp4",
                "duration": 42.5,
            },
        )
        rows = await _load_mix_edit_clips(db, ["vid-1"])  # type: ignore[arg-type]
        assert len(rows) == 1
        assert rows[0]["id"] == "raw_vid-1"
        assert rows[0]["video_id"] == "vid-1"
        assert rows[0]["clip_path"] == "storage/vid-1/video.mp4"
        assert rows[0]["duration"] == 42.5
        assert rows[0]["asr_text"] is None

    asyncio.run(_run())


def test_load_mix_edit_clips_prefers_real_clips():
    async def _run() -> None:
        clip_row = {
            "id": "c1",
            "video_id": "vid-1",
            "clip_path": "storage/vid-1/clips/000.mp4",
            "start_time": 0.0,
            "duration": 10.0,
            "asr_text": "hello",
            "asr_segments": None,
            "vlm_description": None,
        }
        db = _FakeDb(clip_rows=[clip_row])
        rows = await _load_mix_edit_clips(db, ["vid-1"])  # type: ignore[arg-type]
        assert len(rows) == 1
        assert rows[0]["id"] == "c1"

    asyncio.run(_run())


def test_build_mix_plan_accepts_raw_virtual_clip_row():
    row = {
        "id": "raw_vid-1",
        "video_id": "vid-1",
        "clip_path": "storage/vid-1/video.mp4",
        "start_time": 0.0,
        "duration": 8.0,
        "asr_text": None,
        "asr_segments": None,
        "vlm_description": None,
    }
    from unittest.mock import patch

    with patch("app.core.auto_edit.mix_edit.detect_voice_ranges_by_silencedetect") as mock_detect:
        with patch("app.core.auto_edit.mix_edit.resolve_stored_path") as mock_resolve:
            mock_resolve.return_value = "/tmp/video.mp4"
            mock_detect.return_value = [(0.0, 4.0), (4.5, 8.0)]
            plan = build_mix_edit_plan(clip_rows=[row], mix_audio_mode="keep_original")
    assert len(plan.segments) == 2
    assert plan.segments[0].selected_clip_ids == ["raw_vid-1"]
