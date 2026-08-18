/* ============================================================
   太阳系 · 画质分级与性能检测
   三档画质：
     high   全特效（抗锯齿 + 高分辨率渲染 + 完整小行星带）
     low    保留自转动画，但降低渲染规格（无 AA、1x 像素比、精简带）
     static 完全不自转：贴图就绪后仅渲染一帧静态画面（低配机）
   定级手段（启发式，见 detectQualityTier）：
     - prefers-reduced-motion / 软件渲染（SwiftShader 等）→ 直接 static
     - CPU 逻辑核数、deviceMemory、移动设备 → 打分定级
   兜底：运行期帧率守护（见 createSolarSystem.ts）持续低于阈值自动降档。
   手动覆盖（可选，优先级最高）：
     localStorage.setItem('smartclip.homeSceneQuality', 'high' | 'low' | 'static')
   ============================================================ */

export type QualityTier = 'high' | 'low' | 'static'

export interface QualityPreset {
  tier: QualityTier
  /** WebGL 上下文是否开启抗锯齿（创建后不可更改） */
  antialias: boolean
  /** renderer.setPixelRatio 的上限 */
  pixelRatioCap: number
  /** 小行星带实例数 */
  beltCount: number
  /** 星球球体经/纬分段数 */
  sphereSegments: number
  /** 是否驱动动画循环（static 只渲染一帧） */
  animate: boolean
}

export const QUALITY_PRESETS: Record<QualityTier, QualityPreset> = {
  high: {
    tier: 'high', antialias: true, pixelRatioCap: 1.75,
    beltCount: 2200, sphereSegments: 128, animate: true,
  },
  low: {
    tier: 'low', antialias: false, pixelRatioCap: 1,
    beltCount: 700, sphereSegments: 48, animate: true,
  },
  static: {
    // 静态帧只渲一次，抗锯齿与清晰度可以给足（单帧成本可接受）
    tier: 'static', antialias: true, pixelRatioCap: 1.5,
    beltCount: 500, sphereSegments: 48, animate: false,
  },
}

/** 手动覆盖用 localStorage 键 */
export const QUALITY_STORAGE_KEY = 'smartclip.homeSceneQuality'

interface NavigatorWithDeviceMemory extends Navigator {
  /** Chrome 系暴露的近似内存（GB）；Safari/Firefox 无此字段 */
  deviceMemory?: number
}

/** 读取 GPU 渲染器名称；失败返回空串（临时上下文随即销毁） */
function readGpuRenderer(): string {
  try {
    const canvas = document.createElement('canvas')
    const gl = (canvas.getContext('webgl2') ?? canvas.getContext('webgl')) as
      | WebGLRenderingContext
      | null
    if (!gl) return ''
    const dbg = gl.getExtension('WEBGL_debug_renderer_info')
    const name = dbg
      ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) ?? '')
      : String(gl.getParameter(gl.RENDERER) ?? '')
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return name
  } catch {
    return ''
  }
}

/** 软件渲染 / 虚拟机显卡特征——跑动画必卡，直接静态 */
const SOFTWARE_GPU_RE =
  /swiftshader|software|llvmpipe|basic render|offscreen|virtualbox|vmware|gdi\+?/i
const MOBILE_UA_RE = /android|iphone|ipad|ipod|mobile/i

export function detectQualityTier(): QualityTier {
  if (typeof window === 'undefined') return 'static'
  // 用户系统层面要求减少动态效果 → 静态
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return 'static'

  const gpu = readGpuRenderer()
  if (!gpu) return 'static' // 连 WebGL 信息都拿不到，按最保守处理
  if (SOFTWARE_GPU_RE.test(gpu)) return 'static'

  // 移动设备（含 iPad 桌面模式伪装）——GPU/散热撑不住 + 耗电，直接静态
  const isMobile =
    MOBILE_UA_RE.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 1 && /macintosh/i.test(navigator.userAgent))
  if (isMobile) return 'static'

  const cores = navigator.hardwareConcurrency ?? 4
  const mem = (navigator as NavigatorWithDeviceMemory).deviceMemory ?? 0 // 0 = 未知

  if (cores <= 2) return 'static'
  if (mem > 0 && mem <= 2) return 'static'

  let score = 0
  score += cores >= 8 ? 2 : cores >= 4 ? 1 : -1
  score += mem >= 8 ? 2 : mem >= 4 ? 1 : mem > 0 ? -1 : 0
  // 高分屏（dpr 很大）像素压力大，略减分
  if (window.devicePixelRatio > 2.5) score -= 1

  return score >= 3 ? 'high' : score >= 1 ? 'low' : 'static'
}

/** 读取手动覆盖档位；非法值一律忽略 */
export function loadStoredQualityTier(): QualityTier | null {
  try {
    const v = window.localStorage.getItem(QUALITY_STORAGE_KEY)
    return v === 'high' || v === 'low' || v === 'static' ? v : null
  } catch {
    return null
  }
}

export function saveStoredQualityTier(tier: QualityTier): void {
  try {
    window.localStorage.setItem(QUALITY_STORAGE_KEY, tier)
  } catch {
    // 隐私模式等场景写入失败可忽略
  }
}

/** 手动覆盖优先，其次自动检测 */
export function resolveQualityTier(): QualityTier {
  return loadStoredQualityTier() ?? detectQualityTier()
}
