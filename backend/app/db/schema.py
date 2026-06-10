from __future__ import annotations

# 每次破坏性/需备份的数据库变更时递增，并在 release manifest 中声明 min_schema_version。
CURRENT_SCHEMA_VERSION = 1

SCHEMA_META_TABLE = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SCHEMA_VERSION_KEY = "schema_version"
