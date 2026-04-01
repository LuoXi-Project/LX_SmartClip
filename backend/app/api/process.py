import asyncio
import logging
import os
import uuid
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.db.database import get_db_conn, DB_PATH
from app.core.splitter import VideoSplitter
from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.core.license import ensure_license_valid, is_license_enforced

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["process"])
splitter = VideoSplitter()

STEP_LABELS = {
    "split":          "视频切分",
    "extract_frames": "图帧提取",
    "asr":            "语音识别 (ASR)",
    "vlm":            "视觉描述 (VLM)",
    "embed":          "向量入库",
}


async def _read_config(db, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


class ProgressReporter:
    """向 WebSocket 推送进度；无 WebSocket 时仅记录日志"""

    def __init__(self, ws: WebSocket = None):
        self.ws = ws

    async def send(self, step: str, status: str, message: str, detail: dict = None):
        payload = {
            "step":    step,
            "status":  status,
            "message": message,
            "detail":  detail or {},
        }
        logger.info("[%s] %s: %s", step, status, message)
        if self.ws:
            try:
                await self.ws.send_json(payload)
            except Exception:
                pass


async def _set_video_status(video_id: str, status: str):
    db = await get_db_conn()
    try:
        await db.execute("UPDATE videos SET status = ? WHERE id = ?", (status, video_id))
        await db.commit()
    finally:
        await db.close()


async def _get_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


async def _get_clips(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, clip_path, asr_text, vlm_description FROM clips "
            "WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        return await cursor.fetchall()
    finally:
        await db.close()


async def _update_clip_field(clip_id: str, field: str, value: str):
    db = await get_db_conn()
    try:
        await db.execute(f"UPDATE clips SET {field} = ? WHERE id = ?", (value, clip_id))
        await db.commit()
    finally:
        await db.close()


async def _save_clips_to_db(video_id: str, clips):
    """将 ClipInfo 列表写入 clips 表"""
    db = await get_db_conn()
    try:
        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        for clip in clips:
            cid = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, video_id, clip.clip_path, clip.start_time, clip.end_time, clip.duration),
            )
        await db.execute(
            "UPDATE videos SET total_clips = ? WHERE id = ?", (len(clips), video_id)
        )
        await db.commit()
    finally:
        await db.close()


