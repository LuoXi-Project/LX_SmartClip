'use client'

import { useMemo, useState } from 'react'
import { X, Download, Globe, ExternalLink, Sparkles, AlertTriangle } from 'lucide-react'

import type { ExternalSearchExtraction, ExternalSearchResultItem } from '@/lib/api'

interface ExternalSearchResultsModalProps {
  keywords: string[]
  results: ExternalSearchResultItem[]
  notes: string[]
  extraction?: ExternalSearchExtraction | null
  autoProcess: boolean
  onClose: () => void
  /** 勾选确认后回调（下载并预处理） */
  onConfirm: (selected: ExternalSearchResultItem[]) => void
}

function formatDuration(sec: number | null): string {
  if (sec == null || !isFinite(sec)) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

const PLATFORM_BADGE: Record<string, { label: string; cls: string }> = {
  douyin: { label: '抖音', cls: 'bg-fuchsia-500/15 text-fuchsia-300' },
  youtube: { label: 'YouTube', cls: 'bg-red-500/15 text-red-300' },
}

export function ExternalSearchResultsModal({
  keywords,
  results,
  notes,
  extraction,
  autoProcess,
  onClose,
  onConfirm,
}: ExternalSearchResultsModalProps) {
  // 按关键词分组（保持搜索命中顺序）
  const groups = useMemo(() => {
    const map = new Map<string, ExternalSearchResultItem[]>()
    for (const r of results) {
      const key = r.keyword || '搜索结果'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(r)
    }
    return Array.from(map.entries())
  }, [results])

  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(
    () => new Set(results.map((r) => r.url)),
  )

  const toggle = (url: string) => {
    setSelectedUrls((prev) => {
      const next = new Set(prev)
      if (next.has(url)) next.delete(url)
      else next.add(url)
      return next
    })
  }

  const toggleGroup = (items: ExternalSearchResultItem[]) => {
    setSelectedUrls((prev) => {
      const allIn = items.every((i) => prev.has(i.url))
      const next = new Set(prev)
      for (const i of items) {
        if (allIn) next.delete(i.url)
        else next.add(i.url)
      }
      return next
    })
  }

  const selected = results.filter((r) => selectedUrls.has(r.url))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-slate-700/70">
          <div>
            <h3 className="text-base font-semibold text-slate-100">搜索结果</h3>
            <div className="flex flex-wrap items-center gap-2 mt-0.5">
              <p className="text-xs text-slate-500">
                关键词：{keywords.join('、') || '—'} · 共 {results.length} 条，已勾选 {selected.length} 条
              </p>
              {extraction &&
                (extraction.method === 'llm' ? (
                  <span
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-emerald-500/10 text-emerald-400"
                    title="关键词由 LLM 从文案提取"
                  >
                    <Sparkles className="w-3 h-3" />
                    AI 提取
                  </span>
                ) : (
                  <span
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] bg-amber-500/10 text-amber-400"
                    title={extraction.reason || 'LLM 不可用，已降级为文本切分'}
                  >
                    <AlertTriangle className="w-3 h-3" />
                    AI 提取不可用，已用文本切分
                  </span>
                ))}
            </div>
            {extraction && extraction.method === 'fallback' && extraction.reason && (
              <p className="text-[11px] text-amber-400/80 mt-0.5">{extraction.reason}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-8 h-8 rounded-lg hover:bg-slate-800 flex items-center justify-center text-slate-400"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Notes */}
        {notes.length > 0 && (
          <div className="px-5 py-2 text-xs text-amber-400/90 border-b border-slate-800">
            {notes.slice(0, 3).map((n, i) => (
              <p key={i}>· {n}</p>
            ))}
          </div>
        )}

        {/* Results */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {groups.map(([kw, items]) => (
            <div key={kw}>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-medium text-slate-300">「{kw}」</h4>
                <button
                  type="button"
                  onClick={() => toggleGroup(items)}
                  className="text-xs text-cyan-400 hover:text-cyan-300"
                >
                  {items.every((i) => selectedUrls.has(i.url)) ? '取消全选' : '全选'}
                </button>
              </div>
              <div className="grid grid-cols-1 gap-2">
                {items.map((r) => {
                  const checked = selectedUrls.has(r.url)
                  const badge = PLATFORM_BADGE[r.platform] || {
                    label: r.platform,
                    cls: 'bg-slate-500/15 text-slate-300',
                  }
                  return (
                    <label
                      key={r.url}
                      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                        checked
                          ? 'border-fuchsia-500/50 bg-fuchsia-500/5'
                          : 'border-slate-700/60 bg-slate-800/30 hover:border-slate-600'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(r.url)}
                        className="mt-1 accent-fuchsia-500"
                      />
                      {r.cover_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={r.cover_url}
                          alt=""
                          className="w-20 h-12 object-cover rounded bg-slate-800 flex-shrink-0"
                          onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                        />
                      ) : (
                        <div className="w-20 h-12 rounded bg-slate-800 flex-shrink-0 flex items-center justify-center">
                          <Globe className="w-4 h-4 text-slate-600" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-slate-200 line-clamp-2" title={r.title}>
                          {r.title || '（无标题）'}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                          <span className={`px-1.5 py-0.5 rounded ${badge.cls}`}>{badge.label}</span>
                          {r.author && <span>@{r.author}</span>}
                          <span>{formatDuration(r.duration_sec)}</span>
                          {r.stats_text && <span>{r.stats_text}</span>}
                          {r.view_count != null && r.view_count > 0 && (
                            <span>{Intl.NumberFormat('zh-CN', { notation: 'compact' }).format(r.view_count)} 次观看</span>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          window.open(r.url, '_blank', 'noopener,noreferrer')
                        }}
                        title="在新标签页预览原视频"
                        className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-cyan-400 hover:text-cyan-300 hover:bg-cyan-500/10 transition-colors"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        预览
                      </button>
                    </label>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-slate-700/70">
          <p className="text-xs text-slate-500">
            {autoProcess ? '下载完成后将自动进入预处理队列' : '仅下载入库，不自动预处理'}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-9 px-4 rounded-lg text-sm text-slate-300 hover:bg-slate-800"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => onConfirm(selected)}
              disabled={selected.length === 0}
              className={`inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-sm font-medium transition-all ${
                selected.length === 0
                  ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                  : 'bg-fuchsia-600 text-white hover:bg-fuchsia-500 active:scale-95'
              }`}
            >
              <Download className="w-4 h-4" />
              下载 {selected.length > 0 ? `(${selected.length})` : ''}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
