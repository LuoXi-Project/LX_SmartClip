'use client'

import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { MessageSquare, Mic2, Pause, Play, Scissors, Sparkles, Video } from 'lucide-react'
import type { Video as VideoModel } from '@/lib/api'
import { Switch } from '@/components/ui/switch'
import { VoiceInputControl } from '@/components/ui/voice-input'
import { clipsApi, type AutoEditSegmentPlanApi, type TtsVideoAlignConfigApi, type TtsVideoAlignPolicyApi } from '@/lib/api'
import { fmt, videoAudioStreamUrl } from './types'

export type VoiceoverQuickCutStrategy = 'asr_fast' | 'standard' | 'semantic' | 'audio_activity_fast'

export type VoiceoverAudioActivityConfig = {
  activityDbThreshold: number
  activityMinSilenceSec: number
  activityMinKeepSec: number
  activityMergeGapSec: number
  activityHeadPadSec: number
  activityTailPadSec: number
  activityKeepRanges?: Array<{ video_id: string; start: number; end: number }>
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
      targetDurationSec?: number
      allowOverlappingSourceTimeline?: boolean
      audioActivityConfig?: VoiceoverAudioActivityConfig
      asrHeadPadSec?: number
      asrTailPadSec?: number
    }
  ) => void | Promise<void>
  /** 成片使用系统 TTS 按 ASR 重新配音 */
  redubEnabled?: boolean
  onRedubEnabledChange?: (v: boolean) => void
  ttsAlign?: TtsVideoAlignConfigApi
  onTtsAlignChange?: (patch: Partial<TtsVideoAlignConfigApi>) => void
  /** 已生成的口播快剪方案片段，用于在频谱上叠加显示“选中保留段” */
  generatedPlanSegments?: AutoEditSegmentPlanApi[]
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
    desc: '句子评分筛选，自动过滤口癖和低密度片段',
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

function hzToY(hz: number, h: number): number {
  const minHz = 50
  const maxHz = 350
  const v = clampNum(hz, minHz, maxHz)
  const t = (v - minHz) / (maxHz - minHz)
  return h - t * h
}

