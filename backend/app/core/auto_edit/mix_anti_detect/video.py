"""画面防检测：OpenCV 帧级处理。"""
from __future__ import annotations

import logging
import os
import random
from typing import Optional

import cv2
import numpy as np

from app.core.auto_edit.mix_anti_detect.scheduler import RuntimeParams
from app.models.auto_edit import MixAntiDetectVideoConfig

logger = logging.getLogger(__name__)

# 像素噪声用模块级 Generator：比 legacy np.random.normal 快且线程安全，同为高斯分布（防检测效果一致）。
_PIXEL_NOISE_RNG = np.random.default_rng()
# 水印/字幕掩码帧间稳定：每 N 帧重新检测一次，中间帧复用，降低逐帧 Canny+Otsu 开销。
_INPAINT_MASK_REFRESH_INTERVAL = 12


def _detect_inpaint_mask(frame: np.ndarray, strength: float) -> np.ndarray:
    """检测字幕/水印常见区域（底部高对比 + 边角小块）。"""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask = np.zeros((h, w), dtype=np.uint8)

    # 底部字幕带
    band_h = max(8, int(h * 0.14))
    band = gray[h - band_h : h, :]
    _, band_bin = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask[h - band_h : h, :] = band_bin

    # 四角水印候选
    corner = max(24, int(min(w, h) * 0.12))
    for y0, y1 in ((0, corner), (h - corner, h)):
        for x0, x1 in ((0, corner), (w - corner, w)):
            patch = gray[y0:y1, x0:x1]
            if patch.size == 0:
                continue
            edges = cv2.Canny(patch, 60, 180)
            if float(np.mean(edges)) > 8.0 * strength:
                mask[y0:y1, x0:x1] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def _apply_inpaint(frame: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    if mask.max() == 0:
        return frame
    radius = max(2, int(3 + strength * 4))
    return cv2.inpaint(frame, mask, radius, cv2.INPAINT_TELEA)


def _apply_displacement(frame: np.ndarray, dx: float, dy: float) -> np.ndarray:
    if abs(dx) < 0.01 and abs(dy) < 0.01:
        return frame
    h, w = frame.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(frame, m, (w, h), borderMode=cv2.BORDER_REFLECT101)


def _apply_color_shift(frame: np.ndarray, shift: float) -> np.ndarray:
    if abs(shift) < 1e-4:
        return frame
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + shift * 18.0) % 180.0
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * (1.0 + shift), 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * (1.0 + shift * 0.25), 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _apply_scale_jitter(frame: np.ndarray, jitter: float) -> np.ndarray:
    if jitter <= 1e-5:
        return frame
    h, w = frame.shape[:2]
    scale = 1.0 + jitter
    nh, nw = int(h * scale), int(w * scale)
    scaled = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    y0 = max(0, (nh - h) // 2)
    x0 = max(0, (nw - w) // 2)
    if nh >= h and nw >= w:
        return scaled[y0 : y0 + h, x0 : x0 + w]
    canvas = np.zeros_like(frame)
    y1 = max(0, (h - nh) // 2)
    x1 = max(0, (w - nw) // 2)
    canvas[y1 : y1 + nh, x1 : x1 + nw] = scaled
    return canvas


def _apply_pixel_noise(frame: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return frame
    arr = frame.astype(np.float32)
    # 模块级 Generator：同高斯分布，比 legacy np.random.normal 更快；并移除未使用的 normalvariate 死代码。
    arr += _PIXEL_NOISE_RNG.normal(0.0, sigma, arr.shape)
    return np.clip(arr, 0, 255).astype(np.uint8)


def process_video_file(
    input_path: str,
    output_path: str,
    cfg: MixAntiDetectVideoConfig,
    params: RuntimeParams,
    *,
    fps: float,
) -> str:
    if not cfg.enabled:
        import shutil

        shutil.copy2(input_path, output_path)
        return output_path

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {input_path}")

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    in_fps = cap.get(cv2.CAP_PROP_FPS) or fps or 30.0
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    writer = cv2.VideoWriter(output_path, fourcc, in_fps, (w, h))

    rng = random.Random(params.seed + ":video")
    frame_idx = 0
    crawl_by_idx = {k.frame_idx: k for k in params.crawl_path}
    # inpaint 掩码缓存：水印/字幕位置帧间稳定，按间隔复用，避免逐帧 Canny+Otsu。
    last_mask: Optional[np.ndarray] = None
    last_mask_frame = -(10 ** 9)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if cfg.enable_inpaint:
                if (
                    last_mask is None
                    or frame_idx - last_mask_frame >= _INPAINT_MASK_REFRESH_INTERVAL
                ):
                    last_mask = _detect_inpaint_mask(frame, float(cfg.inpaint_strength))
                    last_mask_frame = frame_idx
                frame = _apply_inpaint(frame, last_mask, float(cfg.inpaint_strength))

            crawl = crawl_by_idx.get(frame_idx)
            dx = params.displacement_px
            dy = params.displacement_px * 0.35
            if crawl:
                dx += crawl.dx
                dy += crawl.dy
            if cfg.enable_displacement or cfg.enable_crawl:
                frame = _apply_displacement(frame, dx, dy)

            if cfg.enable_color_shift:
                frame = _apply_color_shift(frame, params.color_shift)

            if cfg.enable_scale_jitter:
                frame = _apply_scale_jitter(frame, params.scale_jitter)

            if cfg.enable_pixel_noise:
                frame = _apply_pixel_noise(frame, params.pixel_noise_sigma)

            write_frame = True
            if cfg.enable_frame_ops and rng.random() < float(cfg.frame_drop_probability):
                write_frame = False

            if write_frame:
                writer.write(frame)
                if cfg.enable_frame_ops and rng.random() < float(cfg.frame_dup_probability):
                    writer.write(frame)

            frame_idx += 1
    finally:
        cap.release()
        writer.release()

    logger.info("防检测画面处理完成 frames=%d out=%s", frame_idx, output_path)
    return output_path
