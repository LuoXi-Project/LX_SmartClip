'use client'

import { useEffect, useState } from 'react'

import { VIDEO_KEYS } from './constants'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import { Save, Scissors, Clock, Layers, Info, Zap, Crosshair, Gauge } from 'lucide-react'
import type { ConfigMap } from './types'
import { SettingsDetails } from './SettingsDetails'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
}

const SPLIT_MODES = [
  {
    value: 'scene',
    label: '镜头检测',
    icon: Scissors,
    desc: '自动分析画面变化，在镜头切换处切分。适合剪辑素材，切分结果更贴近实际镜头边界。',
  },
  {
    value: 'hybrid',
    label: '混合模式',
    icon: Layers,
    desc: '先做镜头识别；若某镜头超过「单镜头最长」阈值，再按「固定分割时长」步长强制切段，避免单段过长。',
  },
  {
    value: 'fixed',
    label: '固定时长',
    icon: Clock,
    desc: '按设定的固定秒数等间隔切分。适合长视频均匀采样，切分数量可预期。',
  },
]

const PARAM_HINTS: Record<string, string> = {
  fixed_duration:      '「固定时长」模式：整段等分；「混合模式」下为超长镜头的强制切段步长（秒）',
  scene_threshold:     '「镜头检测」与「混合模式」：画面变化灵敏度；值越小越敏感（推荐 27~35，旧版 0~1 会自动映射）',
  scene_min_scene_len: '「镜头检测」与「混合模式」：抑制过碎切分；单位为帧（越大越不容易切碎）',
  hybrid_max_segment_sec: '仅在「混合模式」下生效：单镜头超过该秒数时，按「固定分割时长」强制切段',
  cut_mode: '切割模式：`fast` 更快（`-ss` 放在 `-i` 前），`precise` 更准但更慢（`-ss` 放在 `-i` 后）',
  stream_copy: '视频流复制（copy）：开启后尽量不转码，速度更快；但切点需关键帧对齐，且会忽略缩放/fps/pix_fmt 等滤镜参数',
  stream_copy_audio: '音频流复制（copy）：与 `stream_copy` 配合可进一步加速；关闭则使用音频编码器重新编码',
  split_max_workers: '切分并行任务数：越大吞吐越高，但会增加 CPU/磁盘压力（建议 1~4）',
  ffmpeg_threads_per_job: '每个 ffmpeg 任务的线程数：并行切分时建议保持较小值（如 1）',
  quiet_split: '安静切分：减少 ffmpeg/场景检测的控制台输出，通常可提升整体吞吐',
  frame_fps:           '每秒从片段中抽取的帧数，用于 VLM 画面描述',
  frame_concurrency:   '抽帧阶段并行处理的片段数量；值越大吞吐越高，但会增加 CPU/磁盘压力',
  frame_target_pixels: '抽帧时将图像长边压制到此像素（如 512），0 表示不压制。配合 VLM 可显著降低 token 消耗',
  asr_model:           'Whisper 语音识别模型规格，越大精度越高但越慢',
  clip_container: '切分输出片段的容器格式（影响后缀与兼容性；常用 mp4）',
  clip_vcodec: '视频编码器：兼容性优先选 libx264；copy 表示尽量不转码（但浏览器可能无法播放）',
  clip_acodec: '音频编码器：mp4 常用 aac；webm 常用 libopus；copy 表示不转码',
  clip_preset: '编码速度/压缩效率权衡（仅 x264/x265 有效），越慢通常越省码率',
  clip_crf: '质量参数：x264/x265 使用 CRF，NVENC 使用 CQ；越小越清晰（仅在未指定视频码率时使用）',
  clip_video_bitrate_kbps: '指定视频码率（kbps）。>0 时优先使用码率模式并忽略 CRF',
  clip_audio_bitrate_kbps: '指定音频码率（kbps）',
  clip_g: 'GOP 长度（关键帧间隔），常用 48（24fps≈2 秒）',
  clip_keyint_min: '最小关键帧间隔（x264/x265 有效），通常与 GOP 一致',
  clip_sc_threshold: '场景切换阈值（x264/x265 有效），0 表示关闭自动场景切换关键帧',
  clip_fps: '强制输出帧率（0=跟随源视频）',
  clip_scale_width: '强制输出宽度（0=不限制；可只填宽或高，另一边自动等比）',
  clip_scale_height: '强制输出高度（0=不限制；可只填宽或高，另一边自动等比）',
  clip_pix_fmt: '像素格式。yuv420p 兼容性最好（尤其浏览器播放）',
  export_container: '成片文件容器（字幕烧录、原声成片最终文件）',
  export_backend: '成片导出实现：`moviepy`（更稳）或 `ffmpeg`（更快）；通常建议保持默认',
  export_gpu:
    '成片合成最终编码：开启后先尝试 NVENC（libx264→h264_nvenc、libx265→hevc_nvenc；已为 NVENC 时失败则回退 x264/x265）；VP9 等无对应硬件编码则仅用 CPU',
  export_vcodec: '成片视频编码：必须为实际编码器（无 copy），避免 concat 时间戳导致音画不同步',
  export_acodec: '成片音频编码：必须为实际编码器（无 copy）',
  export_preset: '成片 x264/x265 的编码速度与压缩权衡',
  export_crf: '成片恒定质量；数值越小越清晰（未指定视频码率时生效）',
  export_video_bitrate_kbps: '成片视频码率（kbps）；>0 时优先码率模式并忽略 CRF',
  export_audio_bitrate_kbps: '成片音频码率（kbps）',
  export_g: '成片 GOP 长度（关键帧间隔）',
  export_keyint_min: '成片最小关键帧间隔（x264/x265 有效）',
  export_sc_threshold: '成片场景切换阈值（x264/x265 有效）',
  export_fps: '成片强制帧率（0=跟随源）',
  export_scale_width: '成片输出宽度（0=不限制）',
  export_scale_height: '成片输出高度（0=不限制）',
  export_pix_fmt: '成片像素格式，兼容性优先选 yuv420p',
}

