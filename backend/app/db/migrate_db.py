"""数据库迁移脚本

用途：
  - 同步 DEFAULT_CONFIG 中的 label/options 到已有数据库
  - 新增 DEFAULT_CONFIG 中有但数据库中没有的配置项
  - 不会覆盖用户已修改的 value

使用方法：
  python -m app.db.migrate_db
  或直接运行：
  python backend/app/db/migrate_db.py
"""

import asyncio
import sys
import os

# 支持直接运行此脚本
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import aiosqlite
from app.db.init_db import DB_PATH, DEFAULT_CONFIG, CREATE_VIDEOS, CREATE_CLIPS, CREATE_CONFIG


async def migrate():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # 确保表结构存在（幂等）
        await db.execute(CREATE_VIDEOS)
        await db.execute(CREATE_CLIPS)
        await db.execute(CREATE_CONFIG)

        added = 0
        updated = 0

        for key, value, type_, label, options in DEFAULT_CONFIG:
            # 查询当前行是否存在
            async with db.execute(
                "SELECT key, label, options FROM config WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()

            if row is None:
                # 新配置项：直接插入（含默认 value）
                await db.execute(
                    "INSERT INTO config (key, value, type, label, options) VALUES (?,?,?,?,?)",
                    (key, value, type_, label, options),
                )
                print(f"  [新增] {key}  label={label}")
                added += 1
            else:
                # 已有配置项：只更新 label / type / options，保留用户的 value
                old_label, old_options = row[1], row[2]
                if old_label != label or old_options != options:
                    await db.execute(
                        "UPDATE config SET label=?, type=?, options=? WHERE key=?",
                        (label, type_, options, key),
                    )
                    print(f"  [更新] {key}  label: {old_label!r} -> {label!r}")
                    updated += 1

        await db.commit()

    print(f"\n迁移完成：新增 {added} 项，更新 {updated} 项。")


if __name__ == "__main__":
    print(f"数据库路径：{DB_PATH}")
    print("开始迁移...\n")
    asyncio.run(migrate())