function yToHz(y: number, h: number): number {
  const minHz = 50
  const maxHz = 350
  const t = clampNum(1 - y / Math.max(1, h), 0, 1)
  return Math.round(minHz + t * (maxHz - minHz))
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

const ASR_PAD_HELP: Record<'head' | 'tail', ParamHelp> = {
  head: {
    title: '句头多保留秒',
    detail: '在每条 ASR 句子的起点前多保留 n 秒，保留说话间隙、避免切掉开头字。默认 0=严格按句子起点。',
  },
  tail: {
    title: '句尾多保留秒',
    detail: '在每条 ASR 句子的终点后多保留 n 秒，保留说话间隙、避免切掉尾音。默认 0=严格按句子终点。',
  },
}

function HelpLabel({ text, help }: { text: string; help: ParamHelp }) {  return (
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
const TTS_ALIGN_OPTIONS: { id: TtsVideoAlignPolicyApi; label: string; hint: string }[] = [
  {
    id: 'freeze_last_frame',
    label: '不循环素材，末尾定格',
    hint: '画面正常播完后停在最后一帧，直到配音结束（口型可能提前结束）。',
  },
  {
    id: 'loop_video_to_cover',
    label: '循环拼接所选画面',
    hint: '与旧版 TTS 成片类似：重复拼接本段素材直至盖住整段配音。',
  },
  {
    id: 'stretch_audio',
    label: '变速配音贴画面',
    hint: '通过加速/减速 TTS，使口播时长接近所选画面长度；超出限制时仍会定格补偿。',
  },
  {
    id: 'stretch_video',
    label: '变速画面贴配音',
    hint: '通过快放/慢放画面，使视频时长接近 TTS；超出限制时尾部定格补齐。',
  },
]

export function VoiceoverQuickCutPanel({
  selectedVideoIds,
  doneVideos,
  onGenerate,
  generatedPlanSegments,
  redubEnabled = false,
  onRedubEnabledChange,
  ttsAlign,
  onTtsAlignChange,
}: VoiceoverQuickCutPanelProps) {
  const overlapSwitchId = useId()
  const overlapLabelId = `${overlapSwitchId}-label`
  const [strategy, setStrategy] = useState<VoiceoverQuickCutStrategy>('standard')
  const [semanticUserPrompt, setSemanticUserPrompt] = useState('')
  /** 成片目标时长（秒），标准/智能快剪生效；留空则后端从提示词解析 */
  const [semanticTargetDurationSec, setSemanticTargetDurationSec] = useState('')
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
  /** 口播快剪（asr_fast/standard/semantic）句头/句尾补偿秒，用于保留说话间隙 */
  const [asrHeadPadSec, setAsrHeadPadSec] = useState(0)
  const [asrTailPadSec, setAsrTailPadSec] = useState(0)
  const [asrSentenceBlocks, setAsrSentenceBlocks] = useState<
    Array<{ absStart: number; absEnd: number; text: string }>
  >([])
  const [asrBlocksLoading, setAsrBlocksLoading] = useState(false)
  const [asrBlocksError, setAsrBlocksError] = useState<string | null>(null)
  /** canvas 的 CSS 像素宽度（用于 HiDPI 自适应 backing store，避免文字因位图缩放发糊） */
  const [canvasCssWidth, setCanvasCssWidth] = useState(900)
  const canvasCssHeight = 140
  const [previewDurationSec, setPreviewDurationSec] = useState(0)
  const [previewCurrentSec, setPreviewCurrentSec] = useState(0)
  const [previewPlaying, setPreviewPlaying] = useState(false)
  const [waveZoom, setWaveZoom] = useState(1)
  const [waveStartSec, setWaveStartSec] = useState(0)
  const [waveEnergy, setWaveEnergy] = useState<number[]>([])
  const [waveLoading, setWaveLoading] = useState(false)
  const [waveError, setWaveError] = useState<string | null>(null)
  const [pitchHz, setPitchHz] = useState<number[]>([])
  const [pitchLoading, setPitchLoading] = useState(false)
  const [pitchError, setPitchError] = useState<string | null>(null)
  const [pitchThresholdHz, setPitchThresholdHz] = useState(120)
  const [pitchGateEnabled, setPitchGateEnabled] = useState(true)
  const [loopEnabled, setLoopEnabled] = useState(false)
  const [loopRange, setLoopRange] = useState<{ a: number; b: number } | null>(null)
  const [selecting, setSelecting] = useState(false)
  const [selectionPx, setSelectionPx] = useState<{ x1: number; x2: number } | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dragRef = useRef<
    | { mode: 'db_threshold'; pointerId: number }
    | { mode: 'pitch_threshold'; pointerId: number }
    | { mode: 'select'; pointerId: number; x0: number }
    | null
  >(null)
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
  const selectedNotReadyCount = useMemo(
    () => selectedVideos.filter((v) => v.status !== 'done').length,
    [selectedVideos],
  )
  const selectedUnprocessedCount = useMemo(
    () => selectedVideos.filter((v) => v.status === 'done' && Number(v.total_clips || 0) <= 0).length,
    [selectedVideos],
  )
  const previewVideoId = selectedVideos[0]?.id || ''
  const previewSrc = previewVideoId ? videoAudioStreamUrl(previewVideoId) : ''
  const isAsrStrategy = strategy === 'asr_fast' || strategy === 'standard' || strategy === 'semantic'
  const isAudioActivityStrategy = strategy === 'audio_activity_fast'
  /** 波形预览在“音频粗剪”和“ASR 口播剪”下都需要；其中 ASR 口播剪用于叠加查看分段 */
  const showWaveform = isAudioActivityStrategy || isAsrStrategy
  const effectiveAudioConfig = useMemo(
    () => applyDenoiseStrength(audioActivityConfig, denoiseStrength),
    [audioActivityConfig, denoiseStrength],
  )

  const pitchKeepRanges = useMemo(() => {
    if (!pitchGateEnabled || !pitchHz.length || !previewDurationSec || !previewVideoId) return null
    const frameSec = previewDurationSec / pitchHz.length
    const minKeep = Math.max(0.2, effectiveAudioConfig.activityMinKeepSec || 0.35)
    const gap = Math.max(0, effectiveAudioConfig.activityMergeGapSec || 0.2)
    const headPad = Math.max(0, effectiveAudioConfig.activityHeadPadSec || 0)
    const tailPad = Math.max(0, effectiveAudioConfig.activityTailPadSec || 0)
    const ranges: Array<{ video_id: string; start: number; end: number }> = []

    // 1) 先做轻量平滑（中值窗），降低逐帧抖动导致的“看着过线但判不到连续段”
    const median = (arr: number[]) => {
      const a = [...arr].sort((x, y) => x - y)
      return a[Math.floor(a.length / 2)] || 0
    }
    const smooth: number[] = new Array(pitchHz.length).fill(0)
    for (let i = 0; i < pitchHz.length; i += 1) {
      const win: number[] = []
      for (let k = -2; k <= 2; k += 1) {
        const j = i + k
        if (j >= 0 && j < pitchHz.length) {
          const v = pitchHz[j] || 0
          if (v > 0) win.push(v)
        }
      }
      smooth[i] = win.length ? median(win) : 0
    }

    // 2) 音高校验使用双阈值（迟滞）：进入高阈值，保持低阈值，避免边缘抖动
    const onThr = pitchThresholdHz
    const offThr = Math.max(50, pitchThresholdHz * 0.85)
    // 允许短缺口（无音高/跌破）桥接，避免把一句话切碎
    const bridgeSec = 0.12
    const maxGapFrames = Math.max(1, Math.round(bridgeSec / Math.max(0.001, frameSec)))

    let inSeg = false
    let segStart = 0
    let silentRun = 0
    for (let i = 0; i < smooth.length; i += 1) {
      const hz = smooth[i] || 0
      const t = i * frameSec
      const voicedNow = hz > 0 && (inSeg ? hz >= offThr : hz >= onThr)

      if (voicedNow) {
        if (!inSeg) {
          inSeg = true
          segStart = t
        }
        silentRun = 0
        continue
      }

      if (!inSeg) continue
      silentRun += 1
      if (silentRun <= maxGapFrames) {
        continue
      }
      const segEnd = Math.max(segStart, t - silentRun * frameSec)
      inSeg = false
      silentRun = 0
      if (segEnd - segStart >= minKeep) {
        ranges.push({
          video_id: previewVideoId,
          start: Math.max(0, segStart - headPad),
          end: Math.min(previewDurationSec, segEnd + tailPad),
        })
      }
    }
    if (inSeg) {
      const segEnd = previewDurationSec
      if (segEnd - segStart >= minKeep) {
        ranges.push({
          video_id: previewVideoId,
          start: Math.max(0, segStart - headPad),
          end: Math.min(previewDurationSec, segEnd + tailPad),
        })
      }
    }
    // merge small gaps
    ranges.sort((a, b) => a.start - b.start)
    const merged: typeof ranges = []
    for (const r of ranges) {
      const last = merged[merged.length - 1]
      if (last && r.start <= last.end + gap) {
        last.end = Math.max(last.end, r.end)
      } else {
        merged.push({ ...r })
      }
    }
    return merged
  }, [
    pitchGateEnabled,
    pitchHz,
    previewDurationSec,
    previewVideoId,
    pitchThresholdHz,
    effectiveAudioConfig.activityMinKeepSec,
    effectiveAudioConfig.activityMergeGapSec,
    effectiveAudioConfig.activityHeadPadSec,
    effectiveAudioConfig.activityTailPadSec,
  ])
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
      setInfo('请先在上方勾选至少一个视频。')
      return
    }
    if (strategy !== 'audio_activity_fast') {
      const needPreprocessed = selectedVideos.filter(
        (v) => v.status !== 'done' || Number(v.total_clips || 0) <= 0,
      )
      if (needPreprocessed.length > 0) {
        setInfo('极速/智能快剪依赖预处理片段（ASR/clip）。请先处理视频，或切换到「音频粗剪」直接按原音频检测。')
        return
      }
    }
    if (strategy === 'audio_activity_fast' && pitchGateEnabled) {
      if (pitchLoading) {
        setInfo('音高轨仍在解析中，请稍等 1~3 秒后再生成。')
        return
      }
      if (pitchError) {
        setInfo(`音高轨解析失败：${pitchError}（可先关闭音高门控再生成，或刷新重试）`)
        return
      }
      if (!pitchHz.length) {
        setInfo('音高轨为空：当前无法按音高门控生成（可先关闭音高门控再生成）。')
        return
      }
      if (pitchKeepRanges && pitchKeepRanges.length === 0) {
        // 允许“明确生成空方案”——这是用户主动调参得到的合法结果。
        // 保持提示但不阻塞，继续向后端提交 activity_keep_ranges=[]
        setInfo('当前音高阈值过高：按门控将不会保留任何片段。将继续生成空方案。')
      }
    }
    if (strategy === 'semantic') {
      const p = semanticUserPrompt.trim()
      if (!p) {
        setInfo('智能快剪需要填写提示词，说明你想保留或突出的内容（如：只要讲产品卖点的部分、删掉废话和重复）。')
        return
      }
    }
    const userPrompt = strategy === 'semantic' || strategy === 'standard'
      ? semanticUserPrompt.trim() || undefined
      : undefined
    let targetDurationSec: number | undefined
    if ((strategy === 'semantic' || strategy === 'standard') && semanticTargetDurationSec.trim()) {
      const n = Number(semanticTargetDurationSec.trim())
      if (Number.isFinite(n) && n >= 5 && n <= 7200) {
        targetDurationSec = n
      }
    }
    if (onGenerate) {
      setGenerating(true)
      try {
        await onGenerate({
          videoIds,
          strategy,
          userPrompt,
          targetDurationSec,
          allowOverlappingSourceTimeline,
          audioActivityConfig:
            strategy === 'audio_activity_fast'
              ? {
                  ...effectiveAudioConfig,
                  // 只要开启音高门控，就始终显式下发 keep_ranges（即使为空 []），
                  // 方便在 Network 面板验证，并避免“字段被省略看起来没生效”。
                  activityKeepRanges: pitchGateEnabled ? (pitchKeepRanges ?? []) : undefined,
                }
              : undefined,
          asrHeadPadSec: isAsrStrategy ? asrHeadPadSec : undefined,
          asrTailPadSec: isAsrStrategy ? asrTailPadSec : undefined,
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
    const a = audioRef.current
    if (!a) return
    if (!loopEnabled || !loopRange) return
    const onTime = () => {
      const t = a.currentTime || 0
      if (t >= loopRange.b - 0.02) {
        a.currentTime = loopRange.a
      }
    }
    a.addEventListener('timeupdate', onTime)
    return () => a.removeEventListener('timeupdate', onTime)
  }, [loopEnabled, loopRange])

  useEffect(() => {
    let cancelled = false
    async function buildWave() {
      if (!showWaveform || !previewSrc) {
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
  }, [showWaveform, previewSrc])

  useEffect(() => {
    let cancelled = false
    async function buildPitch() {
      if (strategy !== 'audio_activity_fast' || !previewSrc) {
        setPitchHz([])
        return
      }
      setPitchLoading(true)
      setPitchError(null)
      try {
        const resp = await fetch(previewSrc)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const buf = await resp.arrayBuffer()
        const Ctx =
          window.AudioContext ||
          (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (!Ctx) throw new Error('当前浏览器不支持 AudioContext')
        const ctx = new Ctx()
        const audioBuf = await ctx.decodeAudioData(buf.slice(0))
        const data = audioBuf.getChannelData(0)
        const sr = audioBuf.sampleRate
        const hop = Math.max(128, Math.floor(sr * 0.02))
        const minHz = 70
        const maxHz = 320
        const minLag = Math.floor(sr / maxHz)
        const maxLag = Math.floor(sr / minHz)
        const out: number[] = []

        for (let i = 0; i + maxLag < data.length; i += hop) {
          // 能量过低直接判无音高
          let sum = 0
          const end = Math.min(data.length, i + hop)
          for (let j = i; j < end; j += 1) sum += data[j] * data[j]
          const rms = Math.sqrt(sum / Math.max(1, end - i))
          if (rms < 0.01) {
            out.push(0)
            continue
          }
          let bestLag = 0
          let best = 0
          for (let lag = minLag; lag <= maxLag; lag += 1) {
            let c = 0
            for (let j = 0; j < hop; j += 1) c += data[i + j] * data[i + j + lag]
            if (c > best) {
              best = c
              bestLag = lag
            }
          }
          const hz = bestLag > 0 ? sr / bestLag : 0
          out.push(hz >= minHz && hz <= maxHz ? hz : 0)
        }
        await ctx.close()
        if (!cancelled) setPitchHz(out)
      } catch (e) {
        if (!cancelled) setPitchError((e as Error)?.message || '音高解析失败')
      } finally {
        if (!cancelled) setPitchLoading(false)
      }
    }
    void buildPitch()
    return () => {
      cancelled = true
    }
  }, [strategy, previewSrc])

  // ASR 口播剪：拉取当前预览视频的 clips（含 asr_segments），解析为绝对时间句子块，用于频谱分段标注
  useEffect(() => {
    let cancelled = false
    async function loadAsrBlocks() {
      if (!isAsrStrategy || !previewVideoId) {
        setAsrSentenceBlocks([])
        setAsrBlocksError(null)
        return
      }
      setAsrBlocksLoading(true)
      setAsrBlocksError(null)
      try {
        const clips = await clipsApi.listByVideo(previewVideoId)
        const blocks: Array<{ absStart: number; absEnd: number; text: string }> = []
        for (const c of clips) {
          const base = Number(c.start_time || 0)
          let segs: Array<{ start: number; end: number; text?: string }> = []
          if (c.asr_segments) {
            try {
              const parsed = JSON.parse(c.asr_segments)
              if (Array.isArray(parsed)) segs = parsed
            } catch {}
          }
          for (const s of segs) {
            const st = Number(s.start ?? 0)
            const et = Number(s.end ?? st)
            const txt = (s.text || '').trim()
            if (et <= st || !txt) continue
            blocks.push({ absStart: base + st, absEnd: base + et, text: txt })
          }
        }
        if (!cancelled) setAsrSentenceBlocks(blocks)
      } catch (e) {
        if (!cancelled) setAsrBlocksError((e as Error)?.message || 'ASR 句子加载失败')
      } finally {
        if (!cancelled) setAsrBlocksLoading(false)
      }
    }
    void loadAsrBlocks()
    return () => {
      cancelled = true
    }
  }, [isAsrStrategy, previewVideoId])

  useEffect(() => {
    if (waveStartSec > maxStartSec) setWaveStartSec(maxStartSec)
  }, [maxStartSec, waveStartSec])

  // 监听 canvas 容器实际 CSS 宽度，用于 HiDPI 自适应 backing store 尺寸
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const update = () => {
      const rect = canvas.getBoundingClientRect()
      if (rect.width > 0) setCanvasCssWidth(Math.round(rect.width))
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(canvas)
    return () => ro.disconnect()
  }, [showWaveform])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !showWaveform) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    // HiDPI 自适应：backing store 按 CSS 像素 × 设备像素比设置，避免位图缩放导致文字发糊
    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2))
    const cssW = canvasCssWidth
    const cssH = canvasCssHeight
    if (canvas.width !== Math.round(cssW * dpr)) canvas.width = Math.round(cssW * dpr)
    if (canvas.height !== Math.round(cssH * dpr)) canvas.height = Math.round(cssH * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    // 后续全部按 CSS 像素绘制（w=cssW, h=cssH）
    const w = cssW
    const h = cssH
    ctx.clearRect(0, 0, w, h)
    ctx.fillStyle = '#0b1020'
    ctx.fillRect(0, 0, w, h)
    if (!waveEnergy.length || previewDurationSec <= 0) return

    // Split lanes: top = pitch, bottom = waveform (and A/B selection)
    // ASR 口播剪模式不使用音高/dB 门控，整幅 canvas 都给波形与分段标注
    const gap = 6
    const pitchH = isAudioActivityStrategy ? Math.round(h * 0.42) : 0
    const waveTop = pitchH + (pitchH > 0 ? gap : 0)
    const waveH = h - waveTop

    const frameSec = previewDurationSec / waveEnergy.length
    const viewEndSec = waveStartSec + visibleDurationSec
    const startIdx = Math.max(0, Math.floor(waveStartSec / frameSec))
    const endIdx = Math.min(waveEnergy.length, Math.ceil(viewEndSec / frameSec))

    // waveform lane background
    ctx.fillStyle = 'rgba(15, 23, 42, 0.55)'
    ctx.fillRect(0, waveTop, w, waveH)
    ctx.strokeStyle = 'rgba(167, 139, 250, 0.75)'
    ctx.lineWidth = 1
    for (let i = startIdx; i < endIdx; i += 1) {
      const t = i * frameSec
      const x = ((t - waveStartSec) / visibleDurationSec) * w
      const amp = waveEnergy[i]
      const barH = Math.max(1, amp * (waveH - 10))
      const y1 = waveTop + (waveH - barH) / 2
      ctx.beginPath()
      ctx.moveTo(x, y1)
      ctx.lineTo(x, y1 + barH)
      ctx.stroke()
    }

    // pitch curve (Hz) - cyan（仅音频粗剪模式）
    if (isAudioActivityStrategy && pitchHz.length) {
      // pitch lane background
      ctx.fillStyle = 'rgba(2, 6, 23, 0.35)'
      ctx.fillRect(0, 0, w, pitchH)
      const pitchFrameSec = previewDurationSec / pitchHz.length
      const pStart = Math.max(0, Math.floor(waveStartSec / pitchFrameSec))
      const pEnd = Math.min(pitchHz.length, Math.ceil((waveStartSec + visibleDurationSec) / pitchFrameSec))
      // Downsample to ~1px per step to avoid "filled with lines"
      const step = Math.max(1, Math.floor((pEnd - pStart) / Math.max(1, w)))
      ctx.strokeStyle = 'rgba(34, 211, 238, 0.95)'
      ctx.lineWidth = 1.4
      ctx.beginPath()
      let started = false
      for (let i = pStart; i < pEnd; i += step) {
        const hz = pitchHz[i] || 0
        if (hz <= 0) continue
        const t = i * pitchFrameSec
        const x = ((t - waveStartSec) / visibleDurationSec) * w
        const y = hzToY(hz, pitchH)
        if (!started) {
          ctx.moveTo(x, y)
          started = true
        } else {
          ctx.lineTo(x, y)
        }
      }
      if (started) ctx.stroke()

      // pitch threshold line
      const py = hzToY(pitchThresholdHz, pitchH)
      ctx.strokeStyle = 'rgba(34, 211, 238, 0.65)'
      ctx.setLineDash([6, 5])
      ctx.beginPath()
      ctx.moveTo(0, py)
      ctx.lineTo(w, py)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = 'rgba(34, 211, 238, 0.9)'
      ctx.font = '500 10px ui-sans-serif, system-ui, -apple-system, sans-serif'
      ctx.textBaseline = 'top'
      ctx.textAlign = 'left'
      ctx.fillText(`${pitchThresholdHz} Hz`, 8, Math.max(4, py - 14))
    }

    // selection / loop overlay
    const drawSelection = (aSec: number, bSec: number) => {
      const xa = ((aSec - waveStartSec) / visibleDurationSec) * w
      const xb = ((bSec - waveStartSec) / visibleDurationSec) * w
      const left = clampNum(Math.min(xa, xb), 0, w)
      const right = clampNum(Math.max(xa, xb), 0, w)
      if (right - left < 2) return
      ctx.fillStyle = 'rgba(16, 185, 129, 0.10)'
      ctx.fillRect(left, waveTop, right - left, waveH)
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.75)'
      ctx.lineWidth = 1
      ctx.strokeRect(left + 0.5, waveTop + 0.5, right - left - 1, waveH - 1)
      ctx.fillStyle = 'rgba(16, 185, 129, 0.9)'
      ctx.font = '600 10px ui-sans-serif, system-ui, -apple-system, sans-serif'
      ctx.textBaseline = 'top'
      ctx.textAlign = 'left'
      ctx.fillText('A', left + 5, waveTop + 4)
      ctx.fillText('B', Math.max(left + 16, right - 11), waveTop + 4)
    }
    if (selectionPx) {
      const x1 = clampNum(selectionPx.x1, 0, w)
      const x2 = clampNum(selectionPx.x2, 0, w)
      const left = Math.min(x1, x2)
      const right = Math.max(x1, x2)
      ctx.fillStyle = 'rgba(16, 185, 129, 0.08)'
      ctx.fillRect(left, waveTop, right - left, waveH)
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.55)'
      ctx.lineWidth = 1
      ctx.strokeRect(left + 0.5, waveTop + 0.5, Math.max(0, right - left - 1), waveH - 1)
    } else if (loopRange && loopRange.b > loopRange.a) {
      drawSelection(loopRange.a, loopRange.b)
    }

    // dB 阈值线（仅音频粗剪模式）
    if (isAudioActivityStrategy) {
      const y = waveTop + dbToY(effectiveAudioConfig.activityDbThreshold, waveH)
      ctx.strokeStyle = '#f59e0b'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(w, y)
      ctx.stroke()
      ctx.fillStyle = 'rgba(245, 158, 11, 0.9)'
      ctx.font = '500 10px ui-sans-serif, system-ui, -apple-system, sans-serif'
      ctx.textBaseline = 'top'
      ctx.textAlign = 'left'
      ctx.fillText(`${effectiveAudioConfig.activityDbThreshold} dB`, 8, Math.max(waveTop + 4, y - 14))
    }

    // ASR 口播剪：叠加句子分段 + 已生成方案选中段高亮
    if (isAsrStrategy) {
      // 1) 已生成方案的选中段（高亮），先画在底层，句子块覆盖之上
      if (generatedPlanSegments && generatedPlanSegments.length) {
        for (const seg of generatedPlanSegments) {
          if (seg.exclude_from_output) continue
          // 仅渲染当前预览视频的段
          if (previewVideoId && seg.clip_group && !seg.clip_group.some((g) => g.video_id === previewVideoId)) continue
          const xa = ((seg.start_time_sec - waveStartSec) / visibleDurationSec) * w
          const xb = ((seg.end_time_sec - waveStartSec) / visibleDurationSec) * w
          const left = clampNum(Math.min(xa, xb), 0, w)
          const right = clampNum(Math.max(xa, xb), 0, w)
          if (right - left < 1) continue
          ctx.fillStyle = 'rgba(16, 185, 129, 0.16)'
          ctx.fillRect(left, waveTop, right - left, waveH)
          ctx.strokeStyle = 'rgba(16, 185, 129, 0.9)'
          ctx.lineWidth = 1.2
          ctx.strokeRect(left + 0.5, waveTop + 0.5, right - left - 1, waveH - 1)
        }
      }
      // 2) ASR 句子分段块（暗色）+ 首字文本
      ctx.font = '500 9px ui-sans-serif, system-ui, -apple-system, sans-serif'
      ctx.textBaseline = 'top'
      ctx.textAlign = 'left'
      for (const blk of asrSentenceBlocks) {
        if (blk.absEnd < waveStartSec || blk.absStart > waveStartSec + visibleDurationSec) continue
        const xa = ((blk.absStart - waveStartSec) / visibleDurationSec) * w
        const xb = ((blk.absEnd - waveStartSec) / visibleDurationSec) * w
        const left = clampNum(Math.min(xa, xb), 0, w)
        const right = clampNum(Math.max(xa, xb), 0, w)
        if (right - left < 1) continue
        // 句子边界细线
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)'
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(Math.round(left) + 0.5, waveTop)
        ctx.lineTo(Math.round(left) + 0.5, waveTop + waveH)
        ctx.stroke()
        // 文本（截断），画在波形上方
        const head = blk.text.slice(0, 7)
        if (right - left >= 12) {
          // 裁剪到句子块宽度内，避免长文本溢出到相邻块
          ctx.save()
          ctx.beginPath()
          ctx.rect(left + 2, waveTop, right - left - 3, 12)
          ctx.clip()
          ctx.fillStyle = 'rgba(226, 232, 240, 0.92)'
          ctx.fillText(head, left + 2, waveTop + 2)
          ctx.restore()
        }
      }
    }

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
    showWaveform,
    isAudioActivityStrategy,
    isAsrStrategy,
    canvasCssWidth,
    waveEnergy,
    previewDurationSec,
    waveStartSec,
    visibleDurationSec,
    effectiveAudioConfig.activityDbThreshold,
    previewCurrentSec,
    previewVideoId,
    loopRange,
    selectionPx,
    pitchHz,
    pitchThresholdHz,
    asrSentenceBlocks,
    generatedPlanSegments,
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
            <p className="text-xs text-amber-400/90">你已选择 {selectedCount} 个，但当前不可用于口播快剪。</p>
          ) : (
            <ul className="text-xs text-slate-400 space-y-1 max-h-28 overflow-y-auto">
              {selectedVideos.map((v) => (
                <li key={v.id} className="truncate">
                  · {v.name || v.id}{' '}
                  <span className="text-slate-500">
                    {v.status === 'done'
                      ? Number(v.total_clips || 0) > 0
                        ? `（${v.total_clips}片）`
                        : '（未预处理）'
                      : v.status === 'processing'
                        ? '（处理中）'
                        : v.status === 'pending'
                          ? '（待处理）'
                          : '（状态异常）'}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {selectedCount > 0 && (selectedNotReadyCount > 0 || selectedUnprocessedCount > 0) && (
            <p className="text-[10px] text-amber-300/90 leading-relaxed">
              当前选中包含 {selectedNotReadyCount} 个未完成、{selectedUnprocessedCount} 个未预处理视频。
              「极速快剪/智能快剪」需先完成预处理；「音频粗剪」可直接使用。
            </p>
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

        <div className="rounded-xl border border-cyan-500/25 bg-slate-950/35 px-4 py-3 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-1">
              <p className="text-xs font-medium text-slate-200">重新配音成片</p>
              <p className="text-[10px] text-slate-500 leading-relaxed">
                导出时使用系统 TTS 朗读各段的 ASR 文案（需在下方成片卡片点击导出）。无 ASR 的段落（例如「音频粗剪」占位）不满足条件。
              </p>
            </div>
            <Switch
              checked={redubEnabled}
              onCheckedChange={(v) => onRedubEnabledChange?.(v)}
              disabled={generating}
            />
          </div>
          {redubEnabled && ttsAlign && onTtsAlignChange && (
            <>
              <div className="space-y-1">
                <label className="text-[11px] text-slate-400">画面时长 ≠ 配音时长时</label>
                <select
                  value={ttsAlign.policy}
                  onChange={(e) =>
                    onTtsAlignChange({ policy: e.target.value as TtsVideoAlignPolicyApi })
                  }
                  className="w-full rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-2 outline-none focus:border-cyan-500/50"
                >
                  {TTS_ALIGN_OPTIONS.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <p className="text-[10px] text-slate-500 leading-relaxed">
                  {TTS_ALIGN_OPTIONS.find((o) => o.id === ttsAlign.policy)?.hint}
                </p>
              </div>
              {strategy === 'audio_activity_fast' && (
                <p className="text-[10px] text-amber-400/90 leading-relaxed">
                  当前模式多为非 ASR 占位文案，重新配音通常会失败；请改用极速/智能快剪并确保已识别字幕。
                </p>
              )}
              <details className="group text-[11px]">
                <summary className="cursor-pointer text-cyan-300/90 select-none list-none flex items-center gap-1">
                  <span className="opacity-70 group-open:rotate-90 transition-transform">▸</span>
                  变速范围（可选）
                </summary>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
                    配音最快倍数
                    <input
                      type="number"
                      step={0.1}
                      min={1}
                      max={4}
                      value={ttsAlign.max_audio_atempo ?? 2}
                      onChange={(e) =>
                        onTtsAlignChange({ max_audio_atempo: Number(e.target.value) || 2 })
                      }
                      className="rounded-md bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-1"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
                    配音最慢倍数
                    <input
                      type="number"
                      step={0.05}
                      min={0.25}
                      max={1}
                      value={ttsAlign.min_audio_atempo ?? 0.5}
                      onChange={(e) =>
                        onTtsAlignChange({ min_audio_atempo: Number(e.target.value) || 0.5 })
                      }
                      className="rounded-md bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-1"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
                    画面最慢相对倍数
                    <input
                      type="number"
                      step={0.1}
                      min={1}
                      max={4}
                      value={ttsAlign.max_video_pts_factor ?? 2}
                      onChange={(e) =>
                        onTtsAlignChange({ max_video_pts_factor: Number(e.target.value) || 2 })
                      }
                      className="rounded-md bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-1"
                    />
                  </label>
                  <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
                    画面最快相对倍数
                    <input
                      type="number"
                      step={0.05}
                      min={0.25}
                      max={1}
                      value={ttsAlign.min_video_pts_factor ?? 0.5}
                      onChange={(e) =>
                        onTtsAlignChange({ min_video_pts_factor: Number(e.target.value) || 0.5 })
                      }
                      className="rounded-md bg-slate-900 border border-slate-700 text-xs text-slate-200 px-2 py-1"
                    />
                  </label>
                </div>
                <p className="mt-1 text-[10px] text-slate-600 leading-relaxed">
                  配音倍数对应 ffmpeg atempo；画面倍数对应时间轴拉伸系数上下限。仅在所选对齐策略需要变速时生效。
                </p>
              </details>
            </>
          )}
        </div>

        {(strategy === 'semantic' || strategy === 'standard') && (
          <div className="space-y-2 rounded-xl border border-violet-500/20 bg-slate-950/40 px-4 py-3">
            <label className="flex items-center gap-2 text-[11px] font-medium text-violet-200/95">
              <MessageSquare className="w-3.5 h-3.5 text-violet-400" />
              {strategy === 'semantic' ? '智能快剪 · 提示词（必填）' : '标准快剪 · 目标与偏好（可选）'}
            </label>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              {strategy === 'semantic'
                ? '描述你的剪辑诉求，后端将结合 ASR 句子与约束调用 LLM 筛选/保留片段（非全量重写，仅辅助选段）。'
                : '标准快剪不调用 LLM，会按句子信息密度、关键词、口癖和完整性打分；提示词里可写“60秒/2分钟”作为目标时长。'}
            </p>
            <div className="relative">
              <textarea
                value={semanticUserPrompt}
                onChange={(e) => setSemanticUserPrompt(e.target.value)}
                placeholder={strategy === 'semantic'
                  ? '例如：保留介绍价格和优惠的段落，删掉闲聊和重复口癖；节奏紧凑，总时长控制在 2 分钟内…'
                  : '可选：例如 总时长 60 秒，节奏紧凑，尽量删掉口癖和低密度闲聊…'}
                rows={4}
                disabled={generating}
                className="w-full rounded-xl bg-slate-900/70 border border-slate-700 px-3 py-2.5 pr-14 pt-11 text-sm text-slate-200 outline-none focus:border-violet-500/60 placeholder:text-slate-600 resize-y min-h-[88px] disabled:opacity-50"
              />
              <div className="absolute right-2 top-2 z-10">
                <VoiceInputControl
                  intent="口播快剪提示词：说明要保留/删减的内容、节奏与时长偏好；整理成一条清晰中文指令，不要 Markdown。"
                  value={semanticUserPrompt}
                  onTextChange={setSemanticUserPrompt}
                  merge="append"
                  disabled={generating}
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <label className="text-[10px] text-slate-400 shrink-0">目标成片时长（秒）</label>
              <input
                type="number"
                min={5}
                max={7200}
                step={1}
                value={semanticTargetDurationSec}
                onChange={(e) => setSemanticTargetDurationSec(e.target.value)}
                placeholder="留空则从提示词解析，如 2分钟 / 120秒"
                className="w-40 rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1 text-xs text-slate-200 outline-none focus:border-violet-500/60 placeholder:text-slate-600"
              />
              <span className="text-[10px] text-slate-500">
                {strategy === 'semantic'
                  ? '填写后优先于提示词中的时长；仍会与 LLM 筛选 + 程序末尾截断共同生效。'
                  : '填写后优先于提示词中的时长；标准快剪会按评分从高到低保留到目标附近。'}
              </span>
            </div>
          </div>
        )}

        {showWaveform && (
          <div className="space-y-3 rounded-xl border border-violet-500/20 bg-slate-950/40 px-4 py-3">
            <p className="text-[11px] font-medium text-violet-200/95">
              {isAudioActivityStrategy ? '音频粗剪参数（可微调）' : '口播分段预览（波形 · 句子分段 · 选中段）'}
            </p>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              {isAudioActivityStrategy
                ? '该模式通过静音检测保留语音活动区间。阈值越高越容易判静音；头尾补偿用于避免切字。'
                : '在波形上叠加 ASR 句子分段与已生成方案的选中段（绿色高亮=保留，其余=未选/被删）。可框选 A/B 试听、点击跳转；调整下方句头/句尾补偿后重新生成可查看分段变化。'}
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
              {isAudioActivityStrategy && (
                <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
                  <button
                    type="button"
                    onClick={() => setPitchGateEnabled((v) => !v)}
                    className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 hover:border-cyan-500/70"
                  >
                    音高门控：{pitchGateEnabled ? '开' : '关'}
                  </button>
                  <span className="text-slate-500">
                    阈值线：拖动青色虚线（Hz）选“说话音高下限”；生成方案会优先按该门控保留区间（对当前预览视频生效）。
                  </span>
                </div>
              )}
              {isAsrStrategy && (
                <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
                  <span className="text-slate-500">
                    句子分段 {asrSentenceBlocks.length} 条
                    {generatedPlanSegments && generatedPlanSegments.length
                      ? ` · 选中段 ${generatedPlanSegments.filter((s) => !s.exclude_from_output).length} 段`
                      : ''}
                    {asrBlocksLoading ? '（加载中…）' : ''}
                  </span>
                  {asrBlocksError && <span className="text-amber-300">分段加载失败：{asrBlocksError}</span>}
                </div>
              )}
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
                onPointerDown={(e) => {
                  if (!previewDurationSec) return
                  const canvas = e.currentTarget
                  const rect = canvas.getBoundingClientRect()
                  const x = e.clientX - rect.left
                  const y = e.clientY - rect.top
                  const gap = 6
                  const pitchH = isAudioActivityStrategy ? Math.round(rect.height * 0.42) : 0
                  const waveTop = pitchH + (pitchH > 0 ? gap : 0)
                  const waveH = rect.height - waveTop
                  const nearDb =
                    isAudioActivityStrategy &&
                    y >= waveTop - 6 &&
                    Math.abs(y - (waveTop + dbToY(effectiveAudioConfig.activityDbThreshold, waveH))) <= 10
                  const nearPitch =
                    isAudioActivityStrategy &&
                    pitchH > 0 &&
                    y <= pitchH + 6 &&
                    Math.abs(y - hzToY(pitchThresholdHz, pitchH)) <= 10
                  try {
                    canvas.setPointerCapture(e.pointerId)
                  } catch {}
                  if (nearPitch && pitchHz.length) {
                    dragRef.current = { mode: 'pitch_threshold', pointerId: e.pointerId }
                    setSelecting(false)
                    setSelectionPx(null)
                    setPitchThresholdHz(yToHz(y, pitchH))
                    return
                  }
                  if (nearDb) {
                    dragRef.current = { mode: 'db_threshold', pointerId: e.pointerId }
                    setSelecting(false)
                    setSelectionPx(null)
                    const nextDb = yToDb(y - waveTop, waveH)
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({ ...effectiveAudioConfig, activityDbThreshold: nextDb })
                    return
                  }
                  dragRef.current = { mode: 'select', pointerId: e.pointerId, x0: x }
                  setSelecting(true)
                  setSelectionPx({ x1: x, x2: x })
                }}
                onPointerMove={(e) => {
                  const d = dragRef.current
                  if (!d || d.pointerId !== e.pointerId) return
                  const rect = e.currentTarget.getBoundingClientRect()
                  const x = e.clientX - rect.left
                  const y = e.clientY - rect.top
                  if (d.mode === 'pitch_threshold') {
                    const pitchH = Math.round(rect.height * 0.42)
                    setPitchThresholdHz(yToHz(y, pitchH))
                    return
                  }
                  if (d.mode === 'db_threshold') {
                    const gap = 6
                    const pitchH = Math.round(rect.height * 0.42)
                    const waveTop = pitchH + gap
                    const waveH = rect.height - waveTop
                    const nextDb = yToDb(y - waveTop, waveH)
                    setAudioPresetId('custom')
                    setDenoiseStrength(0)
                    setAudioActivityConfig({ ...effectiveAudioConfig, activityDbThreshold: nextDb })
                    return
                  }
                  setSelectionPx((prev) => (prev ? { ...prev, x2: x } : { x1: d.x0, x2: x }))
                }}
                onPointerUp={(e) => {
                  const d = dragRef.current
                  if (!d || d.pointerId !== e.pointerId) return
                  dragRef.current = null
                  try {
                    e.currentTarget.releasePointerCapture(e.pointerId)
                  } catch {}
                  const rect = e.currentTarget.getBoundingClientRect()
                  const x = e.clientX - rect.left
                  const ratioX = clampNum(x / Math.max(1, rect.width), 0, 1)
                  if (d.mode === 'pitch_threshold' || d.mode === 'db_threshold') return
                  const sp = selectionPx
                  setSelecting(false)
                  if (!sp) return
                  const x1 = sp.x1
                  const x2 = sp.x2
                  const left = Math.min(x1, x2)
                  const right = Math.max(x1, x2)
                  if (right - left < 6) {
                    setSelectionPx(null)
                    const sec = waveStartSec + ratioX * visibleDurationSec
                    const a = audioRef.current
                    if (a) a.currentTime = clampNum(sec, 0, previewDurationSec)
                    return
                  }
                  const aSec = clampNum(waveStartSec + (left / rect.width) * visibleDurationSec, 0, previewDurationSec)
                  const bSec = clampNum(waveStartSec + (right / rect.width) * visibleDurationSec, 0, previewDurationSec)
                  setSelectionPx(null)
                  if (bSec - aSec >= 0.25) {
                    setLoopRange({ a: aSec, b: bSec })
                    setLoopEnabled(true)
                    const aEl = audioRef.current
                    if (aEl) aEl.currentTime = aSec
                  }
                }}
                onPointerCancel={() => {
                  dragRef.current = null
                  setSelecting(false)
                  setSelectionPx(null)
                }}
                className={[
                  'w-full h-[140px] rounded-md border border-slate-800 bg-[#0b1020]',
                  selecting ? 'cursor-ew-resize' : 'cursor-crosshair',
                ].join(' ')}
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
              <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-400">
                <button
                  type="button"
                  disabled={!loopRange}
                  onClick={() => setLoopEnabled((v) => !v)}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 hover:border-emerald-500/70 disabled:opacity-40"
                >
                  {loopEnabled ? '循环：开' : '循环：关'}
                </button>
                <button
                  type="button"
                  disabled={!loopRange}
                  onClick={() => {
                    setLoopEnabled(false)
                    setLoopRange(null)
                    setSelectionPx(null)
                  }}
                  className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 hover:border-slate-500 disabled:opacity-40"
                >
                  清除 A/B
                </button>
                {loopRange && (
                  <span className="text-slate-500">
                    A {fmt(loopRange.a)} · B {fmt(loopRange.b)}（{Math.max(0, loopRange.b - loopRange.a).toFixed(2)}s）
                  </span>
                )}
              </div>
              {waveLoading && <p className="text-[10px] text-slate-500">正在解析音频波形...</p>}
              {waveError && <p className="text-[10px] text-amber-300">波形预览失败：{waveError}</p>}
              {isAudioActivityStrategy && pitchLoading && <p className="text-[10px] text-slate-500">正在解析音高轨（Hz）...</p>}
              {isAudioActivityStrategy && pitchError && <p className="text-[10px] text-amber-300">音高预览失败：{pitchError}</p>}
              <p className="text-[10px] text-slate-500">
                {isAudioActivityStrategy
                  ? '提示：拖拽橙色线可调阈值；在波形上拖拽框选可设置 A/B 循环试听；短拖拽视为跳转播放。'
                  : '提示：在波形上拖拽框选可设置 A/B 循环试听；短拖拽视为跳转播放。绿色高亮为已选中保留段。'}
              </p>
            </div>
            {isAudioActivityStrategy && (
              <>
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
              </>
            )}
            {isAsrStrategy && (
              <div className="grid gap-3 sm:grid-cols-2 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-3">
                <label className="text-[11px] text-slate-300 space-y-1">
                  <HelpLabel text="句头多保留秒" help={ASR_PAD_HELP.head} />
                  <input
                    type="number"
                    step={0.02}
                    min={0}
                    max={3}
                    value={asrHeadPadSec}
                    onChange={(e) => setAsrHeadPadSec(Number(e.target.value || 0))}
                    className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                  />
                </label>
                <label className="text-[11px] text-slate-300 space-y-1">
                  <HelpLabel text="句尾多保留秒" help={ASR_PAD_HELP.tail} />
                  <input
                    type="number"
                    step={0.02}
                    min={0}
                    max={3}
                    value={asrTailPadSec}
                    onChange={(e) => setAsrTailPadSec(Number(e.target.value || 0))}
                    className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-violet-500/60"
                  />
                </label>
                <p className="sm:col-span-2 text-[10px] text-slate-500 leading-relaxed">
                  在每条 ASR 句子的起点前/终点后多保留 n 秒，用于保留说话间隙、避免切到首字或尾音。默认 0=严格按句子边界裁剪。调大后重新生成可在上方频谱查看分段外扩。
                </p>
              </div>
            )}
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