const VIDEO_PRESETS = [
  {
    id: 'fast_preview',
    name: '极速预览',
    icon: Zap,
    desc: '优先吞吐，切得快，适合先跑一遍流程看结果。',
    focus: '速度优先',
    impact: {
      speed: '高',
      accuracy: '中低',
      quality: '低',
      load: '中高',
    },
    values: {
      split_mode: 'fixed',
      fixed_duration: '8',
      cut_mode: 'fast',
      stream_copy: 'true',
      stream_copy_audio: 'true',
      split_max_workers: '4',
      ffmpeg_threads_per_job: '1',
      quiet_split: 'true',
      frame_fps: '1',
      frame_target_pixels: '512',
      clip_vcodec: 'libx264',
      clip_acodec: 'aac',
      clip_preset: 'ultrafast',
      clip_crf: '30',
      clip_g: '72',
      clip_keyint_min: '72',
      clip_sc_threshold: '0',
      clip_scale_width: '0',
      clip_scale_height: '0',
      clip_pix_fmt: 'yuv420p',
      export_vcodec: 'libx264',
      export_acodec: 'aac',
      export_preset: 'veryfast',
      export_crf: '30',
      export_scale_width: '960',
      export_scale_height: '540',
      export_pix_fmt: 'yuv420p',
    },
  },
  {
    id: 'accurate_lowres',
    name: '精准快切（低清）',
    icon: Crosshair,
    desc: '切点精度优先，同时降低分辨率/质量来抵消转码开销。',
    focus: '精度优先',
    impact: {
      speed: '中',
      accuracy: '高',
      quality: '低',
      load: '中',
    },
    values: {
      split_mode: 'hybrid',
      fixed_duration: '10',
      scene_threshold: '30',
      scene_min_scene_len: '15',
      hybrid_max_segment_sec: '18',
      cut_mode: 'precise',
      stream_copy: 'false',
      stream_copy_audio: 'false',
      split_max_workers: '2',
      ffmpeg_threads_per_job: '1',
      quiet_split: 'true',
      frame_fps: '1',
      frame_target_pixels: '512',
      clip_vcodec: 'libx264',
      clip_acodec: 'aac',
      clip_preset: 'ultrafast',
      clip_crf: '32',
      clip_g: '24',
      clip_keyint_min: '24',
      clip_sc_threshold: '0',
      clip_scale_width: '960',
      clip_scale_height: '540',
      clip_pix_fmt: 'yuv420p',
      export_vcodec: 'libx264',
      export_acodec: 'aac',
      export_preset: 'veryfast',
      export_crf: '31',
      export_scale_width: '960',
      export_scale_height: '540',
      export_pix_fmt: 'yuv420p',
    },
  },
  {
    id: 'balanced_default',
    name: '平衡推荐',
    icon: Gauge,
    desc: '速度、切点、画质折中，作为日常默认更稳妥。',
    focus: '均衡',
    impact: {
      speed: '中高',
      accuracy: '中高',
      quality: '中',
      load: '中高',
    },
    values: {
      split_mode: 'hybrid',
      fixed_duration: '10',
      scene_threshold: '30',
      scene_min_scene_len: '15',
      hybrid_max_segment_sec: '20',
      cut_mode: 'fast',
      stream_copy: 'false',
      stream_copy_audio: 'false',
      split_max_workers: '3',
      ffmpeg_threads_per_job: '1',
      quiet_split: 'true',
      frame_fps: '1',
      frame_target_pixels: '640',
      clip_vcodec: 'libx264',
      clip_acodec: 'aac',
      clip_preset: 'veryfast',
      clip_crf: '29',
      clip_g: '48',
      clip_keyint_min: '48',
      clip_sc_threshold: '0',
      clip_scale_width: '1280',
      clip_scale_height: '720',
      clip_pix_fmt: 'yuv420p',
      export_vcodec: 'libx264',
      export_acodec: 'aac',
      export_preset: 'veryfast',
      export_crf: '28',
      export_scale_width: '1280',
      export_scale_height: '720',
      export_pix_fmt: 'yuv420p',
    },
  },
] as const

