"""酷我音乐 Provider（从 LX_SmartMixroll 迁移）。

直连酷我公开接口（httpx 异步，免登录），覆盖：
搜索 / 歌曲详情 / 歌词(LRC) / 音频下载（完整曲，多码率降级）。

反爬说明：``www.kuwo.cn/api/*`` 需动态 ``Secret`` 请求头（酷我 2024+ 加密）。
本模块完整移植了 web 端的 Secret 算法（LCG + XOR），实测可用：
  1. 访问主页拿 Cookie ``Hm_Iuvt_xxx=值``（cookie 名会变，运行时动态提取）
  2. ``Secret = h(cookie值, cookie名)``（移植自 kuwoMusicApi/secret.js 的 h 函数）
  3. 请求 API 时带 ``Cookie`` + ``Secret`` + ``csrf=cookie值`` 头

歌词走另一套接口 ``newlyric.kuwo.cn``：参数用 ``yeelion`` 作 XOR key 加密 + base64，
返回 zlib 压缩的 LRC 文本。

免费歌曲（PAY=0）可拿到完整音频；付费歌返回提示，建议改用 netease 源。

与 SmartMixroll 版本的差异：仅 logger（标准 logging）和 import 路径，加密算法原样保留。

合规说明：仅用于个人学习与本地使用。下载音频需有合法授权。
"""
from __future__ import annotations

import ast
import base64
import logging
import math
import os
import random
import uuid
import zlib
from pathlib import Path
from typing import Optional

import httpx

from app.core.audio_library.providers.base import (
    DownloadResult,
    SongMeta,
)

logger = logging.getLogger("audio_library.kuwo")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TIMEOUT = 15.0
# 搜索结果中 web_albumpic_short 拼此前缀得到完整封面 URL
COVER_BASE = "https://img1.kuwo.cn/star/albumcover/"
# 音频码率降级顺序
BITRATES = ("320kmp3", "128kmp3", "2000kflac")


# ---------------------------------------------------------------------------
# Secret 加密（移植自 kuwoMusicApi/app/utils/secret.js 的 h 函数）
# ---------------------------------------------------------------------------

def _js_parse_int(s: str) -> float:
    """模拟 JS parseInt：返回 float，对齐 JS Number 语义。

    JS parseInt 对超大纯数字串 = Number（IEEE754 正确舍入）。
    """
    if not s:
        return float("nan")
    i = 0
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    sign = 1.0
    if i < len(s) and s[i] in "+-":
        if s[i] == "-":
            sign = -1.0
        i += 1
    j = i
    while j < len(s) and s[j].isdigit():
        j += 1
    digits = s[i:j]
    if not digits:
        return float("nan")
    return sign * float(digits)


def _js_num_to_str(x: float) -> str:
    """模拟 JS Number.prototype.toString(10)。"""
    if math.isnan(x):
        return "NaN"
    if x == math.inf:
        return "Infinity"
    if x == -math.inf:
        return "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a < 1e21 and a == int(a):
        return sign + str(int(a))
    return sign + repr(a)


def _kuwo_secret(t: str, e: str) -> str:
    """酷我 Secret 加密。

    t: 明文（Cookie 中 Hm_Iuvt_xxx 的值）
    e: 密钥（Cookie 名 'Hm_Iuvt_xxx'）
    返回: hex 字符串（2*len(t)+8 位）
    """
    if not e:
        return ""
    n = "".join(str(ord(c)) for c in e)
    r = len(n) // 5

    def _ch(s: str, i: int) -> str:
        return s[i] if 0 <= i < len(s) else ""

    o_str = _ch(n, r) + _ch(n, 2 * r) + _ch(n, 3 * r) + _ch(n, 4 * r) + _ch(n, 5 * r)
    o = int(_js_parse_int(o_str))
    l = math.ceil(len(e) / 2)
    c = 2 ** 31 - 1
    if o < 2:
        return ""
    d = random.randint(0, 99999999)
    n = n + str(d)
    while len(n) > 10:
        n = _js_num_to_str(_js_parse_int(n[:10]) + _js_parse_int(n[10:]))
    n_num = (o * _js_parse_int(n) + l) % c
    f = ""
    for ch in t:
        x = ord(ch) ^ math.floor(n_num / c * 255)
        hx = format(x, "x")
        f += ("0" + hx) if x < 16 else hx
        n_num = (o * n_num + l) % c
    return f + format(d, "x").zfill(8)


# ---------------------------------------------------------------------------
# 歌词加解密（移植自 kuwoMusicApi/app/service/lrc.ts，接口 newlyric.kuwo.cn）
# ---------------------------------------------------------------------------

_LRC_KEY = b"yeelion"


