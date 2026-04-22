'use client'

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { MessageSquare, Mic2, Pause, Play, Scissors, Sparkles, Video } from 'lucide-react'
import type { Video as VideoModel } from '@/lib/api'
import { Switch } from '@/components/ui/switch'
import { fmt, videoAudioStreamUrl } from './types'

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
  id: 'quiet_voiceover' | 'noisy_scene' | 'extreme_noisy' | 'tight_rhythm'
  label: string
  desc: string
  config: VoiceoverAudioActivityConfig
}

type ParamHelp = {
  title: string
  detail: string
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
    id: 'extreme_noisy',
    label: '极嘈杂环境',
    desc: '强噪声/底噪场景，严格过滤非语音',
    config: {
      activityDbThreshold: -28,
      activityMinSilenceSec: 0.35,
      activityMinKeepSec: 0.55,
      activityMergeGapSec: 0.1,
      activityHeadPadSec: 0.04,
      activityTailPadSec: 0.08,
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

function clampNum(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

function applyDenoiseStrength(
  cfg: VoiceoverAudioActivityConfig,
  strength: number,
): VoiceoverAudioActivityConfig {
  // 0~100：值越大越严格，适合更嘈杂场景
  const s = clampNum(strength, 0, 100) / 100
  return {
    activityDbThreshold: Math.round(clampNum(cfg.activityDbThreshold + s * 8, -70, -5)),
    activityMinSilenceSec: Number(clampNum(cfg.activityMinSilenceSec + s * 0.2, 0.05, 2).toFixed(2)),
    activityMinKeepSec: Number(clampNum(cfg.activityMinKeepSec + s * 0.3, 0.1, 10).toFixed(2)),
    activityMergeGapSec: Number(clampNum(cfg.activityMergeGapSec - s * 0.12, 0, 2).toFixed(2)),
    activityHeadPadSec: Number(clampNum(cfg.activityHeadPadSec - s * 0.05, 0, 1).toFixed(2)),
    activityTailPadSec: Number(clampNum(cfg.activityTailPadSec - s * 0.06, 0, 1).toFixed(2)),
  }
}

function dbToY(db: number, h: number): number {
  const t = (clampNum(db, -70, -5) + 70) / 65
  return h - t * h
}

function yToDb(y: number, h: number): number {
  const t = clampNum(1 - y / Math.max(1, h), 0, 1)
  return Math.round(-70 + t * 65)
}

const PARAM_HELP_TEXT: Record<
  'db' | 'minSilence' | 'minKeep' | 'mergeGap' | 'headPad' | 'tailPad',
  ParamHelp
> = {
  db: {
    title: '静音阈值 dB',
    detail: '判断“多小的声音算静音”。数值越接近 0（例如 -28），越容易把弱声音当静音，剪得更狠；数值更低（例如 -42）会保留更多细碎声音。',
  },
  minSilence: {
    title: '最短静音秒数',
    detail: '只有连续静音达到这个时长，才会被当作“可切分停顿”。调大可避免频繁切碎，调小会让切点更敏感。',
  },
  minKeep: {
    title: '最短保留秒数',
    detail: '短于该时长的语音片段会被丢弃。调大可过滤口癖/噪声碎片，调小会保留更多短促发音。',
  },
  mergeGap: {
    title: '段间合并阈值秒',
    detail: '两段语音中间停顿小于该值会合并成一段。调大更连贯，调小会切得更碎更紧凑。',
  },
  headPad: {
    title: '前置补偿秒',
    detail: '在每段起点前多留一点，避免吃掉开头字。调大更稳但可能带入杂音。',
  },
  tailPad: {
    title: '后置补偿秒',
    detail: '在每段终点后多留一点，避免吃掉尾音。调大更自然但可能拖尾。',
  },
}

function HelpLabel({ text, help }: { text: string; help: ParamHelp }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span>{text}</span>
      <span
        title={`${help.title}\n\n${help.detail}`}
        aria-label={`${help.title}说明：${help.detail}`}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-500/70 text-[10px] text-slate-300 cursor-help"
      >
        ?
      </span>
    </span>
  )
}

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
  const [denoiseStrength, setDenoiseStrength] = useState(0)
  const [previewDurationSec, setPreviewDurationSec] = useState(0)
  const [previewCurrentSec, setPreviewCurrentSec] = useState(0)
  const [previewPlaying, setPreviewPlaying] = useState(false)
  const [waveZoom, setWaveZoom] = useState(1)
  const [waveStartSec, setWaveStartSec] = useState(0)
  const [waveEnergy, setWaveEnergy] = useState<number[]>([])
  const [waveLoading, setWaveLoading] = useState(false)
  const [waveError, setWaveError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
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
  const previewVideoId = selectedVideos[0]?.id || ''
  const previewSrc = previewVideoId ? videoAudioStreamUrl(previewVideoId) : ''
  const effectiveAudioConfig = useMemo(
    () => applyDenoiseStrength(audioActivityConfig, denoiseStrength),
    [audioActivityConfig, denoiseStrength],
  )
  const visibleDurationSec = useMemo(() => {
    if (previewDurationSec <= 0) return 0
    return Math.max(8, previewDurationSec / Math.max(1, waveZoom))
  }, [previewDurationSec, waveZoom])
  const maxStartSec = useMemo(
    () => Math.max(0, previewDurationSec - visibleDurationSec),
    [previewDurationSec, visibleDurationSec],
  )

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
          audioActivityConfig: strategy === 'audio_activity_fast' ? effectiveAudioConfig : undefined,
        })
      } finally {
        setGenerating(false)
      }
      return
    }
    setInfo('请从父页面传入 onGenerate，以调用口播快剪接口。')
  }

  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    const onLoaded = () => setPreviewDurationSec(Number.isFinite(a.duration) ? a.duration : 0)
    const onTime = () => setPreviewCurrentSec(a.currentTime || 0)
    const onPlay = () => setPreviewPlaying(true)
    const onPause = () => setPreviewPlaying(false)
    const onEnded = () => setPreviewPlaying(false)
    a.addEventListener('loadedmetadata', onLoaded)
    a.addEventListener('timeupdate', onTime)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    a.addEventListener('ended', onEnded)
    return () => {
      a.removeEventListener('loadedmetadata', onLoaded)
      a.removeEventListener('timeupdate', onTime)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
      a.removeEventListener('ended', onEnded)
    }
  }, [previewSrc])

  useEffect(() => {
    let cancelled = false
    async function buildWave() {
      if (strategy !== 'audio_activity_fast' || !previewSrc) {
        setWaveEnergy([])
        return
      }
      setWaveLoading(true)
      setWaveError(null)
      try {
        const resp = await fetch(previewSrc)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const buf = await resp.arrayBuffer()
        const Ctx = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (!Ctx) throw new Error('当前浏览器不支持 AudioContext')
        const ctx = new Ctx()
        const audioBuf = await ctx.decodeAudioData(buf.slice(0))
        const ch0 = audioBuf.getChannelData(0)
        const sampleRate = audioBuf.sampleRate
        const frameSize = Math.max(128, Math.floor(sampleRate * 0.02))
        const out: number[] = []
        for (let i = 0; i < ch0.length; i += frameSize) {
          let sum = 0
          const end = Math.min(ch0.length, i + frameSize)
          for (let j = i; j < end; j += 1) sum += ch0[j] * ch0[j]
          const rms = Math.sqrt(sum / Math.max(1, end - i))
          out.push(clampNum(rms, 0, 1))
        }
        await ctx.close()
        if (!cancelled) setWaveEnergy(out)
      } catch (e) {
        if (!cancelled) setWaveError((e as Error)?.message || '波形解析失败')
      } finally {
        if (!cancelled) setWaveLoading(false)
      }
    }
    void buildWave()
    return () => {
      cancelled = true
    }
  }, [strategy, previewSrc])

  useEffect(() => {
    if (waveStartSec > maxStartSec) setWaveStartSec(maxStartSec)
  }, [maxStartSec, waveStartSec])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || strategy !== 'audio_activity_fast') return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const w = canvas.width
    const h = canvas.height
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#0b1020'
    ctx.fillRect(0, 0, w, h)
    if (!waveEnergy.length || previewDurationSec <= 0) return

    const frameSec = previewDurationSec / waveEnergy.length
    const viewEndSec = waveStartSec + visibleDurationSec
    const startIdx = Math.max(0, Math.floor(waveStartSec / frameSec))
    const endIdx = Math.min(waveEnergy.length, Math.ceil(viewEndSec / frameSec))

    ctx.strokeStyle = '#6d28d9'
    ctx.lineWidth = 1
    for (let i = startIdx; i < endIdx; i += 1) {
      const t = i * frameSec
      const x = ((t - waveStartSec) / visibleDurationSec) * w
      const amp = waveEnergy[i]
      const barH = Math.max(1, amp * (h - 20))
      const y1 = (h - barH) / 2
      ctx.beginPath()
      ctx.moveTo(x, y1)
      ctx.lineTo(x, y1 + barH)
      ctx.stroke()
    }

    const y = dbToY(effectiveAudioConfig.activityDbThreshold, h)
    ctx.strokeStyle = '#f59e0b'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(w, y)
    ctx.stroke()

    const playX = ((previewCurrentSec - waveStartSec) / visibleDurationSec) * w
    if (playX >= 0 && playX <= w) {
      ctx.strokeStyle = '#22d3ee'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(playX, 0)
      ctx.lineTo(playX, h)
      ctx.stroke()
    }
  }, [
    strategy,
    waveEnergy,
    previewDurationSec,
    waveStartSec,
    visibleDurationSec,
    effectiveAudioConfig.activityDbThreshold,
    previewCurrentSec,
  ])

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
            <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-300">
                <button
                  type="button"
                  disabled={!previewSrc}
                  onClick={() => {
                    const a = audioRef.current
                    if (!a) return
                    if (a.paused) {
                      void a.play().catch((e) => {
                        setWaveError((e as Error)?.message || '播放失败')
                      })
                    } else {
                      a.pause()
                    }
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 hover:border-violet-500/70 disabled:opacity-40"
                >
                  {previewPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                  {previewPlaying ? '暂停' : '播放'}
                </button>
                <span className="text-slate-400">
                  {fmt(previewCurrentSec)} / {fmt(previewDurationSec)}
                </span>
                <span className="text-slate-500">预览源：{selectedVideos[0]?.name || '未选择'}</span>
              </div>
              <audio
                ref={audioRef}
                src={previewSrc}
                preload="metadata"
                className="hidden"
                onLoadedMetadata={(e) => setPreviewDurationSec(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)}
                onTimeUpdate={(e) => setPreviewCurrentSec(e.currentTarget.currentTime || 0)}
                onPlay={() => setPreviewPlaying(true)}
                onPause={() => setPreviewPlaying(false)}
                onEnded={() => setPreviewPlaying(false)}
                onError={() => setWaveError('音频预览加载失败（请确认后端音频流可访问）')}
              />
              <canvas
                ref={canvasRef}
                width={900}
                height={140}
                onClick={(e) => {
                  if (!previewDurationSec) return
                  const rect = e.currentTarget.getBoundingClientRect()
                  const x = e.clientX - rect.left
                  const y = e.clientY - rect.top
                  const ratioX = clampNum(x / Math.max(1, rect.width), 0, 1)
                  const sec = waveStartSec + ratioX * visibleDurationSec
                  const nearThreshold = Math.abs(y - dbToY(effectiveAudioConfig.activityDbThreshold, rect.height)) <= 10
                  if (nearThreshold) {
                    const nextDb = yToDb(y, rect.height)
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({ ...effectiveAudioConfig, activityDbThreshold: nextDb })
                    return
                  }
                  const a = audioRef.current
                  if (!a) return
                  a.currentTime = clampNum(sec, 0, previewDurationSec)
                }}
                className="w-full h-[140px] rounded-md border border-slate-800 bg-[#0b1020] cursor-crosshair"
              />
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="text-[10px] text-slate-400 space-y-1">
                  <span>时间轴缩放</span>
                  <input
                    type="range"
                    min={1}
                    max={10}
                    step={1}
                    value={waveZoom}
                    onChange={(e) => setWaveZoom(Number(e.target.value || 1))}
                    className="w-full accent-violet-500"
                  />
                </label>
                <label className="text-[10px] text-slate-400 space-y-1">
                  <span>时间轴平移</span>
                  <input
                    type="range"
                    min={0}
                    max={Math.max(0, maxStartSec)}
                    step={0.01}
                    value={waveStartSec}
                    onChange={(e) => setWaveStartSec(Number(e.target.value || 0))}
                    className="w-full accent-violet-500"
                  />
                </label>
              </div>
              {waveLoading && <p className="text-[10px] text-slate-500">正在解析音频波形...</p>}
              {waveError && <p className="text-[10px] text-amber-300">波形预览失败：{waveError}</p>}
              <p className="text-[10px] text-slate-500">
                提示：点击波形可跳转播放位置；点击接近橙色阈值线的位置可快速设定静音阈值。
              </p>
            </div>
            <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-300">降噪强度（快速轴）</span>
                <span className="text-violet-300">{denoiseStrength}</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={denoiseStrength}
                onChange={(e) => setDenoiseStrength(Number(e.target.value || 0))}
                className="w-full accent-violet-500"
              />
              <p className="text-[10px] text-slate-500 leading-relaxed">
                越大越严格（更适合噪声大场景）：提高静音阈值/最短保留，降低段间合并与补偿。
              </p>
            </div>
            <div className="space-y-1.5">
              <p className="text-[11px] text-slate-300">参数预设</p>
              <div className="grid gap-2 sm:grid-cols-4">
                {AUDIO_ACTIVITY_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => {
                      setAudioActivityConfig(preset.config)
                      setAudioPresetId(preset.id)
                      setDenoiseStrength(0)
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
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 text-[10px] text-slate-400">
              生效参数：阈值 {effectiveAudioConfig.activityDbThreshold} dB / 最短静音 {effectiveAudioConfig.activityMinSilenceSec}s
              / 最短保留 {effectiveAudioConfig.activityMinKeepSec}s / 合并阈值 {effectiveAudioConfig.activityMergeGapSec}s
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="静音阈值 dB" help={PARAM_HELP_TEXT.db} />
                <input
                  type="number"
                  step={1}
                  min={-70}
                  max={-5}
                  value={effectiveAudioConfig.activityDbThreshold}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityDbThreshold: Number(e.target.value || -36),
                    })
                  }}
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="最短静音秒数" help={PARAM_HELP_TEXT.minSilence} />
                <input
                  type="number"
                  step={0.05}
                  min={0.05}
                  max={2}
                  value={effectiveAudioConfig.activityMinSilenceSec}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityMinSilenceSec: Number(e.target.value || 0.25),
                    })
                  }}
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="最短保留秒数" help={PARAM_HELP_TEXT.minKeep} />
                <input
                  type="number"
                  step={0.05}
                  min={0.1}
                  max={10}
                  value={effectiveAudioConfig.activityMinKeepSec}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityMinKeepSec: Number(e.target.value || 0.35),
                    })
                  }}
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="段间合并阈值秒" help={PARAM_HELP_TEXT.mergeGap} />
                <input
                  type="number"
                  step={0.05}
                  min={0}
                  max={2}
                  value={effectiveAudioConfig.activityMergeGapSec}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityMergeGapSec: Number(e.target.value || 0.2),
                    })
                  }}
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="前置补偿秒" help={PARAM_HELP_TEXT.headPad} />
                <input
                  type="number"
                  step={0.01}
                  min={0}
                  max={1}
                  value={effectiveAudioConfig.activityHeadPadSec}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityHeadPadSec: Number(e.target.value || 0.08),
                    })
                  }}
                  className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                />
              </label>
              <label className="text-[11px] text-slate-300 space-y-1">
                <HelpLabel text="后置补偿秒" help={PARAM_HELP_TEXT.tailPad} />
                <input
                  type="number"
                  step={0.01}
                  min={0}
                  max={1}
                  value={effectiveAudioConfig.activityTailPadSec}
                  onChange={(e) => {
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({
                      ...effectiveAudioConfig,
                      activityTailPadSec: Number(e.target.value || 0.12),
                    })
                  }}
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
