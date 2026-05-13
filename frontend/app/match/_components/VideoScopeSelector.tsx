'use client'

import { ChevronLeft, ChevronRight, Film, Search } from 'lucide-react'
import { type Video } from '@/lib/api'
import { VoiceInputControl } from '@/components/ui/voice-input'

type VideoScopeSelectorProps = {
  scopeVideos: Video[]
  filteredScopeVideos: Video[]
  pagedScopeVideos: Video[]
  videoSearch: string
  videoPage: number
  videoTotalPages: number
  selectedVideoIds: string[]
  onToggleVideo: (id: string) => void
  onSearchChange: (value: string) => void
  onPrevPage: () => void
  onNextPage: () => void
}

export function VideoScopeSelector({
  scopeVideos,
  filteredScopeVideos,
  pagedScopeVideos,
  videoSearch,
  videoPage,
  videoTotalPages,
  selectedVideoIds,
  onToggleVideo,
  onSearchChange,
  onPrevPage,
  onNextPage,
}: VideoScopeSelectorProps) {
  if (scopeVideos.length === 0) return null
  const statusLabel = (s: Video['status']) => {
    if (s === 'done') return '已完成'
    if (s === 'processing') return '处理中'
    if (s === 'pending') return '待处理'
    return '异常'
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
          限定视频范围
          <span className="normal-case font-normal text-slate-600 ml-1">（不选 = 全部）</span>
        </p>
        <span className="text-xs text-slate-600">
          {videoSearch ? `${filteredScopeVideos.length} / ${scopeVideos.length}` : scopeVideos.length} 个视频
        </span>
      </div>
      <div className="flex items-stretch rounded-lg border border-slate-700 bg-slate-800/60 focus-within:border-indigo-500 transition-colors overflow-hidden">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          <input
            type="text"
            value={videoSearch}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索视频名称..."
            className="w-full pl-9 pr-3 py-2 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none"
          />
        </div>
        <div className="flex items-center gap-1 pr-2 border-l border-slate-700/50 shrink-0">
          <VoiceInputControl
            intent="在「限定视频范围」列表里按名称筛选视频：把口述整理成应填入搜索框的关键字，不要句子说明。"
            value={videoSearch}
            onTextChange={onSearchChange}
            merge="replace"
            className="relative"
          />
          {videoSearch ? (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              className="text-slate-500 hover:text-slate-300 text-xs px-1"
            >
              ✕
            </button>
          ) : null}
        </div>
      </div>
      {filteredScopeVideos.length === 0 ? (
        <p className="text-slate-500 text-sm">未找到「{videoSearch}」。</p>
      ) : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {pagedScopeVideos.map((v) => (
              <button
                key={v.id}
                onClick={() => onToggleVideo(v.id)}
                className={`text-left px-3 py-2.5 rounded-lg border text-xs flex items-center gap-2 transition-colors ${
                  selectedVideoIds.includes(v.id)
                    ? 'border-indigo-500 bg-indigo-500/15 text-indigo-300'
                    : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                }`}
              >
                <Film className="w-3.5 h-3.5 shrink-0" />
                <span className="truncate">{v.name}</span>
                <span className="ml-auto shrink-0 text-slate-600">
                  {v.status === 'done' ? (v.total_clips > 0 ? `${v.total_clips}片` : '未预处理') : statusLabel(v.status)}
                </span>
              </button>
            ))}
          </div>
          {videoTotalPages > 1 && (
            <div className="flex items-center justify-between pt-1">
              <button
                onClick={onPrevPage}
                disabled={videoPage === 1}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                上一页
              </button>
              <span className="text-xs text-slate-500">
                {videoPage} / {videoTotalPages}
              </span>
              <button
                onClick={onNextPage}
                disabled={videoPage === videoTotalPages}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                下一页
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
