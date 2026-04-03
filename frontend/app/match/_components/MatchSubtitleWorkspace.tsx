'use client'

import type { ReactNode } from 'react'
import type { SubtitleStyle, SRTEntry } from './types'
import { SubtitlePanel } from './SubtitlePanel'

type MatchSubtitleWorkspaceProps = {
  style: SubtitleStyle
  onStyleChange: (s: SubtitleStyle) => void
  entries: SRTEntry[]
  subtitleEnabled: boolean
  onSubtitleEnabledChange: (v: boolean) => void
  timingSource: string
  previewVideoSize: { width: number; height: number } | null
  srtError: string
  /** 导出流程说明（如一键成片 / 原声成片），各模式按需传入 */
  footer?: ReactNode
}

/**
 * 各剪辑模式共用的「字幕手调 + 时间轴预览」区域（SubtitlePanel 封装）。
 * 时间轴条目由上游在生成 SRT / 预览后写入 entries。
 */
export function MatchSubtitleWorkspace({
  style,
  onStyleChange,
  entries,
  subtitleEnabled,
  onSubtitleEnabledChange,
  timingSource,
  previewVideoSize,
  srtError,
  footer,
}: MatchSubtitleWorkspaceProps) {
  return (
    <>
      <SubtitlePanel
        style={style}
        onChange={onStyleChange}
        entries={entries}
        enabled={subtitleEnabled}
        onToggle={onSubtitleEnabledChange}
        timingSource={timingSource}
        previewVideoSize={previewVideoSize}
      />
      {srtError && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-400">
          字幕错误：{srtError}
        </div>
      )}
      {footer}
    </>
  )
}
