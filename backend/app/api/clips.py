import uuid
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.db.database import get_db_conn
from app.core.splitter import VideoSplitter
from app.models.clips import ClipUpdatePayload
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])
splitter = VideoSplitter()


async def _get_config_value(db, key: str, default: str) -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row and row["value"] is not None else default


@router.post("/{video_id}/extract-audio")
async def extract_audio(video_id: str):
    """提取视频音频"""
    db = await get_db_conn()
    try:
        # 查询视频
        cursor = await db.execute(
            "SELECT file_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        video_path = row["file_path"]

        # 提取音频
        audio_path = splitter.extract_audio(video_path)

        return {"video_id": video_id, "audio_path": audio_path}
    except Exception as e:
        logger.error(f"提取音频失败: {e}")
        raise HTTPException(status_code=500, detail=f"提取音频失败: {str(e)}")
    finally:
        await db.close()


@router.post("/{video_id}/split")
async def split_video(video_id: str):
    """
    切分视频

    支持三种模式：
    - scene: 镜头识别切分
    - fixed: 固定时长切分
    - hybrid: 混合（镜头识别 + 超长镜头按固定步长强制切段）
    """
    db = await get_db_conn()
    try:
        # 查询视频
        cursor = await db.execute(
            "SELECT file_path, split_mode FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        video_path = row["file_path"]
        split_mode = row["split_mode"]

        # 从配置读取参数
        scene_threshold = float(await _get_config_value(db, "scene_threshold", "30.0"))
        scene_min_scene_len = int(await _get_config_value(db, "scene_min_scene_len", "30"))
        fixed_duration = float(await _get_config_value(db, "fixed_duration", "10"))
        hybrid_max_segment_sec = float(
            await _get_config_value(db, "hybrid_max_segment_sec", "60")
        )

        # 切分输出转码参数（由前端设置）
        transcode_opts = {
            "clip_container": await _get_config_value(db, "clip_container", "mp4"),
            "clip_vcodec": await _get_config_value(db, "clip_vcodec", "libx264"),
            "clip_acodec": await _get_config_value(db, "clip_acodec", "aac"),
            "clip_preset": await _get_config_value(db, "clip_preset", "veryfast"),
            "clip_crf": await _get_config_value(db, "clip_crf", "23"),
            "clip_video_bitrate_kbps": await _get_config_value(db, "clip_video_bitrate_kbps", "0"),
            "clip_audio_bitrate_kbps": await _get_config_value(db, "clip_audio_bitrate_kbps", "128"),
            "clip_fps": await _get_config_value(db, "clip_fps", "0"),
            "clip_scale_width": await _get_config_value(db, "clip_scale_width", "0"),
            "clip_scale_height": await _get_config_value(db, "clip_scale_height", "0"),
            "clip_pix_fmt": await _get_config_value(db, "clip_pix_fmt", "yuv420p"),
        }

        # 执行切分
        if split_mode == "scene":
            clips = splitter.split_by_scene(
                video_path,
                scene_threshold,
                scene_min_scene_len,
                transcode_opts=transcode_opts,
            )
        elif split_mode == "fixed":
            clips = splitter.split_by_fixed(
                video_path,
                fixed_duration,
                transcode_opts=transcode_opts,
            )
        elif split_mode == "hybrid":
            clips = splitter.split_by_hybrid(
                video_path,
                scene_threshold,
                scene_min_scene_len,
                hybrid_max_segment_sec,
                fixed_duration,
                transcode_opts=transcode_opts,
            )
        else:
            raise HTTPException(status_code=400, detail=f"不支持的切分模式: {split_mode}")

        # 保存片段到数据库
        for clip in clips:
            clip_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_id,
                    video_id,
                    clip.clip_path,
                    clip.start_time,
                    clip.end_time,
                    clip.duration,
                ),
            )

        # 更新视频记录
        await db.execute(
            "UPDATE videos SET total_clips = ?, status = ? WHERE id = ?",
            (len(clips), "processing", video_id),
        )
        await db.commit()

        return {
            "video_id": video_id,
            "split_mode": split_mode,
            "total_clips": len(clips),
            "clips": [clip.to_dict() for clip in clips],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"切分视频失败: {e}")
        raise HTTPException(status_code=500, detail=f"切分视频失败: {str(e)}")
    finally:
        await db.close()