def _lrc_build_params(music_id: str) -> str:
    """构造 newlyric.lrc 的加密查询参数。"""
    params = (
        f"user=12345,web,web,web&requester=localhost&req=1&rid=MUSIC_{music_id}"
    )
    buf = params.encode("latin-1")
    out = bytes(b ^ _LRC_KEY[i % len(_LRC_KEY)] for i, b in enumerate(buf))
    return base64.b64encode(out).decode("ascii")


def _lrc_decode(raw: bytes) -> str:
    """解析 newlyric.lrc 响应为 LRC 文本。"""
    if raw[:10] != b"tp=content":
        return ""
    idx = raw.find(b"\r\n\r\n")
    if idx < 0:
        return ""
    compressed = raw[idx + 4:]
    for wb in (zlib.MAX_WBITS, -zlib.MAX_WBITS, 15 + 32, 47):
        try:
            inflated = zlib.decompress(compressed, wb)
            break
        except zlib.error:
            continue
    else:
        return ""
    return inflated.decode("gb18030", errors="replace")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _clean(s: object) -> str:
    """清洗 r.s 返回文本：解码 HTML 实体 + JSON unicode 转义（\\uXXXX）。"""
    import re
    s = str(s) if s is not None else ""
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = re.sub(r"\\+u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s.strip()


def _parse_duration(val: object) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: object) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


