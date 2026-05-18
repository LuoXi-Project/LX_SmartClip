'use client'

import { useMemo, useState } from 'react'
import { Volume2, Info, Sparkles } from 'lucide-react'
import type { TtsVideoAlignConfigApi, Video as VideoModel } from '@/lib/api'
import { TtsAlignPolicySelect, TTS_ALIGN_ALL_OPTIONS } from './TtsAlignPolicySelect'

export type VideoDubContentSource = 'asr_rewrite' | 'asr_literal' | 'vlm_narrate' | 'auto'

export type VideoDubGeneratePayload = {
  videoIds: string[]
  contentSource: VideoDubContentSource
  userPrompt?: string
  preserveGaps: boolean
}

type VideoDubPanelProps = {
  selectedVideoIds: string[]
  doneVideos: VideoModel[]
  onGenerate?: (payload: VideoDubGeneratePayload) => void | Promise<void>
  loading?: boolean
  ttsAlign: TtsVideoAlignConfigApi
  onTtsAlignChange: (patch: Partial<TtsVideoAlignConfigApi>) => void
}

const SOURCE_OPTIONS: Array<{
  id: VideoDubContentSource
  label: string
  desc: string
}> = [
  {
    id: 'auto',
    label: '智能',
    desc: '有 ASR 则按句洗稿/配音，无 ASR 的片段用画面描述生成旁白',
  },
  {
    id: 'asr_rewrite',
    label: 'ASR 洗稿配音',
    desc: '基于识别台词按诉求改写，尽量贴合原镜头时长',
  },
  {
    id: 'asr_literal',
    label: 'ASR 原文配音',
    desc: '不改写文案，直接按识别结果 TTS（适合原声替换）',
  },
  {
    id: 'vlm_narrate',
    label: '画面解说配音',
    desc: '无口播或需按画面重讲时使用 VLM 描述生成旁白',
  },
]