async def _run_pipeline(video_id: str, reporter: ProgressReporter, skip_steps: list = None):
    """串联执行全素材处理：split -> frames -> asr -> vlm -> embed"""
    skip_steps = skip_steps or []

    video = await _get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

    video_path = video["file_path"]
    await _set_video_status(video_id, "processing")

    # 读取全部配置
    db = await get_db_conn()
    try:
        split_mode      = await _read_config(db, "split_mode", "scene")
        scene_threshold = float(await _read_config(db, "scene_threshold", "0.4"))
        fixed_duration  = float(await _read_config(db, "fixed_duration", "10"))
        asr_provider    = await _read_config(db, "asr_provider", "whisper")
        asr_model       = await _read_config(db, "asr_model", "base")
        asr_base_url    = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key     = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        vlm_base_url    = await _read_config(db, "vlm_base_url", "https://api.openai.com/v1")
        vlm_model       = await _read_config(db, "vlm_model", "gpt-4o")
        vlm_api_key     = await _read_config(db, "vlm_api_key", "")
        vector_dim      = int(await _read_config(db, "vector_dimension", "1536"))
        frame_fps       = float(await _read_config(db, "frame_fps", "1"))
        frame_target_pixels = int(await _read_config(db, "frame_target_pixels", "0"))
        vlm_max_images    = int(await _read_config(db, "vlm_max_images_per_batch", "10"))
        vlm_context_length = int(await _read_config(db, "vlm_context_length", "8192"))
        vlm_concurrency  = int(await _read_config(db, "vlm_concurrency", "3"))
        embedding_base_url = await _read_config(db, "embedding_base_url", "https://api.openai.com/v1")
        embedding_api_key  = await _read_config(db, "embedding_api_key", "")
        embedding_model    = await _read_config(db, "embedding_model", "text-embedding-3-small")
    finally:
        await db.close()

    loop = asyncio.get_event_loop()

    # STEP 1: 视频切分
    if "split" not in skip_steps:
        await reporter.send("split", "running", f"开始切分视频（模式：{split_mode})")
        try:
            if split_mode == "fixed":
                clips = await loop.run_in_executor(
                    None, splitter.split_by_fixed, video_path, fixed_duration
                )
            else:
                clips = await loop.run_in_executor(
                    None, splitter.split_by_scene, video_path, scene_threshold
                )
            await _save_clips_to_db(video_id, clips)
            await reporter.send(
                "split", "done", f"切分完成，共 {len(clips)} 个片段",
                {"total_clips": len(clips)},
            )
        except Exception as e:
            await reporter.send("split", "error", f"切分失败: {e}")
            await _set_video_status(video_id, "error")
            raise
    else:
        await reporter.send("split", "skip", "跳过视频切分")

    clips_rows = await _get_clips(video_id)
    if not clips_rows:
        await reporter.send("extract_frames", "error", "没有可处理的片段")
        await _set_video_status(video_id, "error")
        return

    # STEP 2: 图帧提取
    if "extract_frames" not in skip_steps:
        await reporter.send("extract_frames", "running", f"开始为 {len(clips_rows)} 个片段抽帧（{frame_fps} 帧/秒）")
        frame_errors = 0
        for clip in clips_rows:
            try:
                await loop.run_in_executor(None, splitter.extract_frames, clip["clip_path"], frame_fps, frame_target_pixels)
            except Exception as e:
                logger.warning("片段 %s 抽帧失败: %s", clip["id"], e)
                frame_errors += 1
        await reporter.send(
            "extract_frames", "done", f"抽帧完成，失败 {frame_errors} 个",
            {"total": len(clips_rows), "errors": frame_errors},
        )
    else:
        await reporter.send("extract_frames", "skip", "跳过图帧提取")

    # STEP 3: ASR
    if "asr" not in skip_steps:
        try:
            if asr_provider == "openai":
                await reporter.send("asr", "running", f"使用 OpenAI ASR ({asr_openai_model}) 开始语音识别...")
                from app.core.asr.openai_asr import OpenAIASR
                asr_instance = OpenAIASR(
                    base_url=asr_base_url,
                    api_key=asr_api_key,
                    model=asr_openai_model,
                )
            else:
                await reporter.send("asr", "running", f"加载 Whisper ({asr_model}) 开始语音识别...")
                from app.core.asr.whisper_asr import WhisperASR
                asr_instance = await loop.run_in_executor(None, WhisperASR, asr_model)
            processed_asr = 0
            for i, clip in enumerate(clips_rows):
                clip_id   = clip["id"]
                clip_path = clip["clip_path"]
                try:
                    audio_path = await loop.run_in_executor(
                        None, splitter.extract_audio, clip_path, True
                    )
                    text = await loop.run_in_executor(
                        None, asr_instance.transcribe, audio_path
                    )
                    await _update_clip_field(clip_id, "asr_text", text)
                    processed_asr += 1
                    await reporter.send(
                        "asr", "running",
                        f"ASR {i+1}/{len(clips_rows)} 完成",
                        {"current": i + 1, "total": len(clips_rows)},
                    )
                except Exception as e:
                    logger.warning("片段 %s ASR 失败: %s", clip_id, e)
            await reporter.send(
                "asr", "done",
                f"语音识别完成，成功 {processed_asr}/{len(clips_rows)} 个",
                {"processed": processed_asr, "total": len(clips_rows)},
            )
        except Exception as e:
            await reporter.send("asr", "error", f"ASR 初始化失败: {e}")
    else:
        await reporter.send("asr", "skip", "跳过语音识别")

    # STEP 4: VLM
    if "vlm" not in skip_steps:
        if not vlm_api_key:
            await reporter.send("vlm", "skip", "VLM API Key 未配置，跳过")
        else:
            await reporter.send("vlm", "running", f"使用 {vlm_model} 生成视觉描述...")
            try:
                from app.core.vlm.openai_vlm import OpenAIVLM
                vlm_instance = OpenAIVLM(
                    base_url=vlm_base_url, model=vlm_model, api_key=vlm_api_key
                )
                clips_rows = await _get_clips(video_id)
                processed_vlm = 0
                sem = asyncio.Semaphore(max(1, vlm_concurrency))

                async def _process_clip_vlm(i: int, clip):
                    nonlocal processed_vlm
                    clip_id   = clip["id"]
                    clip_path = clip["clip_path"]
                    async with sem:
                        try:
                            clip_name  = os.path.splitext(os.path.basename(clip_path))[0]
                            frames_dir = os.path.join(splitter.frames_dir, clip_name)
                            if os.path.isdir(frames_dir):
                                frame_paths = sorted(
                                    os.path.join(frames_dir, f)
                                    for f in os.listdir(frames_dir)
                                    if f.lower().endswith((".jpg", ".png"))
                                )
                            else:
                                frame_paths = await loop.run_in_executor(
                                    None, splitter.extract_frames, clip_path, frame_fps, frame_target_pixels
                                )
                            if not frame_paths:
                                return
                            description = await loop.run_in_executor(
                                None, vlm_instance.generate_description, frame_paths, vlm_max_images, vlm_context_length
                            )
                            await _update_clip_field(clip_id, "vlm_description", description)
                            processed_vlm += 1
                            await reporter.send(
                                "vlm", "running",
                                f"VLM {i+1}/{len(clips_rows)} 完成",
                                {"current": i + 1, "total": len(clips_rows)},
                            )
                        except Exception as e:
                            logger.warning("片段 %s VLM 失败: %s", clip_id, e)

                await asyncio.gather(*[
                    _process_clip_vlm(i, clip) for i, clip in enumerate(clips_rows)
                ])
                await reporter.send(
                    "vlm", "done",
                    f"视觉描述完成，成功 {processed_vlm}/{len(clips_rows)} 个（并发={vlm_concurrency})",
                    {"processed": processed_vlm, "total": len(clips_rows)},
                )
            except Exception as e:
                await reporter.send("vlm", "error", f"VLM 失败: {e}")
    else:
        await reporter.send("vlm", "skip", "跳过视觉描述")

    # STEP 5: Embedding 入库
    if "embed" not in skip_steps:
        if not embedding_api_key:
            await reporter.send("embed", "skip", "Embedding API Key 未配置，跳过向量入库")
        else:
            await reporter.send("embed", "running", "开始生成 Embedding 并入库...")
            try:
                embedder  = Embedder(base_url=embedding_base_url, api_key=embedding_api_key, model=embedding_model)
                vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)
                clips_rows = await _get_clips(video_id)
                processed_emb = 0
                for i, clip in enumerate(clips_rows):
                    clip_id  = clip["id"]
                    text     = ((clip["asr_text"] or "") + " " + (clip["vlm_description"] or "")).strip()
                    if not text:
                        continue
                    try:
                        embedding = await loop.run_in_executor(None, embedder.embed, text)
                        vector_db.add_embedding(clip_id, embedding)
                        processed_emb += 1
                        await reporter.send(
                            "embed", "running",
                            f"Embedding {i+1}/{len(clips_rows)} 入库",
                            {"current": i + 1, "total": len(clips_rows)},
                        )
                    except Exception as e:
                        logger.warning("片段 %s Embedding 失败: %s", clip_id, e)
                await reporter.send(
                    "embed", "done",
                    f"向量入库完成，成功 {processed_emb}/{len(clips_rows)} 个（model={embedding_model})",
                    {"processed": processed_emb, "total": len(clips_rows)},
                )
            except Exception as e:
                await reporter.send("embed", "error", f"Embedding 失败: {e}")
    else:
        await reporter.send("embed", "skip", "跳过向量入库")

    await _set_video_status(video_id, "done")
    await reporter.send("done", "done", "全部处理完成！")


