import type { CSSProperties } from 'react'
import type { SegmentVisualEffectApi } from '@/lib/api'

/** 与后端 FFmpeg / 剪映 ClipSettings 顺序对齐的 CSS 预览（近似） */
export function visualEffectToPreviewStyle(
  effect: SegmentVisualEffectApi | null | undefined,
): CSSProperties {
  if (!effect) return {}

  const transforms: string[] = []
  const filters: string[] = []

  const z = effect.zoom
  if (z != null && z > 1.001) {
    transforms.push(`scale(${z})`)
  }
  if (effect.mirror) {
    transforms.push('scaleX(-1)')
  }
  const rot = effect.rotation_deg
  if (rot != null && Math.abs(rot) > 0.001) {
    transforms.push(`rotate(${rot}deg)`)
  }

  const ci = effect.color_intensity
  if (ci != null && Math.abs(ci) > 0.0001) {
    filters.push(`saturate(${1 + ci})`)
    filters.push(`contrast(${1 + ci * 0.35})`)
    filters.push(`hue-rotate(${ci * 18}deg)`)
  }

  const style: CSSProperties = {}
  if (transforms.length) style.transform = transforms.join(' ')
  if (filters.length) style.filter = filters.join(' ')
  return style
}

export function hasVisualEffectPreview(effect: SegmentVisualEffectApi | null | undefined): boolean {
  if (!effect) return false
  if (effect.mirror) return true
  if (effect.zoom != null && effect.zoom > 1.001) return true
  if (effect.rotation_deg != null && Math.abs(effect.rotation_deg) > 0.001) return true
  if (effect.color_intensity != null && Math.abs(effect.color_intensity) > 0.0001) return true
  return false
}
