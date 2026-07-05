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
    # 封面处理策略：
    #   ""               = 不处理（平台不强制封面，或由其他逻辑处理）
    #   "auto_cut"       = 点击「添加封面/选择封面」后应用视频自动截取的第一帧（B站等）
    #   "upload_cover"   = 用 item.cover_path 上传自定义封面（无 cover_path 时回退 auto_cut）
    # 封面是 B站等平台投稿的必填项，缺封面「立即投稿」会一直 disabled
    cover_strategy: str = ""
    # 封面入口选择器（逗号分隔多候选，如「添加封面」「选择封面」按钮）
    cover_entry_selector: str = ""
    # 封面确认选择器（逗号分隔，选完帧/上传后点「完成/确定」应用封面）
    cover_confirm_selector: str = ""
    # 创作声明处理：B站「创作声明」是必选下拉框（bcc-select），默认"内容无需标注"，
    # 需改成目标声明（如"内容为自制：未经作者允许，禁止转载"）才能投稿。
    # originality_selector = 创作声明下拉容器的选择器（多候选逗号分隔）
    # originality_target_text = 要选的目标声明文案（逗号分隔多候选，命中第一个即选）
    # 留空=不处理。
    originality_selector: str = ""
    originality_target_text: str = "内容为自制"
    # 平台专用的发布点击 JS（穿透 closed shadow DOM 等）。
    # 小红书 <xhs-publish-btn> 是 closed shadow DOM，常规点击只命中外壳不触发内部发布。
    # 此 JS 在 page.evaluate 执行，返回 true 表示已触发点击。
    # 留空=走常规 DOM 点击逻辑。
    publish_click_js: str = ""
    # 发布后二级确认弹窗：部分平台（视频号）点「发表」后会弹原创声明/确认对话框，
    # 需再点「直接发表」等按钮才真正发布。留空=无二级确认。
    confirm_dialog_selector: str = ""   # 确认弹窗容器选择器（出现即说明需要二次确认）
    confirm_btn_selector: str = ""      # 确认弹窗里要点的目标按钮选择器（多候选逗号分隔）
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
        # 小红书发布按钮 <xhs-publish-btn> 是 closed shadow DOM，常规 querySelector 穿不透。
        # 注意：has-text 是 Playwright 选择器，浏览器 querySelector 不支持，不能用。
        # closed shadow DOM 的 el.shadowRoot 返回 null，所以无法从外部定位内部按钮。
        # 可靠策略：1) 调组件实例方法 _onPublish/handlePublish 2) 外壳 dispatchEvent click。
        # 此 JS 在 page.evaluate 执行，返回 true=已触发，false=未触发（disabled 或没找到）。
        publish_click_js="""() => {
  const el = document.querySelector('xhs-publish-btn');
  if (!el) return false;
  if (el.getAttribute('submit-disabled') === 'true') return false;
  if (el.getAttribute('submit-loading') === 'true') return false;
  // 策略1：调组件实例的发布方法
  if (typeof el._onPublish === 'function') { try { el._onPublish(); return true; } catch(e){} }
  if (typeof el.handlePublish === 'function') { try { el.handlePublish(); return true; } catch(e){} }
  // 策略2：派发 click 事件到外壳（部分版本监听宿主 click）
  try { el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); } catch(e){}
  // 策略3：坐标点击外壳右半部分（XHS 内部布局：暂存在左、发布在右）
  // 返回坐标供 Playwright 用 page.mouse.click 精确点击（evaluate 内无法直接点击）
  const r = el.getBoundingClientRect();
  return {x: Math.round(r.left + r.width * 0.75), y: Math.round(r.top + r.height / 2)};
}""",
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
        # 视频号描述区是 div.input-editor[contenteditable]（contenteditable 无显式值）
        desc_selector='div.input-editor[contenteditable], div[contenteditable], textarea',
        publish_btn_text="发表",
        publish_success_fragment="platform/post/list",
        # 发布后二级确认弹窗：原创声明对话框，需点「直接发表」才真正发布
        # DOM: .weui-desktop-dialog 内 .weui-desktop-btn_default:has-text("直接发表")
        confirm_dialog_selector='.weui-desktop-dialog',
        confirm_btn_selector=(
            '.weui-desktop-dialog button.weui-desktop-btn_default:has-text("直接发表"),'
            '.weui-desktop-dialog button:has-text("直接发表"),'
            '.original-interceptor-footer .cancel-btn button'
        ),
        risk="normal",
        verified=False,
        note="视频号需微信扫码；点「发表」后会弹原创声明对话框，需再点「直接发表」",
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
        # 封面（必填）：auto_cut=点击「添加封面」后应用视频自动截帧；有 cover_path 则上传自定义封面
        cover_strategy="upload_cover",
        cover_entry_selector=(
            '.video-cover-list .video-cover-upload-btn,'
            '.video-cover-list .upload-trigger,'
            'button:has-text("添加封面"),'
            'button:has-text("选择封面"),'
            '.video-cover:has-text("添加封面")'
        ),
        cover_confirm_selector=(
            '.cover-cropper-wrap button:has-text("完成"),'
            '.cover-upload-wrap button:has-text("完成"),'
            'button:has-text("截取封面"),'
            '.van-modal button:has-text("完成"),'
            'button.btn:has-text("完成")'
        ),
        # 创作声明（B站必选下拉框）：点开 .bcc-select 下拉，选「内容为自制」授权声明
        originality_selector=(
            '.creation-statement-container,'
            '.form-item:has(.creation-statement-container),'
            '.bcc-select:has(input.bcc-select-input-inner[placeholder*="创作声明"])'
        ),
        originality_target_text="内容无需标注",
        risk="low",
        verified=False,
        note="B站上传/转码较慢，已加完成检测；封面+原创声明为必填项；后续可叠加官方 API（更稳定）",
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
