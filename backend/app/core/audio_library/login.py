"""音频库账号扫码登录（网易云）。

仿 publisher/generic.py 的 _do_login，用 patchright 打开 music.163.com：
  1. 打开 https://music.163.com（有头浏览器，用户扫码或账密登录）
  2. 轮询 context cookies 直到出现 MUSIC_U（最长 5 分钟）
  3. storage_state 落盘 + 提取 cookie dict 写入账号 cookie 文件
  4. 调网易云 /api/nuser/account/get 拿昵称/VIP 信息一并存档

酷我免登录，本模块不处理。

浏览器引擎探测、反检测、代理复用 publisher 的 _browser.py / _stealth.py。
进度通过 publisher/_progress.py 的 emit_* 写 stdout（worker 协议一致）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from app.core.audio_library._cookie import cookie_file_for
from app.core.publisher._browser import (
    build_launch_kwargs,
    get_publish_proxy,
    resolve_browser,
)
from app.core.publisher._progress import emit_error, emit_log, emit_progress
from app.core.publisher._stealth import set_init_script

logger = logging.getLogger("audio_library.login")

# 网易云首页（未登录会显示登录入口）
NETEASE_HOME = "https://music.163.com/"
# 登录成功标志 cookie 名
NETEASE_LOGIN_COOKIE = "MUSIC_U"
# 扫码等待最长时间（秒）
LOGIN_SCAN_TIMEOUT = 300


async def _fetch_login_info(cookies: dict[str, str]) -> Optional[dict]:
    """用 cookie 调网易云接口拿用户信息（昵称/uid/vip）。失败返回 None。"""
    import httpx
    try:
        async with httpx.AsyncClient(
            base_url="https://music.163.com",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Referer": "https://music.163.com",
            },
            cookies=cookies,
            timeout=15.0,
            follow_redirects=True,
        ) as cli:
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
        logger.warning("获取网易云登录信息失败: %s", e)
    return None


async def netease_login(account: str = "main") -> bool:
    """网易云扫码登录（弹出可见浏览器）。

    成功后 cookie（含 MUSIC_U）+ storage_state + login_info 写入账号 cookie 文件。
    返回是否登录成功。
    """
    from patchright.async_api import async_playwright

    emit_progress(platform="netease", step="login_qrcode", status="running", pct=5,
                  account=account, message="已打开网易云登录页，请在弹出的浏览器中登录")

    resolved = resolve_browser()
    proxy = get_publish_proxy()  # 自动探测系统代理（音乐站点对代理无特殊需求，走系统代理即可）
    launch_kwargs = build_launch_kwargs(resolved, headless=False, proxy=proxy)

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()

        await page.goto(NETEASE_HOME, wait_until="domcontentloaded", timeout=90000)

        emit_progress(platform="netease", step="login_wait", status="running", pct=10,
                      account=account,
                      message=f"等待登录完成（最长 {LOGIN_SCAN_TIMEOUT // 60} 分钟），请在浏览器中扫码或登录")

        # 轮询 cookie 直到出现 MUSIC_U
        poll_loops = max(1, LOGIN_SCAN_TIMEOUT // 3)
        login_done = False
        for i in range(poll_loops):
            try:
                if page.is_closed():
                    emit_error("网易云登录页已关闭，登录中止")
                    return False
            except Exception:
                pass
            try:
                cks = await context.cookies()
                cookie_dict = {c["name"]: c["value"] for c in cks}
                if cookie_dict.get(NETEASE_LOGIN_COOKIE):
                    login_done = True
                    emit_log(f"检测到网易云登录成功 account={account}")
                    break
            except Exception as exc:
                logger.debug("网易云登录轮询第 %d 次异常: %s", i + 1, exc)
            await asyncio.sleep(3)

        if not login_done:
            emit_error(f"网易云登录超时（{LOGIN_SCAN_TIMEOUT} 秒未完成）")
            return False

        # 等待 cookie 稳定（登录后服务端可能续写几个 cookie）
        await asyncio.sleep(2)
        cks = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cks}

        if not cookie_dict.get(NETEASE_LOGIN_COOKIE):
            emit_error("网易云登录流程完成但未拿到 MUSIC_U cookie")
            return False

        # 拿用户信息
        login_info = await _fetch_login_info(cookie_dict)

        # storage_state 落盘（先写 storage_state，再补 cookies/login_info）
        cf = cookie_file_for("netease", account)
        cf.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(cf))

        # 合并：storage_state 已写入，追加 cookies dict + login_info（provider 读 cookies dict）
        try:
            bundle = json.loads(cf.read_text(encoding="utf-8"))
        except Exception:
            bundle = {}
        bundle["cookies"] = cookie_dict
        bundle["login_info"] = login_info
        cf.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        nickname = (login_info or {}).get("nickname", "?")
        emit_progress(platform="netease", step="login_wait", status="success", pct=15,
                      account=account, message=f"网易云登录成功：{nickname}，cookie 已保存")
        return True
    except Exception as exc:
        emit_error(f"网易云登录流程异常: {exc}")
        logger.exception("netease 登录流程异常")
        return False
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass


async def check_login(source: str, account: str = "main") -> bool:
    """精确校验某音乐源账号登录态是否仍有效。

    网易云：用 cookie 调 /api/nuser/account/get，code=200 即有效。
    酷我：免登录，永远 True（但不应走到这里，调用方会跳过）。
    """
    if source != "netease":
        return True
    from app.core.audio_library.providers.netease import NeteaseProvider
    provider = NeteaseProvider(account=account)
    try:
        return await provider.check_login()
    finally:
        await provider.close()
