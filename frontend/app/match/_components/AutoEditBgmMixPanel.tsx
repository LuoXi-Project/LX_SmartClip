'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'
import { type BgmTrack } from '@/lib/api'
import { Music2 } from 'lucide-react'

export type AutoEditBgmMixPanelProps = {
  wrapperClassName?: string

  bgmTracks: BgmTrack[]
  bgmListError: string

  autoBgmMixEnabled: boolean
  onAutoBgmMixEnabledChange: (value: boolean) => void

  autoBgmPlanPolicy: 'auto' | 'none' | 'user' | 'ai'
  onAutoBgmPlanPolicyChange: (value: 'auto' | 'none' | 'user' | 'ai') => void

  autoBgmTrackFilename: string
  onAutoBgmTrackFilenameChange: (value: string) => void

  /** 规划区：策略下拉框在生成中需要禁用 */
  policySelectDisabled?: boolean

  helperText: ReactNode

  strategyLabel?: string
  emptyBgmHintPrefix: string
}

export function AutoEditBgmMixPanel({
  wrapperClassName = 'space-y-2',
  bgmTracks,
  bgmListError,
  autoBgmMixEnabled,
  onAutoBgmMixEnabledChange,
  autoBgmPlanPolicy,
  onAutoBgmPlanPolicyChange,
  autoBgmTrackFilename,
  onAutoBgmTrackFilenameChange,
  policySelectDisabled = false,
  helperText,
  strategyLabel = '规划阶段 BGM 策略（写给模型）',
  emptyBgmHintPrefix,
}: AutoEditBgmMixPanelProps) {
  return (
    <div className={wrapperClassName}>
      <label className="text-xs text-slate-300 flex items-center gap-2">
        <Music2 className="w-3.5 h-3.5 text-emerald-400/90" />
        背景音乐（成片混音）
      </label>
      <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-3 space-y-3">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoBgmMixEnabled}
            onChange={(e) => onAutoBgmMixEnabledChange(e.target.checked)}
            className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40"
          />
          <span className="text-sm text-slate-200">导出成片时叠加背景音乐（FFmpeg 混音）</span>
        </label>
        <p className="text-[11px] text-slate-500 leading-relaxed">{helperText}</p>
            <div className="grid sm:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <span className="text-[11px] text-slate-400">{strategyLabel}</span>
            <select
              value={autoBgmPlanPolicy}
              onChange={(e) => onAutoBgmPlanPolicyChange(e.target.value as 'auto' | 'none' | 'user' | 'ai')}
              disabled={policySelectDisabled}
              className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400 disabled:opacity-50"
            >
              <option value="auto">自动（由模型与曲库配合）</option>
              <option value="none">不要 BGM</option>
              <option value="user">用户指定取向</option>
              <option value="ai">AI 推荐曲目</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <span className="text-[11px] text-slate-400">成片使用的曲目</span>
            <select
              value={autoBgmTrackFilename}
              onChange={(e) => onAutoBgmTrackFilenameChange(e.target.value)}
              disabled={!autoBgmMixEnabled}
              className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400 disabled:opacity-50"
            >
              <option value="">自动（方案推荐 / 曲库匹配）</option>
              {bgmTracks.map((t) => (
                <option key={t.id} value={t.filename}>
                  {t.title || t.filename}
                </option>
              ))}
            </select>
            {bgmListError && <p className="text-[11px] text-amber-400/90">{bgmListError}</p>}
            {autoBgmMixEnabled && bgmTracks.length === 0 && !bgmListError && (
              <p className="text-[11px] text-slate-500">
                {emptyBgmHintPrefix}{' '}
                <Link href="/settings" className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2">
                  设置 → BGM
                </Link>{' '}
                或{' '}
                <Link href="/bgm" className="text-cyan-400 hover:text-cyan-300 underline underline-offset-2">
                  BGM 页
                </Link>{' '}
                上传音频。
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