const HOW_IT_WORKS = [
  '切点是否精确主要由 cut_mode + stream_copy 决定：precise + 非 copy 更准，fast + copy 更快。',
  '速度主要由并行度与编码成本决定：split_max_workers 越高越快，但 CPU/磁盘占用更高。',
  '降低分辨率/质量（scale + crf）可显著提速，但会降低片段清晰度与细节。',
  'fixed 更可控，scene/hybrid 更贴近镜头边界；hybrid 还能防止单段过长。',
]

const IMPACT_LABELS = [
  { key: 'speed', label: '速度' },
  { key: 'accuracy', label: '切点准确' },
  { key: 'quality', label: '画质' },
  { key: 'load', label: '资源占用' },
] as const

function impactBadgeClass(level: string) {
  if (level === '高') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
  if (level === '中高') return 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
  if (level === '中') return 'border-amber-500/40 bg-amber-500/10 text-amber-300'
  if (level === '中低') return 'border-orange-500/40 bg-orange-500/10 text-orange-300'
  return 'border-slate-600 bg-slate-800/60 text-slate-300'
}

export function VideoSection({ config, edits, saving, saved, onSet, onSave, onSaveGroup }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const hasConfig = (k: string) => Boolean(config[k])
  const groupDirty = VIDEO_KEYS.some((k) => isDirty(k) && config[k])
  const currentMode = v('split_mode') || 'scene'
  const [sceneHybridAdvOpen, setSceneHybridAdvOpen] = useState(currentMode === 'scene' || currentMode === 'hybrid')
  const [frameExtractionOpen, setFrameExtractionOpen] = useState(true)
  const [cutPerfOpen, setCutPerfOpen] = useState(true)
  const [exportEncOpen, setExportEncOpen] = useState(true)

  useEffect(() => {
    setSceneHybridAdvOpen(currentMode === 'scene' || currentMode === 'hybrid')
  }, [currentMode])

  const renderField = (key: string) => (
    <div key={key} className="space-y-1.5">
      <label className="text-xs text-slate-400">{config[key].label || key}</label>
      {PARAM_HINTS[key] && (
        <div className="flex items-start gap-1.5 text-xs text-slate-500 mb-1">
          <Info className="w-3 h-3 mt-0.5 shrink-0 text-slate-600" />
          <span>{PARAM_HINTS[key]}</span>
        </div>
      )}
      <div className="flex gap-2">
        <div className="flex-1">
          <ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => onSet(key, val)} />
        </div>
        <SaveBtn dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => onSave(key)} />
      </div>
    </div>
  )

  const renderFields = (keys: string[]) => keys.filter((k) => k !== 'split_mode' && config[k]).map(renderField)

  const FIXED_KEYS = ['fixed_duration']
  const SCENE_HYBRID_ADV_KEYS = ['scene_threshold', 'scene_min_scene_len', 'hybrid_max_segment_sec']
  const CUT_PERF_KEYS = ['cut_mode', 'stream_copy', 'stream_copy_audio', 'split_max_workers', 'ffmpeg_threads_per_job', 'quiet_split']
  const FRAME_KEYS = ['frame_fps', 'frame_concurrency', 'frame_target_pixels']
  const CLIP_BASIC_KEYS = ['clip_container']
  const CLIP_ADV_KEYS = VIDEO_KEYS.filter((k) => k.startsWith('clip_') && k !== 'clip_container')
  const EXPORT_KEYS = VIDEO_KEYS.filter((k) => k.startsWith('export_'))
  const presetDirty = (values: Record<string, string>) =>
    Object.entries(values).some(([key, val]) => hasConfig(key) && v(key) !== val)
  const presetMatchStats = (values: Record<string, string>) => {
    const entries = Object.entries(values).filter(([key]) => hasConfig(key))
    if (!entries.length) return { matched: 0, total: 0, score: 0 }
    const matched = entries.reduce((acc, [key, val]) => (v(key) === val ? acc + 1 : acc), 0)
    return {
      matched,
      total: entries.length,
      score: matched / entries.length,
    }
  }
  const bestPreset = VIDEO_PRESETS.reduce<{
    id: string
    name: string
    matched: number
    total: number
    score: number
  } | null>((best, preset) => {
    const stats = presetMatchStats(preset.values)
    if (stats.total === 0) return best
    if (!best || stats.score > best.score) {
      return {
        id: preset.id,
        name: preset.name,
        matched: stats.matched,
        total: stats.total,
        score: stats.score,
      }
    }
    return best
  }, null)
  const applyPreset = (values: Record<string, string>) => {
    Object.entries(values).forEach(([key, val]) => {
      if (hasConfig(key)) onSet(key, val)
    })
  }
  const savePreset = (values: Record<string, string>) => {
    const keys = Object.keys(values).filter((key) => hasConfig(key))
    onSaveGroup(keys)
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">视频处理</h2>
          <p className="text-xs text-slate-500 mt-0.5">切分策略与帧提取参数</p>
        </div>
        {groupDirty && (
          <button onClick={() => onSaveGroup(VIDEO_KEYS)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
            <Save className="w-3.5 h-3.5" />保存全部
          </button>
        )}
      </div>

      <div className="px-6 py-5 space-y-5">
        <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4 space-y-3">
          <div>
            <p className="text-sm font-medium text-indigo-200">视频处理模板</p>
            <p className="text-xs text-slate-400 mt-1">
              先一键套参数，再按素材微调。你当前需求建议优先试「精准快切（低清）」。
            </p>
            {bestPreset && (
              <p className="text-[11px] text-emerald-300 mt-1.5">
                当前配置最接近：{bestPreset.name}（匹配 {bestPreset.matched}/{bestPreset.total}）
              </p>
            )}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {VIDEO_PRESETS.map((preset) => {
              const Icon = preset.icon
              const dirty = presetDirty(preset.values)
              const isClosest = bestPreset?.id === preset.id
              return (
                <div key={preset.id} className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 space-y-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5">
                        <Icon className="w-4 h-4 text-indigo-300" />
                        <p className="text-sm font-medium text-slate-100">{preset.name}</p>
                      </div>
                      <p className="text-[11px] text-indigo-300/80 mt-1">{preset.focus}</p>
                    </div>
                    {isClosest && (
                      <span className="text-[10px] font-semibold text-emerald-300 border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">
                        最接近当前
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">{preset.desc}</p>
                  <div className="grid grid-cols-2 gap-1.5">
                    {IMPACT_LABELS.map((item) => {
                      const level = preset.impact[item.key]
                      return (
                        <div
                          key={item.key}
                          className={`rounded-md border px-2 py-1 text-[10px] leading-tight ${impactBadgeClass(level)}`}
                        >
                          <span className="text-slate-300/90">{item.label}</span>
                          <span className="ml-1 font-semibold">{level}</span>
                        </div>
                      )
                    })}
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => applyPreset(preset.values)}
                      className="flex-1 px-2.5 py-1.5 rounded-md text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
                    >
                      一键应用
                    </button>
                    <button
                      type="button"
                      onClick={() => savePreset(preset.values)}
                      disabled={!dirty}
                      className="px-2.5 py-1.5 rounded-md text-xs font-medium border border-slate-600 text-slate-200 hover:border-slate-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      保存模板参数
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="rounded-lg border border-slate-700/80 bg-slate-950/40 px-3 py-2.5 space-y-1.5">
            <p className="text-xs font-medium text-slate-200">这套参数会如何工作</p>
            {HOW_IT_WORKS.map((line) => (
              <p key={line} className="text-[11px] text-slate-400 leading-relaxed">- {line}</p>
            ))}
            <p className="text-[11px] text-amber-300/85 pt-0.5">
              建议流程：先用「极速预览」做粗切确认内容，再切到「精准快切（低清）」重跑关键素材。
            </p>
          </div>
        </div>

        {/* split_mode — card picker */}
        {config['split_mode'] && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs text-slate-400">分割模式</label>
              <SaveBtn
                dirty={isDirty('split_mode')}
                saving={!!saving['split_mode']}
                saved={!!saved['split_mode']}
                onSave={() => onSave('split_mode')}
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {SPLIT_MODES.map((mode) => {
                const Icon = mode.icon
                const active = currentMode === mode.value
                return (
                  <button
                    key={mode.value}
                    type="button"
                    onClick={() => onSet('split_mode', mode.value)}
                    className={`text-left rounded-xl border px-4 py-3.5 transition-all duration-200 ${
                      active
                        ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30'
                        : 'border-slate-700 bg-slate-800/40 hover:border-slate-500 hover:bg-slate-800/70'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Icon className={`w-4 h-4 shrink-0 ${active ? 'text-indigo-400' : 'text-slate-400'}`} />
                      <span className={`text-sm font-medium ${active ? 'text-indigo-300' : 'text-slate-200'}`}>
                        {mode.label}
                      </span>
                      {active && (
                        <span className="ml-auto text-[10px] font-semibold text-indigo-400 bg-indigo-500/15 px-1.5 py-0.5 rounded-full">
                          当前
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 leading-relaxed">{mode.desc}</p>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* split strategy basic */}
        {renderFields(FIXED_KEYS)}

        {/* scene/hybrid advanced */}
        {SCENE_HYBRID_ADV_KEYS.some((k) => config[k]) && (
          <SettingsDetails
            title="镜头检测/混合模式高级参数"
            hint={currentMode === 'scene' || currentMode === 'hybrid' ? '当前模式相关' : '不常用，保持默认即可'}
            open={sceneHybridAdvOpen}
            onOpenChange={setSceneHybridAdvOpen}
          >
            {renderFields(SCENE_HYBRID_ADV_KEYS)}
          </SettingsDetails>
        )}

        {/* cut performance */}
        {CUT_PERF_KEYS.some((k) => config[k]) && (
          <SettingsDetails
            title="切分性能参数"
            hint="可提升切分速度/降低日志输出；copy 模式对播放器兼容性需留意"
            open={cutPerfOpen}
            onOpenChange={setCutPerfOpen}
          >
            {renderFields(CUT_PERF_KEYS)}
          </SettingsDetails>
        )}

        {/* frame extraction for VLM */}
        {FRAME_KEYS.some((k) => config[k]) && (
          <SettingsDetails
            title="帧提取（VLM 画面描述）"
            hint="专业参数，通常无需改"
            open={frameExtractionOpen}
            onOpenChange={setFrameExtractionOpen}
          >
            {renderFields(FRAME_KEYS)}
          </SettingsDetails>
        )}

        {/* 切片/预处理编码（可与成片不同） */}
        {renderFields(CLIP_BASIC_KEYS)}
        {CLIP_ADV_KEYS.some((k) => config[k]) && (
          <SettingsDetails
            title="切片与预处理编码"
            hint="切分输出与成片前的片段处理；可选用 copy 换速度（多片段拼接时仍可能重编码）"
          >
            {renderFields(CLIP_ADV_KEYS)}
          </SettingsDetails>
        )}

        {EXPORT_KEYS.some((k) => config[k]) && (
          <SettingsDetails
            title="成片导出编码"
            hint="字幕烧录与原声成片的最终输出；仅提供实际编码器，保证时间轴一致"
            open={exportEncOpen}
            onOpenChange={setExportEncOpen}
          >
            {renderFields(EXPORT_KEYS)}
          </SettingsDetails>
        )}

      </div>
    </section>
  )
}
