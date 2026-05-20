'use client'

import Link from 'next/link'
import type { ReactNode } from 'react'
import { type BgmTrack } from '@/lib/api'
import { BgmTrackPicker } from '@/components/ui/bgm-track-picker'
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
  hideTrackSelector?: boolean
  /** 文案素材成片等无 LLM 规划场景：隐藏「规划阶段 BGM 策略」 */
  hideStrategy?: boolean
  /** 曲目下拉 value：曲库 id（推荐）或文件名 */
  trackValueField?: 'id' | 'filename'
}

const POLICY_OPTIONS: { value: AutoEditBgmMixPanelProps['autoBgmPlanPolicy']; label: string; hint: string }[] = [
  { value: 'auto', label: '自动匹配', hint: '模型结合曲库选曲' },
  { value: 'ai', label: 'AI 推荐', hint: '由模型推荐具体曲目' },
  { value: 'user', label: '我指定', hint: '按下方曲目或风格取向' },
  { value: 'none', label: '不要 BGM', hint: '成片不叠加背景音乐' },
]

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
  hideTrackSelector = false,
  hideStrategy = false,
  trackValueField = 'filename',
}: AutoEditBgmMixPanelProps) {
  const emptyHint = (
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
  )

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
          <span className="text-sm text-slate-200">导出成片时叠加背景音乐</span>
        </label>
        <p className="text-[11px] text-slate-500 leading-relaxed">{helperText}</p>

        {autoBgmMixEnabled && (
          <div className="space-y-3 pt-1 border-t border-slate-800/80">
            {!hideStrategy && (
              <div className="space-y-2">
                <span className="text-[11px] text-slate-400">{strategyLabel}</span>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                  {POLICY_OPTIONS.map((opt) => {
                    const active = autoBgmPlanPolicy === opt.value
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        disabled={policySelectDisabled}
                        onClick={() => onAutoBgmPlanPolicyChange(opt.value)}
                        className={`rounded-lg border px-2 py-2 text-left transition-colors disabled:opacity-50 ${
                          active
                            ? 'border-emerald-500/50 bg-emerald-500/10'
                            : 'border-slate-700 bg-slate-900/50 hover:border-slate-600'
                        }`}
                      >
                        <span className="block text-xs font-medium text-slate-200">{opt.label}</span>
                        <span className="block text-[10px] text-slate-500 mt-0.5 leading-snug">{opt.hint}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {!hideTrackSelector && (
              <div className="space-y-1.5">
                <span className="text-[11px] text-slate-400">指定成片曲目（可选）</span>
                <BgmTrackPicker
                  tracks={bgmTracks}
                  value={autoBgmTrackFilename}
                  onChange={onAutoBgmTrackFilenameChange}
                  trackValueField={trackValueField}
                  disabled={!autoBgmMixEnabled}
                  listError={bgmListError}
                  emptyHint={autoBgmMixEnabled && bgmTracks.length === 0 && !bgmListError ? emptyHint : undefined}
                />
              </div>
            )}
          </div>
        )}

        {!autoBgmMixEnabled && (
          <p className="text-[11px] text-slate-600">开启后可配置规划策略与指定曲目。</p>
        )}
      </div>
    </div>
  )
}