# HTTP 接口：POST /api/videos/{id}/process
@router.post("/{video_id}/process")
async def process_video_http(video_id: str):
    """一键处理接口（HTTP），串联执行所有处理步骤。"""
    reporter = ProgressReporter(ws=None)
    try:
        await _run_pipeline(video_id, reporter)
        return {"video_id": video_id, "status": "done", "message": "处理完成"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


# WebSocket 接口：WS /api/videos/{id}/process-ws
@router.websocket("/{video_id}/process-ws")
async def process_video_ws(video_id: str, ws: WebSocket):
    """
    WebSocket 处理接口，实时推送每步进度。
    消息格式: {"step": str, "status": str, "message": str, "detail": dict}
    客户端可在连接后发送: {"skip_steps": ["vlm", "embed"]}
    """
    await ws.accept()
    if is_license_enforced() and not await ensure_license_valid():
        await ws.close(code=1008, reason="LICENSE_REQUIRED")
        return
    reporter = ProgressReporter(ws=ws)

    skip_steps = []
    try:
        data = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
        skip_steps = data.get("skip_steps", [])
    except (asyncio.TimeoutError, Exception):
        pass

    try:
        await _run_pipeline(video_id, reporter, skip_steps=skip_steps)
    except WebSocketDisconnect:
        logger.info("WebSocket 断开: video_id=%s", video_id)
    except HTTPException as e:
        await reporter.send("error", "error", e.detail)
    except Exception as e:
        await reporter.send("error", "error", f"处理异常: {str(e)}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass
