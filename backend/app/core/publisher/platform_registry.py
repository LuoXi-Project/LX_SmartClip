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
    # 视频上传/转码完成的检测选择器（逗号分隔多候选）。
    # 任一可见即认为上传完成（如「重新上传」按钮、上传完成提示文本）。
    # 留空则退化成「固定等待」粗等策略。
    upload_done_selector: str = ""
    # 上传/转码失败的检测选择器（逗号分隔多候选，含「上传失败」「转码失败」等文案）
    upload_fail_selector: str = ""
    # 发布成功的 URL 片段候选（逗号分隔），任一命中即成功。比 publish_success_fragment 更宽松
    publish_success_url_fragments: str = ""
    # 发布成功的页面元素选择器（逗号分隔，如「发布成功」弹窗/Toast），任一可见即成功
    publish_success_selector: str = ""
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
        publish_success_fragment="upload/report",
        # B站上传/转码完成检测：视频卡片出现「重新上传」按钮，或上传区出现完成提示
        # 每个候选都是独立合法的 Playwright 选择器（逗号分隔，程序里逐个尝试）
        # 用 :has-text() 而非 text= 以兼容更多匹配场景（包含子元素）
        upload_done_selector=(
            'button:has-text("重新上传"),'
            '.video-upload-item:has-text("重新上传"),'
            'a:has-text("重新上传"),'
            ':has-text("上传完成"),'
            ':has-text("点击添加封面")'
        ),
        upload_fail_selector=(
            ':has-text("上传失败"),'
            ':has-text("转码失败")'
        ),
        # 投稿成功跳转候选：投稿管理页 / 提交成功页
        publish_success_url_fragments="upload/report,upload/submitted",
        # B站投稿成功后可能出现「稿件投递成功」Toast
        publish_success_selector=':has-text("稿件投递成功"),:has-text("投稿成功")',
        risk="low",
        verified=False,
        note="B站上传/转码较慢，已加完成检测；后续可叠加官方 API（更稳定）",
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
