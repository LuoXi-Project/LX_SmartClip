'use client'

import { useId, useMemo, useState } from 'react'
import { MessageSquare, Mic2, Scissors, Sparkles, Video } from 'lucide-react'
import type { Video as VideoModel } from '@/lib/api'
import { Switch } from '@/components/ui/switch'

export type VoiceoverQuickCutStrategy = 'asr_fast' | 'semantic' | 'audio_activity_fast'

export type VoiceoverAudioActivityConfig = {
  activityDbThreshold: number
  activityMinSilenceSec: number
  activityMinKeepSec: number
  activityMergeGapSec: number
  activityHeadPadSec: number
  activityTailPadSec: number
}

type VoiceoverAudioActivityPreset = {
  id: 'quiet_voiceover' | 'noisy_scene' | 'tight_rhythm'
  label: string
  desc: string
  config: VoiceoverAudioActivityConfig
}

type VoiceoverQuickCutPanelProps = {
  selectedVideoIds: string[]
  doneVideos: VideoModel[]
  /** 接入后端生成接口后由父组件传入方案与回调；智能快剪时携带 user_prompt 供 LLM 按诉求筛选片段 */
  onGenerate?: (
    payload: {
      videoIds: string[]
      strategy: VoiceoverQuickCutStrategy
      userPrompt?: string
      allowOverlappingSourceTimeline?: boolean
      audioActivityConfig?: VoiceoverAudioActivityConfig
    }
  ) => void | Promise<void>
}

const STRATEGY_OPTIONS = [
  {
    id: 'asr_fast' as const,
    label: '极速快剪',
    desc: '有 ASR 字幕保留，无 ASR 段删除，速度优先',
  },
  {
    id: 'semantic' as const,
    label: '智能快剪',
    desc: '句子打分筛选，带缓冲合并与保护策略（推荐默认）',
  },
  {
    id: 'audio_activity_fast' as const,
    label: '音频粗剪',
    desc: '无需 ASR，按音频活动自动保留语音段（支持参数微调）',
  },
]

const AUDIO_ACTIVITY_PRESETS: VoiceoverAudioActivityPreset[] = [
  {
    id: 'quiet_voiceover',
    label: '安静口播',
    desc: '室内相对安静，尽量保留完整语句',
    config: {
      activityDbThreshold: -38,
      activityMinSilenceSec: 0.22,
      activityMinKeepSec: 0.3,
      activityMergeGapSec: 0.25,
      activityHeadPadSec: 0.1,
      activityTailPadSec: 0.14,
    },
  },
  {
    id: 'noisy_scene',
    label: '嘈杂环境',
    desc: '环境噪声明显，减少误保留',
    config: {
      activityDbThreshold: -31,
      activityMinSilenceSec: 0.3,
      activityMinKeepSec: 0.45,
      activityMergeGapSec: 0.16,
      activityHeadPadSec: 0.06,
      activityTailPadSec: 0.1,
    },
  },
  {
    id: 'tight_rhythm',
    label: '紧凑节奏',
    desc: '更强删减，优先速度与密度',
    config: {
      activityDbThreshold: -34,
      activityMinSilenceSec: 0.2,
      activityMinKeepSec: 0.5,
      activityMergeGapSec: 0.12,
      activityHeadPadSec: 0.04,
      activityTailPadSec: 0.08,
    },
  },
]

/**
 * v3 口播快剪：不经过「文案匹配」。流程为选视频 → 选模式 → 生成剪辑方案；时间轴微调与成片导出在下方 AutoEditPanel（与自动/模板一致）。
 */