class KuwoProvider:
    """酷我音乐 Provider（完整音频下载 + 歌词，免登录）。"""

    name = "kuwo"

    def __init__(self, account: str = "main") -> None:
        # 酷我免登录，account 仅用于日志一致性
        self.account = account
        self._client: Optional[httpx.AsyncClient] = None
        self._cookie_name: Optional[str] = None
        self._cookie_value: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ---------- 鉴权（Hm_Iuvt cookie）----------
    async def _ensure_auth(self) -> bool:
        if self._cookie_name and self._cookie_value:
            return True
        cli = await self._get_client()
        try:
            await cli.get("http://www.kuwo.cn/", headers={"Accept": "text/html"})
            for ck in cli.cookies.jar:
                if ck.name.startswith("Hm_Iuvt_"):
                    self._cookie_name = ck.name
                    self._cookie_value = ck.value
                    logger.debug("酷我 cookie: %s=%s...", ck.name, ck.value[:8])
                    return True
        except Exception as e:
            logger.warning("获取酷我 cookie 失败: %s", e)
        return False

    def _auth_headers(self) -> dict:
        secret = _kuwo_secret(self._cookie_value or "", self._cookie_name or "")
        return {
            "Cookie": f"{self._cookie_name}={self._cookie_value}",
            "Secret": secret,
            "csrf": self._cookie_value or "",
            "Host": "www.kuwo.cn",
            "Referer": "http://www.kuwo.cn/",
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
        }

    async def _api_get(self, path: str, params: dict) -> Optional[dict]:
        if not await self._ensure_auth():
            return None
        params = {"httpsStatus": 1, "plat": "web_www", "reqId": str(uuid.uuid4()), **params}
        headers = self._auth_headers()
        cli = await self._get_client()
        try:
            r = await cli.get(f"http://www.kuwo.cn{path}", params=params, headers=headers)
            return r.json()
        except Exception as e:
            logger.warning("酷我 API 请求失败 %s: %s", path, e)
            return None

    # ---------- 搜索 ----------
    async def search(self, keyword: str, limit: int = 20) -> list[SongMeta]:
        """搜索（用 r.s 老接口，稳定且无需 Secret）。"""
        cli = await self._get_client()
        try:
            r = await cli.get(
                "http://search.kuwo.cn/r.s",
                params={
                    "all": keyword, "ft": "music", "client": "kt",
                    "pn": "0", "rn": str(limit), "rformat": "json",
                    "encoding": "utf8", "cluster": "0",
                    "itemset": "web_2013", "vipver": "1",
                },
            )
        except Exception as e:
            logger.error("酷我搜索失败: %s", e)
            return []

        try:
            data = ast.literal_eval(r.text)
        except (ValueError, SyntaxError) as e:
            logger.warning("酷我搜索响应解析失败: %s", e)
            return []

        items = data.get("abslist", []) or []
        result: list[SongMeta] = []
        skipped_paid = 0
        for s in items:
            musicrid = str(s.get("MUSICRID") or "")
            rid = musicrid.replace("MUSIC_", "") or str(s.get("DC_TARGETID") or "")
            if not rid or not rid.isdigit():
                continue
            # 付费歌曲无法下载完整音频，直接过滤不展示
            if str(s.get("PAY")) != "0":
                skipped_paid += 1
                continue
            webpic = s.get("web_albumpic_short") or ""
            cover = COVER_BASE + webpic if webpic else None
            meta = SongMeta(
                source="kuwo",
                source_id=rid,
                title=_clean(s.get("SONGNAME") or s.get("NAME")),
                artist=_clean(s.get("ARTIST")) or None,
                album=_clean(s.get("ALBUM")) or None,
                duration=_parse_duration(s.get("DURATION")),
                cover_url=cover,
                heat=_safe_int(s.get("PLAYCNT")),
            )
            meta.tags = ["free"]
            result.append(meta)
        logger.info("酷我搜索 '%s' -> %d 首（过滤付费 %d）",
                    keyword, len(result), skipped_paid)
        return result

    # ---------- 详情 ----------
    async def get_detail(self, rid: str) -> Optional[dict]:
        data = await self._api_get("/api/www/music/musicInfo", {"mid": rid})
        if not data or data.get("code") != 200:
            return None
        return data.get("data")

    # ---------- 歌词 ----------
    async def get_lyric(self, rid: str) -> Optional[str]:
        """获取 LRC 歌词文本（newlyric.kuwo.cn 加密接口，标准 LRC）。"""
        params = _lrc_build_params(rid)
        url = f"http://newlyric.kuwo.cn/newlyric.lrc?{params}"
        cli = await self._get_client()
        try:
            r = await cli.get(url)
        except Exception as e:
            logger.warning("获取酷我歌词失败 rid=%s: %s", rid, e)
            return None
        if r.status_code != 200:
            return None
        text = _lrc_decode(r.content)
        return text if text.strip() else None

    # ---------- 音频 URL ----------
    async def get_audio_url(self, rid: str) -> Optional[str]:
        """获取音频 URL。多码率降级（320k → 128k → flac）。"""
        for br in BITRATES:
            data = await self._api_get(
                "/api/v1/www/music/playUrl",
                {"mid": rid, "type": "music", "br": br, "from": ""},
            )
            if not data or data.get("code") != 200:
                continue
            url = (data.get("data") or {}).get("url")
            if url and url.startswith("http"):
                logger.info("酷我音频URL: rid=%s br=%s", rid, br)
                return url
            if data.get("success") is False:
                logger.info("酷我 rid=%s 无法播放: %s", rid, data.get("msg"))
                return None
        return None

    # ---------- 下载 ----------
    async def download(self, meta: SongMeta, dest_dir: str) -> DownloadResult:
        """下载音频 + 歌词到本地。"""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        rid = meta.source_id
        safe_title = "".join(c for c in meta.title if c not in '<>:"/\\|?*')[:60] or rid

        # 1. 下载音频
        audio_path: Optional[str] = None
        url = await self.get_audio_url(rid)
        if url:
            audio_path = str(dest / f"{safe_title}.mp3")
            ok = await self._download_file(url, audio_path)
            if not ok:
                audio_path = None
        if not audio_path:
            hint = "（可能为付费/无版权歌曲，建议改用 netease 源）"
            return DownloadResult(
                meta=meta, audio_path="", success=False,
                error=f"无法获取酷我音频URL{hint}",
            )

        # 2. 下载歌词（失败不影响音频）
        lrc_path: Optional[str] = None
        lrc_format: Optional[str] = None
        lrc_text = await self.get_lyric(rid)
        if lrc_text:
            lrc_path = str(dest / f"{safe_title}.lrc")
            try:
                Path(lrc_path).write_text(lrc_text, encoding="utf-8")
                lrc_format = "lrc"
            except Exception as e:
                logger.warning("保存酷我歌词失败: %s", e)
                lrc_path = None

        # 3. 补全元数据
        if not meta.duration or not meta.album or not meta.cover_url:
            detail = await self.get_detail(rid)
            if detail:
                if not meta.duration and detail.get("duration"):
                    meta.duration = _parse_duration(detail.get("duration"))
                if not meta.album:
                    meta.album = detail.get("album") or detail.get("albname")
                if not meta.cover_url:
                    pic = detail.get("pic") or detail.get("albpic")
                    if pic:
                        meta.cover_url = pic

        logger.info("酷我下载完成: %s - %s (audio=%s, lrc=%s)",
                    meta.title, meta.artist, bool(audio_path), lrc_format)
        return DownloadResult(
            meta=meta,
            audio_path=audio_path,
            lrc_path=lrc_path,
            lrc_format=lrc_format,
            success=True,
        )

    async def _download_file(self, url: str, dest: str) -> bool:
        """流式下载文件（带 Referer 防盗链）。"""
        try:
            headers = {"User-Agent": UA, "Referer": "http://www.kuwo.cn/"}
            async with httpx.AsyncClient(
                headers=headers, timeout=60.0, follow_redirects=True
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
