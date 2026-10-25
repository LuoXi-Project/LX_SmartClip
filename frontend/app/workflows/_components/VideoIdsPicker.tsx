'use client'

import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { Check, Loader2, RefreshCw, Search, X } from 'lucide-react'
import { videosApi, type Video } from '@/lib/api'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  done: { label: '已处理', cls: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10' },
  processing: { label: '处理中', cls: 'text-cyan-300 border-cyan-500/40 bg-cyan-500/10' },
  pending: { label: '待处理', cls: 'text-amber-300 border-amber-500/40 bg-amber-500/10' },
  error: { label: '失败', cls: 'text-rose-300 border-rose-500/40 bg-rose-500/10' },
}

function fmtDuration(sec?: number | null): string {
  if (!sec || sec < 1) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}

/** video_ids 参数专用选择器：素材库列表点选（多选），未预处理的也可选（运行时自动排队） */
export function VideoIdsPicker({
  value,
  onChange,
}: {
  value: unknown
  onChange: (value: string[]) => void
}) {
  const selected = useMemo(() => {
    if (Array.isArray(value)) return (value as (string | number)[]).map(String)
    if (typeof value === 'string' && value.trim())
      return value.split(/[,，\s]+/).filter(Boolean)
    return []
  }, [value])

  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [thumbFail, setThumbFail] = useState<Record<string, boolean>>({})

  const load = () => {
    setLoading(true)
    setError('')
    videosApi
      .list({ page_size: 500, exclude_status: 'error' })
      .then((res) => setVideos(res.items || []))
      .catch(() => setError('素材列表加载失败，请刷新重试'))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return videos
    return videos.filter((v) => v.name.toLowerCase().includes(q))
  }, [videos, query])

  const toggle = (id: string) => {
    onChange(selected.includes(id) ? selected.filter((v) => v !== id) : [...selected, id])
  }

  const selectedSet = useMemo(() => new Set(selected), [selected])
  const selectedVideos = useMemo(
    () => videos.filter((v) => selectedSet.has(v.id)),
    [videos, selectedSet],
  )

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950/50">
      {/* 已选摘要 */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-800 px-2.5 py-2">
        <span className="text-[11px] text-slate-500">
          已选 <span className="font-medium text-slate-200">{selected.length}</span> 个素材
        </span>
        {selectedVideos.map((v) => (
          <span
            key={v.id}
            className="inline-flex max-w-[160px] items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-px text-[10px] text-cyan-200"
          >
            <span className="truncate">{v.name}</span>
            <button type="button" onClick={() => toggle(v.id)} className="shrink-0 hover:text-cyan-50">
              <X size={9} />
            </button>
          </span>
        ))}
        {selected.length > 0 && selectedVideos.length < selected.length && (
          <span className="text-[10px] text-slate-500">
            （另有 {selected.length - selectedVideos.length} 个素材已不在库中，运行时将报错）
          </span>
        )}
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="ml-auto shrink-0 text-[10px] text-slate-500 transition-colors hover:text-slate-300"
          >
            清空
          </button>
        )}
      </div>

      {/* 搜索 + 刷新 */}
      <div className="flex items-center gap-2 px-2.5 py-1.5">
        <div className="relative flex-1">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索素材名…"
            className="w-full rounded border border-slate-700 bg-slate-900/70 py-1 pl-7 pr-2 text-xs text-slate-100 placeholder:text-slate-600 focus:border-cyan-500/60 focus:outline-none"
          />
        </div>
        <button
          type="button"
          onClick={load}
          title="刷新素材列表"
          className="rounded border border-slate-700 p-1 text-slate-400 transition-colors hover:border-slate-500 hover:text-slate-200"
        >
          <RefreshCw size={11} className={clsx(loading && 'animate-spin')} />
        </button>
      </div>

      {/* 素材列表 */}
      <div className="max-h-56 overflow-y-auto styled-scrollbar border-t border-slate-800">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-500">
            <Loader2 size={13} className="animate-spin" /> 加载素材库…
          </div>
        ) : error ? (
          <div className="py-6 text-center text-xs text-rose-300">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="py-6 text-center text-xs text-slate-500">
            {query ? '没有匹配的素材' : '素材库为空：先在「素材库」上传或采集素材'}
          </div>
        ) : (
          filtered.map((v) => {
            const on = selectedSet.has(v.id)
            const meta = STATUS_META[v.status] || STATUS_META.pending
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => toggle(v.id)}
                className={clsx(
                  'flex w-full items-center gap-2.5 px-2.5 py-1.5 text-left transition-colors',
                  on ? 'bg-cyan-500/10' : 'hover:bg-slate-900/70',
                )}
              >
                <span
                  className={clsx(
                    'flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors',
                    on
                      ? 'border-cyan-400 bg-cyan-500/80 text-white'
                      : 'border-slate-600 bg-slate-900',
                  )}
                >
                  {on && <Check size={10} strokeWidth={3} />}
                </span>
                <span className="h-7 w-11 shrink-0 overflow-hidden rounded bg-slate-900">
                  {!thumbFail[v.id] && v.thumbnail_path ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={`/api/videos/${v.id}/thumbnail`}
                      alt=""
                      className="h-full w-full object-cover"
                      onError={() => setThumbFail((prev) => ({ ...prev, [v.id]: true }))}
                    />
                  ) : (
                    <span className="flex h-full w-full items-center justify-center text-[9px] text-slate-600">
                      无图
                    </span>
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs text-slate-200">{v.name}</span>
                  <span className="block text-[10px] text-slate-500">
                    {[
                      fmtDuration(v.duration),
                      v.total_clips > 0 ? `${v.total_clips} 片段` : '',
                    ]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </span>
                </span>
                <span
                  className={clsx(
                    'shrink-0 rounded border px-1 py-px text-[10px]',
                    meta.cls,
                  )}
                >
                  {meta.label}
                </span>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
