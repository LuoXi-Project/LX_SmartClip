"""将混剪段落 ``SegmentVisualEffect`` 映射为 pyJianYingDraft ``ClipSettings``。"""
from __future__ import annotations

from typing import Any, Optional

from app.models.subtitle import SegmentVisualEffect


def visual_effect_to_clip_settings(effect: Optional[SegmentVisualEffect]) -> Any | None:
    """
    剪映草稿「视频整体调节」：镜像 / 旋转 / 缩放。

    随机调色（eq/hue）无对应 ClipSettings 字段，剪映侧不写入。
    """
    if effect is None:
        return None

    flip_h = bool(effect.mirror)
    rotation = 0.0
    if effect.rotation_deg is not None and abs(float(effect.rotation_deg)) > 0.001:
        rotation = float(effect.rotation_deg)

    scale = 1.0
    if effect.zoom is not None and float(effect.zoom) > 1.001:
        scale = float(effect.zoom)

    if not flip_h and abs(rotation) < 0.001 and abs(scale - 1.0) < 0.001:
        return None

    from pyJianYingDraft.segment import ClipSettings

    return ClipSettings(
        flip_horizontal=flip_h,
        rotation=rotation,
        scale_x=scale,
        scale_y=scale,
    )
