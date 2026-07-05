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

from app.core.publisher._browser import build_launch_kwargs, get_publish_proxy, read_publish_proxy_config, resolve_browser
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
    proxy = await read_publish_proxy_config()
    launch_kwargs = build_launch_kwargs(resolved, headless=True, proxy=proxy)
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
    proxy = await read_publish_proxy_config()
    if proxy:
        emit_log(f"{cfg.label}登录使用代理: {proxy['server']}")
    launch_kwargs = build_launch_kwargs(resolved, headless=False, proxy=proxy)
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


async def _set_cover(page, cfg: PlatformConfig, cover_path: str | None) -> None:
    """设置封面（B站等平台必填项，缺封面「立即投稿」会 disabled）。

    策略由 cfg.cover_strategy 决定：
    - upload_cover：有 cover_path 则上传自定义封面，无则回退 auto_cut
    - auto_cut：点击「添加封面」→ 应用视频自动截取的第一帧

    容错：失败不中断，日志记录（用户可在有头模式手动补）。
    """
    if not cfg.cover_strategy:
        return
    strategy = cfg.cover_strategy
    if strategy == "upload_cover" and not cover_path:
        strategy = "auto_cut"  # 无自定义封面，回退自动截帧
    if not cover_path or not Path(cover_path).is_file():
        if strategy == "upload_cover":
            strategy = "auto_cut"
        elif strategy not in ("auto_cut",):
            return

    emit_progress(platform=cfg.name, step="set_cover", status="running", pct=82,
                  message="设置封面")
    # 清掉可能拦截点击的浮层
    try:
        await page.evaluate(
            "() => document.querySelectorAll('.shepherd-element,.shepherd-modal-overlay-container').forEach(e=>e.remove())"
        )
    except Exception:
        pass

    # 1) 点封面入口
    entry_clicked = False
    for sel in [s.strip() for s in cfg.cover_entry_selector.split(",") if s.strip()]:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=8000)
            await loc.click(force=True)
            entry_clicked = True
            break
        except Exception:
            continue
    if not entry_clicked:
        emit_log(f"{cfg.label}未找到封面入口（可能已有封面），跳过封面设置")
        return

    await page.wait_for_timeout(2000)

    # 2a) 上传自定义封面
    if strategy == "upload_cover" and cover_path and Path(cover_path).is_file():
        try:
            cover_input = page.locator("input[type='file'][accept*='image'], input[type='file']").first
            await cover_input.wait_for(state="attached", timeout=8000)
            await cover_input.set_input_files(cover_path)
            emit_log(f"{cfg.label}已上传自定义封面: {Path(cover_path).name}")
            await page.wait_for_timeout(2000)
        except Exception as exc:
            emit_log(f"{cfg.label}上传自定义封面失败，回退自动截帧: {exc}")
            strategy = "auto_cut"

    # 2b) 自动截帧模式：选第一帧/裁剪区域已默认，直接点确认
    if strategy == "auto_cut":
        emit_log(f"{cfg.label}使用视频自动截取的封面")
        await page.wait_for_timeout(1500)

    # 3) 点「完成/确定」应用封面
    for sel in [s.strip() for s in cfg.cover_confirm_selector.split(",") if s.strip()]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.click(force=True)
                emit_log(f"{cfg.label}封面已应用")
                await page.wait_for_timeout(1500)
                return
        except Exception:
            continue
    emit_log(f"{cfg.label}封面确认按钮未找到（可能已自动应用），继续")


