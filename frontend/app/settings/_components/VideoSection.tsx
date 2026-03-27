'use client'

import { VIDEO_KEYS } from './constants'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import { Save, Scissors, Clock, Info } from 'lucide-react'
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
    value: 'fixed',
    label: '固定时长',
    icon: Clock,
    desc: '按设定的固定秒数等间隔切分。适合长视频均匀采样，切分数量可预期。',
  },
]

const PARAM_HINTS: Record<string, string> = {
  fixed_duration: '仅在「固定时长」模式下生效，每段片段的秒数',
  scene_threshold: '仅在「镜头检测」模式下生效，值越小越灵敏（0.1 ~ 1.0）',
  frame_fps:       '每秒从片段中抽取的帧数，用于 VLM 画面描述',
  asr_model:       'Whisper 语音识别模型规格，越大精度越高但越慢',
}

export function VideoSection({ config, edits, saving, saved, onSet, onSave, onSaveGroup }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = VIDEO_KEYS.some((k) => isDirty(k) && config[k])
  const currentMode = v('split_mode') || 'scene'

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
            <div className="grid grid-cols-2 gap-3">
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

        {/* remaining VIDEO_KEYS except split_mode */}
        {VIDEO_KEYS.filter((k) => k !== 'split_mode' && config[k]).map((key) => (
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
        ))}

      </div>
    </section>
  )
}
