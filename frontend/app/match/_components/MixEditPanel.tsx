'use client'

import { useMemo, useState } from 'react'
import { Layers, Mic2, VolumeX, Sparkles, Info } from 'lucide-react'
import type { TtsVideoAlignConfigApi, Video as VideoModel } from '@/lib/api'
import type { MixAudioMode, MuteAudioTrack } from './mixEditTypes'
import { TtsAlignPolicySelect } from './TtsAlignPolicySelect'

export type MixEditGeneratePayload = {
  videoIds: string[]
  mixAudioMode: MixAudioMode
  muteAudioTrack: MuteAudioTrack
  targetDurationSec?: number
  userPrompt?: string
}

type MixEditPanelProps = {
  selectedVideoIds: string[]
  doneVideos: VideoModel[]
  onGenerate?: (payload: MixEditGeneratePayload) => void | Promise<void>
  loading?: boolean
  /** 模式二 AI 配音成片：画面与 TTS 时长对齐策略 */
  ttsAlign?: TtsVideoAlignConfigApi
  onTtsAlignChange?: (patch: Partial<TtsVideoAlignConfigApi>) => void
}

const MODE_OPTIONS: Array<{
  id: MixAudioMode
  label: string
  desc: string
  icon: typeof Mic2
}> = [
  {
    id: 'keep_original',
    label: '模式一：保留素材原声',
    desc: '带 ASR 的片段保留原声，可自由穿插拼接',
    icon: Mic2,
  },
  {
    id: 'mute_all_original',
    label: '模式二：关闭全部原声',
    desc: '素材全部静音，成片使用 AI 配音或纯 BGM',
    icon: VolumeX,
  },
]

const MUTE_TRACK_OPTIONS: Array<{ id: MuteAudioTrack; label: string; desc: string; badge?: string }> = [
  {
    id: 'ai_tts_llm',
    label: 'AI 生成文案配音',
    badge: '推荐',
    desc: '根据素材 ASR/VLM + 你的诉求，LLM 撰写全新旁白再 TTS',
  },
  {
    id: 'ai_tts_asr',
    label: '沿用 ASR 原文配音',
    desc: '直接按识别台词合成 TTS，不改写文案',
  },
  { id: 'bgm_only', label: '仅 BGM', desc: '素材全静音，仅叠加背景音乐' },
]

const TIER_LEGEND = [
  { tier: 'ASR + VLM', arrange: '语义智能混剪' },
  { tier: '仅 ASR', arrange: '文本语义编排' },
  { tier: '仅 VLM', arrange: '画面语义匹配' },
  { tier: '全无', arrange: '纯随机混剪' },
]

