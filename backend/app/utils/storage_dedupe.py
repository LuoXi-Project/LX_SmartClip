"""素材目录内文件名：去掉重复的 ``{material_id}_`` 前缀（迁移/历史数据用）。"""

import os


def strip_duplicate_material_prefix(material_id: str, name: str) -> str:
    """
    将 ``<id>_<id>_rest`` 规范为 ``<id>_rest``（两段 ``<id>`` 须与 ``material_id`` 完全一致）。

    循环折叠直至不再出现 ``{material_id}_{material_id}_`` 前缀。
    纯 ``<id>_<id>``（无后续下划线）的 stem 会变为单个 ``<id>``。
    """
    mid = (material_id or "").strip()
    if not mid or not name:
        return name
    dup = f"{mid}_{mid}_"
    s = name
    while s.startswith(dup):
        s = f"{mid}_{s[len(dup):]}"
    if s == f"{mid}_{mid}":
        return mid
    stem, ext = os.path.splitext(s)
    if stem == f"{mid}_{mid}":
        return f"{mid}{ext}"
    return s


def strip_leading_material_id_from_clip_basename(material_id: str, basename: str) -> str:
    """
    切片文件名去掉前导 ``<material_id>_``（目录已含素材 id 时不再叠在文件名上）。
    先执行 ``strip_duplicate_material_prefix``，再反复去掉首段 ``<id>_``。
    """
    mid = (material_id or "").strip()
    if not mid or not basename:
        return basename
    s = strip_duplicate_material_prefix(mid, basename)
    p = f"{mid}_"
    while s.startswith(p):
        s = s[len(p) :]
    return s
