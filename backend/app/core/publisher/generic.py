"""通用平台发布/登录流程（参数化各平台配置）。

复用 douyin.py 已验证的浏览器启动、cookie 校验、登录轮询、上传流程骨架，
通过 PlatformConfig 表达各平台差异（URL/选择器），实现"一套代码多平台"。

注意：抖音（douyin）仍用独立的 douyin.py（已深度联调，DOM 适配最完整）；
其余平台（xhs/wxchannels/bilibili/kuaishou）走本模块的通用流程。
通用流程对 DOM 选择器做了多候选兜底，但可能因平台改版需要调整。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.publisher._browser import build_launch_kwargs, resolve_browser
from app.core.publisher._cookie import cookie_file_for
from app.core.publisher._progress import emit_error, emit_log, emit_progress
from app.core.publisher._stealth import set_init_script
from app.core.publisher.platform_registry import PlatformConfig, get_config
from app.core.publisher.types import PublishItem, TaskItemResult

logger = logging.getLogger("publisher.generic")


async def _cookie_auth(cfg: PlatformConfig, account_file: str) -> bool:
    """通用 cookie 校验：打开上传页，若 URL 含登录后片段且无登录按钮 → 有效。"""
    from patchright.async_api import async_playwright

    resolved = resolve_browser()
    launch_kwargs = build_launch_kwargs(resolved, headless=True)
    for _ in range(2):
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(**launch_kwargs)
                try:
                    context = await browser.new_context(storage_state=account_file)
                    context = await set_init_script(context)
                    page = await context.new_page()
                    await page.goto(cfg.upload_url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(2500)
                    has_login = await page.get_by_text(cfg.login_btn_text, exact=False).first.count()
                    if cfg.logged_in_url_fragment in page.url and not has_login:
                        return True
                finally:
                    await browser.close()
        except Exception as exc:
            logger.debug("%s cookie 校验异常: %s", cfg.name, exc)
    return False


async def check_login(platform: str, account: str = "main") -> bool:
    """精确校验某账号登录态。"""
    cfg = get_config(platform)
    if not cfg:
        return False
    f = cookie_file_for(platform, account)
    if not f.exists():
        return False
    return await _cookie_auth(cfg, str(f))


async def _do_login(cfg: PlatformConfig, account_file: str) -> bool:
    """通用扫码登录：打开首页→等待扫码→检测登录成功→保存 cookie。"""
    from patchright.async_api import async_playwright

    resolved = resolve_browser()
    launch_kwargs = build_launch_kwargs(resolved, headless=False)
    emit_progress(platform=cfg.name, step="login_qrcode", status="running", pct=5,
                  message=f"已打开{cfg.label}登录页，请在弹出的浏览器中扫码")

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()

        await page.goto(cfg.creator_home, wait_until="domcontentloaded", timeout=90000)
        try:
            await page.get_by_text(cfg.login_btn_text, exact=False).first.wait_for(state="attached", timeout=60000)
        except Exception:
            pass
        emit_progress(platform=cfg.name, step="login_wait", status="running", pct=10,
                      message=f"等待扫码登录完成（最长 5 分钟），请在浏览器中扫码")

        login_done = False
        for i in range(100):  # 5min
            try:
                if page.is_closed():
                    emit_error(f"{cfg.label}浏览器页面已关闭，登录中止")
                    return False
            except Exception:
                pass
            try:
                cur_url = page.url or ""
                if cfg.logged_in_url_fragment in cur_url:
                    try:
                        login_btn_count = await page.get_by_text(cfg.login_btn_text, exact=False).first.count()
                    except Exception:
                        login_btn_count = 0
                    if login_btn_count == 0:
                        login_done = True
                        emit_log(f"检测到{cfg.label}登录成功：URL={cur_url}")
                        break
            except Exception as exc:
                logger.debug("%s 登录轮询第 %d 次异常: %s", cfg.name, i + 1, exc)
            await asyncio.sleep(3)

        if not login_done:
            emit_error(f"{cfg.label}登录超时（5 分钟未完成扫码）")
            return False

        await asyncio.sleep(2)
        Path(account_file).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=account_file)

        if await _cookie_auth(cfg, account_file):
            emit_progress(platform=cfg.name, step="login_wait", status="success", pct=15,
                          message=f"{cfg.label}登录成功，cookie 已保存")
            return True
        emit_error(f"{cfg.label}登录流程完成但 cookie 校验失败")
        return False
    except Exception as exc:
        emit_error(f"{cfg.label}登录流程异常: {exc}")
        logger.exception("%s 登录流程异常", cfg.name)
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


async def login(platform: str, account: str = "main") -> bool:
    """触发平台扫码登录。"""
    cfg = get_config(platform)
    if not cfg:
        emit_error(f"不支持的平台: {platform}")
        return False
    f = cookie_file_for(platform, account)
    if f.exists() and await _cookie_auth(cfg, str(f)):
        emit_log(f"{cfg.label}账号已登录（cookie 有效），无需重复登录")
        return True
    return await _do_login(cfg, str(f))


async def _try_selectors(page, selectors: str, action: str = "fill", value: str = "") -> bool:
    """多候选选择器兜底：依次尝试，第一个成功的生效。"""
    for sel in [s.strip() for s in selectors.split(",") if s.strip()]:
        try:
            loc = page.locator(sel).first
            if action == "fill":
                await loc.wait_for(state="visible", timeout=10000)
                await loc.fill(value)
            elif action == "click":
                await loc.wait_for(state="visible", timeout=10000)
                await loc.click()
            return True
        except Exception:
            continue
    return False


async def _any_visible(page, selectors: str) -> bool:
    """多候选选择器中任一可见即返回 True（用于状态检测）。

    对每个候选用 count()>0 判断（比 is_visible 更稳，避免多元素/隐藏元素异常）。
    """
    for sel in [s.strip() for s in selectors.split(",") if s.strip()]:
        try:
            cnt = await page.locator(sel).count()
            if cnt > 0:
                return True
        except Exception:
            continue
    return False


async def _wait_upload_done(page, cfg: PlatformConfig, timeout_sec: int = 600) -> bool:
    """等待视频上传/转码完成。返回 True=完成，False=超时或失败。

    优先用平台配置的 upload_done_selector 轮询检测（B站等）；
    未配置则退化成固定等待 + 失败检测的粗等策略。
    """
    deadline = datetime.now().timestamp() + timeout_sec
    # 先给平台一点反应时间（上传初始化）
    await page.wait_for_timeout(3000)

    while datetime.now().timestamp() < deadline:
        # 失败检测：上传/转码失败直接返回
        if cfg.upload_fail_selector and await _any_visible(page, cfg.upload_fail_selector):
            emit_log(f"{cfg.label}检测到上传/转码失败标志")
            return False
        # 成功检测：配置了完成选择器则轮询，命中即返回
        if cfg.upload_done_selector:
            if await _any_visible(page, cfg.upload_done_selector):
                return True
        else:
            # 未配置选择器：粗等（最多等 timeout_sec，但提早结束不太可能，这里保底）
            # 退化策略：等待 timeout_sec 后返回 True（兼容旧行为）
            await page.wait_for_timeout(8000)
            return True
        await asyncio.sleep(3)

    emit_log(f"{cfg.label}等待上传完成超时（{timeout_sec}s）")
    return False


async def publish(item: PublishItem, video_path: str) -> TaskItemResult:
    """通用发布流程。供 worker 调用。"""
    from patchright.async_api import async_playwright

    cfg = get_config(item.platform)
    result = TaskItemResult(platform=item.platform, account=item.account)
    if not cfg:
        result.status = "failed"
        result.message = f"不支持的平台: {item.platform}"
        emit_error(result.message)
        return result

    start_ts = datetime.now()

    if not Path(video_path).is_file():
        result.status = "failed"
        result.message = f"视频文件不存在: {video_path}"
        emit_error(result.message)
        return result

    account_file = str(cookie_file_for(item.platform, item.account))
    if not Path(account_file).exists():
        result.status = "failed"
        result.message = f"{cfg.label}账号 {item.account} 未登录"
        emit_error(result.message)
        return result

    resolved = resolve_browser()
    publish_headless = os.environ.get("PUBLISH_HEADLESS", "true").lower() in ("1", "true", "yes")
    launch_kwargs = build_launch_kwargs(resolved, headless=publish_headless)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(storage_state=account_file, permissions=["geolocation"])
            context = await set_init_script(context)
            page = await context.new_page()

            emit_progress(platform=cfg.name, step="upload_start", status="running", pct=20,
                          message=f"打开{cfg.label}上传页")
            await page.goto(cfg.upload_url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(2000)

            # 设置视频文件
            emit_progress(platform=cfg.name, step="uploading", status="running", pct=30,
                          message=f"视频上传中: {Path(video_path).name}")
            # 多候选：平台配置选择器 + 通用 input[type=file]
            uploaded = False
            for sel in [cfg.upload_input_selector, "input[type='file']", "input[accept*='video']"]:
                try:
                    inp = page.locator(sel).first
                    await inp.wait_for(state="attached", timeout=15000)
                    await inp.set_input_files(video_path)
                    uploaded = True
                    break
                except Exception:
                    continue
            if not uploaded:
                raise RuntimeError(f"未找到{cfg.label}的视频上传入口")

            # 填标题
            if cfg.title_selector and item.title:
                emit_progress(platform=cfg.name, step="fill_meta", status="running", pct=50,
                              message="填写标题、描述、话题")
                await _try_selectors(page, cfg.title_selector, "fill", item.title[:50])

            # 填描述 + 话题
            if cfg.desc_selector:
                if await _try_selectors(page, cfg.desc_selector, "click"):
                    await page.keyboard.press("Control+KeyA")
                    await page.keyboard.press("Delete")
                    desc = item.description or ""
                    for tag in item.tags:
                        desc += f" #{tag}"
                    if desc:
                        await page.keyboard.type(desc)
                    await page.keyboard.press("Escape")

            # 等视频上传/转码完成（带状态检测，替代旧的固定 8 秒粗等）
            emit_progress(platform=cfg.name, step="uploading", status="running", pct=70,
                          message="等待视频上传/处理完成")
            upload_ok = await _wait_upload_done(page, cfg, timeout_sec=600)
            if not upload_ok:
                emit_progress(platform=cfg.name, step="uploading", status="running", pct=70,
                              message="上传完成检测未确认，仍尝试投稿（可能失败）")
            else:
                emit_progress(platform=cfg.name, step="uploading", status="success", pct=80,
                              message="视频上传/处理完成")

            # 点发布按钮（等待按钮可点击：转码完成前通常 disabled）
            emit_progress(platform=cfg.name, step="publishing", status="running", pct=90,
                          message=f"点击{cfg.publish_btn_text}按钮")
            published = False
            deadline = datetime.now().timestamp() + 180
            clicked_once = False
            while datetime.now().timestamp() < deadline:
                try:
                    await page.evaluate(
                        "() => document.querySelectorAll('.shepherd-element, [class*=\"mention-wrapper\"]').forEach(e=>e.remove())"
                    )
                    btn = page.get_by_role("button", name=cfg.publish_btn_text, exact=False)
                    if await btn.count():
                        btn_first = btn.first
                        # 检测按钮是否可点（非 disabled）：B站转码未完成时按钮 disabled
                        disabled = False
                        try:
                            disabled = await btn_first.is_disabled()
                        except Exception:
                            disabled = False
                        if not disabled:
                            await btn_first.click(force=True)
                            clicked_once = True
                        elif not clicked_once:
                            # 首次点击尝试：按钮 disabled，记录日志继续等
                            emit_log(f"{cfg.publish_btn_text}按钮暂不可点（可能转码未完成），等待中…")
                    await page.wait_for_timeout(3000)
                    # 检测发布成功：1) URL 跳转（精确片段）2) URL 候选片段 3) 成功元素 4) URL 离开上传页
                    cur_url = page.url or ""
                    # 1) 精确片段
                    if cfg.publish_success_fragment and cfg.publish_success_fragment in cur_url:
                        published = True
                        break
                    # 2) URL 候选片段（更宽松）
                    if cfg.publish_success_url_fragments:
                        for frag in [f.strip() for f in cfg.publish_success_url_fragments.split(",") if f.strip()]:
                            if frag and frag in cur_url:
                                published = True
                                break
                        if published:
                            break
                    # 3) 成功元素（Toast/弹窗）
                    if cfg.publish_success_selector and await _any_visible(page, cfg.publish_success_selector):
                        published = True
                        break
                    # 4) 兜底：URL 离开上传页（非登录态）
                    if cfg.upload_url not in cur_url and "login" not in cur_url:
                        published = True
                        break
                except Exception:
                    await asyncio.sleep(2)

            if published:
                emit_progress(platform=cfg.name, step="publish_done", status="success", pct=100,
                              message=f"{cfg.label}发布成功")
                result.status = "success"
                result.message = f"{cfg.label}发布成功"
            else:
                result.status = "failed"
                # 区分失败原因：是否曾成功点击过按钮
                if not clicked_once:
                    result.message = f"{cfg.label}投稿按钮始终不可点击（视频可能仍在转码），发布超时"
                else:
                    result.message = f"{cfg.label}发布超时或未检测到成功跳转"
                emit_error(result.message)

            try:
                await context.storage_state(path=account_file)
            except Exception:
                pass
            await asyncio.sleep(2)
            await context.close()
            await browser.close()

    except Exception as exc:
        result.status = "failed"
        result.message = f"{cfg.label}发布异常: {exc}"
        emit_error(result.message)
        logger.exception("%s 发布异常", cfg.name)

    result.duration_sec = round((datetime.now() - start_ts).total_seconds(), 1)
    return result
