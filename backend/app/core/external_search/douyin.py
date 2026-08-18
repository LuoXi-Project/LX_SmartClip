"""抖音关键词搜索：patchright（Playwright 反检测分支）+ 主站扫码登录态。

设计要点：
- www.douyin.com 主站搜索必须真实登录（创作者中心 cookie 不被主站搜索识别），
  采集模块维护独立登录态：data/cookies/douyin/search.json（扫码一次即可复用）；
  若不存在则回退复用发布模块的 main 账号（部分场景可用）。
- 浏览器只承担「搜索」；拿到视频 ID 后构造 iesdouyin 分享页 URL，下载仍走现有
  douyin_downloader 的匿名解析（免水印），两条链路互不依赖。
- 搜索结果 DOM 选择器做多级 fallback，缓解抖音页面结构变更的影响。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote

from .types import PLATFORM_DOUYIN, ExternalSearchResult

logger = logging.getLogger(__name__)

DOUYIN_SEARCH_URL = "https://www.douyin.com/search/{query}?type=video"
DOUYIN_HOME_URL = "https://www.douyin.com/"

# 采集专用登录账号名（与发布模块 main 区分，互不影响）
SEARCH_ACCOUNT = "search"

# 登录轮询：3s × 100 = 5 分钟（与发布模块一致）
_LOGIN_POLL_INTERVAL_SEC = 3
_LOGIN_TIMEOUT_ROUNDS = 100

# 视频卡片链接（/video/<19位数字>）
_VIDEO_ID_RE = re.compile(r"/video/(\d{6,32})")
# 卡片文本里的时长（MM:SS 或 H:MM:SS，如 01:23 / 1:02:45）
_DURATION_RE = re.compile(r"(?<!\d)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?!\d)")

# 结果卡片里应排除的导航/页脚类链接关键词
_BAD_LINK_HINTS = ("search", "user", "note", "live", "login")


def _headless_flag() -> bool:
    """抖音搜索是否无头运行。

    默认有头：与发布模块一致，无头模式会撞抖音「验证码中间页」风控
    （发布模块 _cookie_auth 的先例：有头模式，避免无头撞反爬误判）。
    调试时可设 DOUYIN_SEARCH_HEADLESS=1 强制无头。
    """
    raw = (os.environ.get("DOUYIN_SEARCH_HEADLESS") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def preferred_cookie_file() -> Path | None:
    """搜索可用的登录态文件：专用 search 账号优先，回退发布模块 main 账号。"""
    from app.core.publisher._cookie import cookie_file_for

    dedicated = cookie_file_for("douyin", SEARCH_ACCOUNT)
    if dedicated.exists():
        return dedicated
    main = cookie_file_for("douyin", "main")
    if main.exists():
        return main
    return None


def douyin_cookie_ready() -> bool:
    """抖音搜索依赖的登录态是否存在（粗判：cookie 文件存在）。"""
    return preferred_cookie_file() is not None


async def login_douyin_search(on_stage=None) -> bool:
    """打开可见浏览器供用户在抖音主站扫码登录，成功后保存专用 storage_state。

    登录成功的可靠标志：上下文出现 domain 含 douyin.com 的 sessionid cookie。
    on_stage: 可选的 async 回调（(stage, message)），供 API 层接 JobReporter 汇报进度。
    """

    async def _report(stage: str, message: str) -> None:
        if on_stage is not None:
            try:
                await on_stage(stage, message)
            except Exception:
                pass

    from app.core.publisher._browser import build_launch_kwargs, resolve_browser
    from app.core.publisher._cookie import cookie_file_for
    from app.core.publisher._stealth import set_init_script

    resolved = resolve_browser()
    launch_kwargs = build_launch_kwargs(resolved, headless=False)

    from patchright.async_api import async_playwright

    # 用 start()/stop() 显式管理 patchright（避免 async with 在 sleep 让出时提前退出）
    playwright = await async_playwright().start()
    browser = None
    try:
        await _report("login_open", "已打开抖音首页，请在弹出窗口中扫码登录")
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto(DOUYIN_HOME_URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(3000)

        # 匿名访问通常会自动弹出二维码登录框；若没有则尝试点击顶部「登录」按钮
        try:
            login_btn = page.get_by_role("button", name="登录").first
            if await login_btn.count():
                await login_btn.click(timeout=3000)
        except Exception:
            pass
        await _report("login_wait", "等待扫码登录完成（最长 5 分钟）…")

        for _round in range(_LOGIN_TIMEOUT_ROUNDS):
            try:
                if page.is_closed():
                    await _report("login_error", "浏览器窗口被关闭，登录中止")
                    return False
                cookies = await context.cookies()
                has_session = any(
                    c.get("name") == "sessionid" and "douyin.com" in (c.get("domain") or "")
                    for c in cookies
                )
                if has_session:
                    target = cookie_file_for("douyin", SEARCH_ACCOUNT)
                    await context.storage_state(path=str(target))
                    await _report("login_done", f"抖音登录成功，登录态已保存：{target.name}")
                    return True
            except Exception as exc:
                logger.debug("登录轮询异常：%s", exc)
            await asyncio.sleep(_LOGIN_POLL_INTERVAL_SEC)

        await _report("login_error", "抖音登录超时（5 分钟未完成扫码）")
        return False
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        await playwright.stop()


# 在浏览器上下文里跑的采集脚本：收集去重后的视频卡片原始信息。
_EXTRACT_JS = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/video/"]').forEach((a) => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/\\/video\\/(\\d{6,32})/);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    // 向上找卡片容器：包含图片且有足够文本的最近祖先
    let card = a;
    for (let i = 0; i < 6 && card && card.parentElement; i++) {
      card = card.parentElement;
      if (card.querySelector && card.querySelector('img') && (card.innerText || '').trim().length > 8) break;
    }
    const text = ((card && card.innerText) || a.innerText || '').trim();
    const img = card && card.querySelector ? card.querySelector('img') : null;
    seen.add(id);
    out.push({
      href: a.href || href,
      text: text.slice(0, 400),
      alt: img ? (img.getAttribute('alt') || '') : '',
      cover: img ? (img.src || '') : '',
      aria: a.getAttribute('aria-label') || '',
    });
  });
  return out;
}
"""


