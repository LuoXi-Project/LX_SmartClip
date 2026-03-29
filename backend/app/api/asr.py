from fastapi import APIRouter, HTTPException
from app.db.database import get_db_conn
from app.core.asr.whisper_asr import WhisperASR
from app.core.asr.openai_asr import OpenAIASR
from app.core.splitter import VideoSplitter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["asr"])

# ASR 单例缓存（key = provider+model_size/model）
_asr_cache: dict = {}
splitter = VideoSplitter()


def _cache_key(provider: str, **kwargs) -> str:
    return "|".join([provider] + [f"{k}={v}" for k, v in sorted(kwargs.items())])


def get_asr(provider: str = "whisper", model_size: str = "base",
            base_url: str = "", api_key: str = "", model: str = "whisper-1"):
    """获取 ASR 实例（带缓存）"""
    key = _cache_key(provider, model_size=model_size, base_url=base_url, model=model)
    if key not in _asr_cache:
        if provider == "openai":
            logger.info("初始化 OpenAI ASR (base_url=%s, model=%s)", base_url, model)
            _asr_cache[key] = OpenAIASR(base_url=base_url, api_key=api_key, model=model)
        else:
            logger.info("初始化 Whisper ASR (model_size=%s)", model_size)
            _asr_cache[key] = WhisperASR(model_size=model_size)
    return _asr_cache[key]


async def _read_config(db, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


@router.post("/{video_id}/process-asr")
async def process_asr(video_id: str):
    """
    处理视频的所有片段的 ASR

    从 config 读取 asr_provider、asr_model（whisper 模型大小）、
    asr_base_url、asr_api_key、asr_openai_model 参数
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

        # 读取 ASR 配置
        asr_provider   = await _read_config(db, "asr_provider", "whisper")
        model_size     = await _read_config(db, "asr_model", "base")
        asr_base_url   = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key    = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")

        # 获取 ASR 实例
        asr_instance = get_asr(
            provider=asr_provider,
            model_size=model_size,
            base_url=asr_base_url,
            api_key=asr_api_key,
            model=asr_openai_model,
        )

        # 查询视频的所有片段
        cursor = await db.execute(
            "SELECT id, clip_path FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")

        logger.info("开始处理 %d 个片段的 ASR (provider=%s)", len(clips), asr_provider)

        # 处理每个片段
        results = []
        for i, clip in enumerate(clips):
            clip_id = clip["id"]
            clip_path = clip["clip_path"]

            try:
                logger.info("处理片段 %d/%d: %s", i + 1, len(clips), clip_id)

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

                logger.info("片段 %s ASR 成功: %d 个字符", clip_id, len(asr_text))

            except Exception as e:
                logger.error("片段 %s ASR 失败: %s", clip_id, e)
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
        logger.error("ASR 处理失败: %s", e)
        raise HTTPException(status_code=500, detail=f"ASR 处理失败: {str(e)}")
    finally:
        await db.close()


@router.get("/asr/info")
async def get_asr_info():
    """获取当前 ASR 配置信息"""
    from app.db.database import get_db_conn as _get
    db = await _get()
    try:
        asr_provider     = await _read_config(db, "asr_provider", "whisper")
        model_size       = await _read_config(db, "asr_model", "base")
        asr_base_url     = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key      = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
    finally:
        await db.close()

    return {
        "provider": asr_provider,
        "model_size": model_size,
        "asr_base_url": asr_base_url,
        "asr_openai_model": asr_openai_model,
    }
