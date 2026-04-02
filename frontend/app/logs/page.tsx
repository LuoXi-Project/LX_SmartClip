'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import apiClient from '@/lib/api'
import { ArrowLeft, Loader2, RefreshCw, Search, Copy, Check } from 'lucide-react'

type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

interface LogItem {
  ts: string
  level: string
  logger: string
  message: string
}

type LogSource = 'memory' | 'file' | 'both'

interface LogsResponse {
  items: LogItem[]
  limit: number
  q: string | null
  level: string | null
  source?: LogSource
}

function levelPill(level: string) {
  const lv = (level || '').toUpperCase()
  if (lv === 'ERROR' || lv === 'CRITICAL') return 'border-red-600/30 bg-red-500/10 text-red-200'
  if (lv === 'WARNING') return 'border-amber-600/30 bg-amber-500/10 text-amber-200'
  if (lv === 'DEBUG') return 'border-slate-700 bg-slate-800/60 text-slate-300'
  return 'border-emerald-600/30 bg-emerald-500/10 text-emerald-200'
}

export default function LogsPage() {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [limit, setLimit] = useState(300)
  const [source, setSource] = useState<LogSource>('both')
  const [level, setLevel] = useState<LogLevel | ''>('')

  const [items, setItems] = useState<LogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [lastUpdatedAt, setLastUpdatedAt] = useState('')
  const [copied, setCopied] = useState(false)

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => setDebouncedQ(q), 250)
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current)
    }
  }, [q])

  const fetchLogs = async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number | undefined> = {
        q: debouncedQ.trim() || undefined,
        limit,
        level: level || undefined,
        source,
      }
      const res = await apiClient.get<unknown, LogsResponse>('/api/logs', { params })
      setItems(res.items || [])
      setLastUpdatedAt(new Date().toLocaleString())
    } catch (e) {
      console.error('Failed to fetch logs:', e)
      setError('拉取日志失败，请确认后端已启动且版本包含 /api/logs 接口。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, limit, level, source])

  const filteredCountText = useMemo(() => {
    const q2 = debouncedQ.trim()
    const parts: string[] = []
    if (q2) parts.push(`关键字「${q2}」`)
    if (level) parts.push(`级别 ${level}`)
    parts.push(`最新 ${limit} 条`)
    if (source === 'memory') parts.push('来源：内存')
    else if (source === 'file') parts.push('来源：落盘文件')
    else parts.push('来源：内存+文件')
    return parts.join(' · ')
  }, [debouncedQ, limit, level, source])

  const plainText = useMemo(() => {
    return (items || [])
      .map((it) => `${it.ts} [${it.level}] ${it.logger}: ${it.message}`)
      .join('\n')
  }, [items])

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(plainText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch (e) {
      console.error('Copy failed:', e)
    }
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center gap-4">
        <Link href="/" className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">
          <ArrowLeft className="w-4 h-4" />首页
        </Link>
        <div className="h-4 w-px bg-slate-700" />
        <h1 className="text-lg font-semibold">日志</h1>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={fetchLogs}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-900/40 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="刷新"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            刷新
          </button>
          <button
            type="button"
            onClick={copyAll}
            disabled={!plainText}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-900/40 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title="复制当前列表"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            复制
          </button>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <section className="rounded-2xl border border-slate-800 bg-slate-900/30 p-5">
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(280px,1fr)_160px_200px_180px_160px] gap-3 items-end">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">检索</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="输入关键字：错误信息 / 文件名 / logger / 请求路径..."
                  className="w-full pl-10 pr-3 py-2.5 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1.5">数量</label>
              <input
                type="number"
                min={1}
                max={5000}
                value={limit}
                onChange={(e) => setLimit(Math.max(1, Math.min(5000, Number(e.target.value || 200))))}
                className="w-full px-3 py-2.5 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 outline-none focus:border-indigo-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1.5">来源</label>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as LogSource)}
                className="w-full px-3 py-2.5 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 outline-none focus:border-indigo-500 transition-colors"
              >
                <option value="both">内存 + 落盘（推荐）</option>
                <option value="memory">仅当前进程内存</option>
                <option value="file">仅 app.log 文件</option>
              </select>
            </div>

            <div>
              <label className="block text-xs text-slate-500 mb-1.5">级别</label>
              <select
                value={level}
                onChange={(e) => setLevel((e.target.value as LogLevel | '') || '')}
                className="w-full px-3 py-2.5 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 outline-none focus:border-indigo-500 transition-colors"
              >
                <option value="">全部</option>
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
                <option value="CRITICAL">CRITICAL</option>
              </select>
            </div>

            <div className="text-xs text-slate-500">
              <div>条件：{filteredCountText}</div>
              <div className="mt-1">更新时间：{lastUpdatedAt || '—'}</div>
            </div>
          </div>

          <p className="text-[11px] text-slate-600 mt-3">
            提示：默认合并「进程内缓冲」与「storage/logs/app.log」落盘日志；仅内存模式在重启后会变少，与文件条数不一致是正常现象。
          </p>

          {error && (
            <div className="mt-4 rounded-xl border border-red-600/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-slate-800 bg-black/20 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
            <p className="text-sm font-medium text-slate-200">最新日志</p>
            <p className="text-xs text-slate-500 tabular-nums">{items.length} 条</p>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 px-5 py-10 text-slate-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中...
            </div>
          ) : items.length === 0 ? (
            <div className="px-5 py-10 text-slate-500 text-sm">
              没有日志可显示。你可以尝试降低过滤条件或点击“刷新”。
            </div>
          ) : (
            <div className="divide-y divide-slate-800">
              {items.map((it, idx) => (
                <div key={`${it.ts}-${idx}`} className="px-5 py-3 hover:bg-slate-900/40 transition-colors">
                  <div className="flex items-start gap-3">
                    <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-md border text-[11px] font-semibold ${levelPill(it.level)}`}>
                      {String(it.level || 'INFO').toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-[11px] text-slate-500 font-mono">{it.ts}</span>
                        <span className="text-[11px] text-slate-400 font-mono truncate">{it.logger}</span>
                      </div>
                      <pre className="mt-1 text-xs text-slate-200/90 whitespace-pre-wrap break-words font-mono">
                        {it.message}
                      </pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

