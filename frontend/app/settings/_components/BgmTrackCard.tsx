'use client'

import { useMemo, useState } from 'react'
import { Loader2, Save, Trash2 } from 'lucide-react'
import type { BgmTrack } from '@/lib/api'
import { BgmMiniPlayer } from './BgmMiniPlayer'

type TrackEditState = {
  title?: string
  mood?: string
  bpm?: number
  tags?: string[]
}

interface Props {
  track: BgmTrack
  editingState?: TrackEditState
  moodOptions: Array<{ value: string; label: string }>
  tagOptions: string[]
  onFieldChange: (id: string, key: 'title' | 'mood' | 'bpm', value: string) => void
  onToggleTrackTag: (id: string, currentTags: string[], tag: string) => void
  onSave: (t: BgmTrack) => void
  onDelete: (t: BgmTrack) => void
  /** 元数据保存中：按钮转 spinner 并防重复提交 */
  saving?: boolean
}

export function BgmTrackCard({
  track,
  editingState,
  moodOptions,
  tagOptions,
  onFieldChange,
  onToggleTrackTag,
  onSave,
  onDelete,
  saving,
}: Props) {
  const t = track
  const selectedTags = editingState?.tags ?? t.tags
  const [expandTags, setExpandTags] = useState(false)

  const visibleTags = useMemo(() => {
    if (expandTags) return tagOptions
    const selectedFirst = tagOptions.filter((tag) => selectedTags.includes(tag))
    const rest = tagOptions.filter((tag) => !selectedTags.includes(tag))
    const limit = Math.max(12, selectedFirst.length)
    return [...selectedFirst, ...rest].slice(0, limit)
  }, [expandTags, selectedTags, tagOptions])
  const hiddenTagCount = Math.max(0, tagOptions.length - visibleTags.length)

  return (
    <div
      className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 flex flex-col md:flex-row md:items-center md:gap-4 gap-3"
    >
      <div className="flex-1 space-y-1.5">
        <div className="flex flex-col md:flex-row md:items-center md:gap-3 gap-1.5">
          <input
            type="text"
            defaultValue={t.title}
            onChange={(e) => onFieldChange(t.id, 'title', e.target.value)}
            className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
            placeholder="曲目标题"
          />

          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500">情绪</span>
            <select
              defaultValue={t.mood || ''}
              onChange={(e) => onFieldChange(t.id, 'mood', e.target.value)}
              className="w-36 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
            >
              {moodOptions.map((opt) => (
                <option key={opt.value || 'none'} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500">BPM</span>
            <input
              type="number"
              defaultValue={t.bpm ?? ''}
              onChange={(e) => onFieldChange(t.id, 'bpm', e.target.value)}
              className="w-20 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
              placeholder="120"
            />
          </div>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-start lg:gap-3 gap-2">
          <div className="flex-1 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-500">
                标签（已选 {selectedTags.length} / {tagOptions.length}）
              </span>
              <button
                type="button"
                onClick={() => setExpandTags((v) => !v)}
                className="text-[10px] px-2 py-0.5 rounded-md border border-slate-700 bg-slate-900/70 text-slate-300 hover:text-white hover:border-slate-500 transition-colors"
              >
                {expandTags ? '收起' : `展开${hiddenTagCount > 0 ? ` +${hiddenTagCount}` : ''}`}
              </button>
            </div>
            <div className={`flex flex-wrap gap-1.5 ${expandTags ? 'max-h-28 overflow-y-auto styled-scrollbar pr-1' : ''}`}>
              {visibleTags.map((tag) => {
                const selected = selectedTags.includes(tag)
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => onToggleTrackTag(t.id, t.tags, tag)}
                    className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
                      selected
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

          <BgmMiniPlayer
            src={t.url}
            downloadFilename={t.filename}
            className="w-full lg:min-w-[320px] lg:max-w-md mt-1.5 lg:mt-0"
          />
        </div>

        <p className="text-[10px] text-slate-500 break-all">
          文件名：<span className="font-mono text-slate-400">{t.filename}</span>
        </p>
      </div>

      <div className="flex flex-row md:flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => onSave(t)}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          {saving ? '保存中' : '保存'}
        </button>
        <button
          type="button"
          onClick={() => onDelete(t)}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/60 bg-red-500/10 text-red-200 text-xs hover:bg-red-500/20 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <Trash2 className="w-3.5 h-3.5" />
          删除
        </button>
      </div>
    </div>
  )
}

