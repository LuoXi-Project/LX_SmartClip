"""视频生成空镜兜底（检索无强匹配时用文生视频补画面）。

协议按 SiliconFlow 风格的「提交 → 轮询 → 下载」三步实现（Wan/Kling 系托管
模型多为同构 REST），仅依赖 base_url + api_key + model 三个配置：
  POST {base}/v1/video/submissions  {"model","prompt",...}        -> {"id"}
  GET  {base}/v1/video/status?id=…  {"status":"SUCCEEDED","results":{"videos":[{"url"}]}}

生成产物落盘 storage/generated/，并注册成 videos+clips 两行（vlm_description
= 生成提示词），使其与普通素材走同一条 clip_id 链路——计划/导出/剪映草稿
无需感知差异。所有失败路径都返回 None，绝不阻塞匹配主流程。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Mapping, Optional

import requests

from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC = 5.0
_DOWNLOAD_TIMEOUT_SEC = 300


def _headers(cfg: Mapping) -> dict:
    return {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }


def submit_video_task(cfg: Mapping, prompt: str, *, duration_sec: float = 5.0) -> str:
    """提交文生视频任务，返回任务 id。"""
    base = str(cfg["base_url"]).rstrip("/")
    payload: dict = {"model": cfg["model"], "prompt": prompt}
    if duration_sec and duration_sec > 0:
        payload["duration"] = int(round(float(duration_sec)))
    resp = requests.post(
        f"{base}/v1/video/submissions",
        json=payload,
        headers=_headers(cfg),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    task_id = str(data.get("id") or data.get("request_id") or "").strip()
    if not task_id:
        raise RuntimeError(f"视频生成提交响应缺少任务 id: {data}")
    logger.info("[VideoGen] 提交成功 task_id=%s prompt=%s", task_id, prompt[:40])
    return task_id


def poll_video_url(cfg: Mapping, task_id: str, *, timeout_sec: float = 600.0) -> str:
    """轮询任务状态直到完成，返回视频下载 URL。"""
    base = str(cfg["base_url"]).rstrip("/")
    deadline = time.monotonic() + max(60.0, float(timeout_sec))
    last_status = ""
    while time.monotonic() < deadline:
        resp = requests.get(
            f"{base}/v1/video/status",
            params={"id": task_id},
            headers=_headers(cfg),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = str(data.get("status") or "").upper()
        last_status = status
        if status in ("SUCCEEDED", "SUCCESS", "COMPLETED"):
            videos = (data.get("results") or {}).get("videos") or data.get("videos") or []
            for v in videos:
                url = str((v or {}).get("url") or "").strip()
                if url:
                    return url
            raise RuntimeError(f"视频生成已完成但无下载地址: {data}")
        if status in ("FAILED", "CANCELLED", "ERROR"):
            raise RuntimeError(f"视频生成失败 status={status}: {data}")
        time.sleep(_POLL_INTERVAL_SEC)
    raise TimeoutError(f"视频生成轮询超时（最后状态 {last_status}）")


def download_video(url: str, dest_dir: str) -> str:
    """流式下载视频到 dest_dir，返回绝对路径。"""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"gen_{uuid.uuid4().hex[:12]}.mp4")
    with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT_SEC) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
    if not os.path.isfile(dest) or os.path.getsize(dest) < 1024:
        raise RuntimeError(f"视频下载产物异常: {dest}")
    return dest


def register_generated_clip(db_conn, abs_path: str, prompt: str, duration_sec: float) -> dict:
    """把生成的空镜注册成 videos+clips 行，返回与 Matcher 候选同构的 clip dict。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    video_id = f"gen-{uuid.uuid4().hex[:12]}"
    clip_id = f"genclip-{uuid.uuid4().hex[:12]}"
    dur = max(1.0, float(duration_sec or 5.0))

    db_conn.execute(
        "INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, "
        "split_mode, status, is_replica_ref, upload_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (video_id, f"AI 生成 · {prompt[:24]}", abs_path, None, dur, 1, "none", "done", 0, now),
    )
    db_conn.execute(
        "INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration, "
        "asr_text, asr_segments, vlm_description, tags, abstract_summary, keywords, emotion_tags, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            clip_id, video_id, abs_path, 0.0, dur, dur,
            "", None, prompt, json_dumps(["AI生成", "空镜"]),
            "", json_dumps(["AI生成", "空镜"]), json_dumps([]),
            now, now,
        ),
    )
    db_conn.commit()
    return {
        "clip_id": clip_id,
        "video_id": video_id,
        "clip_path": abs_path,
        "start_time": 0.0,
        "end_time": dur,
        "duration": dur,
        "asr_text": "",
        "vlm_description": prompt,
        "abstract_summary": "",
        "keywords": ["AI生成", "空镜"],
        "emotion_tags": [],
    }


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def generate_broll_sync(
    db_conn,
    gen_cfg: Mapping,
    prompt: str,
    *,
    duration_sec: float = 5.0,
    timeout_sec: float = 600.0,
) -> Optional[dict]:
    """端到端生成一条空镜并入库；任何失败返回 None（调用方回退普通推荐）。"""
    prompt = (prompt or "").strip()
    if not prompt or not str(gen_cfg.get("api_key") or "").strip():
        return None
    gen_dir = ensure_storage_subpath("generated")
    try:
        stage = submit_video_task(gen_cfg, prompt, duration_sec=duration_sec)
        url = poll_video_url(gen_cfg, stage, timeout_sec=timeout_sec)
        path = download_video(url, gen_dir)
        clip = register_generated_clip(db_conn, path, prompt, duration_sec)
        logger.info("[VideoGen] 空镜生成入库成功: %s", clip["clip_id"])
        return clip
    except Exception as e:
        logger.warning("[VideoGen] 空镜生成失败，回退普通推荐: %s", e)
        return None
