"""音频库任务 worker 子进程入口（仿 publisher/worker.py）。

被 start_backend.py 的 --audio-worker / --audio-login 分流调用：
    sys.executable --audio-worker  <task.json 绝对路径>
    sys.executable --audio-login   <source> <account>

职责：
- search：调 provider.search → 写 result.json（歌曲列表）
- download：逐首调 provider.download（音频落临时目录）→ 调 BGM 入库 → 去重 → PROGRESS 上报
- login：仅 netease，调 login.netease_login

崩溃隔离：本进程崩溃不影响主服务。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from app.core.audio_library.types import AudioTaskPayload, AudioTaskResult
from app.core.publisher._progress import emit_error, emit_log, emit_progress


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def _write_result(result_dir: Path, result: AudioTaskResult) -> None:
    result_path = result_dir / f"result_{result.task_id}.json"
    try:
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit_log(f"结果已写入: {result_path}")
    except Exception as exc:
        emit_error(f"写 result.json 失败: {exc}")


def _song_meta_to_dict(meta) -> dict:
    """把 provider 的 SongMeta dataclass 序列化成 dict（供 result.json / 前端）。"""
    from dataclasses import asdict
    return asdict(meta)


def _dict_to_song_meta(d: dict):
    """把 dict 反序列化成 SongMeta（download 任务从前端勾选的歌曲恢复）。"""
    from app.core.audio_library.providers.base import SongMeta
    return SongMeta(
        source=d.get("source", ""),
        source_id=str(d.get("source_id", "")),
        title=d.get("title", ""),
        artist=d.get("artist"),
        album=d.get("album"),
        duration=d.get("duration"),
        cover_url=d.get("cover_url"),
        heat=int(d.get("heat", 0) or 0),
        tags=list(d.get("tags", []) or []),
    )


# ── search 模式 ─────────────────────────────────────────────────────────────
def _run_search(payload: AudioTaskPayload, result_dir: Path) -> int:
    from app.core.audio_library.providers import get_provider_instance

    emit_log(f"=== 搜索任务 task_id={payload.task_id} ===")
    emit_log(f"源: {payload.source} 账号: {payload.account} 关键词: {payload.keyword} limit={payload.limit}")
    emit_progress(platform=payload.source, step="search", status="running", pct=5,
                  account=payload.account, message=f"正在搜索「{payload.keyword}」")

    provider = get_provider_instance(payload.source, payload.account)
    if provider is None:
        emit_error(f"不支持的音乐源: {payload.source}")
        _write_result(result_dir, AudioTaskResult(task_id=payload.task_id, status="failed"))
        return 2

    try:
        songs = asyncio_run(provider.search(payload.keyword, payload.limit))
    except Exception:
        emit_error(f"搜索异常:\n{traceback.format_exc()}")
        _write_result(result_dir, AudioTaskResult(task_id=payload.task_id, status="failed"))
        return 2
    finally:
        try:
            asyncio_run(provider.close())
        except Exception:
            pass

    song_dicts = [_song_meta_to_dict(s) for s in songs]
    emit_progress(platform=payload.source, step="search", status="success", pct=100,
                  account=payload.account, message=f"搜索完成，共 {len(song_dicts)} 首")
    result = AudioTaskResult(
        task_id=payload.task_id, status="succeeded", songs=song_dicts,
    )
    _write_result(result_dir, result)
    return 0


# ── download 模式 ───────────────────────────────────────────────────────────
def _run_download(payload: AudioTaskPayload, result_dir: Path) -> int:
    """批量下载勾选歌曲到 BGM 库。"""
    from app.core.audio_library.bgm_import import import_audio_file, manifest_has_source_id
    from app.core.audio_library.providers import get_provider_instance
    from app.utils.paths import ensure_storage_subpath

    emit_log(f"=== 下载任务 task_id={payload.task_id} ===")
    emit_log(f"源: {payload.source} 账号: {payload.account} 共 {len(payload.songs)} 首")

    provider = get_provider_instance(payload.source, payload.account)
    if provider is None:
        emit_error(f"不支持的音乐源: {payload.source}")
        _write_result(result_dir, AudioTaskResult(task_id=payload.task_id, status="failed"))
        return 2

    # 临时下载目录（音频下完移入 BGM 库，歌词留这里）
    tmp_audio_dir = ensure_storage_subpath("audio_library", "audio_tmp")
    lrc_dir = ensure_storage_subpath("audio_library", "lrc")

    total = len(payload.songs)
    downloaded = 0
    failed = 0
    skipped = 0
    detail: list[dict] = []

    try:
        for idx, sd in enumerate(payload.songs):
            meta = _dict_to_song_meta(sd)
            pct = int(5 + (idx / max(1, total)) * 90)
            title = f"{meta.title} - {meta.artist or '未知'}"
            emit_progress(
                platform=payload.source, step="download", status="running", pct=pct,
                account=payload.account,
                message=f"[{idx + 1}/{total}] {title}",
            )

            # 去重：按 source:source_id 标记查 BGM manifest
            if manifest_has_source_id(meta.source, meta.source_id):
                emit_log(f"已存在，跳过: {title}")
                skipped += 1
                detail.append({"title": title, "status": "skipped"})
                continue

            try:
                dl = asyncio_run(provider.download(meta, tmp_audio_dir))
            except Exception:
                emit_error(f"[{idx + 1}/{total}] 下载异常 {title}:\n{traceback.format_exc()}")
                failed += 1
                detail.append({"title": title, "status": "failed", "error": "下载异常"})
                continue

            if not dl.success or not dl.audio_path or not os.path.isfile(dl.audio_path):
                emit_error(f"[{idx + 1}/{total}] 下载失败: {title} ({dl.error})")
                failed += 1
                detail.append({"title": title, "status": "failed", "error": dl.error})
                continue

            # 纳入 BGM 库
            tags = [meta.source, f"{meta.source}:{meta.source_id}"]
            if meta.artist:
                tags.append(meta.artist)
            try:
                track = import_audio_file(
                    src_audio_path=dl.audio_path,
                    title=meta.title,
                    tags=tags,
                    preferred_filename=title,
                    move=True,
                )
                downloaded += 1
                detail.append({
                    "title": title, "status": "success",
                    "bgm_id": track.id, "filename": track.filename,
                })
                emit_log(f"[{idx + 1}/{total}] 已入库: {track.filename}")
            except Exception:
                emit_error(f"[{idx + 1}/{total}] 入库异常 {title}:\n{traceback.format_exc()}")
                failed += 1
                detail.append({"title": title, "status": "failed", "error": "BGM 入库异常"})

            # 歌词移到 lrc 目录（不入 BGM，BGM 不带歌词）
            if dl.lrc_path and os.path.isfile(dl.lrc_path):
                try:
                    import shutil
                    lrc_name = os.path.basename(dl.lrc_path)
                    shutil.move(dl.lrc_path, os.path.join(lrc_dir, lrc_name))
                except Exception:
                    pass
    finally:
        try:
            asyncio_run(provider.close())
        except Exception:
            pass

    # 汇总
    if downloaded == total:
        status, exit_code = "succeeded", 0
    elif downloaded == 0:
        status, exit_code = "failed", 2
    else:
        status, exit_code = "partial", 1

    emit_progress(platform=payload.source, step="download", status="success", pct=100,
                  account=payload.account,
                  message=f"下载完成：成功 {downloaded}，失败 {failed}，跳过 {skipped}")
    result = AudioTaskResult(
        task_id=payload.task_id, status=status,
        downloaded=downloaded, failed=failed, skipped=skipped, detail=detail,
    )
    _write_result(result_dir, result)
    return exit_code


# ── login 模式 ──────────────────────────────────────────────────────────────
def _run_login(source: str, account: str) -> int:
    from app.core.audio_library import login as audio_login

    if source != "netease":
        emit_error(f"音乐源 {source} 不需要登录或暂不支持登录")
        return 3
    try:
        ok = asyncio_run(audio_login.netease_login(account))
        return 0 if ok else 1
    except Exception:
        emit_error(f"登录异常:\n{traceback.format_exc()}")
        return 2


def main(task_json_path: str) -> int:
    """任务主入口：读 task.json → 执行 → 写 result.json。"""
    result_dir = Path(task_json_path).parent
    try:
        payload = AudioTaskPayload.from_dict(
            json.loads(Path(task_json_path).read_text(encoding="utf-8"))
        )
    except Exception as exc:
        emit_error(f"读取 task.json 失败: {exc}")
        return 3

    if payload.job_type == "search":
        return _run_search(payload, result_dir)
    elif payload.job_type == "download":
        return _run_download(payload, result_dir)
    else:
        emit_error(f"未知 job_type: {payload.job_type}")
        return 3


def entry() -> int:
    """统一入口：根据 argv[1] 分发 login / worker 模式。

    调用约定（见 start_backend.py 入口分流）：
        --audio-login  <source> <account>     登录子模式
        --audio-worker <task.json>            任务子模式
    """
    if len(sys.argv) < 3:
        emit_error(f"参数不足: {sys.argv}")
        return 3

    mode = sys.argv[1]
    if mode == "--audio-login":
        if len(sys.argv) < 4:
            emit_error("登录模式需要 source 和 account 参数")
            return 3
        return _run_login(sys.argv[2], sys.argv[3])
    elif mode == "--audio-worker":
        return main(sys.argv[2])
    else:
        emit_error(f"未知子进程模式: {mode}")
        return 3


if __name__ == "__main__":
    sys.exit(entry())
