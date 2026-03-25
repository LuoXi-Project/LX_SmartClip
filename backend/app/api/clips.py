import uuid
from fastapi import APIRouter, HTTPException
from app.db.database import get_db_conn
from app.core.splitter import VideoSplitter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])
splitter = VideoSplitter()


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
    
    支持两种模式：
    - scene: 镜头识别切分
    - fixed: 固定时长切分
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
        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("scene_threshold",)
        )
        threshold_row = await cursor.fetchone()
        scene_threshold = float(threshold_row["value"]) if threshold_row else 30.0

        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("scene_min_scene_len",)
        )
        min_scene_len_row = await cursor.fetchone()
        scene_min_scene_len = int(min_scene_len_row["value"]) if min_scene_len_row else 30

        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("fixed_duration",)
        )
        duration_row = await cursor.fetchone()
        fixed_duration = float(duration_row["value"]) if duration_row else 10

        # 执行切分
        if split_mode == "scene":
            clips = splitter.split_by_scene(video_path, scene_threshold, scene_min_scene_len)
        elif split_mode == "fixed":
            clips = splitter.split_by_fixed(video_path, fixed_duration)
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
async def extract_frames(video_id: str, n_frames: int = 3):
    """
    为视频的所有片段抽取帧
    
    Args:
        video_id: 视频 ID
        n_frames: 每个片段抽取的帧数
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

        # 为每个片段抽取帧
        results = []
        for clip in clips:
            clip_id = clip["id"]
            clip_path = clip["clip_path"]

            try:
                frame_paths = splitter.extract_frames(clip_path, n_frames)
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
            "SELECT id, clip_path, start_time, end_time, duration, asr_text, vlm_description FROM clips WHERE video_id = ? ORDER BY start_time",
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
                "vlm_description": clip["vlm_description"],
            }
            for clip in clips
        ]
    except Exception as e:
        logger.error(f"获取片段失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取片段失败: {str(e)}")
    finally:
        await db.close()
