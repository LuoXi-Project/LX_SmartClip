"""抖音视频上传（social-auto-upload 源码内联 + 桌面化改造）。

基于 dreammis/social-auto-upload 的 uploader/douyin_uploader/main.py 改造：
- 去掉 conf / loguru / cv2 / segno 依赖，改用标准 logging + 项目进度协议
- cookie 路径走 _cookie.py（落 <home>/data/cookies/douyin/）
- 浏览器启动走 _browser.py 的本地 Chrome/Edge 优先策略
- 去掉终端二维码（桌面 App 直接在可见浏览器里扫码）
- 用 patchright（Playwright 反检测分支）替代裸 playwright

登录态校验、上传页定位、标题/描述/话题填写、封面设置、发布按钮等核心 DOM 交互逻辑
保留上游实现（已适配 2026-06 抖音创作者中心版本）。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.core.publisher._browser import build_launch_kwargs, resolve_browser
from app.core.publisher._cookie import cookie_file_for
from app.core.publisher._progress import emit_error, emit_log, emit_progress
from app.core.publisher._stealth import set_init_script
from app.core.publisher.types import PublishItem, TaskItemResult

logger = logging.getLogger("publisher.douyin")

DOUYIN_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
DOUYIN_PUBLISH_STRATEGY_SCHEDULED = "scheduled"

# 抖音创作者中心关键 URL
DOUYIN_CREATOR_HOME = "https://creator.douyin.com/"
DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"


async def _cookie_auth(account_file: str) -> bool:
    """校验 cookie 是否有效（有头模式，避免无头撞反爬误判）。

    保留上游逻辑：打开上传页，若 URL 仍含 content/upload 且无登录文案 → cookie 有效。
    重试 3 次 + 宽松判定，应对页面瞬时跳转。
    """
    from patchright.async_api import async_playwright

    resolved = resolve_browser()
    use_headless = os.environ.get("DOUYIN_COOKIE_AUTH_HEADLESS", "").lower() in ("1", "true", "yes")
    launch_kwargs = build_launch_kwargs(resolved, headless=use_headless)

    for _attempt in range(3):
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(**launch_kwargs)
                try:
                    context = await browser.new_context(storage_state=account_file)
                    context = await set_init_script(context)
                    page = await context.new_page()
                    await page.goto(
                        "https://creator.douyin.com/creator-micro/content/upload",
                        wait_until="domcontentloaded",
                        timeout=90000,
                    )
                    await page.wait_for_timeout(2500)
                    has_login = (
                        await page.get_by_text("手机号登录").count()
                        or await page.get_by_text("扫码登录").count()
                    )
                    if "content/upload" in page.url and not has_login:
                        return True
                finally:
                    await browser.close()
        except Exception as exc:
            logger.debug("cookie 校验第 %d 次异常: %s", _attempt + 1, exc)
    return False


async def douyin_check_login(account: str = "main") -> bool:
    """供 /accounts/douyin/check 调用：精确校验某账号登录态。"""
    f = cookie_file_for("douyin", account)
    if not f.exists():
        return False
    return await _cookie_auth(str(f))


async def _do_login(account_file: str) -> bool:
    """打开可见浏览器供用户扫码登录，登录成功后保存 cookie。

    用 start()/stop() 显式管理 patchright（而非 async with），避免 async with
    在 sleep 让出控制权时因 transport 事件提前退出 __aexit__ 导致登录循环中断。
    """
    from patchright.async_api import async_playwright

    resolved = resolve_browser()
    launch_kwargs = build_launch_kwargs(resolved, headless=False)
    emit_progress(platform="douyin", step="login_qrcode", status="running", pct=5,
                  message="已打开抖音登录页，请在弹出的浏览器中扫码")

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(**launch_kwargs)

        context = await browser.new_context()
        context = await set_init_script(context)
        page = await context.new_page()

        await page.goto(DOUYIN_CREATOR_HOME, wait_until="domcontentloaded", timeout=90000)
        # 等扫码登录入口出现（最多 60s）
        try:
            await page.get_by_text("扫码登录", exact=True).first.wait_for(state="attached", timeout=60000)
        except Exception:
            pass
        emit_progress(platform="douyin", step="login_wait", status="running", pct=10,
                      message="等待扫码登录完成（最长 5 分钟），请在浏览器中扫码")

        # 轮询检测登录完成。
        # 登录成功的可靠标志：URL 跳到 creator-micro，且扫码登录按钮消失。
        login_done = False
        for i in range(100):  # 100 * 3s = 5min
            # 浏览器/页面被手动关闭 → 退出
            try:
                if page.is_closed():
                    emit_error("浏览器页面已关闭，登录中止")
                    return False
            except Exception:
                pass
            try:
                cur_url = page.url or ""
                if "creator.douyin.com/creator-micro" in cur_url:
                    try:
                        scan_btn_count = await page.get_by_text("扫码登录", exact=True).first.count()
                    except Exception:
                        scan_btn_count = 0
                    if scan_btn_count == 0:
                        login_done = True
                        emit_log(f"检测到登录成功：URL={cur_url}")
                        break
            except Exception as exc:
                # 页面/上下文可能已失效（浏览器被关）
                logger.debug("登录轮询第 %d 次异常: %s", i + 1, exc)
            await asyncio.sleep(3)

        if not login_done:
            emit_error("抖音登录超时（5 分钟未完成扫码）")
            return False

        await asyncio.sleep(2)
        Path(account_file).parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=account_file)

        # 二次校验
        if await _cookie_auth(account_file):
            emit_progress(platform="douyin", step="login_wait", status="success", pct=15,
                          message="抖音登录成功，cookie 已保存")
            return True
        emit_error("登录流程完成但 cookie 校验失败")
        return False
    except Exception as exc:
        emit_error(f"登录流程异常: {exc}")
        logger.exception("登录流程异常")
        return False
    finally:
        # 显式清理（顺序：context 已在 try 内用完，这里只关 browser + playwright）
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


async def douyin_login(account: str = "main") -> bool:
    """触发抖音扫码登录。返回是否成功。"""
    f = cookie_file_for("douyin", account)
    # 已有有效 cookie 则跳过
    if f.exists() and await _cookie_auth(str(f)):
        emit_log("抖音账号已登录（cookie 有效），无需重复登录")
        return True
    return await _do_login(str(f))


async def fill_title_and_description(page, title: str, description: str, tags: list[str] | None = None) -> None:
    """填写标题、描述、话题（保留上游 2026-06 版本适配）。"""
    # 2026-06 抖音发布页 DOM：标题=input[placeholder*=填写作品标题]，描述=div.zone-container[contenteditable]
    title_input = page.locator('input[placeholder*="填写作品标题"]').first
    await title_input.wait_for(state="visible", timeout=120000)
    await title_input.fill(title[:30])

    description_editor = page.locator('div.zone-container[contenteditable="true"]').first
    await description_editor.wait_for(state="visible", timeout=120000)
    await description_editor.click()
    await page.keyboard.press("Control+KeyA")
    await page.keyboard.press("Delete")

    for tag in tags or []:
        await page.keyboard.type(" #" + tag)
        await page.keyboard.press("Space")
    await page.keyboard.press("Escape")  # 收起话题下拉，避免浮层拦截后续点击


async def set_schedule_time(page, publish_date: datetime) -> None:
    """定时发布时间设置。"""
    label_element = page.locator("[class^='radio']:has-text('定时发布')")
    await label_element.click()
    await asyncio.sleep(1)
    publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")
    await asyncio.sleep(1)
    await page.locator('.semi-input[placeholder="日期和时间"]').click()
    await page.keyboard.press("Control+KeyA")
    await page.keyboard.type(str(publish_date_hour))
    await page.keyboard.press("Enter")
    await asyncio.sleep(1)


async def _set_cover(page, cover_path: Optional[str]) -> None:
    """设置视频封面（简化版上游逻辑）。"""
    if not cover_path:
        return
    if not Path(cover_path).is_file():
        logger.warning("封面文件不存在，跳过封面设置: %s", cover_path)
        return
    emit_log("正在设置视频封面")
    # 清掉新手引导浮层，否则拦截点击
    await page.evaluate(
        "() => document.querySelectorAll('.shepherd-element,.shepherd-modal-overlay-container').forEach(e=>e.remove())"
    )
    try:
        await page.get_by_text("选择封面", exact=True).first.click(force=True)
    except Exception as exc:
        logger.warning("点击「选择封面」失败，跳过封面: %s", exc)
        return
    cover_locator_str = "div.dy-creator-content-modal"
    try:
        await page.wait_for_selector(cover_locator_str, timeout=20000)
    except Exception:
        logger.warning("封面弹窗未出现，跳过封面设置")
        return
    cover_locator = page.locator(cover_locator_str).first
    await page.wait_for_timeout(1500)
    # version_2 封面弹窗有 4 个隐藏 file input，第 2 个（nth(1)）才是真正封面上传
    cover_upload = cover_locator.locator("input.semi-upload-hidden-input").nth(1)
    await cover_upload.set_input_files(cover_path)
    await page.wait_for_timeout(3000)
    emit_log("封面已上传到预览")
    try:
        await cover_locator.get_by_role("button", name="完成", exact=True).first.click()
        await cover_locator.wait_for(state="detached", timeout=20000)
        emit_log("视频封面设置完成")
    except Exception as exc:
        logger.warning("封面应用失败（忽略，继续发布）: %s", exc)


async def set_self_declaration(page) -> None:
    """抖音「自主声明」为发布必选项（容错：失败则跳过不中断）。"""
    try:
        entry = page.get_by_text("请选择自主声明").first
        await entry.wait_for(state="visible", timeout=6000)
        await entry.click()
        dialog = page.locator(".semi-modal-content").filter(has_text="对作品内容添加声明").first
        await dialog.wait_for(state="visible", timeout=6000)
        option = dialog.locator(".semi-radio").filter(has_text="内容为个人观点或见解").first
        if await option.count():
            await option.click(timeout=6000)
        else:
            await dialog.get_by_text("内容为个人观点或见解", exact=True).first.click(timeout=6000, force=True)
        await dialog.get_by_role("button", name="确定").click(timeout=6000)
        await dialog.wait_for(state="hidden", timeout=6000)
        emit_log("自主声明已选择")
    except Exception as exc:
        logger.warning("自主声明设置失败，跳过该步骤继续发布: %s", exc)


async def handle_auto_video_cover(page) -> bool:
    """发布前提示设置封面时，自动选第一个推荐封面。"""
    try:
        if await page.get_by_text("请设置封面后再发布").first.is_visible():
            recommend_cover = page.locator('[class^="recommendCover-"]').first
            if await recommend_cover.count():
                await recommend_cover.click()
                await asyncio.sleep(1)
                if await page.get_by_text("是否确认应用此封面？").first.is_visible():
                    await page.get_by_role("button", name="确定").click()
                    await asyncio.sleep(1)
                return True
    except Exception:
        pass
    return False


async def publish(item: PublishItem, video_path: str) -> TaskItemResult:
    """抖音视频发布主流程。供 worker 调用。

    Args:
        item: 单平台发布请求
        video_path: 视频文件绝对路径
    Returns:
        TaskItemResult：含 success/failed 状态与结果说明
    """
    from patchright.async_api import async_playwright

    result = TaskItemResult(platform="douyin", account=item.account)
    start_ts = datetime.now()

    # 前置校验
    if not Path(video_path).is_file():
        result.status = "failed"
        result.message = f"视频文件不存在: {video_path}"
        emit_error(result.message)
        return result

    account_file = str(cookie_file_for("douyin", item.account))
    if not Path(account_file).exists():
        result.status = "failed"
        result.message = f"抖音账号 {item.account} 未登录，请先在账号管理中登录"
        emit_error(result.message)
        return result

    resolved = resolve_browser()
    # 发布流程可无头（更快、不弹窗），但首次若风控严重可改有头调试
    publish_headless = os.environ.get("DOUYIN_PUBLISH_HEADLESS", "true").lower() in ("1", "true", "yes")
    launch_kwargs = build_launch_kwargs(resolved, headless=publish_headless)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                storage_state=account_file,
                permissions=["geolocation"],
            )
            context = await set_init_script(context)
            page = await context.new_page()

            emit_progress(platform="douyin", step="upload_start", status="running", pct=20,
                          message="打开抖音上传页")

            await page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_url(DOUYIN_UPLOAD_URL, timeout=90000)
            # 等上传 input 挂载
            await page.wait_for_selector("div[class^='container'] input", state="attached", timeout=60000)
            await page.locator("div[class^='container'] input").set_input_files(video_path)

            emit_progress(platform="douyin", step="uploading", status="running", pct=30,
                          message=f"视频上传中: {Path(video_path).name}")

            # 等进入发布页（version_1 或 version_2）
            while True:
                try:
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/publish?enter_from=publish_page",
                        timeout=3000,
                    )
                    break
                except Exception:
                    try:
                        await page.wait_for_url(
                            "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
                            timeout=3000,
                        )
                        break
                    except Exception:
                        await asyncio.sleep(0.5)

            await asyncio.sleep(1)
            emit_progress(platform="douyin", step="fill_meta", status="running", pct=50,
                          message="填写标题、描述、话题")

            await fill_title_and_description(page, item.title, item.description or item.title, item.tags)

            # 等视频上传完成（"重新上传" 出现）
            while True:
                try:
                    number = await page.locator('[class^="long-card"] div:has-text("重新上传")').count()
                    if number > 0:
                        emit_progress(platform="douyin", step="uploading", status="success", pct=70,
                                      message="视频上传完成")
                        break
                    await asyncio.sleep(2)
                    if await page.locator('div.progress-div > div:has-text("上传失败")').count():
                        emit_progress(platform="douyin", step="uploading", status="running", pct=30,
                                      message="上传失败，重试中")
                        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(video_path)
                except Exception:
                    await asyncio.sleep(2)

            # 封面
            if item.cover_path:
                emit_progress(platform="douyin", step="set_cover", status="running", pct=75,
                              message="设置封面")
                await _set_cover(page, item.cover_path)

            # 自主声明（抖音必选）
            await set_self_declaration(page)

            # 第三方内容开关（若存在）
            third_part_element = '[class^="info"] > [class^="first-part"] div div.semi-switch'
            if await page.locator(third_part_element).count():
                cls = await page.eval_on_selector(third_part_element, "div => div.className")
                if "semi-switch-checked" not in cls:
                    await page.locator(third_part_element).locator("input.semi-switch-native-control").click()

            # 定时发布
            if item.publish_strategy == DOUYIN_PUBLISH_STRATEGY_SCHEDULED and item.publish_date:
                try:
                    pd = datetime.fromisoformat(item.publish_date)
                    await set_schedule_time(page, pd)
                except Exception as exc:
                    logger.warning("定时发布设置失败，改用立即发布: %s", exc)

            # 点击发布按钮
            emit_progress(platform="douyin", step="publishing", status="running", pct=90,
                          message="点击发布按钮")
            publish_deadline = datetime.now().timestamp() + 120  # 最多等 2 分钟
            while datetime.now().timestamp() < publish_deadline:
                try:
                    # 移除会拦截点击的新手引导/话题下拉浮层
                    await page.evaluate(
                        "() => { document.querySelectorAll('.shepherd-element, .shepherd-modal-overlay-container, [class*=\"mention-wrapper\"]').forEach(e => e.remove()); }"
                    )
                    publish_button = page.get_by_role("button", name="发布", exact=True)
                    if await publish_button.count():
                        await publish_button.click(force=True)
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/manage**",
                        timeout=3000,
                    )
                    emit_progress(platform="douyin", step="publish_done", status="success", pct=100,
                                  message="视频发布成功")
                    result.status = "success"
                    result.message = "抖音发布成功"
                    break
                except Exception:
                    await handle_auto_video_cover(page)
                    await asyncio.sleep(0.5)
            else:
                result.status = "failed"
                result.message = "发布超时（2 分钟内未跳转到内容管理页）"
                emit_error(result.message)

            # 更新 cookie（无论成功失败，刷新登录态）
            try:
                await context.storage_state(path=account_file)
            except Exception:
                pass
            await asyncio.sleep(2)
            await context.close()
            await browser.close()

    except Exception as exc:
        result.status = "failed"
        result.message = f"抖音发布异常: {exc}"
        emit_error(result.message)
        logger.exception("抖音发布异常")

    result.duration_sec = round((datetime.now() - start_ts).total_seconds(), 1)
    return result