async def _set_originality(page, cfg: PlatformConfig) -> None:
    """选择创作声明（B站必选，默认"内容无需标注"，需改成目标声明项才能投稿）。

    B站「创作声明」是 bcc-select 下拉框，结构：
      .creation-statement-container
        .bcc-select > .bcc-select-input-wrap > .bcc-select-input-inner (触发器)
                     > .bcc-select-list-wrap (下拉列表，默认 display:none)
                        li.bcc-option / .auth-content > .option-text

    流程：1) 点开下拉 2) 点目标 option（含授权声明的 div.auth-content）。
    容错：失败不中断。
    """
    if not cfg.originality_selector:
        return
    emit_progress(platform=cfg.name, step="set_originality", status="running", pct=85,
                  message="选择创作声明")
    try:
        await page.evaluate(
            "() => document.querySelectorAll('.shepherd-element,.shepherd-modal-overlay-container').forEach(e=>e.remove())"
        )
    except Exception:
        pass

    # 找到创作声明下拉容器（多候选）
    container = None
    for sel in [s.strip() for s in cfg.originality_selector.split(",") if s.strip()]:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                container = loc
                break
        except Exception:
            continue
    if container is None:
        emit_log(f"{cfg.label}创作声明下拉未找到，跳过")
        return

    # 点开下拉（点 .bcc-select-input-wrap 或 input）
    try:
        trigger = container.locator(".bcc-select-input-wrap, .bcc-select-input-inner").first
        await trigger.click(force=True)
        await page.wait_for_timeout(800)
    except Exception as exc:
        emit_log(f"{cfg.label}创作声明下拉点开失败，尝试点容器: {exc}")
        try:
            await container.click(force=True)
            await page.wait_for_timeout(800)
        except Exception:
            emit_log(f"{cfg.label}创作声明下拉无法点开，跳过")
            return

    # 选目标创作声明（顶部主选项 li.bcc-option，如"内容无需标注"）。
    # 注意：底部「内容为自制」授权声明默认已选中（option-text-selected），不要去动它。
    target_texts = [t.strip() for t in (cfg.originality_target_text or "内容无需标注").split(",") if t.strip()]
    selected = False
    for txt in target_texts:
        try:
            # 只匹配顶部主选项 li.bcc-option（排除底部授权声明区 .auth-content）。
            # 用 .bcc-option > span 精确定位文案，避免误匹配授权声明。
            opt = container.locator(
                f'.bcc-select-list-wrap li.bcc-option:has(span:has-text("{txt}"))'
            ).first
            if not await opt.count():
                # 兜底：宽松匹配 li.bcc-option
                opt = container.locator(
                    f'.bcc-select-list-wrap li.bcc-option:has-text("{txt}")'
                ).first
            if await opt.count():
                # 检测该主选项是否已选中（class 含 selected）。已选则跳过。
                try:
                    cls = await opt.get_attribute("class") or ""
                    if "selected" in cls:
                        emit_log(f"{cfg.label}创作声明「{txt}」已选中，跳过")
                        selected = True
                        break
                except Exception:
                    pass
                await opt.click(force=True)
                emit_log(f"{cfg.label}已选择创作声明「{txt}」")
                selected = True
                await page.wait_for_timeout(800)
                break
        except Exception as exc:
            emit_log(f"{cfg.label}选择创作声明「{txt}」异常: {exc}")
            continue

    if not selected:
        emit_log(f"{cfg.label}创作声明目标项未找到（保持默认），继续")

    # 收起下拉（点别处或 Escape）
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


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
    proxy = await read_publish_proxy_config()
    if proxy:
        emit_log(f"{cfg.label}发布使用代理: {proxy['server']}")
    launch_kwargs = build_launch_kwargs(resolved, headless=publish_headless, proxy=proxy)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context(storage_state=account_file, permissions=["geolocation"])
            context = await set_init_script(context)
            page = await context.new_page()

            emit_progress(platform=cfg.name, step="upload_start", status="running", pct=20,
                          message=f"打开{cfg.label}上传页")
            # 健壮加载：优先 networkidle（等静态资源/JS chunk 加载完），失败回退 domcontentloaded。
            # 解决 B站等 SPA 页面 ChunkLoadError（JS chunk 没加载完就操作导致功能不可用）。
            goto_ok = False
            for wait_strategy in ("networkidle", "domcontentloaded"):
                try:
                    await page.goto(cfg.upload_url, wait_until=wait_strategy, timeout=60000)
                    goto_ok = True
                    break
                except Exception as exc:
                    emit_log(f"{cfg.label}上传页加载（{wait_strategy}）失败，重试: {exc}")
            if not goto_ok:
                raise RuntimeError(f"打开{cfg.label}上传页失败（多次重试均超时）")
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
                    # 先输入描述正文（若有）
                    desc = (item.description or "").strip()
                    if desc:
                        await page.keyboard.type(desc)
                        # 描述与首个话题间确保有空格分隔，否则 # 不被识别为话题
                        await page.keyboard.type(" ")
                    # 逐个输入话题：每个话题前空格 + 文本 + 后置空格，
                    # 这样平台（B站/小红书等 contenteditable）能识别 # 为话题触发符。
                    for tag in item.tags:
                        tag = (tag or "").strip().lstrip("#")
                        if not tag:
                            continue
                        await page.keyboard.type("#" + tag)
                        await page.keyboard.press("Space")
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

            # 设置封面（B站等必填项，缺封面「立即投稿」会 disabled）
            await _set_cover(page, cfg, item.cover_path)
            # 选择原创声明/类型（B站「原创」默认未选，投稿按钮 disabled 的常见原因）
            await _set_originality(page, cfg)

            # 点发布按钮（等待按钮可点击：转码完成前通常 disabled）
            emit_progress(platform=cfg.name, step="publishing", status="running", pct=90,
                          message=f"点击{cfg.publish_btn_text}按钮")
            published = False
            deadline = datetime.now().timestamp() + 180
            clicked_once = False
            # 发布按钮多策略定位：B站「立即投稿」是 <span class="submit-add">，不是 <button>，
            # get_by_role("button") 匹配不到，需多候选兜底。
            btn_text = cfg.publish_btn_text
            while datetime.now().timestamp() < deadline:
                try:
                    await page.evaluate(
                        "() => document.querySelectorAll('.shepherd-element, [class*=\"mention-wrapper\"]').forEach(e=>e.remove())"
                    )
                    # 优先：平台专用发布点击 JS（穿透 closed shadow DOM，如小红书 xhs-publish-btn）
                    if cfg.publish_click_js:
                        try:
                            res = await page.evaluate(cfg.publish_click_js)
                            if res is True:
                                # JS 内部已触发点击（_onPublish / dispatchEvent）
                                clicked_once = True
                            elif isinstance(res, dict) and "x" in res and "y" in res:
                                # JS 返回坐标（closed shadow DOM 无法内部点击），用 mouse 精确点击该坐标
                                try:
                                    await page.mouse.click(res["x"], res["y"])
                                    clicked_once = True
                                except Exception as exc2:
                                    if not clicked_once:
                                        emit_log(f"{btn_text}坐标点击失败: {exc2}")
                            elif res is False and not clicked_once:
                                emit_log(f"{btn_text}专用点击未触发（可能 submit-disabled/loading 或元素未就绪），等待中…")
                        except Exception as exc:
                            if not clicked_once:
                                emit_log(f"{btn_text}专用点击异常，回退常规定位: {exc}")
                            res = None
                        # 专用 JS 路径成功触发则跳过常规定位（避免重复点击点到歪处）
                        if clicked_once and cfg.publish_click_js:
                            await page.wait_for_timeout(3000)
                            cur_url = page.url or ""
                            # 仍走成功检测
                            if cfg.publish_success_fragment and cfg.publish_success_fragment in cur_url:
                                published = True
                                break
                            if cfg.publish_success_url_fragments:
                                hit = any(f.strip() and f.strip() in cur_url for f in cfg.publish_success_url_fragments.split(","))
                                if hit:
                                    published = True
                                    break
                            if cfg.publish_success_selector and await _any_visible(page, cfg.publish_success_selector):
                                published = True
                                break
                            if cfg.upload_url not in cur_url and "login" not in cur_url:
                                published = True
                                break
                            # 专用 JS 已触发但未跳转，继续循环等
                            continue
                    # 常规定位（标准 button / span / div 等）
                    btn = None
                    # 1) button role（标准按钮平台）
                    cand = page.get_by_role("button", name=btn_text, exact=False)
                    if await cand.count():
                        btn = cand.first
                    # 2) 含目标文案的可点元素（B站 span.submit-add 等）
                    if btn is None:
                        for sel in (
                            f'span.submit-add:has-text("{btn_text}")',
                            f'span:has-text("{btn_text}")',
                            f'div:has-text("{btn_text}"):not(:has(div)):not(:has(span))',
                            f'a:has-text("{btn_text}")',
                            f'button:has-text("{btn_text}")',
                            f'[class*="submit"]:has-text("{btn_text}")',
                            f'[class*="publish"]:has-text("{btn_text}")',
                        ):
                            try:
                                loc = page.locator(sel).last
                                if await loc.count():
                                    btn = loc
                                    break
                            except Exception:
                                continue
                    if btn is not None:
                        # 检测是否可点：多种平台异构表达
                        disabled = False
                        # a) 标准 button 的 disabled 属性
                        try:
                            disabled = await btn.is_disabled()
                        except Exception:
                            disabled = False
                        # b) 自身/父级 class 含 disabled（B站 span 靠 class）
                        if not disabled:
                            try:
                                cls = await btn.get_attribute("class") or ""
                                if "disabled" in cls or "is-disabled" in cls:
                                    disabled = True
                            except Exception:
                                pass
                        # c) 属性形式（小红书 xhs-publish-btn：submit-disabled / submit-loading）
                        if not disabled:
                            try:
                                sd = (await btn.get_attribute("submit-disabled") or "").lower()
                                sl = (await btn.get_attribute("submit-loading") or "").lower()
                                if sd == "true" or sl == "true":
                                    disabled = True
                            except Exception:
                                pass
                        if not disabled:
                            await btn.click(force=True)
                            clicked_once = True
                        elif not clicked_once:
                            emit_log(f"{btn_text}暂不可点（可能转码/封面/声明未完成），等待中…")
                    elif not clicked_once:
                        emit_log(f"未找到「{btn_text}」按钮，重试中…")
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
