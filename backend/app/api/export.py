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
from app.models.export import ExportRequest

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])



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

