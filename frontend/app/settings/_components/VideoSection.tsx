'use client'

import { useEffect, useState } from 'react'

import { VIDEO_KEYS } from './constants'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import { Save, Scissors, Clock, Layers, Info, ChevronDown } from 'lucide-react'
import type { ConfigMap } from './types'

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
  frame_fps:           '每秒从片段中抽取的帧数，用于 VLM 画面描述',
  frame_target_pixels: '抽帧时将图像长边压制到此像素（如 512），0 表示不压制。配合 VLM 可显著降低 token 消耗',
  asr_model:           'Whisper 语音识别模型规格，越大精度越高但越慢',
  clip_container: '切分输出片段的容器格式（影响后缀与兼容性；常用 mp4）',
  clip_vcodec: '视频编码器：兼容性优先选 libx264；copy 表示尽量不转码（但浏览器可能无法播放）',
  clip_acodec: '音频编码器：mp4 常用 aac；webm 常用 libopus；copy 表示不转码',
  clip_preset: '编码速度/压缩效率权衡（仅 x264/x265 有效），越慢通常越省码率',
  clip_crf: '恒定质量模式：越小越清晰但文件更大（仅在未指定视频码率时使用）',
  clip_video_bitrate_kbps: '指定视频码率（kbps）。>0 时优先使用码率模式并忽略 CRF',
  clip_audio_bitrate_kbps: '指定音频码率（kbps）',
  clip_fps: '强制输出帧率（0=跟随源视频）',
  clip_scale_width: '强制输出宽度（0=不限制；可只填宽或高，另一边自动等比）',
  clip_scale_height: '强制输出高度（0=不限制；可只填宽或高，另一边自动等比）',
  clip_pix_fmt: '像素格式。yuv420p 兼容性最好（尤其浏览器播放）',
}

export function VideoSection({ config, edits, saving, saved, onSet, onSave, onSaveGroup }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = VIDEO_KEYS.some((k) => isDirty(k) && config[k])
  const currentMode = v('split_mode') || 'scene'
  const [sceneHybridAdvOpen, setSceneHybridAdvOpen] = useState(currentMode === 'scene' || currentMode === 'hybrid')
  const [frameExtractionOpen, setFrameExtractionOpen] = useState(true)

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
  const FRAME_KEYS = ['frame_fps', 'frame_target_pixels']
  const CLIP_BASIC_KEYS = ['clip_container']
  const CLIP_ADV_KEYS = VIDEO_KEYS.filter((k) => k.startsWith('clip_') && k !== 'clip_container')

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
          <details
            className="group rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden"
            open={sceneHybridAdvOpen}
            onToggle={(e) => {
              setSceneHybridAdvOpen((e.currentTarget as HTMLDetailsElement).open)
            }}
          >
            <summary className="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none px-4 py-3 flex items-center justify-between bg-slate-900/20 hover:bg-slate-900/30">
              <span className="text-sm font-medium text-slate-200">镜头检测/混合模式高级参数</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">
                  {currentMode === 'scene' || currentMode === 'hybrid' ? '当前模式相关' : '不常用，保持默认即可'}
                </span>
                <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:rotate-180" />
              </div>
            </summary>
            <div className="px-4 pb-4 pt-1 space-y-5">
              {renderFields(SCENE_HYBRID_ADV_KEYS)}
            </div>
          </details>
        )}

        {/* frame extraction for VLM */}
        {FRAME_KEYS.some((k) => config[k]) && (
          <details
            className="group rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden"
            open={frameExtractionOpen}
            onToggle={(e) => {
              setFrameExtractionOpen((e.currentTarget as HTMLDetailsElement).open)
            }}
          >
            <summary className="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none px-4 py-3 flex items-center justify-between bg-slate-900/20 hover:bg-slate-900/30">
              <span className="text-sm font-medium text-slate-200">帧提取（VLM 画面描述）</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">专业参数，通常无需改</span>
                <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:rotate-180" />
              </div>
            </summary>
            <div className="px-4 pb-4 pt-1 space-y-5">
              {renderFields(FRAME_KEYS)}
            </div>
          </details>
        )}

        {/* output encoding */}
        {renderFields(CLIP_BASIC_KEYS)}
        {CLIP_ADV_KEYS.some((k) => config[k]) && (
          <details className="group rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden">
            <summary className="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none px-4 py-3 flex items-center justify-between bg-slate-900/20 hover:bg-slate-900/30">
              <span className="text-sm font-medium text-slate-200">输出编码高级参数</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">兼容性/体积/速度可调</span>
                <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:rotate-180" />
              </div>
            </summary>
            <div className="px-4 pb-4 pt-1 space-y-5">
              {renderFields(CLIP_ADV_KEYS)}
            </div>
          </details>
        )}

      </div>
    </section>
  )
}
