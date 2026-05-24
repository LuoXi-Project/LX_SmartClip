from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

import requests

# 通过移动端分享页解析，不读取、不要求用户提供任何登录 Cookie。


class DouyinDownloadError(Exception):
    pass


_MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_URL_RE = re.compile(
    r"https?://[^\s<>'\"]+",
    re.IGNORECASE,
)

_ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
    re.DOTALL,
)

_DOUYIN_HOST_RE = re.compile(r"(?:^|\.)(?:douyin|iesdouyin)\.com$", re.IGNORECASE)

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def extract_first_url(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise DouyinDownloadError("未提供链接")
    match = _URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,;)'\"]")
    if text.startswith("http"):
        return text.split()[0]
    raise DouyinDownloadError("未在文本中找到有效的 http(s) 链接")


def is_douyin_link(text: str) -> bool:
    try:
        url = extract_first_url(text)
    except DouyinDownloadError:
        return False
    host = (urlparse(url).hostname or "").lower()
    return bool(_DOUYIN_HOST_RE.search(host))


def _sanitize_title(title: str, *, video_id: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", (title or "").strip())
    return cleaned or f"douyin_{video_id}"


def _resolve_video_id(share_url: str, session: requests.Session, timeout_sec: int) -> str:
    resp = session.get(
        share_url,
        headers=_MOBILE_HEADERS,
        timeout=timeout_sec,
        allow_redirects=True,
    )
    try:
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DouyinDownloadError(f"访问分享链接失败：{exc}") from exc

    final_path = urlparse(resp.url).path.rstrip("/")
    video_id = final_path.split("/")[-1] if final_path else ""
    if not video_id or not video_id.isdigit():
        raise DouyinDownloadError("无法从分享链接解析视频 ID，请使用有效的抖音分享链接")
    return video_id


def parse_douyin_video_info(share_text: str, *, timeout_sec: int = 30) -> dict[str, str]:
    """
    解析抖音分享链接，返回 video_id、title、download_url。
    仅使用匿名移动端页面，不依赖用户登录态。
    """
    share_url = extract_first_url(share_text)
    session = requests.Session()

    video_id = _resolve_video_id(share_url, session, timeout_sec)
    page_url = f"https://www.iesdouyin.com/share/video/{video_id}"

    try:
        page_resp = session.get(page_url, headers=_MOBILE_HEADERS, timeout=timeout_sec)
        page_resp.raise_for_status()
    except requests.RequestException as exc:
        raise DouyinDownloadError(f"获取视频页面失败：{exc}") from exc

    router_match = _ROUTER_DATA_RE.search(page_resp.text)
    if not router_match:
        raise DouyinDownloadError("解析视频信息失败，抖音页面结构可能已变更，请稍后重试")

    try:
        router_data = json.loads(router_match.group(1).strip())
    except json.JSONDecodeError as exc:
        raise DouyinDownloadError("解析视频 JSON 失败") from exc

    loader = router_data.get("loaderData") or {}
    video_page = loader.get("video_(id)/page") or {}
    note_page = loader.get("note_(id)/page") or {}
    if video_page:
        item_list = (video_page.get("videoInfoRes") or {}).get("item_list") or []
    elif note_page:
        item_list = (note_page.get("videoInfoRes") or {}).get("item_list") or []
    else:
        raise DouyinDownloadError("未找到视频数据（可能为不支持的图集/直播链接）")

    if not item_list:
        raise DouyinDownloadError("视频列表为空，链接可能已失效")

    item = item_list[0]
    video = item.get("video") or {}
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []
    if not url_list:
        raise DouyinDownloadError("未获取到视频播放地址")

    download_url = str(url_list[0]).replace("playwm", "play")
    title = _sanitize_title(str(item.get("desc") or ""), video_id=video_id)

    return {
        "video_id": video_id,
        "title": title,
        "download_url": download_url,
    }


def download_douyin_video(
    *,
    share_text: str,
    output_dir: str,
    file_stem: str,
    timeout_sec: int = 60 * 20,
) -> tuple[str, str]:
    """
    下载抖音视频到 output_dir/{file_stem}.mp4。
    返回 (文件路径, 建议素材名)。
    """
    info = parse_douyin_video_info(share_text, timeout_sec=min(timeout_sec, 60))
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{file_stem}.mp4")

    connect_timeout = min(30, timeout_sec)
    try:
        with requests.get(
            info["download_url"],
            headers=_MOBILE_HEADERS,
            stream=True,
            timeout=(connect_timeout, timeout_sec),
        ) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as exc:
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        raise DouyinDownloadError(f"下载视频文件失败：{exc}") from exc

    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise DouyinDownloadError("下载完成但文件为空，请重试或更换链接")

    return out_path, info["title"]
