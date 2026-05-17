'use client'

import type { TtsVideoAlignConfigApi, TtsVideoAlignPolicyApi } from '@/lib/api'

export const TTS_ALIGN_BASIC_OPTIONS: {
  id: TtsVideoAlignPolicyApi
  label: string
  hint: string
}[] = [
  {
    id: 'loop_video_to_cover',
    label: '循环拼接所选画面',
    hint: '重复播放本段素材直至盖住整段配音。',
  },
  {
    id: 'freeze_last_frame',
    label: '不循环素材，末尾定格',
    hint: '画面播完后停在最后一帧，直到配音结束（当前默认）。',
  },
]

export const TTS_ALIGN_ALL_OPTIONS: {
  id: TtsVideoAlignPolicyApi
  label: string
  hint: string
}[] = [
  ...TTS_ALIGN_BASIC_OPTIONS,
  {
    id: 'stretch_audio',
    label: '变速配音贴画面',
    hint: '加速/减速 TTS 使口播时长接近画面；超出限制时仍会定格补偿。',
  },
  {
    id: 'stretch_video',
    label: '变速画面贴配音',
    hint: '快放/慢放画面使时长接近 TTS；超出限制时尾部定格补齐。',
  },
]

type TtsAlignPolicySelectProps = {
  value: TtsVideoAlignConfigApi
  onChange: (patch: Partial<TtsVideoAlignConfigApi>) => void
  /** 仅展示「定格 / 循环」两项，适合混剪 AI 配音 */
  basicOnly?: boolean
  disabled?: boolean
  className?: string
}

export function TtsAlignPolicySelect({
  value,
  onChange,
  basicOnly = false,
  disabled = false,
  className = '',
}: TtsAlignPolicySelectProps) {
  const options = basicOnly ? TTS_ALIGN_BASIC_OPTIONS : TTS_ALIGN_ALL_OPTIONS
  const active = options.find((o) => o.id === value.policy) ?? options[0]

  return (
    <div className={`space-y-1 ${className}`.trim()}>
      <label className="text-[11px] text-slate-400">配音与画面时长不一致时</label>
      <select
        value={value.policy}
        onChange={(e) => onChange({ policy: e.target.value as TtsVideoAlignPolicyApi })}
        disabled={disabled}
        className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-2 outline-none focus:border-cyan-500/50 disabled:opacity-50"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
      <p className="text-[10px] text-slate-500 leading-relaxed">{active.hint}</p>
      <p className="text-[10px] text-slate-600 leading-relaxed">
        配音短于画面时，成片会自动裁切画面至配音结束，无需额外设置。
      </p>
    </div>
  )
}
