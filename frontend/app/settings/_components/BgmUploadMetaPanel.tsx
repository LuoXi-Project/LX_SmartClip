'use client'

import type { ReactNode } from 'react'

type UploadMetaState = {
  title: string
  mood: string
  tags: string[]
}

type MoodOption = { value: string; label: string }

interface Props {
  uploadMeta: UploadMetaState
  onUploadMetaChange: (next: UploadMetaState) => void
  onToggleTag: (tag: string) => void
  moodOptions: MoodOption[]
  tagOptions: string[]
  childrenAboveTags?: ReactNode
}

export function BgmUploadMetaPanel({
  uploadMeta,
  onUploadMetaChange,
  onToggleTag,
  moodOptions,
  tagOptions,
  childrenAboveTags,
}: Props) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 space-y-3">
      <p className="text-xs text-slate-400">上传时可直接配置元数据（可选）</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        <input
          type="text"
          value={uploadMeta.title}
          onChange={(e) => onUploadMetaChange({ ...uploadMeta, title: e.target.value })}
          className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
          placeholder="曲目标题（可选）"
        />
        <select
          value={uploadMeta.mood}
          onChange={(e) => onUploadMetaChange({ ...uploadMeta, mood: e.target.value })}
          className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
        >
          {moodOptions.map((opt) => (
            <option key={opt.value || 'none'} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <div className="rounded-lg bg-slate-900 border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-400 flex items-center">
          BPM 上传后自动检测
        </div>
      </div>

      {childrenAboveTags}

      <div className="flex flex-wrap gap-2">
        {tagOptions.map((tag) => {
          const active = uploadMeta.tags.includes(tag)
          return (
            <button
              key={tag}
              type="button"
              onClick={() => onToggleTag(tag)}
              className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                active
                  ? 'border-indigo-500/60 bg-indigo-500/20 text-indigo-200'
                  : 'border-slate-700 bg-slate-900/70 text-slate-400 hover:text-slate-200'
              }`}
            >
              {tag}
            </button>
          )
        })}
      </div>
    </div>
  )
}

