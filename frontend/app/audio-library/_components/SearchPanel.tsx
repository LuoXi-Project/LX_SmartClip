'use client'

import { useState } from 'react'
import { Download, Loader2, Play, Pause, Search } from 'lucide-react'
import type {
  AudioLibraryStatusResp,
  SongMetaDTO,
} from '@/lib/api'

interface SearchPanelProps {
  status: AudioLibraryStatusResp | null
  searching: boolean
  searchSongs: SongMetaDTO[]
  onSearch: (source: string, keyword: string, account: string) => void
  onDownload: (source: string, account: string, songs: SongMetaDTO[]) => void
}

// 从 tags 里提取试听 URL（网易云搜索结果会带 preview_url:xxx）
function extractPreviewUrl(song: SongMetaDTO): string | null {
  for (const t of song.tags || []) {
    if (t.startsWith('preview_url:')) return t.slice('preview_url:'.length)
  }
  return null
}

function formatDuration(sec?: number | null): string {
  if (!sec || sec <= 0) return '--'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function SearchPanel({
  status,
  searching,
  searchSongs,
  onSearch,
  onDownload,
}: SearchPanelProps) {
  const sources = status?.sources ?? [] // 全部源都允许搜索
  const [source, setSource] = useState(sources[0]?.source || 'netease')
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [playingId, setPlayingId] = useState<string | null>(null)

  // 该源的默认账号（需登录源用 main，实际账号从父组件 accounts 取，这里用 main 占位）
  const account = 'main'

  const handleSearch = () => {
    if (!keyword.trim()) return
    setSelected(new Set())
    setPlayingId(null)
    onSearch(source, keyword.trim(), account)
  }

  const toggleSelect = (key: string) => {
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleDownload = () => {
    const picked = searchSongs.filter((s) =>
      selected.has(`${s.source}:${s.source_id}`),
    )
    onDownload(source, account, picked)
    setSelected(new Set())
  }

  return (
    <div className="rounded-xl border border-slate-700/50 bg-[#161922] p-4">
      <div className="mb-3 flex items-center gap-2">
        <Search className="h-4 w-4 text-emerald-400" />
        <h2 className="text-sm font-semibold text-zinc-200">搜索音乐</h2>
      </div>

      {/* 搜索栏 */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="rounded-md border border-slate-700 bg-[#0d0f14] px-2 py-1.5 text-sm text-zinc-200 outline-none focus:border-emerald-500/50"
        >
          {sources.map((s) => (
            <option key={s.source} value={s.source}>
              {s.label}
              {s.needs_login ? '（需登录享 VIP）' : '（免登录）'}
            </option>
          ))}
        </select>
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSearch()
          }}
          placeholder="输入歌曲名 / 歌手"
          className="min-w-0 flex-1 rounded-md border border-slate-700 bg-[#0d0f14] px-3 py-1.5 text-sm text-zinc-200 outline-none focus:border-emerald-500/50"
        />
        <button
          onClick={handleSearch}
          disabled={searching || !keyword.trim()}
          className="flex items-center gap-1.5 rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:opacity-50"
        >
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          {searching ? '搜索中' : '搜索'}
        </button>
      </div>

      {/* 结果列表 */}
      <div className="mt-4">
        {searchSongs.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500">
            {searching ? '正在搜索…' : '输入关键词搜索，勾选后下载到 BGM 库'}
          </div>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-zinc-500">
                共 {searchSongs.length} 首 · 已选 {selected.size}
              </span>
              <button
                onClick={handleDownload}
                disabled={selected.size === 0}
                className="flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-40"
              >
                <Download className="h-3.5 w-3.5" />
                下载选中到 BGM 库
              </button>
            </div>
            <div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">
              {searchSongs.map((song) => {
                const key = `${song.source}:${song.source_id}`
                const isSel = selected.has(key)
                const previewUrl = extractPreviewUrl(song)
                const isPlaying = playingId === key
                return (
                  <div
                    key={key}
                    className={`flex items-center gap-3 rounded-md border px-3 py-2 transition ${
                      isSel
                        ? 'border-emerald-500/40 bg-emerald-500/5'
                        : 'border-transparent bg-slate-800/30 hover:bg-slate-800/50'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSel}
                      onChange={() => toggleSelect(key)}
                      className="h-3.5 w-3.5 accent-emerald-500"
                    />
                    {/* 试听 */}
                    {previewUrl ? (
                      <button
                        onClick={() => {
                          const el = document.getElementById(`audio-${key}`) as HTMLAudioElement | null
                          if (!el) return
                          if (isPlaying) {
                            el.pause()
                            setPlayingId(null)
                          } else {
                            // 暂停其他
                            document.querySelectorAll('audio').forEach((a) => {
                              if (a.id !== `audio-${key}`) a.pause()
                            })
                            el.play().catch(() => {})
                            setPlayingId(key)
                          }
                        }}
                        className="rounded-full bg-emerald-500/15 p-1.5 text-emerald-400 hover:bg-emerald-500/25"
                      >
                        {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </button>
                    ) : (
                      <span className="w-7" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-zinc-200">
                        {song.title}
                      </div>
                      <div className="truncate text-[11px] text-zinc-500">
                        {song.artist || '未知'} · {song.album || '未知专辑'} · {formatDuration(song.duration)}
                      </div>
                    </div>
                    {previewUrl && (
                      <audio
                        id={`audio-${key}`}
                        src={previewUrl}
                        onEnded={() => setPlayingId(null)}
                        preload="none"
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