export function VideoDubPanel({
  selectedVideoIds,
  doneVideos,
  onGenerate,
  loading = false,
  ttsAlign,
  onTtsAlignChange,
}: VideoDubPanelProps) {
  const [contentSource, setContentSource] = useState<VideoDubContentSource>('auto')
  const [userPrompt, setUserPrompt] = useState('')
  const [preserveGaps, setPreserveGaps] = useState(true)

  const selectedCount = selectedVideoIds.length

  const scopeHint = useMemo(() => {
    if (selectedCount === 0) return '请先在上方勾选一个视频（建议单选）'
    if (selectedCount > 1) return `已选 ${selectedCount} 个视频，将按顺序拼接；推荐单视频以获得最佳对齐`
    const v = doneVideos.find((x) => x.id === selectedVideoIds[0])
    return v ? `已选：${v.name || v.id}` : '已选 1 个视频'
  }, [doneVideos, selectedVideoIds, selectedCount])

  const promptRequired = contentSource === 'asr_rewrite'
  const promptMissing = promptRequired && !userPrompt.trim()
  const canGenerate = selectedCount > 0 && !loading && !promptMissing

  const handleGenerate = () => {
    if (!canGenerate || !onGenerate) return
    onGenerate({
      videoIds: selectedVideoIds,
      contentSource,
      userPrompt: userPrompt.trim() || undefined,
      preserveGaps,
    })
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-6">
      <header className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-teal-500/15">
          <Volume2 className="w-5 h-5 text-teal-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-100">视频配音</h2>
          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
            保留原片镜头与时长编排，替换为 TTS 旁白。素材需已完成 ASR 和/或 VLM；与混剪不同，不以配音驱动重剪。
          </p>
        </div>
      </header>

      <div className="flex items-start gap-2 rounded-lg border border-slate-700/80 bg-slate-900/50 px-3 py-2.5">
        <Info className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-slate-400 leading-relaxed">{scopeHint}</p>
      </div>

      <section className="space-y-2">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">文案来源</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {SOURCE_OPTIONS.map((opt) => {
            const active = contentSource === opt.id
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => setContentSource(opt.id)}
                className={`text-left rounded-xl border p-3 transition-colors ${
                  active
                    ? 'border-teal-500 bg-teal-500/10 ring-1 ring-teal-500/30'
                    : 'border-slate-700 hover:border-slate-600 bg-slate-900/30'
                }`}
              >
                <span className="text-sm font-medium text-slate-200">{opt.label}</span>
                <p className="text-[10px] text-slate-500 mt-1 leading-relaxed">{opt.desc}</p>
              </button>
            )
          })}
        </div>
      </section>

      <section className="space-y-2">
        <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
          配音诉求
          {contentSource !== 'asr_literal' && (
            <span className="text-teal-400/90 font-normal normal-case ml-1">（洗稿/解说建议填写）</span>
          )}
        </label>
        <textarea
          value={userPrompt}
          onChange={(e) => setUserPrompt(e.target.value)}
          placeholder={
            contentSource === 'vlm_narrate'
              ? '例如：用轻松口语介绍画面中的产品亮点，适合无原声 B-roll…'
              : '例如：保留原意，语气更活泼，突出性价比，适合短视频口播…'
          }
          rows={3}
          className={`w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm resize-none ${
            promptMissing ? 'border-amber-500/60' : 'border-slate-700'
          }`}
        />
        {promptMissing && (
          <p className="text-[11px] text-amber-400/90">洗稿模式请填写配音诉求后再生成方案</p>
        )}
      </section>

      <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/30 p-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">时长对齐策略</p>
        <TtsAlignPolicySelect
          value={ttsAlign}
          onChange={onTtsAlignChange}
          options={TTS_ALIGN_ALL_OPTIONS}
          disabled={loading}
        />
        <div className="grid grid-cols-2 gap-3 pt-1 border-t border-slate-800">
          <label className="space-y-1">
            <span className="text-[11px] text-slate-400">配音加速上限</span>
            <input
              type="number"
              min={1}
              max={4}
              step={0.1}
              value={ttsAlign.max_audio_atempo ?? 2}
              disabled={loading}
              onChange={(e) => onTtsAlignChange({ max_audio_atempo: Number(e.target.value) || 2 })}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs px-2 py-1.5 text-slate-200"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[11px] text-slate-400">配音减速下限</span>
            <input
              type="number"
              min={0.25}
              max={1}
              step={0.05}
              value={ttsAlign.min_audio_atempo ?? 0.5}
              disabled={loading}
              onChange={(e) => onTtsAlignChange({ min_audio_atempo: Number(e.target.value) || 0.5 })}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs px-2 py-1.5 text-slate-200"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[11px] text-slate-400">画面慢放上限</span>
            <input
              type="number"
              min={1}
              max={4}
              step={0.1}
              value={ttsAlign.max_video_pts_factor ?? 2}
              disabled={loading}
              onChange={(e) => onTtsAlignChange({ max_video_pts_factor: Number(e.target.value) || 2 })}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs px-2 py-1.5 text-slate-200"
            />
          </label>
          <label className="space-y-1">
            <span className="text-[11px] text-slate-400">画面快放下限</span>
            <input
              type="number"
              min={0.25}
              max={1}
              step={0.05}
              value={ttsAlign.min_video_pts_factor ?? 0.5}
              disabled={loading}
              onChange={(e) => onTtsAlignChange({ min_video_pts_factor: Number(e.target.value) || 0.5 })}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs px-2 py-1.5 text-slate-200"
            />
          </label>
        </div>
        <p className="text-[10px] text-slate-600 leading-relaxed">
          默认「保留画面时长」：配音短不裁画面、尾部补静音；配音长则定格/循环/变速。方案卡片里的预估时长为各镜头之和，成片应接近原片长度。
        </p>
      </section>

      <label className="flex items-start gap-2.5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={preserveGaps}
          disabled={loading}
          onChange={(e) => setPreserveGaps(e.target.checked)}
          className="mt-0.5 rounded border-slate-600 bg-slate-900 text-teal-500 focus:ring-teal-500/40"
        />
        <span className="min-w-0">
          <span className="text-xs text-slate-200">保留句间/无标注间隙画面</span>
          <span className="block text-[10px] text-slate-500 mt-0.5 leading-relaxed">
            开启后在无口播区间仍保留原画面（静音轨），总时长更接近原片；关闭则只导出有声段。
          </span>
        </span>
      </label>

      <button
        type="button"
        disabled={!canGenerate}
        onClick={handleGenerate}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 disabled:opacity-40 disabled:pointer-events-none text-sm font-medium text-white transition-colors"
      >
        <Sparkles className="w-4 h-4" />
        {loading ? '生成配音方案中…' : '生成配音方案'}
      </button>
    </div>
  )
}