export function MixEditPanel({
  selectedVideoIds,
  doneVideos,
  onGenerate,
  loading = false,
  ttsAlign,
  onTtsAlignChange,
}: MixEditPanelProps) {
  const [mixAudioMode, setMixAudioMode] = useState<MixAudioMode>('keep_original')
  const [muteAudioTrack, setMuteAudioTrack] = useState<MuteAudioTrack>('ai_tts_llm')
  const [targetDuration, setTargetDuration] = useState('')
  const [userPrompt, setUserPrompt] = useState('')

  const selectedCount = selectedVideoIds.length
  const canGenerate = selectedCount > 0 && !loading

  const scopeHint = useMemo(() => {
    if (selectedCount === 0) return '请先在上方勾选参与混剪的视频'
    const names = doneVideos
      .filter((v) => selectedVideoIds.includes(v.id))
      .map((v) => v.name || v.id)
      .slice(0, 3)
    const suffix = selectedCount > 3 ? ` 等 ${selectedCount} 个` : ''
    return `已选：${names.join('、')}${suffix}`
  }, [doneVideos, selectedVideoIds, selectedCount])

  const needsLlmPrompt =
    mixAudioMode === 'mute_all_original' && muteAudioTrack === 'ai_tts_llm'
  const usesTtsTrack =
    mixAudioMode === 'mute_all_original' &&
    (muteAudioTrack === 'ai_tts_llm' || muteAudioTrack === 'ai_tts_asr')
  const promptMissing = needsLlmPrompt && !userPrompt.trim()

  const handleGenerate = () => {
    if (!canGenerate || !onGenerate || promptMissing) return
    const td = targetDuration.trim() ? Number(targetDuration) : undefined
    onGenerate({
      videoIds: selectedVideoIds,
      mixAudioMode,
      muteAudioTrack,
      targetDurationSec: td && Number.isFinite(td) && td > 0 ? td : undefined,
      userPrompt: userPrompt.trim() || undefined,
    })
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-6">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-indigo-500/15">
          <Layers className="w-5 h-5 text-indigo-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-100">混剪</h2>
          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
            多素材智能编排：两大顶层音轨模式；自动识别 ASR / VLM 分级。
          </p>
        </div>
      </header>

      <section className="space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">顶层模式</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {MODE_OPTIONS.map((opt) => {
            const Icon = opt.icon
            const active = mixAudioMode === opt.id
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => setMixAudioMode(opt.id)}
                className={`text-left rounded-xl border p-3 transition-colors ${
                  active
                    ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30'
                    : 'border-slate-700 hover:border-slate-600 bg-slate-900/30'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon className={`w-4 h-4 ${active ? 'text-indigo-300' : 'text-slate-500'}`} />
                  <span className="text-sm font-medium text-slate-200">{opt.label}</span>
                </div>
                <p className="text-[10px] text-slate-500 mt-1">{opt.desc}</p>
              </button>
            )
          })}
        </div>
      </section>

      {mixAudioMode === 'keep_original' ? (
        <section className="space-y-2 rounded-xl border border-violet-500/20 bg-violet-500/5 p-4">
          <p className="text-xs font-semibold text-violet-200">原声编排说明</p>
          <ul className="text-[11px] text-slate-500 list-disc list-inside space-y-1">
            <li>带 ASR 素材原声可自由穿插拼接</li>
            <li>无 ASR 素材静音，仅作画面填充</li>
            <li>请自行保证素材人声、收音环境一致</li>
          </ul>
        </section>
      ) : (
        <section className="space-y-3 rounded-xl border border-sky-500/20 bg-sky-500/5 p-4">
          <p className="text-xs font-semibold text-sky-200">成片音轨</p>
          <p className="text-[11px] text-slate-500">
            无视素材 ASR，全部静音；按素材元数据等级编排画面
          </p>
          <MuteTrackGrid value={muteAudioTrack} onChange={setMuteAudioTrack} />
          {needsLlmPrompt ? (
            <p className="text-[11px] text-amber-300/90">
              已选 AI 生成文案：请在下方填写剪辑诉求（风格、主题、受众等），将结合素材内容生成旁白，不会照抄 ASR。
            </p>
          ) : null}
          {usesTtsTrack && ttsAlign && onTtsAlignChange ? (
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 px-3 py-3">
              <TtsAlignPolicySelect
                basicOnly
                value={ttsAlign}
                onChange={onTtsAlignChange}
                disabled={loading}
              />
            </div>
          ) : null}
        </section>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 space-y-2">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Info className="w-3.5 h-3.5 shrink-0" />
          <span>素材分级与编排（ASR / VLM 兼容）</span>
        </div>
        <TierLegendGrid />
      </section>

      <section className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-[11px] text-slate-500">目标时长（秒，可选）</span>
          <input
            type="number"
            min={5}
            max={7200}
            value={targetDuration}
            onChange={(e) => setTargetDuration(e.target.value)}
            placeholder="如 60"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
          />
        </label>
        <label className="block space-y-1 sm:col-span-2">
          <span className="text-[11px] text-slate-500">
            剪辑诉求{needsLlmPrompt ? '（AI 生成文案必填）' : '（可选）'}
          </span>
          <textarea
            value={userPrompt}
            onChange={(e) => setUserPrompt(e.target.value)}
            placeholder={
              needsLlmPrompt
                ? '例如：为这段混剪写一段有感染力的带货旁白，突出性价比与使用场景…'
                : '如：偏干货、节奏快'
            }
            rows={needsLlmPrompt ? 3 : 2}
            className={`w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm resize-none ${
              promptMissing ? 'border-amber-500/60' : 'border-slate-700'
            }`}
          />
        </label>
      </section>

      <p className="text-[11px] text-slate-500">{scopeHint}</p>

      <button
        type="button"
        disabled={!canGenerate || promptMissing}
        onClick={handleGenerate}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors"
      >
        <Sparkles className="w-4 h-4" />
        {loading ? '生成混剪方案中…' : '生成混剪方案'}
      </button>
    </div>
  )
}

function MuteTrackGrid({
  value,
  onChange,
}: {
  value: MuteAudioTrack
  onChange: (v: MuteAudioTrack) => void
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {MUTE_TRACK_OPTIONS.map((opt) => (
        <button
          key={opt.id}
          type="button"
          onClick={() => onChange(opt.id)}
          className={`text-left rounded-xl border px-3 py-2.5 transition-colors ${
            value === opt.id
              ? 'border-sky-500 bg-sky-500/15 ring-1 ring-sky-500/30'
              : 'border-slate-700 hover:border-slate-600'
          }`}
        >
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-sm font-medium text-slate-200">{opt.label}</span>
            {opt.badge ? (
              <span className="text-[10px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                {opt.badge}
              </span>
            ) : null}
          </div>
          <p className="text-[10px] text-slate-500 mt-1 leading-snug">{opt.desc}</p>
        </button>
      ))}
    </div>
  )
}

function TierLegendGrid() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px]">
      {TIER_LEGEND.map((row) => (
        <div key={row.tier} className="rounded-lg border border-slate-800 px-2 py-1.5">
          <p className="text-slate-300 font-medium">{row.tier}</p>
          <p className="text-slate-500">→ {row.arrange}</p>
        </div>
      ))}
    </div>
  )
}
