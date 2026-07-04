"""各平台的配置注册表（URL、登录检测、上传选择器等）。

新增平台只需在此添加一条 PlatformConfig，并在 platform_impls 注册实现。
所有平台共享通用发布流程（generic.py），仅差异点通过 PlatformConfig 表达。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Awaitable


@dataclass
class PlatformConfig:
    """单个平台的发布配置。"""
    name: str                          # 平台标识（与 types.PLATFORM_META key 一致）
    label: str                         # 中文名
    creator_home: str                  # 创作者中心首页（登录页）
    upload_url: str                    # 视频上传页 URL
    # 登录态判定：登录成功后 URL 会包含此片段（如 creator-micro、publish/success）
    logged_in_url_fragment: str
    # 登录页上"扫码登录"按钮文案（用于检测登录 UI 是否还在）
    login_btn_text: str = "扫码登录"
    # 上传页文件 input 选择器（用于 set_input_files）
    upload_input_selector: str = "input[type='file']"
    # 标题输入框选择器
    title_selector: str = ""
    # 描述/正文输入框选择器（contenteditable div）
    desc_selector: str = ""
    # 发布按钮文案
    publish_btn_text: str = "发布"
    # 发布成功后 URL 包含的片段
    publish_success_fragment: str = ""
    # 风控等级（前端展示用）
    risk: str = "normal"
    # 是否已联调验证（False = 代码就绪但未经真机测试，UI 标"测试版"）
    verified: bool = False
    # 备注（特殊注意事项）
    note: str = ""


# ── 各平台配置 ──────────────────────────────────────────────────────────────
PLATFORM_CONFIGS: dict[str, PlatformConfig] = {
    "douyin": PlatformConfig(
        name="douyin",
        label="抖音",
        creator_home="https://creator.douyin.com/",
        upload_url="https://creator.douyin.com/creator-micro/content/upload",
        logged_in_url_fragment="creator.douyin.com/creator-micro",
        login_btn_text="扫码登录",
        upload_input_selector="div[class^='container'] input",
        title_selector='input[placeholder*="填写作品标题"]',
        desc_selector='div.zone-container[contenteditable="true"]',
        publish_btn_text="发布",
        publish_success_fragment="creator-micro/content/manage",
        risk="normal",
        verified=True,  # 已联调
        note="",
    ),
    "xhs": PlatformConfig(
        name="xhs",
        label="小红书",
        creator_home="https://creator.xiaohongshu.com/",
        upload_url="https://creator.xiaohongshu.com/publish/publish",
        logged_in_url_fragment="creator.xiaohongshu.com",
        login_btn_text="扫码登录",
        upload_input_selector="input[type='file']",
        title_selector='input[placeholder*="标题"]',
        desc_selector='div#post-textarea, div[contenteditable="true"]',
        publish_btn_text="发布",
        publish_success_fragment="publish/success",
        risk="strict",  # 风控最严
        verified=False,
        note="小红书风控严格，建议小批量、低频率发布，优先用本地 Chrome",
    ),
    "wxchannels": PlatformConfig(
        name="wxchannels",
        label="视频号",
        creator_home="https://channels.weixin.qq.com/",
        upload_url="https://channels.weixin.qq.com/platform/post/create",
        logged_in_url_fragment="channels.weixin.qq.com/platform",
        login_btn_text="扫码登录",
        upload_input_selector="input[type='file']",
        title_selector='input[placeholder*="标题"]',
        desc_selector='div[contenteditable="true"], textarea',
        publish_btn_text="发表",
        publish_success_fragment="platform/post/list",
        risk="normal",
        verified=False,
        note="视频号需微信扫码，登录态与微信绑定",
    ),
    "bilibili": PlatformConfig(
        name="bilibili",
        label="哔哩哔哩",
        creator_home="https://member.bilibili.com/platform/home",
        upload_url="https://member.bilibili.com/platform/upload/video/frame",
        logged_in_url_fragment="member.bilibili.com",
        login_btn_text="扫码登录",
        upload_input_selector="input[type='file']",
        title_selector='input[placeholder*="标题"]',
        desc_selector='div[contenteditable="true"], textarea',
        publish_btn_text="立即投稿",
        publish_success_fragment="upload/submitted",
        risk="low",
        verified=False,
        note="B站后续可叠加官方 API（更稳定）",
    ),
    "kuaishou": PlatformConfig(
        name="kuaishou",
        label="快手",
        creator_home="https://cp.kuaishou.com/article/publish/video",
        upload_url="https://cp.kuaishou.com/article/publish/video",
        logged_in_url_fragment="cp.kuaishou.com",
        login_btn_text="扫码登录",
        upload_input_selector="input[type='file']",
        title_selector='input[placeholder*="标题"]',
        desc_selector='div[contenteditable="true"], textarea',
        publish_btn_text="发布",
        publish_success_fragment="publish/success",
        risk="normal",
        verified=False,
        note="",
    ),
}


def get_config(platform: str) -> PlatformConfig | None:
    return PLATFORM_CONFIGS.get(platform)


def implemented_platforms() -> list[str]:
    """所有已配置（可发布）的平台。"""
    return list(PLATFORM_CONFIGS.keys())
