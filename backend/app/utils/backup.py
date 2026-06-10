from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.db.database import DB_PATH
from app.utils.paths import get_data_dir, get_writable_backend_root


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def backup_dir() -> Path:
    p = get_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_backup(*, include_config: bool = True, note: str = "") -> dict:
    """
    备份 smartclip.db 与 config.json 到 data/backups/。
    返回备份元信息（路径、时间戳等）。
    """
    from app.version import get_app_version, get_schema_version

    stamp = _now_stamp()
    root = get_writable_backend_root()
    out_dir = backup_dir() / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    db_src = Path(DB_PATH)
    if not db_src.is_file():
        raise FileNotFoundError(f"数据库不存在: {db_src}")

    db_dst = out_dir / "smartclip.db"
    shutil.copy2(db_src, db_dst)

    config_src = root / "config.json"
    if include_config and config_src.is_file():
        shutil.copy2(config_src, out_dir / "config.json")

    meta = {
        "timestamp": stamp,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": get_app_version(),
        "schema_version": get_schema_version(),
        "note": note,
        "files": [p.name for p in out_dir.iterdir() if p.is_file()],
        "path": str(out_dir.resolve()),
    }
    (out_dir / "backup.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta


def list_backups(limit: int = 20) -> list[dict]:
    root = backup_dir()
    if not root.is_dir():
        return []
    items: list[dict] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        meta_file = child / "backup.meta.json"
        if meta_file.is_file():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    items.append(data)
                    continue
            except Exception:
                pass
        items.append({"timestamp": child.name, "path": str(child.resolve()), "files": []})
        if len(items) >= limit:
            break
    return items
