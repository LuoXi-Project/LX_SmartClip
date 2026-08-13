"""网易云音乐 Provider（从 LX_SmartMixroll 迁移）。

直连网易云公开 API（无需 Node 服务），用 httpx 异步请求。
覆盖：搜索 / 歌曲详情 / 歌词(LRC/YRC) / 音频下载 / 登录态校验。

与 SmartMixroll 版本的差异：
- Cookie 按账号持久化到 <home>/data/audio_cookies/netease/<account>.json（多账号），
  登录流程由上层 core/audio_library/login.py 用 patchright 扫码完成，本 provider 只负责读 cookie。
- 不再在模块加载时注册单例，由调用方按账号实例化（worker 内）。
- logger 改用标准 logging。

合规说明：仅用于个人学习与本地使用。下载音频需有合法授权。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from app.core.audio_library.providers.base import (
    DownloadResult,
    SongMeta,
)
from app.core.audio_library._cookie import cookie_file_for, load_cookie_bundle

logger = logging.getLogger("audio_library.netease")

# 网易云公开接口基址
BASE_URL = "https://music.163.com"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://music.163.com",
}
# 请求超时
TIMEOUT = 15.0


class NeteaseProvider:
    """网易云 Provider（纯 httpx，无外部服务依赖）。

    Cookie 来自扫码登录后落盘的账号 cookie 文件。登录后可获取 VIP 歌曲的高品质音频 URL。
    """

    name = "netease"

    def __init__(self, account: str = "main") -> None:
        self.account = account
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies: dict[str, str] = {}
        self._login_info: Optional[dict] = None
        self._load_cookies()

    # ---------- Cookie（来自扫码登录落盘文件） ----------
    @property
    def is_logged_in(self) -> bool:
        """是否已登录（有有效 MUSIC_U Cookie）。"""
        return bool(self._cookies.get("MUSIC_U"))

    @property
    def login_info(self) -> Optional[dict]:
        return self._login_info

    def _load_cookies(self) -> None:
        """从账号 cookie 文件加载。"""
        bundle = load_cookie_bundle("netease", self.account)
        if not bundle:
            return
        self._cookies = bundle.get("cookies", {}) or {}
        self._login_info = bundle.get("login_info")
        if self._cookies.get("MUSIC_U"):
            logger.info("网易云 Cookie 已加载 account=%s (uid=%s)",
                        self.account,
                        (self._login_info or {}).get("userId", "?"))

    def _save_cookies(self) -> None:
        """保存 Cookie 到账号文件（含 login_info 元数据）。"""
        cf = cookie_file_for("netease", self.account)
        try:
            cf.parent.mkdir(parents=True, exist_ok=True)
            # 合并保留扫码登录时存的 storage_state，便于后续重登复用
            existing: dict = {}
            if cf.exists():
                try:
                    existing = json.loads(cf.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}
            existing.update({
                "cookies": self._cookies,
                "login_info": self._login_info,
            })
            cf.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("保存网易云 Cookie 失败: %s", e)

    async def _get_login_status(self) -> Optional[dict]:
        """通过 /api/nuser/account/get 获取登录状态。"""
        cli = await self._get_client()
        try:
            r = await cli.get("/api/nuser/account/get")
            data = r.json()
            if data.get("code") == 200:
                profile = data.get("profile") or {}
                account = data.get("account") or {}
                return {
                    "userId": account.get("id") or profile.get("userId"),
                    "nickname": profile.get("nickname", "?"),
                    "vipType": profile.get("vipType", 0),
                }
        except Exception as e:
            logger.warning("获取登录状态失败: %s", e)
        return None

    async def check_login(self) -> bool:
        """校验当前账号 cookie 是否仍有效（供 /accounts/check 调用）。"""
        if not self.is_logged_in:
            return False
        info = await self._get_login_status()
        if info:
            self._login_info = info
            self._save_cookies()
            return True
        return False

    # ---------- HTTP Client ----------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers=DEFAULT_HEADERS,
                cookies=self._cookies,
                timeout=TIMEOUT,
                follow_redirects=True,
            )
        return self._client

    async def _reset_client(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ---------- 搜索 ----------
    async def search(self, keyword: str, limit: int = 20) -> list[SongMeta]:
        """搜索歌曲。"""
        cli = await self._get_client()
        try:
            r = await cli.get(
                "/api/search/get",
                params={"s": keyword, "type": 1, "limit": limit, "offset": 0},
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error("网易云搜索失败: %s", e)
            return []

        if data.get("code") != 200:
            logger.warning("网易云搜索返回异常: code=%s", data.get("code"))
            return []

        songs = data.get("result", {}).get("songs", []) or []
        result: list[SongMeta] = []
        for s in songs:
            artists = s.get("artists") or s.get("ar") or []
            artist_name = artists[0]["name"] if artists else None
            # 有些歌曲在搜索结果里直接带了试听片段 URL（30s 免费片段）
            preview_url = s.get("mp3Url") or None
            meta = SongMeta(
                source="netease",
                source_id=str(s["id"]),
                title=s.get("name", ""),
                artist=artist_name,
                album=(s.get("album") or s.get("al") or {}).get("name"),
                duration=(s.get("duration") or 0) / 1000.0 if s.get("duration") else None,
                heat=int(s.get("popularity", 0)),
            )
            # 如果搜索结果自带试听 URL，存到 tags 里以便前端使用
            if preview_url:
                meta.tags = [f"preview_url:{preview_url}"]
            result.append(meta)
        logger.info("网易云搜索 '%s' -> %d 首", keyword, len(result))
        return result

    # ---------- 详情 ----------
    async def get_detail(self, song_id: str) -> Optional[dict]:
        """获取单曲详情（补全元数据）。"""
        cli = await self._get_client()
        try:
            r = await cli.get(
                "/api/song/detail",
                params={"ids": f"[{song_id}]"},
            )
            data = r.json()
            songs = data.get("songs") or []
            return songs[0] if songs else None
        except Exception as e:
            logger.warning("获取详情失败 id=%s: %s", song_id, e)
            return None

    # ---------- 歌词 ----------
    async def get_lyric(self, song_id: str) -> tuple[Optional[str], Optional[str]]:
        """获取歌词。返回 (lrc_text, yrc_text)。yrc 为逐字歌词（可能为空）。"""
        cli = await self._get_client()
        try:
            r = await cli.get(
                "/api/song/lyric",
                params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
            )
            data = r.json()
        except Exception as e:
            logger.warning("获取歌词失败 id=%s: %s", song_id, e)
            return None, None

        lrc = (data.get("lrc") or {}).get("lyric")
        yrc = (data.get("yrc") or {}).get("lyric")
        return lrc, yrc

    # ---------- 音频 URL ----------
    async def get_audio_url(self, song_id: str) -> Optional[str]:
        """获取音频试听/下载 URL。

        策略：已登录优先 API 拿高品质 URL（VIP 也能拿）；否则用公开直链（128kbps）。
        """
        if self.is_logged_in:
            url = await self._get_audio_url_api(song_id)
            if url:
                return url

        # 公开直链：免费歌曲都可播放（128kbps，无需登录）
        direct_url = f"https://music.163.com/song/media/outer/url?id={song_id}.mp3"
        logger.debug("使用公开直链: id=%s", song_id)
        return direct_url

    async def _get_audio_url_api(self, song_id: str) -> Optional[str]:
        """通过 API 获取音频 URL（需登录，支持 VIP 歌曲）。"""
        cli = await self._get_client()
        try:
            r = await cli.get(
                "/api/song/enhance/player/url/v1",
                params={"ids": f"[{song_id}]", "level": "higher", "encodeType": "mp3"},
            )
            data = r.json()
        except Exception as e:
            logger.warning("API获取音频URL失败 id=%s: %s", song_id, e)
            return None

        if data.get("code") != 200:
            return None
        urls = data.get("data") or []
        if not urls:
            return None
        url = urls[0].get("url")
        if url:
            br = urls[0].get("br", 0)
            logger.info("API获取音频URL: id=%s br=%s", song_id, br)
            return url
        return None

    # ---------- 下载 ----------
    async def download(self, meta: SongMeta, dest_dir: str) -> DownloadResult:
        """下载音频 + 歌词到本地。"""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        song_id = meta.source_id

        # 安全文件名
        safe_title = "".join(c for c in meta.title if c not in '<>:"/\\|?*')[:60] or song_id

        # 1. 下载音频
        audio_path: Optional[str] = None
        url = await self.get_audio_url(song_id)
        if url:
            audio_path = str(dest / f"{safe_title}.mp3")
            ok = await self._download_file(url, audio_path)
            if not ok:
                audio_path = None
        if not audio_path:
            hint = ""
            if not self.is_logged_in:
                hint = "（提示：登录网易云账号后可下载 VIP 歌曲）"
            return DownloadResult(
                meta=meta, audio_path="", success=False,
                error=f"无法获取音频URL（可能需要VIP/付费授权，或接口限流）{hint}",
            )

        # 2. 下载歌词（失败不影响音频）
        lrc_path: Optional[str] = None
        lrc_format: Optional[str] = None
        lrc_text, yrc_text = await self.get_lyric(song_id)
        lyric_text = yrc_text or lrc_text  # 优先逐字
        if lyric_text:
            lrc_path = str(dest / f"{safe_title}.lrc")
            try:
                Path(lrc_path).write_text(lyric_text, encoding="utf-8")
                lrc_format = "yrc" if yrc_text else "lrc"
            except Exception as e:
                logger.warning("保存歌词失败: %s", e)
                lrc_path = None

        # 3. 补全元数据（搜索结果可能缺字段）
        if not meta.duration or not meta.album:
            detail = await self.get_detail(song_id)
            if detail:
                if not meta.duration and detail.get("duration"):
                    meta.duration = detail["duration"] / 1000.0
                if not meta.album and detail.get("album"):
                    meta.album = detail["album"].get("name")
                if not meta.cover_url and detail.get("album"):
                    meta.cover_url = (detail["album"].get("picUrl")
                                      or detail["album"].get("picStr"))

        logger.info("网易云下载完成: %s - %s (audio=%s, lrc=%s)",
                    meta.title, meta.artist, bool(audio_path), lrc_format)
        return DownloadResult(
            meta=meta,
            audio_path=audio_path,
            lrc_path=lrc_path,
            lrc_format=lrc_format,
            success=True,
        )

    async def _download_file(self, url: str, dest: str) -> bool:
        """流式下载文件。"""
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS, timeout=60.0, follow_redirects=True
            ) as dl_cli:
                with open(dest, "wb") as f:
                    async with dl_cli.stream("GET", url) as resp:
                        resp.raise_for_status()
                        async for chunk in resp.aiter_bytes(65536):
                            f.write(chunk)
            if os.path.getsize(dest) < 1024:
                logger.warning("下载文件过小，可能无效: %s", dest)
                os.remove(dest)
                return False
            return True
        except Exception as e:
            logger.error("下载失败 %s: %s", url[:60], e)
            if os.path.exists(dest):
                os.remove(dest)
            return False