def _parse_duration(text: str) -> float | None:
    """从卡片文本解析时长（取最后一次出现的时间样式）。

    支持 MM:SS 与 H:MM:SS 两种格式；时长徽标一般出现在卡片文本末尾。
    """
    matches = _DURATION_RE.findall(text)
    if not matches:
        return None
    h, m, s = matches[-1]
    try:
        total = (int(h) if h else 0) * 3600 + int(m) * 60 + int(s)
    except ValueError:
        return None
    if 0 < total < 24 * 3600:
        return float(total)
    return None


# 纯数字/点赞统计行（如 "28.3万" "1,234" "12赞"）
_STATS_LINE_RE = re.compile(r"^[\d.,]+\s*[万亿]?(?:赞|喜欢|粉丝|次?播放|评论|收藏)?$")


def _clean_title(raw_text: str, alt: str, aria: str) -> str:
    """标题启发式：卡片内最长的非统计/非时长/非作者行；兜底 img alt / aria-label。"""
    candidates: list[str] = []
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not (2 <= len(line) <= 120):
            continue
        if _DURATION_RE.search(line):
            continue
        if _STATS_LINE_RE.match(line):
            continue
        if line.startswith("@"):
            continue
        candidates.append(line)
    if candidates:
        # 标题通常是卡片文本里最长的一行
        return max(candidates, key=len)[:120]
    for cand in (alt, aria):
        cand = (cand or "").strip()
        if cand:
            return cand[:120]
    return ""


def _parse_card(item: dict, keyword: str) -> ExternalSearchResult | None:
    href = str(item.get("href") or "")
    m = _VIDEO_ID_RE.search(href)
    if not m:
        return None
    video_id = m.group(1)
    if any(h in href for h in _BAD_LINK_HINTS):
        return None
    text = str(item.get("text") or "")
    title = _clean_title(text, str(item.get("alt") or ""), str(item.get("aria") or ""))
    # 作者名通常是卡片里 @ 开头的行
    author = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("@") and 1 < len(line) <= 40:
            author = line.lstrip("@")[:40]
            break
    stats_text = ""
    for line in text.splitlines():
        line = line.strip()
        if _STATS_LINE_RE.match(line) and any(ch.isdigit() for ch in line):
            stats_text = line
            break
    return ExternalSearchResult(
        platform=PLATFORM_DOUYIN,
        video_id=video_id,
        title=title or f"抖音视频_{video_id[:8]}",
        author=author,
        duration_sec=_parse_duration(text),
        # 下载走 iesdouyin 匿名分享页解析（douyin_downloader.is_douyin_link 命中）
        url=f"https://www.iesdouyin.com/share/video/{video_id}",
        cover_url=str(item.get("cover") or ""),
        keyword=keyword,
        stats_text=stats_text,
    )