export function VoiceoverQuickCutPanel({
  selectedVideoIds,
  doneVideos,
  onGenerate,
}: VoiceoverQuickCutPanelProps) {
  const overlapSwitchId = useId()
  const overlapLabelId = `${overlapSwitchId}-label`
  const [strategy, setStrategy] = useState<VoiceoverQuickCutStrategy>('asr_fast')
  const [semanticUserPrompt, setSemanticUserPrompt] = useState('')
  const [audioActivityConfig, setAudioActivityConfig] = useState<VoiceoverAudioActivityConfig>({
    activityDbThreshold: -36,
    activityMinSilenceSec: 0.25,
    activityMinKeepSec: 0.35,
    activityMergeGapSec: 0.2,
    activityHeadPadSec: 0.08,
    activityTailPadSec: 0.12,
  })
  const [audioPresetId, setAudioPresetId] = useState<VoiceoverAudioActivityPreset['id'] | 'custom'>('custom')
  /** 默认关闭：与后端一致，避免同一 clip 源时间重叠导致口播重复播放 */
  const [allowOverlappingSourceTimeline, setAllowOverlappingSourceTimeline] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [info, setInfo] = useState<string | null>(null)

  const selectedVideos = useMemo(() => {
    const set = new Set(selectedVideoIds)
    return doneVideos.filter((v) => set.has(v.id))
  }, [doneVideos, selectedVideoIds])

  const selectedCount = selectedVideoIds.length
  const selectedDoneCount = selectedVideos.length

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
        await onGenerate({
          videoIds,
          strategy,
          userPrompt,
          allowOverlappingSourceTimeline,
          audioActivityConfig: strategy === 'audio_activity_fast' ? audioActivityConfig : undefined,
        })
      } finally {
        setGenerating(false)
      }
      return
    }
    setInfo('请从父页面传入 onGenerate，以调用口播快剪接口。')
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
            当前选中视频 · {selectedCount} 个
          </p>
          {selectedCount === 0 ? (
            <p className="text-xs text-amber-400/90">未选择视频。</p>
          ) : selectedDoneCount === 0 ? (
            <p className="text-xs text-amber-400/90">你已选择 {selectedCount} 个，但它们尚未出现在已完成列表中。</p>
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

        <div className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 space-y-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <p id={overlapLabelId} className="text-xs font-medium text-slate-200">
                允许源时间轴重叠
              </p>
              <p className="text-[10px] text-slate-500 leading-relaxed">
                关闭（推荐）：同一视频素材下（含多个 clip）若成片段在源文件绝对时间上重叠，会按顺序裁掉已播区间，避免同一段画面/口播听两遍。仅在确有需要时开启。
              </p>
            </div>
            <Switch
              id={overlapSwitchId}
              aria-labelledby={overlapLabelId}
              checked={allowOverlappingSourceTimeline}
              onCheckedChange={setAllowOverlappingSourceTimeline}
              disabled={generating}
            />
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

        {strategy === 'audio_activity_fast' && (
          <div className="space-y-3 rounded-xl border border-violet-500/20 bg-slate-950/40 px-4 py-3">
            <p className="text-[11px] font-medium text-violet-200/95">
              音频粗剪参数（可微调）
            </p>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              该模式通过静音检测保留语音活动区间。阈值越高越容易判静音；头尾补偿用于避免切字。
            </p>
            <div className="space-y-1.5">
              <p className="text-[11px] text-slate-300">参数预设</p>
              <div className="grid gap-2 sm:grid-cols-3">
                {AUDIO_ACTIVITY_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => {
                      setAudioActivityConfig(preset.config)
                      setAudioPresetId(preset.id)
                    }}
                    className={`text-left rounded-lg border px-2.5 py-2 transition-colors ${
                      audioPresetId === preset.id
                        ? 'border-violet-500/70 bg-violet-500/15 text-violet-100'
                        : 'border-slate-700 bg-slate-900/40 text-slate-300 hover:border-slate-600'
                    }`}
                  >
                    <span className="block text-[11px] font-medium">{preset.label}</span>
                    <span className="mt-1 block text-[10px] text-slate-500 leading-snug">{preset.desc}</span>
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>静音阈值 dB</span>
                <input
                  type="number"
                  step={1}
                  min={-70}
                  max={-5}
                  value={audioActivityConfig.activityDbThreshold}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityDbThreshold: Number(e.target.value || -36),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>最短静音秒数</span>
                <input
                  type="number"
                  step={0.05}
                  min={0.05}
                  max={2}
                  value={audioActivityConfig.activityMinSilenceSec}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityMinSilenceSec: Number(e.target.value || 0.25),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>最短保留秒数</span>
                <input
                  type="number"
                  step={0.05}
                  min={0.1}
                  max={10}
                  value={audioActivityConfig.activityMinKeepSec}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityMinKeepSec: Number(e.target.value || 0.35),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>段间合并阈值秒</span>
                <input
                  type="number"
                  step={0.05}
                  min={0}
                  max={2}
                  value={audioActivityConfig.activityMergeGapSec}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityMergeGapSec: Number(e.target.value || 0.2),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>前置补偿秒</span>
                <input
                  type="number"
                  step={0.01}
                  min={0}
                  max={1}
                  value={audioActivityConfig.activityHeadPadSec}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityHeadPadSec: Number(e.target.value || 0.08),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <span>后置补偿秒</span>
                <input
                  type="number"
                  step={0.01}
                  min={0}
                  max={1}
                  value={audioActivityConfig.activityTailPadSec}
                  onChange={(e) =>
                    setAudioActivityConfig((prev) => {
                      setAudioPresetId('custom')
                      return {
                        ...prev,
                        activityTailPadSec: Number(e.target.value || 0.12),
                      }
                    })
                  }
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
            </div>
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
    </div>
  )
}
