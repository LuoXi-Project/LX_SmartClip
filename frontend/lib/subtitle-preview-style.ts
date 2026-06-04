import type { CSSProperties } from 'react'
import type { SubtitleStyle } from '@/lib/subtitle-types'

/** 画布视频预览区字幕叠加样式（与 SubtitlePanel 预览语义一致） */
export function subtitleOverlayStyle(style: SubtitleStyle, scale = 0.38): CSSProperties {
  const xPct = typeof style.pos_x_pct === 'number' ? style.pos_x_pct : 50
  const yPct = typeof style.pos_y_pct === 'number' ? style.pos_y_pct : 90
  const outline = style.outline_width ?? 2
  const shadow = style.shadow ?? 1
  const fs = Math.max(11, Math.round((style.font_size || 56) * scale))

  const shadows: string[] = []
  if (outline > 0) {
    const o = Math.max(1, Math.round(outline * scale * 2))
    for (let dx = -o; dx <= o; dx++) {
      for (let dy = -o; dy <= o; dy++) {
        if (dx === 0 && dy === 0) continue
        shadows.push(`${dx}px ${dy}px 0 ${style.outline_color || '#000'}`)
      }
    }
  }
  if (shadow > 0) {
    shadows.push(`0 ${shadow}px ${shadow * 2}px rgba(0,0,0,0.85)`)
  }

  const base: CSSProperties = {
    position: 'absolute',
    left: `${xPct}%`,
    top: `${yPct}%`,
    transform: 'translate(-50%, -50%)',
    maxWidth: '92%',
    textAlign: 'center',
    fontSize: fs,
    lineHeight: 1.35,
    color: style.font_color || '#fff',
    fontWeight: style.bold ? 700 : 400,
    fontStyle: style.italic ? 'italic' : 'normal',
    fontFamily: style.font_name || 'Arial, sans-serif',
    textShadow: shadows.length ? shadows.join(', ') : undefined,
    pointerEvents: 'none',
    zIndex: 10,
  }

  if (style.background) {
    const op = (style.background_opacity ?? 55) / 100
    base.backgroundColor = `rgba(0,0,0,${op * 0.85})`
    base.padding = `${Math.max(2, (style.background_pad_y ?? 3) * scale)}px ${Math.max(
      4,
      (style.background_pad_x ?? 6) * scale
    )}px`
    base.borderRadius = 4
  }

  return base
}