async def search_douyin(
    query: str,
    limit: int = 10,
) -> list[ExternalSearchResult]:
    """在抖音网页版搜索视频关键词，返回去重后的结果列表。

    Raises:
        DouyinSearchError: 未登录 / 页面结构失效 / 超时等。
    """
    from .types import DouyinSearchError

    query = (query or "").strip()
    if not query:
        raise DouyinSearchError("搜索关键词为空")
    limit = max(1, min(int(limit or 10), 30))

    cookie_file = preferred_cookie_file()
    if cookie_file is None:
        raise DouyinSearchError(
            "未找到抖音登录态：请在素材库「关键词采集」面板点击「登录抖音」完成主站扫码登录"
        )

    from app.core.publisher._browser import build_launch_kwargs, resolve_browser
    from app.core.publisher._stealth import set_init_script

    resolved = resolve_browser()
    launch_kwargs = build_launch_kwargs(resolved, headless=_headless_flag())

    from patchright.async_api import async_playwright

    results: dict[str, ExternalSearchResult] = {}
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(storage_state=str(cookie_file))
                context = await set_init_script(context)
                page = await context.new_page()

                await page.goto(
                    DOUYIN_SEARCH_URL.format(query=quote(query)),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )

                # 等首批卡片出现；无感验证偶发拦截时重载一次再等
                try:
                    await page.wait_for_selector(
                        'a[href*="/video/"]', timeout=30000
                    )
                except Exception:
                    reloaded = False
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_selector('a[href*="/video/"]', timeout=20000)
                        reloaded = True
                    except Exception:
                        pass
                    if not reloaded:
                        page_title = ""
                        try:
                            page_title = await page.title()
                        except Exception:
                            pass
                        if "验证" in page_title:
                            raise DouyinSearchError(
                                "抖音触发验证码：请在弹出的浏览器窗口中完成验证后重试；"
                                "频繁出现时可稍后再试或降低采集频率"
                            )
                        # 登录墙判定：仅统计「可见」的扫码登录元素（页面常含隐藏文案，避免误判）
                        login_hit = False
                        try:
                            loc = page.get_by_text("扫码登录").first
                            if await loc.count() > 0:
                                login_hit = await loc.is_visible()
                        except Exception:
                            pass
                        if login_hit:
                            raise DouyinSearchError(
                                "抖音登录态已失效：请在素材库「关键词采集」面板重新扫码登录"
                            )
                        raise DouyinSearchError(
                            "抖音搜索页加载超时，未获取到结果（页面结构可能已变更）"
                        )

                # 滚动加载直到凑够 limit 或连续两屏无新增
                stall = 0
                for _round in range(10):
                    raw_items = await page.evaluate(_EXTRACT_JS)
                    before = len(results)
                    for item in raw_items or []:
                        parsed = _parse_card(item, query)
                        if parsed and parsed.video_id not in results:
                            results[parsed.video_id] = parsed
                    if len(results) >= limit:
                        break
                    stall = stall + 1 if len(results) == before else 0
                    if stall >= 2:
                        break
                    await page.mouse.wheel(0, 2400)
                    await page.wait_for_timeout(1500)

                # 会话 cookie 会轮转（msToken/ttwid 等），成功访问后回存以延长登录态寿命
                try:
                    await context.storage_state(path=str(cookie_file))
                except Exception:
                    pass
            finally:
                await browser.close()
    except DouyinSearchError:
        raise
    except Exception as exc:
        from .types import DouyinSearchError as _Err

        raise _Err(f"抖音搜索失败：{str(exc).strip()[-300:]}") from exc

    ordered = list(results.values())[:limit]
    logger.info("抖音搜索 %r 命中 %d 条（取 %d）", query, len(results), len(ordered))
    return ordered