@router.post("/{video_id}/extract-frames")
async def extract_frames(video_id: str, fps: float | None = None, target_pixels: int | None = None):
    """
    为视频的所有片段抽取帧

    Args:
        video_id: 视频 ID
        fps: 抽帧帧率（覆盖配置，可选）
        target_pixels: 抽帧目标像素（覆盖配置，可选）
    """
    db = await get_db_conn()
    try:
        # 查询视频的所有片段
        cursor = await db.execute(
            "SELECT id, clip_path FROM clips WHERE video_id = ?", (video_id,)
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")

        cfg_fps = float(await _get_config_value(db, "frame_fps", "1"))
        cfg_px = int(await _get_config_value(db, "frame_target_pixels", "512"))
        use_fps = float(fps) if fps is not None else cfg_fps
        use_px = int(target_pixels) if target_pixels is not None else cfg_px

        # 为每个片段抽取帧
        results = []
        for clip in clips:
            clip_id = clip["id"]
            clip_path = clip["clip_path"]

            try:
                frame_paths = splitter.extract_frames(clip_path, fps=use_fps, target_pixels=use_px)
                results.append(
                    {
                        "clip_id": clip_id,
                        "frame_count": len(frame_paths),
                        "frames": frame_paths,
                    }
                )
            except Exception as e:
                logger.error(f"抽取片段 {clip_id} 的帧失败: {e}")
                results.append(
                    {
                        "clip_id": clip_id,
                        "error": str(e),
                    }
                )

        return {
            "video_id": video_id,
            "total_clips": len(clips),
            "fps": use_fps,
            "target_pixels": use_px,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"抽取帧失败: {e}")
        raise HTTPException(status_code=500, detail=f"抽取帧失败: {str(e)}")
    finally:
        await db.close()


@router.get("/{video_id}/clips")
async def get_clips(video_id: str):
    """获取视频的所有片段"""
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, clip_path, start_time, end_time, duration, asr_text, asr_segments, vlm_description FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        return [
            {
                "id": clip["id"],
                "clip_path": clip["clip_path"],
                "start_time": clip["start_time"],
                "end_time": clip["end_time"],
                "duration": clip["duration"],
                "asr_text": clip["asr_text"],
                "asr_segments": clip["asr_segments"],
                "vlm_description": clip["vlm_description"],
            }
            for clip in clips
        ]
    except Exception as e:
        logger.error(f"获取片段失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取片段失败: {str(e)}")
    finally:
        await db.close()


@router.get("/clips/{clip_id}/stream")
async def stream_clip(clip_id: str):
    """流式预览单个视频片段"""
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT clip_path FROM clips WHERE id = ?",
            (clip_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"片段 '{clip_id}' 不存在")
        clip_path = row["clip_path"]
    finally:
        await db.close()

    if not clip_path or not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="片段文件不存在")

    ext = os.path.splitext(clip_path)[1].lower()
    _mime_map = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg",
    }
    media_type = _mime_map.get(ext, "video/mp4")
    return FileResponse(clip_path, media_type=media_type, filename=os.path.basename(clip_path))


@router.get("/clips/{clip_id}")
async def get_clip_meta(clip_id: str):
    """获取 clip 元信息（用于前端把 clip 关联回原视频）"""
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, video_id, start_time, end_time, duration FROM clips WHERE id = ?",
            (clip_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"片段 '{clip_id}' 不存在")
        return {
            "clip_id": str(row["id"]),
            "video_id": str(row["video_id"]),
            "start_time": float(row["start_time"]),
            "end_time": float(row["end_time"]),
            "duration": float(row["duration"]),
        }
    finally:
        await db.close()


@router.patch("/clips/{clip_id}")
async def update_clip_result(clip_id: str, payload: ClipUpdatePayload):
    """更新 clip 的 ASR / VLM 结果（用于人工纠错）"""
    if (
        payload.asr_text is None
        and payload.asr_segments is None
        and payload.vlm_description is None
    ):
        raise HTTPException(
            status_code=400,
            detail="至少提供一个字段：asr_text、asr_segments 或 vlm_description",
        )

    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT id FROM clips WHERE id = ?", (clip_id,))
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"片段 '{clip_id}' 不存在")

        sets: list[str] = []
        params: list = []
        if payload.asr_text is not None:
            sets.append("asr_text = ?")
            params.append(payload.asr_text)
        if payload.asr_segments is not None:
            sets.append("asr_segments = ?")
            params.append(payload.asr_segments)
        if payload.vlm_description is not None:
            sets.append("vlm_description = ?")
            params.append(payload.vlm_description)

        params.append(clip_id)
        await db.execute(f"UPDATE clips SET {', '.join(sets)} WHERE id = ?", tuple(params))
        await db.commit()

        return {"ok": True, "clip_id": clip_id}
    finally:
        await db.close()
