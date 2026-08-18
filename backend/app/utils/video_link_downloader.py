from __future__ import annotations

from app.utils.douyin_downloader import DouyinDownloadError, download_douyin_video, is_douyin_link
from app.utils.yt_dlp_downloader import YtDlpDownloadError, download_video_with_yt_dlp


class VideoLinkDownloadError(Exception):
    pass


def download_video_from_link(
    *,
    url: str,
    output_dir: str,
    file_stem: str,
    timeout_sec: int = 60 * 20,
    resolution: str = "best",
    fps_limit: int | None = None,
    prefer_mp4: bool = True,
    proxy: str | None = None,
    cookiefile: str | None = None,
) -> tuple[str, str | None]:
    """
    按链接类型选择下载方式：
    - 抖音：匿名移动端页面解析（无需用户 Cookie / 登录）
    - 其它：yt-dlp（proxy/cookiefile 仅对 yt-dlp 生效）

    返回 (落盘路径, 可选推断素材名)。
    """
    raw = (url or "").strip()
    if not raw:
        raise VideoLinkDownloadError("未提供链接")

    if is_douyin_link(raw):
        try:
            path, title = download_douyin_video(
                share_text=raw,
                output_dir=output_dir,
                file_stem=file_stem,
                timeout_sec=timeout_sec,
            )
            return path, title
        except DouyinDownloadError as exc:
            raise VideoLinkDownloadError(str(exc)) from exc

    try:
        path = download_video_with_yt_dlp(
            url=raw,
            output_dir=output_dir,
            file_stem=file_stem,
            timeout_sec=timeout_sec,
            resolution=resolution,
            fps_limit=fps_limit,
            prefer_mp4=prefer_mp4,
            proxy=proxy,
            cookiefile=cookiefile,
        )
        return path, None
    except YtDlpDownloadError as exc:
        detail = str(exc)
        raise VideoLinkDownloadError(detail) from exc
