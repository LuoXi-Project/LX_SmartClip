'use client'

import { useMemo, useState } from 'react'
import { Clapperboard, MessageSquare, Mic2, Scissors, Sparkles, Video } from 'lucide-react'
import type { Video as VideoModel } from '@/lib/api'

export type VoiceoverQuickCutStrategy = 'asr_fast' | 'standard' | 'semantic'

type VoiceoverQuickCutPanelProps = {
  selectedVideoIds: string[]
  doneVideos: VideoModel[]
  /** 接入后端生成接口后由父组件传入方案与回调；智能快剪时携带 user_prompt 供 LLM 按诉求筛选片段 */
  onGenerate?: (
    payload: { videoIds: string[]; strategy: VoiceoverQuickCutStrategy; userPrompt?: string }
  ) => void | Promise<void>
}

const STRATEGY_OPTIONS = [
  {
    id: 'asr_fast' as const,
    label: '极速快剪',
    desc: '有 ASR 字幕保留，无 ASR 段删除，速度优先',
  },
  {
    id: 'standard' as const,
    label: '标准快剪',
    desc: 'ASR + 音频能量，补漏句、保留笑声/音乐等',
  },
  {
    id: 'semantic' as const,
    label: '智能快剪',
    desc: '句子打分筛选，带缓冲合并与保护策略（推荐默认）',
  },
]

/**
 * v3 口播快剪：不经过「文案匹配」。流程为选视频 → 选模式 → 生成剪辑方案 → 微调时间轴 → 成片导出（导出侧与自动/模板一致，走方案 realize）。
 */
export function VoiceoverQuickCutPanel({
  selectedVideoIds,
  doneVideos,
  onGenerate,
}: VoiceoverQuickCutPanelProps) {
  const [strategy, setStrategy] = useState<VoiceoverQuickCutStrategy>('asr_fast')
  const [semanticUserPrompt, setSemanticUserPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [info, setInfo] = useState<string | null>(null)

  const selectedVideos = useMemo(() => {
    const set = new Set(selectedVideoIds)
    return doneVideos.filter((v) => set.has(v.id))
  }, [doneVideos, selectedVideoIds])

  async function handleGenerate() {
    setInfo(null)
    const videoIds = selectedVideos.map((v) => v.id)
    if (videoIds.length === 0) {
      setInfo('请先在上方勾选至少一个已处理完成的视频。')
      return
    }
    if (strategy === 'semantic') {
      const p = semanticUserPrompt.trim()
      if (!p) {
        setInfo('智能快剪需要填写提示词，说明你想保留或突出的内容（如：只要讲产品卖点的部分、删掉废话和重复）。')
        return
      }
    }
    const userPrompt = strategy === 'semantic' ? semanticUserPrompt.trim() : undefined
    if (onGenerate) {
      setGenerating(true)
      try {
        await onGenerate({ videoIds, strategy, userPrompt })
      } finally {
        setGenerating(false)
      }
      return
    }
    setInfo(
      strategy === 'semantic'
        ? '口播快剪后端接口尚未接入。接入后将把提示词与 ASR 片段交给 LLM，在规则约束下筛选/排序片段并生成可编辑时间轴。'
        : '口播快剪后端接口尚未接入。接入后将根据所选视频 ASR/能量 直接生成可编辑时间轴。'
    )
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-violet-500/25 bg-violet-500/5 p-5 space-y-4">
        <p className="text-xs font-semibold text-violet-300 uppercase tracking-widest flex items-center gap-2">
          <Mic2 className="w-4 h-4" />
          口播快剪（v3）
        </p>
        <p className="text-sm text-slate-300 leading-relaxed">
          从已选视频直接生成剪辑方案，再微调片段时间轴与字幕后输出。与「手动匹配」无关：不需要粘贴宣传文案或逐段检索素材。
        </p>

        <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 space-y-2">
          <p className="text-[11px] text-slate-500 flex items-center gap-2">
            <Video className="w-3.5 h-3.5" />
            当前选中视频 · {selectedVideos.length} 个
          </p>
          {selectedVideos.length === 0 ? (
            <p className="text-xs text-amber-400/90">未选择视频，或所选项尚未出现在已完成列表中。</p>
          ) : (
            <ul className="text-xs text-slate-400 space-y-1 max-h-28 overflow-y-auto">
              {selectedVideos.map((v) => (
                <li key={v.id} className="truncate">
                  · {v.name || v.id}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">快剪模式</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {STRATEGY_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setStrategy(opt.id)}
                className={`text-left rounded-xl border px-3 py-2.5 transition-colors ${
                  strategy === opt.id
                    ? 'border-violet-500/70 bg-violet-500/15 text-violet-100'
                    : 'border-slate-700 bg-slate-900/50 text-slate-400 hover:border-slate-600'
                }`}
              >
                <span className="flex items-center gap-1.5 text-xs font-medium text-slate-200">
                  <Scissors className="w-3 h-3 text-violet-400 shrink-0" />
                  {opt.label}
                </span>
                <span className="mt-1 block text-[10px] text-slate-500 leading-snug">{opt.desc}</span>
              </button>
            ))}
          </div>
        </div>

        {strategy === 'semantic' && (
          <div className="space-y-2 rounded-xl border border-violet-500/20 bg-slate-950/40 px-4 py-3">
            <label className="flex items-center gap-2 text-[11px] font-medium text-violet-200/95">
              <MessageSquare className="w-3.5 h-3.5 text-violet-400" />
              智能快剪 · 提示词（必填）
            </label>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              描述你的剪辑诉求，后端将结合 ASR 句子与约束调用 LLM 筛选/保留片段（非全量重写，仅辅助选段）。
            </p>
            <textarea
              value={semanticUserPrompt}
              onChange={(e) => setSemanticUserPrompt(e.target.value)}
              placeholder="例如：保留介绍价格和优惠的段落，删掉闲聊和重复口癖；节奏紧凑，总时长控制在 2 分钟内…"
              rows={4}
              className="w-full rounded-xl bg-slate-900/70 border border-slate-700 px-3 py-2.5 text-sm text-slate-200 outline-none focus:border-violet-500/60 placeholder:text-slate-600 resize-y min-h-[88px]"
            />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={generating}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-sm font-medium text-white transition-colors"
          >
            <Sparkles className="w-4 h-4" />
            {generating ? '生成中…' : '生成快剪方案'}
          </button>
          <span className="text-[11px] text-slate-500">生成结果将出现在下方，可再细调顺序与入出点。</span>
        </div>

        {info && (
          <div className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-200/95 leading-relaxed">
            {info}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-800 bg-slate-900/35 p-5 space-y-3">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
          <Clapperboard className="w-4 h-4 text-slate-500" />
          方案微调
        </p>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          后端返回剪辑计划后，将在此展示片段时间轴（与「自动一键成片」方案详情类似的顺序与起止时间编辑），确认后使用右侧说明的成片导出流程。
        </p>
        <div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/40 px-4 py-10 text-center text-xs text-slate-600">
          暂无方案 · 点击「生成快剪方案」后在此展示可编辑时间轴
        </div>
      </section>
    </div>
  )
}
