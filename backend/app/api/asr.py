from fastapi import APIRouter, HTTPException
from app.db.database import get_db_conn
from app.core.asr.whisper_asr import WhisperASR
from app.core.splitter import VideoSplitter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["asr"])

# 初始化 ASR 和 Splitter
asr = None
splitter = VideoSplitter()


def get_asr(model_size: str = "base"):
    """获取 ASR 实例（单例）"""
    global asr
    if asr is None:
        logger.info(f"初始化 Whisper ASR (model_size={model_size})")
        asr = WhisperASR(model_size=model_size)
    return asr


@router.post("/{video_id}/process-asr")
async def process_asr(video_id: str):
    """
    处理视频的所有片段的 ASR
    
    从 config 读取 asr_model 参数
    """
    db = await get_db_conn()
    try:
        # 查询视频
        cursor = await db.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        # 从配置读取 ASR 模型大小
        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("asr_model",)
        )
        model_row = await cursor.fetchone()
        model_size = model_row["value"] if model_row else "base"

        # 获取 ASR 实例
        asr_instance = get_asr(model_size)

        # 查询视频的所有片段
        cursor = await db.execute(
            "SELECT id, clip_path FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")

        logger.info(f"开始处理 {len(clips)} 个片段的 ASR")

        # 处理每个片段
        results = []
        for i, clip in enumerate(clips):
            clip_id = clip["id"]
            clip_path = clip["clip_path"]

            try:
                logger.info(f"处理片段 {i+1}/{len(clips)}: {clip_id}")

                # 提取音频
                audio_path = splitter.extract_audio(clip_path)

                # 转写音频
                asr_text = asr_instance.transcribe(audio_path)

                # 保存到数据库
                await db.execute(
                    "UPDATE clips SET asr_text = ? WHERE id = ?",
                    (asr_text, clip_id),
                )

                results.append(
                    {
                        "clip_id": clip_id,
                        "status": "success",
                        "text_length": len(asr_text),
                        "text": asr_text[:100] + "..." if len(asr_text) > 100 else asr_text,
                    }
                )

                logger.info(f"片段 {clip_id} ASR 成功: {len(asr_text)} 个字符")

            except Exception as e:
                logger.error(f"片段 {clip_id} ASR 失败: {e}")
                results.append(
                    {
                        "clip_id": clip_id,
                        "status": "error",
                        "error": str(e),
                    }
                )

        # 提交数据库更改
        await db.commit()

        return {
            "video_id": video_id,
            "total_clips": len(clips),
            "processed": sum(1 for r in results if r["status"] == "success"),
            "failed": sum(1 for r in results if r["status"] == "error"),
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ASR 处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"ASR 处理失败: {str(e)}")
    finally:
        await db.close()


@router.get("/asr/info")
async def get_asr_info():
    """获取 ASR 模型信息"""
    try:
        asr_instance = get_asr()
        return asr_instance.get_model_info()
    except Exception as e:
        logger.error(f"获取 ASR 信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 ASR 信息失败: {str(e)}")
