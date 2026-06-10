"""系统信息、备份与软件更新（GitHub Releases）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.schema import CURRENT_SCHEMA_VERSION
from app.db.run_migrations import read_installed_schema_version
from app.release_config import asset_name_for_version, get_release_repo
from app.utils.backup import create_backup, list_backups
from app.utils.paths import get_writable_backend_root
from app.version import compare_versions, get_app_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

_GITHUB_API = "https://api.github.com"
_CHECK_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_CACHE_TTL_SEC = 6 * 3600


class BackupRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class ApplyUpdateRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=64)
    download_url: str = Field(..., min_length=8)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    requires_backup: bool = False
    backup_confirmed: bool = False


def _install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return get_writable_backend_root()


def _updater_script_path() -> Path | None:
    root = _install_root()
    candidates = [
        root / "tools" / "apply_update.ps1",
        root / "tools" / "apply_update.template",
        Path(__file__).resolve().parents[2] / "tools" / "apply_update.ps1",
        Path(__file__).resolve().parents[3] / "scripts" / "tools" / "apply_update.template",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _parse_release_manifest(body: str) -> dict[str, Any] | None:
    text = (body or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _manifest_from_release(release: dict[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "breaking": False,
        "requires_backup": False,
        "min_schema_version": 1,
        "schema_version": CURRENT_SCHEMA_VERSION,
    }
    body = str(release.get("body") or "")
    parsed = _parse_release_manifest(body)
    if parsed:
        manifest.update({k: parsed.get(k, manifest.get(k)) for k in manifest})
        manifest.update(parsed)
    return manifest


def _pick_asset(release: dict[str, Any], version: str) -> dict[str, Any] | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    expected = asset_name_for_version(version)
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name == expected:
            return asset
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower().endswith(".zip"):
            return asset
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _fetch_latest_release() -> dict[str, Any]:
    repo = get_release_repo()
    if not repo or "/" not in repo:
        raise HTTPException(
            status_code=503,
            detail="未配置公开发版仓库 release.config.json -> release_repo",
        )
    url = f"{_GITHUB_API}/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "LX-SmartClip-Updater",
    }
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="公开发版仓库尚无 Release")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub API 错误: HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="GitHub API 返回格式异常")
    return data


@router.get("/version")
async def get_version_info():
    schema_version = await read_installed_schema_version()
    return {
        "app_version": get_app_version(),
        "schema_version": schema_version,
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "release_repo": get_release_repo(),
        "install_root": str(_install_root()),
    }


@router.get("/update/check")
async def check_update(force: bool = False):
    import time

    now = time.time()
    if (
        not force
        and _CHECK_CACHE.get("payload") is not None
        and now - float(_CHECK_CACHE.get("at") or 0) < _CACHE_TTL_SEC
    ):
        return _CHECK_CACHE["payload"]

    current = get_app_version()
    release = await _fetch_latest_release()
    tag = str(release.get("tag_name") or "").strip()
    latest = tag[1:] if tag.startswith("v") else tag
    manifest = _manifest_from_release(release)
    asset = _pick_asset(release, latest)
    download_url = str(asset.get("browser_download_url") or "") if asset else ""
    asset_name = str(asset.get("name") or "") if asset else asset_name_for_version(latest)
    cmp = compare_versions(current, latest) if latest else 0
    has_update = bool(latest) and cmp < 0
    schema_version = await read_installed_schema_version()

    payload = {
        "current_version": current,
        "latest_version": latest,
        "tag": tag or f"v{latest}",
        "has_update": has_update,
        "download_url": download_url,
        "asset_name": asset_name,
        "release_url": str(release.get("html_url") or ""),
        "published_at": str(release.get("published_at") or ""),
        "release_notes": str(release.get("body") or ""),
        "breaking": bool(manifest.get("breaking")),
        "requires_backup": bool(manifest.get("requires_backup")),
        "min_schema_version": int(manifest.get("min_schema_version") or 1),
        "target_schema_version": int(manifest.get("schema_version") or CURRENT_SCHEMA_VERSION),
        "schema_version": schema_version,
    }
    _CHECK_CACHE["at"] = now
    _CHECK_CACHE["payload"] = payload
    return payload


@router.post("/backup")
async def create_data_backup(body: BackupRequest):
    try:
        meta = create_backup(note=body.note or "manual")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("backup failed")
        raise HTTPException(status_code=500, detail=f"备份失败: {e}") from e
    return {"ok": True, "backup": meta}


@router.get("/backup/list")
async def get_backup_list():
    return {"items": list_backups()}


@router.post("/update/apply")
async def apply_update(body: ApplyUpdateRequest):
    if body.requires_backup and not body.backup_confirmed:
        raise HTTPException(status_code=400, detail="破坏性升级需先确认已备份数据")

    script = _updater_script_path()
    if not script:
        raise HTTPException(status_code=503, detail="未找到升级脚本 tools/apply_update.ps1")

    install_root = _install_root()
    job_dir = install_root / "data" / "update_jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    job_file = job_dir / "pending.json"

    backup_meta = None
    if body.requires_backup or body.backup_confirmed:
        try:
            backup_meta = create_backup(note=f"pre-update {body.tag}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"升级前自动备份失败: {e}") from e

    job = {
        "tag": body.tag,
        "download_url": body.download_url,
        "sha256": (body.sha256 or "").lower().strip() or None,
        "install_root": str(install_root),
        "backup_path": backup_meta.get("path") if backup_meta else None,
    }
    job_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    if sys.platform != "win32":
        raise HTTPException(status_code=501, detail="当前仅支持 Windows 一键升级")

    ps_cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-JobFile",
        str(job_file),
    ]
    try:
        subprocess.Popen(
            ps_cmd,
            cwd=str(install_root),
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动升级程序失败: {e}") from e

    return {
        "ok": True,
        "message": "升级程序已启动，本窗口将在数秒后关闭。请勿手动结束升级进程。",
        "job_file": str(job_file),
        "backup": backup_meta,
    }


@router.get("/update/sha256")
async def fetch_release_sha256(version: str):
    """读取同版本 .sha256 附件（由 prepare_release 生成）。"""
    repo = get_release_repo()
    if not repo:
        raise HTTPException(status_code=503, detail="未配置 release_repo")
    tag = version if version.startswith("v") else f"v{version}"
    url = f"{_GITHUB_API}/repos/{repo}/releases/tags/{tag}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "LX-SmartClip-Updater"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="未找到对应 Release")
    release = resp.json()
    assets = release.get("assets") or []
    stem = asset_name_for_version(version).replace(".zip", "")
    for asset in assets:
        name = str(asset.get("name") or "")
        if name == f"{stem}.sha256":
            dl = str(asset.get("browser_download_url") or "")
            if not dl:
                break
            async with httpx.AsyncClient(timeout=30.0) as client:
                text = (await client.get(dl)).text
            m = re.search(r"([a-fA-F0-9]{64})", text)
            if m:
                return {"sha256": m.group(1).lower()}
    raise HTTPException(status_code=404, detail="Release 未附带 .sha256 文件")
