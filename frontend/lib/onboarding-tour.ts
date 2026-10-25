/**
 * 新手指引锚点契约：用稳定的 data-tour 标识绑定 UI，而非写死坐标。
 * 导航/页面改版时只要锚点随元素迁移，聚光灯会自动跟到正确位置。
 */

export const TOUR_ANCHORS = {
  navSettings: 'nav-settings',
  navLibrary: 'nav-library',
  navProcess: 'nav-process',
  navStudio: 'nav-studio',
  pageSettingsLlm: 'page-settings-llm',
  pageLibraryUpload: 'page-library-upload',
  pageProcessStart: 'page-process-start',
  pageStudioInput: 'page-studio-input',
} as const

export type TourAnchorId = (typeof TOUR_ANCHORS)[keyof typeof TOUR_ANCHORS]

export type TourPlacement = 'auto' | 'top' | 'bottom' | 'left' | 'right'

export interface OnboardingTourStep {
  id: string
  /** 无锚点时为居中欢迎/完成页 */
  anchor?: TourAnchorId
  title: string
  description: string
  bullets?: string[]
  /** 进入本步前跳转（页面内锚点步骤） */
  href?: string
  routePrefix?: string
  placement?: TourPlacement
  /** 页面内滚动定位（设置页分区 id） */
  scrollToId?: string
  /** 本步显示前准备：移动端展开导航等 */
  prepare?: 'mobile-nav'
}

export const ONBOARDING_TOUR_STEPS: OnboardingTourStep[] = [
  {
    id: 'welcome',
    title: '欢迎使用洛曦智剪',
    description: '接下来会用高亮框标出你要点击或关注的区域。指引状态保存在本机数据库，与访问端口无关。',
    bullets: [
      '推荐直接到「智剪工作台」用一句话开始；缺少配置或素材时，再按指引逐步补齐。',
      '可随时点顶部「指引」重新查看。',
    ],
  },
  {
    id: 'nav-studio',
    anchor: TOUR_ANCHORS.navStudio,
    title: '第一步：智剪工作台',
    description: '主路径就是对话：描述你要的成片，Agent 会规划并执行。暂时没有本地素材也不妨先试试。',
    bullets: ['没有素材时可让 AI 走「文案素材成片」从在线素材库出片。'],
    prepare: 'mobile-nav',
    placement: 'bottom',
  },
  {
    id: 'page-studio-input',
    anchor: TOUR_ANCHORS.pageStudioInput,
    title: '输入剪辑指令',
    description: '例如：「用最新素材做 60 秒电商口播并导出成片」。右侧可检视方案与导出结果。',
    href: '/studio',
    routePrefix: '/studio',
    placement: 'auto',
  },
  {
    id: 'nav-settings',
    anchor: TOUR_ANCHORS.navSettings,
    title: '第二步：按需补配置',
    description: '对话成片至少需要 LLM；设置页顶部的「配置就绪状态」会标出还缺什么，其余模型可后续按需补齐。',
    bullets: ['桌面端点顶部「设置」；手机端先展开右上角菜单。'],
    prepare: 'mobile-nav',
    placement: 'bottom',
  },
  {
    id: 'page-settings-llm',
    anchor: TOUR_ANCHORS.pageSettingsLlm,
    title: '填写 LLM（其余按需）',
    description: '先填 LLM 的 API 地址与密钥即可开始对话；「配置就绪状态」卡里琥珀色的项就是待补项，点击直达。',
    href: '/settings',
    routePrefix: '/settings',
    scrollToId: 'llm',
    placement: 'auto',
  },
  {
    id: 'nav-library',
    anchor: TOUR_ANCHORS.navLibrary,
    title: '第三步：想用自己的素材',
    description: '想让 AI 剪你自己的视频时，先在这里把素材导入本地库。',
    prepare: 'mobile-nav',
    placement: 'bottom',
  },
  {
    id: 'page-library-upload',
    anchor: TOUR_ANCHORS.pageLibraryUpload,
    title: '上传或导入视频',
    description: '拖拽文件到虚线框，或粘贴链接导入；建议先上传 1～2 条试跑素材。',
    href: '/library',
    routePrefix: '/library',
    placement: 'bottom',
  },
  {
    id: 'nav-process',
    anchor: TOUR_ANCHORS.navProcess,
    title: '第四步：素材处理',
    description: '对已上传视频跑切分、ASR、VLM、向量化流水线，生成可检索片段。',
    prepare: 'mobile-nav',
    placement: 'bottom',
  },
  {
    id: 'page-process-start',
    anchor: TOUR_ANCHORS.pageProcessStart,
    title: '选择视频并开始处理',
    description: '左侧选中视频后，点击「开始处理（全流程）」；口播场景可用「口播快轨」仅跑 ASR。',
    href: '/process',
    routePrefix: '/process',
    placement: 'auto',
  },
  {
    id: 'complete',
    title: '可以开始创作了',
    description: '日常创作推荐从「智剪工作台」开始；需要逐段精修时用顶部「剪辑」菜单里的经典模式。',
  },
]

export function tourAnchorProps(anchor: TourAnchorId): { 'data-tour': TourAnchorId } {
  return { 'data-tour': anchor }
}

export function isElementTourVisible(el: HTMLElement): boolean {
  const rect = el.getBoundingClientRect()
  if (rect.width < 2 || rect.height < 2) return false
  const style = window.getComputedStyle(el)
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false
  return true
}

/** 解析锚点：优先当前可见的元素（兼容桌面/移动双份 DOM） */
export function resolveTourTarget(anchor: string): HTMLElement | null {
  const nodes = document.querySelectorAll<HTMLElement>(`[data-tour="${anchor}"]`)
  for (const el of nodes) {
    if (isElementTourVisible(el)) return el
  }
  return nodes.length ? nodes[0] : null
}

export function waitForTourTarget(
  anchor: string,
  options?: { timeoutMs?: number; intervalMs?: number },
): Promise<HTMLElement | null> {
  const timeoutMs = options?.timeoutMs ?? 5000
  const intervalMs = options?.intervalMs ?? 80
  const start = Date.now()
  return new Promise((resolve) => {
    const tick = () => {
      const el = resolveTourTarget(anchor)
      if (el) {
        resolve(el)
        return
      }
      if (Date.now() - start >= timeoutMs) {
        resolve(null)
        return
      }
      window.setTimeout(tick, intervalMs)
    }
    tick()
  })
}

export const ONBOARDING_PREPARE_EVENT = 'lx-smartclip-onboarding-prepare'

export function dispatchOnboardingPrepare(detail: {
  anchor?: string
  scrollToId?: string
  openMobileNav?: boolean
}) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(ONBOARDING_PREPARE_EVENT, { detail }))
}
