'use client'

import { VIDEO_KEYS } from './constants'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import { Save } from 'lucide-react'
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

export function VideoSection({ config, edits, saving, saved, onSet, onSave, onSaveGroup }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = VIDEO_KEYS.some((k) => isDirty(k) && config[k])

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
      <div className="px-6 py-5 space-y-4">
        {VIDEO_KEYS.filter((k) => config[k]).map((key) => (
          <div key={key} className="space-y-1.5">
            <label className="text-xs text-slate-400">{config[key].label || key}</label>
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
