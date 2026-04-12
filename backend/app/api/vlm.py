from fastapi import APIRouter, HTTPException
from app.db.database import get_db_conn
from app.core.vlm.openai_vlm import OpenAIVLM
from app.api.process_shared import get_splitter
from app.utils.storage_dedupe import strip_leading_material_id_from_clip_basename
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["vlm"])

# 初始化 VLM
vlm = None


def get_vlm(base_url: str, model: str, api_key: str):
    """获取 VLM 实例（单例）"""
    global vlm
    if vlm is None:
        logger.info(f"初始化 OpenAI VLM (model={model})")
        vlm = OpenAIVLM(base_url=base_url, model=model, api_key=api_key)
    return vlm


@router.post("/{video_id}/process-vlm")
async def process_vlm(video_id: str):
    """
    处理视频的所有片段的 VLM 描述
    
    从 config 读取 vlm_provider、vlm_base_url、vlm_model、vlm_api_key 参数
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

        splitter = get_splitter(video_id)

        # 从配置读取 VLM 参数
        config_keys = ["vlm_base_url", "vlm_model", "vlm_api_key"]
        config = {}
        for key in config_keys:
            cursor = await db.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            )
            config_row = await cursor.fetchone()
            config[key] = config_row["value"] if config_row else None

        # 检查必要的配置
        if not config["vlm_api_key"]:
            raise HTTPException(
                status_code=400,
                detail="VLM API Key 未配置，请在设置页面配置",
            )

        base_url = config["vlm_base_url"] or "https://api.openai.com/v1"
        model = config["vlm_model"] or "gpt-4o"

        async def _read_cfg(key: str, default: str) -> str:
            c = await db.execute(
                "SELECT value FROM config WHERE key = ?", (key,)
            )
            r = await c.fetchone()
            if r and r["value"] is not None and str(r["value"]).strip() != "":
                return str(r["value"])
            return default

        fps_raw = await _read_cfg("frame_fps", "1")
        px_raw = await _read_cfg("frame_target_pixels", "0")
        try:
            frame_fps = float(fps_raw)
        except (TypeError, ValueError):
            frame_fps = 1.0
        try:
            frame_target_pixels = int(float(px_raw))
        except (TypeError, ValueError):
            frame_target_pixels = 0

        # 获取 VLM 实例
        vlm_instance = get_vlm(base_url, model, config["vlm_api_key"])

        # 查询视频的所有片段
        cursor = await db.execute(
            "SELECT id, clip_path FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")

        logger.info(f"开始处理 {len(clips)} 个片段的 VLM 描述")

        # 处理每个片段
        results = []
        for i, clip in enumerate(clips):
            clip_id = clip["id"]
            clip_path = clip["clip_path"]

            try:
                logger.info(f"处理片段 {i+1}/{len(clips)}: {clip_id}")

                # 与 extract_frames 一致：帧目录名对 clip basename 去前导素材 id
                bn = os.path.basename(clip_path)
                bn2 = strip_leading_material_id_from_clip_basename(video_id, bn)
                clip_stem = os.path.splitext(bn2)[0]
                frames_dir = os.path.join(splitter.frames_dir, clip_stem)

                if not os.path.exists(frames_dir):
                    # 如果帧不存在，按配置帧率抽帧（与全处理流水线一致）
                    logger.info("帧不存在，正在抽帧...")
                    frame_paths = splitter.extract_frames(
                        clip_path, fps=frame_fps, target_pixels=frame_target_pixels
                    )
                else:
                    # 获取已有的帧
                    frame_paths = sorted(
                        [
                            os.path.join(frames_dir, f)
                            for f in os.listdir(frames_dir)
                            if f.lower().endswith((".jpg", ".png"))
                        ]
                    )

                if not frame_paths:
                    logger.warning(f"片段 {clip_id} 没有帧，跳过")
                    results.append(
                        {
                            "clip_id": clip_id,
                            "status": "skipped",
                            "reason": "没有帧",
                        }
                    )
                    continue

                # 与 extract_frames 一致的片内时间轴；在 VLM 请求中注入 [t second]
                frame_times_sec = splitter.frame_timestamps_in_clip(
                    clip_path, len(frame_paths)
                )
                description = vlm_instance.generate_description(
                    frame_paths, frame_times_sec
                )

                # 保存到数据库
                await db.execute(
                    "UPDATE clips SET vlm_description = ? WHERE id = ?",
                    (description, clip_id),
                )

                results.append(
                    {
                        "clip_id": clip_id,
                        "status": "success",
                        "description_length": len(description),
                        "description": description[:500]
                        + "..."
                        if len(description) > 500
                        else description,
                    }
                )

                logger.info(f"片段 {clip_id} VLM 成功: {len(description)} 个字符")

            except Exception as e:
                logger.error(f"片段 {clip_id} VLM 失败: {e}")
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
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"VLM 处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"VLM 处理失败: {str(e)}")
    finally:
        await db.close()


@router.get("/vlm/info")
async def get_vlm_info():
    """获取 VLM 模型信息"""
    db = await get_db_conn()
    try:
        # 从配置读取 VLM 参数
        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("vlm_model",)
        )
        model_row = await cursor.fetchone()
        model = model_row["value"] if model_row else "gpt-4o"

        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", ("vlm_base_url",)
        )
        base_url_row = await cursor.fetchone()
        base_url = base_url_row["value"] if base_url_row else "https://api.openai.com/v1"

        return {
            "provider": "openai",
            "model": model,
            "base_url": base_url,
            "type": "vision",
        }
    except Exception as e:
        logger.error(f"获取 VLM 信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取 VLM 信息失败: {str(e)}")
    finally:
        await db.close()
