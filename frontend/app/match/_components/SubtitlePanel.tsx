'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Subtitles, Eye } from 'lucide-react'
import type { SubtitleStyle, SRTEntry } from './types'
import { DEFAULT_SUBTITLE_STYLE } from './types'

interface Props {
  style: SubtitleStyle
  onChange: (s: SubtitleStyle) => void
  entries?: SRTEntry[]
  enabled: boolean
  onToggle: (v: boolean) => void
  strictUseClientSrt?: boolean
  onStrictUseClientSrtChange?: (v: boolean) => void
  timingSource?: string
  previewVideoSize?: { width: number; height: number } | null
  previewFrameUrl?: string | null
}

export function SubtitlePanel({
  style,
  onChange,
  entries,
  enabled,
  onToggle,
  strictUseClientSrt,
  onStrictUseClientSrtChange,
  timingSource,
  previewVideoSize,
  previewFrameUrl,
}: Props) {
  const [open, setOpen] = useState(false)
  const [previewImageError, setPreviewImageError] = useState(false)

  function patch(k: keyof SubtitleStyle, v: SubtitleStyle[typeof k]) {
    onChange({ ...style, [k]: v })
  }

  function applyPresetPosition(pos: 'bottom' | 'center' | 'top') {
    if (pos === 'bottom') onChange({ ...style, position: pos, pos_x_pct: 50, pos_y_pct: 90 })
    else if (pos === 'center') onChange({ ...style, position: pos, pos_x_pct: 50, pos_y_pct: 50 })
    else onChange({ ...style, position: pos, pos_x_pct: 50, pos_y_pct: 10 })
  }

  const sourceW = previewVideoSize?.width && previewVideoSize.width > 0 ? previewVideoSize.width : 1920
  const sourceH = previewVideoSize?.height && previewVideoSize.height > 0 ? previewVideoSize.height : 1080
  const scale = Math.min(420 / sourceW, 220 / sourceH, 1)
  const previewW = Math.round(sourceW * scale)
  const previewH = Math.round(sourceH * scale)
  const xPct = typeof style.pos_x_pct === 'number' ? style.pos_x_pct : 50
  const yPct = typeof style.pos_y_pct === 'number' ? style.pos_y_pct : 90
  const bgPadX = typeof style.background_pad_x === 'number' ? style.background_pad_x : 6
  const bgPadY = typeof style.background_pad_y === 'number' ? style.background_pad_y : 3
  const bgOpacity = typeof style.background_opacity === 'number' ? style.background_opacity : 55
  const showPreviewImage = Boolean(previewFrameUrl) && !previewImageError

  useEffect(() => {
    setPreviewImageError(false)
  }, [previewFrameUrl])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
      {/* header toggle */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen(o => !o)
          }
        }}
        className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-800/40 transition-colors"
      >
        <Subtitles className="w-4 h-4 text-cyan-400 shrink-0" />
        <span className="text-sm font-medium text-slate-200">字幕设置</span>
        {timingSource && (
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ml-1 ${
            timingSource === 'tts'
              ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-400'
              : timingSource === 'mixed'
              ? 'border-amber-500/30 bg-amber-500/10 text-amber-400'
              : 'border-slate-600 bg-slate-800 text-slate-500'
          }`}>
            {timingSource === 'tts' ? '⏱ TTS时长' : timingSource === 'mixed' ? '⏱ 混合时长' : '⏱ 视频时长'}
          </span>
        )}
        {typeof strictUseClientSrt === 'boolean' && onStrictUseClientSrtChange && (
          <button
            onClick={(e) => { e.stopPropagation(); onStrictUseClientSrtChange(!strictUseClientSrt) }}
            className="ml-1 flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 hover:bg-slate-800/60 transition-colors"
            title="开启后：导出成片时严格使用当前 SRT，不再自动按 TTS 时长兜底重排"
          >
            <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center text-[9px] transition-colors ${
              strictUseClientSrt ? 'bg-cyan-600 border-cyan-600 text-white' : 'border-slate-600 text-transparent'
            }`}>✓</span>
            <span className="text-[10px] text-slate-400">严格SRT</span>
          </button>
        )}
        <div className="flex-1" />
        {/* enable toggle */}
        <span className="text-xs text-slate-500 mr-2">添加字幕</span>
        <button
          onClick={e => { e.stopPropagation(); onToggle(!enabled) }}
          className={`relative w-10 h-5 rounded-full transition-colors ${
            enabled ? 'bg-cyan-600' : 'bg-slate-700'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            enabled ? 'translate-x-5' : 'translate-x-0'
          }`} />
        </button>
        {open ? <ChevronUp className="w-4 h-4 text-slate-500 ml-2" /> : <ChevronDown className="w-4 h-4 text-slate-500 ml-2" />}
      </div>

      {open && (
        <div className="px-5 pb-5 space-y-5 border-t border-slate-800">

          {/* preview strip */}
          {entries && entries.length > 0 && (
            <div className="mt-4 rounded-xl bg-slate-950 border border-slate-800 overflow-hidden">
              <div className="px-3 py-2 border-b border-slate-800 flex items-center gap-2">
                <Eye className="w-3 h-3 text-slate-500" />
                <span className="text-[10px] text-slate-500 uppercase tracking-widest">时间轴预览</span>
                <span className="ml-auto text-[10px] text-slate-600">{entries.length} 条</span>
              </div>
              <div className="max-h-36 overflow-y-auto">
                {entries.slice(0, 20).map(e => (
                  <div key={e.index} className="flex items-baseline gap-3 px-3 py-1.5 border-b border-slate-900 hover:bg-slate-900/60">
                    <span className="text-[10px] text-slate-600 tabular-nums w-4 shrink-0">{e.index}</span>
                    <span className="text-[10px] text-cyan-600 tabular-nums shrink-0">
                      {_fmt(e.start)} → {_fmt(e.end)}
                    </span>
                    <span className="text-xs text-slate-300 truncate">{e.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* style controls */}
          <div className="mt-4 grid grid-cols-2 gap-3">
            {/* font */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">字体</label>
              <select
                value={style.font_name}
                onChange={e => patch('font_name', e.target.value)}
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-xs text-slate-200"
              >
                {['Arial','Microsoft YaHei','PingFang SC','Noto Sans SC','SimHei','SimSun','STHeiti','Impact'].map(f => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </div>

            {/* size */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">字号 {style.font_size}px</label>
              <input
                type="range" min={1} max={200} value={style.font_size}
                onChange={e => patch('font_size', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            {/* position */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">位置</label>
              <div className="flex gap-1">
                {(['bottom','center','top'] as const).map(pos => (
                  <button
                    key={pos}
                    onClick={() => applyPresetPosition(pos)}
                    className={`flex-1 py-1 rounded-lg text-xs transition-colors ${
                      style.position === pos
                        ? 'bg-cyan-600 text-white'
                        : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                    }`}
                  >
                    {pos === 'bottom' ? '下' : pos === 'center' ? '中' : '上'}
                  </button>
                ))}
              </div>
            </div>

            {/* margin */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">边距 {style.margin_v}px</label>
              <input
                type="range" min={0} max={80} value={style.margin_v}
                onChange={e => patch('margin_v', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">横向坐标 {Math.round(xPct)}%</label>
              <input
                type="range" min={0} max={100} value={xPct}
                onChange={e => patch('pos_x_pct', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">纵向坐标 {Math.round(yPct)}%</label>
              <input
                type="range" min={0} max={100} value={yPct}
                onChange={e => patch('pos_y_pct', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            {/* font color */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">字体颜色</label>
              <div className="flex items-center gap-2">
                <input
                  type="color" value={style.font_color}
                  onChange={e => patch('font_color', e.target.value)}
                  className="w-8 h-8 rounded cursor-pointer bg-transparent border-0"
                />
                <span className="text-xs text-slate-400 font-mono">{style.font_color}</span>
              </div>
            </div>

            {/* outline color */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">描边颜色</label>
              <div className="flex items-center gap-2">
                <input
                  type="color" value={style.outline_color}
                  onChange={e => patch('outline_color', e.target.value)}
                  className="w-8 h-8 rounded cursor-pointer bg-transparent border-0"
                />
                <span className="text-xs text-slate-400 font-mono">{style.outline_color}</span>
              </div>
            </div>

            {/* outline width */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">描边 {style.outline_width}</label>
              <input
                type="range" min={0} max={6} step={0.5} value={style.outline_width}
                onChange={e => patch('outline_width', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            {/* max chars */}
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest">每行字数 {style.max_chars_per_line}</label>
              <input
                type="range" min={8} max={40} value={style.max_chars_per_line}
                onChange={e => patch('max_chars_per_line', +e.target.value)}
                className="w-full accent-cyan-500"
              />
            </div>

            {style.background && (
              <>
                <div className="col-span-2 rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2 text-[10px] text-slate-500">
                  背景框参数用于提升对原始字幕的覆盖率：横向/纵向扩展控制覆盖范围，不透明度控制遮挡强度。
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 uppercase tracking-widest">背景横向扩展 {bgPadX.toFixed(1)}</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="range" min={0} max={1200} step={1} value={bgPadX}
                      onChange={e => patch('background_pad_x', +e.target.value)}
                      className="flex-1 accent-cyan-500"
                    />
                    <button
                      type="button"
                      onClick={() => patch('background_pad_x', Math.round(sourceW / 2))}
                      className="shrink-0 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 transition-colors"
                      title="按当前视频宽度设置为全宽覆盖（左右各半屏）"
                    >
                      全宽覆盖
                    </button>
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 uppercase tracking-widest">背景纵向扩展 {bgPadY.toFixed(1)}</label>
                  <input
                    type="range" min={0} max={20} step={0.5} value={bgPadY}
                    onChange={e => patch('background_pad_y', +e.target.value)}
                    className="w-full accent-cyan-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[10px] text-slate-500 uppercase tracking-widest">背景不透明度 {Math.round(bgOpacity)}%</label>
                  <input
                    type="range" min={0} max={100} step={1} value={bgOpacity}
                    onChange={e => patch('background_opacity', +e.target.value)}
                    className="w-full accent-cyan-500"
                  />
                </div>
              </>
            )}
          </div>

          {/* toggles row */}
          <div className="flex items-center gap-4 pt-1">
            <Toggle label="加粗" value={style.bold} onChange={v => patch('bold', v)} />
            <Toggle label="斜体" value={style.italic} onChange={v => patch('italic', v)} />
            <Toggle label="背景框" value={style.background} onChange={v => patch('background', v)} />
            <button
              onClick={() => onChange(DEFAULT_SUBTITLE_STYLE)}
              className="ml-auto text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
            >
              重置默认
            </button>
          </div>

          {/* live preview box */}
          <div className="rounded-xl bg-slate-950 border border-slate-800 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[9px] text-slate-600">预览像素: {sourceW} × {sourceH}</span>
              <span className="text-[9px] text-slate-700">坐标: {Math.round(xPct)}%, {Math.round(yPct)}%</span>
            </div>
            <div
              className="relative overflow-hidden rounded-lg border border-slate-800/80 bg-slate-900"
              style={{ width: previewW, height: previewH }}
            >
              {showPreviewImage && (
                <>
                  <img
                    src={previewFrameUrl ?? ''}
                    alt="匹配片段截图"
                    className="absolute inset-0 w-full h-full object-cover"
                    loading="lazy"
                    onError={() => setPreviewImageError(true)}
                  />
                  <div className="absolute inset-0 bg-black/30" />
                </>
              )}
              <span
                className="absolute"
                style={{
                  fontFamily: style.font_name,
                  fontSize: Math.max(style.font_size * scale, 10),
                  color: style.font_color,
                  fontWeight: style.bold ? 'bold' : 'normal',
                  fontStyle: style.italic ? 'italic' : 'normal',
                  textShadow: style.outline_width > 0
                    ? `0 0 ${style.outline_width}px ${style.outline_color}, 0 0 ${style.outline_width}px ${style.outline_color}`
                    : 'none',
                  background: style.background
                    ? `rgba(0,0,0,${Math.max(0, Math.min(100, bgOpacity)) / 100})`
                    : 'transparent',
                  padding: style.background
                    ? `${Math.max(0, bgPadY * scale)}px ${Math.max(0, bgPadX * scale)}px`
                    : undefined,
                  borderRadius: style.background ? 4 : undefined,
                  left: `${xPct}%`,
                  top: `${yPct}%`,
                  transform: 'translate(-50%, -50%)',
                  whiteSpace: 'nowrap',
                }}
              >
                字幕预览 Preview 123
              </span>
              <span className="absolute top-1 left-2 text-[9px] text-slate-700">预览</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button onClick={() => onChange(!value)} className="flex items-center gap-1.5">
      <span className={`w-4 h-4 rounded border flex items-center justify-center text-[10px] transition-colors ${
        value ? 'bg-cyan-600 border-cyan-600 text-white' : 'border-slate-600 text-transparent'
      }`}>✓</span>
      <span className="text-xs text-slate-400">{label}</span>
    </button>
  )
}

function _fmt(s: number) {
  const totalMs = Math.max(0, Math.round((Number.isFinite(s) ? s : 0) * 1000))
  const m = Math.floor(totalMs / 60000)
  const sec = Math.floor((totalMs % 60000) / 1000)
  const ms = totalMs % 1000
  return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
}
