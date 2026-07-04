'use client'

import { Eraser, Film, Loader2, Play, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { ScriptStockOnlineProvider } from '@/lib/api'
import { API_BASE_URL } from '@/lib/api'

import type { StockCacheItem } from './stockOnlineTypes'
import { onlineProviderLabel } from './stockOnlineTypes'

function fmtBytes(n: number) {
  const x = Number(n) || 0
  if (x < 1024) return `${x} B`
  if (x < 1048576) return `${(x / 1024).toFixed(1)} KB`
  return `${(x / 1048576).toFixed(1)} MB`
}

function storageBrowserVideoUrl(storedRelPath: string): string {
  const r = (storedRelPath || '').replace(/\\/g, '/').replace(/^\/+/, '')
  const webPath = r.startsWith('storage/') ? `/${r}` : `/storage/${r}`
  const base = API_BASE_URL.replace(/\/$/, '')
  return base ? `${base}${webPath}` : webPath
}

function cacheItemId(provider: ScriptStockOnlineProvider, it: StockCacheItem): string {
  if (provider === 'pexels') return String((it as { pexels_video_id?: number }).pexels_video_id || '')
  if (provider === 'pixabay') return String((it as { pixabay_video_id?: number }).pixabay_video_id || '')
  return String((it as { unsplash_photo_id?: string }).unsplash_photo_id || '')
}

function cacheThumb(provider: ScriptStockOnlineProvider, it: StockCacheItem): string {
  if (provider === 'pexels') return String((it as { pexels_image?: string }).pexels_image || '')
  return String((it as { preview_image?: string }).preview_image || '')
}

type Props = {
  providers: ScriptStockOnlineProvider[]
  itemsByProvider: Record<ScriptStockOnlineProvider, StockCacheItem[]>
  loadingByProvider: Record<ScriptStockOnlineProvider, boolean>
  clearingByProvider: Record<ScriptStockOnlineProvider, boolean>
  onRefresh: (p: ScriptStockOnlineProvider) => void
  onClear: (p: ScriptStockOnlineProvider) => void
  onDelete: (p: ScriptStockOnlineProvider, storedRelPath: string) => void
  onPreview: (url: string) => void
}

export function StockOnlineCachePanel({
  providers,
  itemsByProvider,
  loadingByProvider,
  clearingByProvider,
  onRefresh,
  onClear,
  onDelete,
  onPreview,
}: Props) {
  const [tab, setTab] = useState<ScriptStockOnlineProvider>(providers[0] ?? 'pexels')
  const items = itemsByProvider[tab] || []
  const loading = loadingByProvider[tab]
  const clearing = clearingByProvider[tab]

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-950/50 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-400">在线素材本地下载缓存</p>
        <div className="flex rounded-lg border border-slate-700 overflow-hidden">
          {providers.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setTab(p)}
              className={`px-2.5 py-1 text-[11px] font-medium ${
                tab === p ? 'bg-sky-600 text-white' : 'bg-slate-900 text-slate-400 hover:text-slate-200'
              }`}
            >
              {onlineProviderLabel(p)}
              {(itemsByProvider[p]?.length || 0) > 0 ? (
                <span className="ml-1 opacity-80">({itemsByProvider[p].length})</span>
              ) : null}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={loading || clearing || items.length === 0}
          onClick={() => onClear(tab)}
          className="text-xs px-3 py-1.5 rounded-lg border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 disabled:opacity-40 inline-flex items-center gap-1"
        >
          {clearing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Eraser className="w-3.5 h-3.5" />}
          清空 {onlineProviderLabel(tab)}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => onRefresh(tab)}
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" /> : null}
          刷新列表
        </button>
      </div>
      {items.length === 0 ? (
        <p className="text-[11px] text-slate-500">
          {onlineProviderLabel(tab)} 暂无已下载文件。搜索并下载后此处会列出；可单条删除或一键清空。
        </p>
      ) : (
        <ul className="max-h-72 overflow-y-auto styled-scrollbar space-y-2 pr-1">
          {items.map((it) => {
            const thumb = cacheThumb(tab, it).trim()
            const q = String((it as { search_query?: string }).search_query || '').trim()
            const dur = Number((it as { duration_sec?: number }).duration_sec) > 0
              ? `${(it as { duration_sec?: number }).duration_sec}s`
              : '—'
                  const isVideo =
                    (it as { media_type?: string }).media_type === 'video' ||
                    /\.(mp4|mov|webm|mkv)$/i.test(it.filename)
                  const playUrl = isVideo ? storageBrowserVideoUrl(it.stored_rel_path) : ''
                  return (
              <li
                key={it.stored_rel_path}
                className="flex items-stretch gap-2 rounded-lg bg-slate-900/80 border border-slate-700/80 p-2 text-[11px]"
              >
                <div className="relative w-[88px] h-[52px] shrink-0 rounded-md overflow-hidden bg-slate-800 border border-slate-700/80">
                  {thumb ? (
                    <img src={thumb} alt="" className="w-full h-full object-cover pointer-events-none" loading="lazy" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600">
                      <Film className="w-6 h-6" />
                    </div>
                  )}
                        {isVideo ? (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              onPreview(playUrl)
                            }}
                            className="absolute bottom-0.5 left-0.5 z-[1] flex items-center justify-center rounded-full bg-black/75 text-white p-1 ring-1 ring-white/25 hover:bg-black/90"
                            title="预览本地视频"
                            aria-label="预览"
                          >
                            <Play className="w-3 h-3 fill-current shrink-0" />
                          </button>
                        ) : (
                          <span className="absolute bottom-0.5 left-0.5 z-[1] text-[9px] px-1 rounded bg-black/70 text-slate-200">
                            图
                          </span>
                        )}
                </div>
                <div className="min-w-0 flex-1 flex flex-col justify-center gap-0.5">
                  <p className="text-[10px] text-sky-300/95 truncate" title={q || undefined}>
                    <span className="text-slate-500">搜索：</span>
                    {q || '（无记录）'}
                  </p>
                  <p className="text-slate-400 truncate">
                    ID {cacheItemId(tab, it) || '?'} · {dur} · {fmtBytes(it.size_bytes)}
                  </p>
                  <p className="text-[10px] text-slate-600 truncate">{it.filename}</p>
                </div>
                <button
                  type="button"
                  onClick={() => onDelete(tab, it.stored_rel_path)}
                  className="shrink-0 self-center p-1.5 rounded text-rose-400 hover:bg-rose-500/15 hover:text-rose-300"
                  title="从本机删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
