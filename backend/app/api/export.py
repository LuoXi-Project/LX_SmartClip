import io
import json
import logging
import os
import subprocess
import tempfile
import zipfile
from urllib.parse import quote
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    clip_ids: List[str] = Field(..., min_length=1, description="要导出的片段 ID 列表")
    project_name: Optional[str] = Field("smartclip_project", description="工程包名称")
    include_audio: bool = Field(True, description="是否包含 TTS 音频文件")
    tts_filenames: Optional[List[str]] = Field(None, description="TTS 音频文件名列表（与 clip_ids 一一对应）")


@router.post("/project")
async def export_project(req: ExportRequest):
    """
    打包导出工程 ZIP：
    - clips/         视频片段文件
    - audio/         TTS 音频文件（如有）
    - project.json   工程元数据（片段信息、文案、描述等）
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        placeholders = ",".join(["?"] * len(req.clip_ids))
        cursor = await db.execute(
            f"""
            SELECT c.id, c.video_id, c.clip_path, c.start_time, c.end_time,
                   c.duration, c.asr_text, c.vlm_description,
                   v.name as video_name
            FROM clips c
            JOIN videos v ON c.video_id = v.id
            WHERE c.id IN ({placeholders})
            ORDER BY c.start_time
            """,
            req.clip_ids,
        )
        clips = await cursor.fetchall()

    if not clips:
        raise HTTPException(status_code=404, detail="未找到任何指定片段")

    buf = io.BytesIO()
    project_meta = {
        "project_name": req.project_name,
        "total_clips": len(clips),
        "clips": [],
    }

    TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, clip in enumerate(clips):
            clip_path = clip["clip_path"]
            clip_filename = os.path.basename(clip_path) if clip_path else f"clip_{i}.mp4"

            clip_entry: dict = {
                "index": i,
                "clip_id": clip["id"],
                "video_id": clip["video_id"],
                "video_name": clip["video_name"],
                "start_time": clip["start_time"],
                "end_time": clip["end_time"],
                "duration": clip["duration"],
                "asr_text": clip["asr_text"],
                "vlm_description": clip["vlm_description"],
                "clip_file": f"clips/{clip_filename}",
                "audio_file": None,
            }

            if clip_path and os.path.isfile(clip_path):
                zf.write(clip_path, f"clips/{clip_filename}")
            else:
                logger.warning("片段文件不存在，跳过: %s", clip_path)

            if req.include_audio and req.tts_filenames and i < len(req.tts_filenames):
                tts_name = req.tts_filenames[i]
                if tts_name:
                    tts_path = os.path.join(TTS_AUDIO_DIR, os.path.basename(tts_name))
                    if os.path.isfile(tts_path):
                        zf.write(tts_path, f"audio/{os.path.basename(tts_name)}")
                        clip_entry["audio_file"] = f"audio/{os.path.basename(tts_name)}"

            project_meta["clips"].append(clip_entry)

        zf.writestr("project.json", json.dumps(project_meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    zip_name = f"{req.project_name}.zip"
    encoded_zip_name = quote(zip_name)
    content_disposition = (
        f'attachment; filename="smartclip_project.zip"; '
        f"filename*=UTF-8''{encoded_zip_name}"
    )
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition},
    )


# ─────────────────── 合并导出：完整带配音视频 ─────────────────── #

class MergedSegment(BaseModel):
    clip_id: str = Field(..., description="视频片段 ID")
    tts_filename: Optional[str] = Field(None, description="对应的 TTS 音频文件名")
    copy_text: Optional[str] = Field(None, description="该段文案（仅元数据）")


class MergeRequest(BaseModel):
    segments: List[MergedSegment] = Field(..., min_length=1)
    project_name: Optional[str] = Field("smartclip_merged", description="输出文件名前缀")


@router.post("/merged")
async def export_merged_video(req: MergeRequest):
    """
    将多段「视频片段 + TTS 音频」合并为一个完整 MP4。
    每段先用 ffmpeg 把 TTS 音频替换原视频音轨，再 concat 拼接所有段。
    依赖：ffmpeg 需在系统 PATH 中。
    """
    TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))

    clip_ids = [s.clip_id for s in req.segments]
    placeholders = ",".join(["?"] * len(clip_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT id, clip_path FROM clips WHERE id IN ({placeholders})",
            clip_ids,
        )
        rows = await cursor.fetchall()

    clip_map = {row["id"]: row["clip_path"] for row in rows}

    with tempfile.TemporaryDirectory() as tmpdir:
        segment_files: List[str] = []

        for i, seg in enumerate(req.segments):
            clip_path = clip_map.get(seg.clip_id)
            if not clip_path or not os.path.isfile(clip_path):
                raise HTTPException(status_code=404, detail=f"片段文件不存在: {seg.clip_id}")

            out_seg = os.path.join(tmpdir, f"seg_{i:03d}.mp4")

            if seg.tts_filename:
                tts_path = os.path.join(TTS_AUDIO_DIR, os.path.basename(seg.tts_filename))
                if os.path.isfile(tts_path):
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", clip_path,
                        "-i", tts_path,
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-shortest",
                        out_seg,
                    ]
                else:
                    cmd = ["ffmpeg", "-y", "-i", clip_path, "-c", "copy", out_seg]
            else:
                cmd = ["ffmpeg", "-y", "-i", clip_path, "-c", "copy", out_seg]

            proc = subprocess.run(cmd, capture_output=True, timeout=120)
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-500:]
                raise HTTPException(status_code=500, detail=f"ffmpeg 合成第 {i + 1} 段失败: {err}")
            segment_files.append(out_seg)

        if len(segment_files) == 1:
            final_path = segment_files[0]
        else:
            concat_list = os.path.join(tmpdir, "concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for sf in segment_files:
                    f.write(f"file '{sf}'\n")
            final_path = os.path.join(tmpdir, "final.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                final_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-500:]
                raise HTTPException(status_code=500, detail=f"ffmpeg 拼接失败: {err}")

        with open(final_path, "rb") as f:
            video_bytes = f.read()

    out_name = f"{req.project_name}.mp4"
    encoded_name = quote(out_name)
    return StreamingResponse(
        io.BytesIO(video_bytes),
        media_type="video/mp4",
        headers={
            "Content-Disposition": (
                f'attachment; filename="smartclip_merged.mp4"; '
                f"filename*=UTF-8''{encoded_name}"
            )
        },
    )
