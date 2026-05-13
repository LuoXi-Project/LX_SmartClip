'use client'

import type { NoteLayoutOptions } from '../_lib/types'
import { NOTE_LAYOUT_ROWS } from './constants'
import { VoiceInputControl } from '@/components/ui/voice-input'

type NoteStylePanelProps = {
  noteOptions: NoteLayoutOptions
  onNoteOptionsChange: (updater: (prev: NoteLayoutOptions) => NoteLayoutOptions) => void
  styleText: string
  onStyleTextChange: (v: string) => void
  loading: boolean
  hasVideo: boolean
  onGenerate: () => void
}

export function NoteStylePanel({
  noteOptions,
  onNoteOptionsChange,
  styleText,
  onStyleTextChange,
  loading,
  hasVideo,
  onGenerate,
}: NoteStylePanelProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4 shadow-lg shadow-black/20">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-slate-200">笔记风格与版式</div>
          <p className="text-xs text-slate-500 mt-1 leading-relaxed">
            风格说明与下方版式勾选会写入本次提示词；「立即生成」输出完整 Markdown 笔记（StageA 分段 JSON + StageB 合并）。
          </p>
        </div>
      </div>

      <div className="mt-4">
        <div className="text-xs text-slate-400 mb-2">笔记版式（写入本次生成提示词）</div>
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 space-y-2.5">
          {NOTE_LAYOUT_ROWS.map((row) => (
            <label key={row.k} className="flex items-start gap-2.5 cursor-pointer select-none text-slate-300">
              <input
                type="checkbox"
                checked={noteOptions[row.k]}
                onChange={(e) =>
                  onNoteOptionsChange((prev) => ({ ...prev, [row.k]: e.target.checked }))
                }
                disabled={loading}
                className="mt-0.5 rounded border-slate-600 bg-slate-900 text-cyan-600 focus:ring-cyan-600"
              />
              <span>
                <span className="text-sm font-medium">{row.label}</span>
                <span className="block text-[11px] text-slate-500 leading-snug">{row.desc}</span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        <label className="block">
          <div className="text-xs text-slate-400 mb-1">笔记风格（自定义）</div>
          <div className="relative">
            <textarea
              value={styleText}
              onChange={(e) => onStyleTextChange(e.target.value)}
              className="w-full min-h-[140px] rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 pr-14 pt-10 text-sm text-slate-200"
              placeholder="例如：结论先行、偏技术细节、按「背景→步骤→坑点」组织；篇幅适中，每条要点带时间锚。"
            />
            <div className="absolute right-2 top-2 z-10">
              <VoiceInputControl
                intent="这是「视频总结笔记」的自定义风格说明：把口述整理成写入该框的中文要点（结构、详略、语气、时间锚等），不要输出无关说明。"
                value={styleText}
                onTextChange={onStyleTextChange}
                merge="append"
                disabled={loading}
              />
            </div>
          </div>
          <div className="text-xs text-slate-500 mt-1">
            直接描述结构、详略、语气与重点方向；会与内置 BASE/MERGE 提示词及上方版式开关一起发给模型。
          </div>
        </label>
      </div>

      <button
        type="button"
        onClick={onGenerate}
        disabled={loading || !hasVideo}
        className="mt-5 w-full py-3 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium shadow-md shadow-cyan-900/20"
      >
        {loading ? '生成中…' : '立即生成'}
      </button>
    </div>
  )
}
