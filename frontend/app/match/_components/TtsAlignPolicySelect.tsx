'use client'

import type { TtsVideoAlignConfigApi, TtsVideoAlignPolicyApi } from '@/lib/api'

export const TTS_ALIGN_BASIC_OPTIONS: {
  id: TtsVideoAlignPolicyApi
  label: string
  hint: string
}[] = [
  {
    id: 'preserve_video_duration',
    label: '保留画面时长（推荐）',
    hint: '配音短于画面时不裁画面，尾部补静音；配音长于画面时末尾定格。',
  },
  {
    id: 'loop_video_to_cover',
    label: '循环本段画面',
    hint: '仅重复播放该段 TTS 对应的素材，直至盖住整段配音。',
  },
  {
    id: 'loop_playlist_to_cover',
    label: '智能轮播全部素材',
    hint: '配音长于画面时，按混剪方案中的完整素材列表智能轮播',
  },
  {
    id: 'freeze_last_frame',
    label: '不循环，末尾定格',
    hint: '画面播完后停在最后一帧，直到配音结束。',
  },
]

/** 混剪模式二：默认展示「本段循环 / 全列表轮播 / 定格」 */
export const MIX_EDIT_TTS_ALIGN_OPTIONS = TTS_ALIGN_BASIC_OPTIONS.filter(
  (o) => o.id !== 'preserve_video_duration',
)

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

type AlignOption = { id: TtsVideoAlignPolicyApi; label: string; hint: string }

type TtsAlignPolicySelectProps = {
  value: TtsVideoAlignConfigApi
  onChange: (patch: Partial<TtsVideoAlignConfigApi>) => void
  /** 仅展示基础三项（本段循环 / 全列表轮播 / 定格），不传 options 时生效 */
  basicOnly?: boolean
  /** 自定义选项列表（混剪可传 MIX_EDIT_TTS_ALIGN_OPTIONS） */
  options?: AlignOption[]
  /** 混剪模式二：是否展示「按句拆段」开关 */
  showNarrationSplitOption?: boolean
  disabled?: boolean
  className?: string
}

export function TtsAlignPolicySelect({
  value,
  onChange,
  basicOnly = false,
  options: optionsProp,
  showNarrationSplitOption = false,
  disabled = false,
  className = '',
}: TtsAlignPolicySelectProps) {
  const options = optionsProp ?? (basicOnly ? TTS_ALIGN_BASIC_OPTIONS : TTS_ALIGN_ALL_OPTIONS)
  const active = options.find((o) => o.id === value.policy) ?? options[0]
  const splitBySentence = value.split_narration_by_sentence ?? false

  return (
    <div className={`space-y-3 ${className}`.trim()}>
      <div className="space-y-1">
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

      {showNarrationSplitOption ? (
        <label className="flex items-start gap-2.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={splitBySentence}
            disabled={disabled}
            onChange={(e) => onChange({ split_narration_by_sentence: e.target.checked })}
            className="mt-0.5 rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500/40"
          />
          <span className="min-w-0">
            <span className="text-xs text-slate-200">按逗号拆成短条配音</span>
            <span className="block text-[10px] text-slate-500 mt-0.5 leading-relaxed">
              开启后按逗号、顿号等拆成短条并分段配音（旁白里需有相应标点）；关闭时仅按句号/换行分条。修改后请重新生成混剪方案再导出。
            </span>
          </span>
        </label>
      ) : null}
    </div>
  )
}
