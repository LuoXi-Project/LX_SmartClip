"""素材目录内主视频与封面的固定文件名（目录已含 ``videos.id``，文件名不再重复 UUID）。"""

# 主视频：上传 / 下载落盘名（扩展名随上传或 yt-dlp 结果）
SOURCE_VIDEO_STEM = "source"

# 重编码输出（当前管线固定 mp4）
REENCODED_VIDEO_NAME = "reencoded.mp4"

# 封面图
THUMBNAIL_FILENAME = "cover.jpg"


def source_video_basename(ext: str) -> str:
    ext = (ext or "").strip() or ".mp4"
    if not ext.startswith("."):
        ext = "." + ext
    return f"{SOURCE_VIDEO_STEM}{ext}"
