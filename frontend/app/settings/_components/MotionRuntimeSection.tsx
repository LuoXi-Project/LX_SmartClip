'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  Clapperboard,
  Download,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react'
import { jobsApi, motionApi, type MotionRuntimeStatus } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'

/**
 * 动效引擎（HyperFrames）运行时状态：Node / 渲染依赖 / Chromium / FFmpeg。
 * 开发环境缺依赖时可一键 bootstrap（npm install 后台任务，带进度）。
 */
export function MotionRuntimeSection() {
  const toast = useToast()
  const [status, setStatus] = useState<MotionRuntimeStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [bootJobId, setBootJobId] = useState<string | null>(null)
  const [bootMessage, setBootMessage] = useState('')
  const [bootError, setBootError] = useState('')
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    motionApi
      .runtimeStatus()
      .then(setStatus)
      .catch(() => setError('动效引擎状态加载失败，请确认后端服务正常'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  // bootstrap job 轮询（终态后刷新状态）
  useEffect(() => {
    if (!bootJobId) return
    let disposed = false
    const poll = async () => {
      try {
        const job = await jobsApi.get(bootJobId)
        if (disposed) return
        const step = job.current_step || 'install'
        const msg = job.steps?.[step]?.message || ''
        setBootMessage(msg)
        if (job.status === 'running' || job.status === 'pending') {
          pollRef.current = setTimeout(poll, 2500)
        } else if (job.status === 'done') {
          setBootJobId(null)
          setBootMessage('')
          toast.success('动效渲染依赖已就绪')
          load()
        } else {
          setBootJobId(null)
          setBootError(job.error_message || '依赖安装失败')
        }
      } catch (e) {
        if (!disposed) setBootError((e as Error).message)
      }
    }
    void poll()
    return () => {
      disposed = true
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [bootJobId, load, toast])

  const startBootstrap = async () => {
    setBootError('')
    try {
      const res = await motionApi.bootstrap()
      setBootJobId(res.job_id)
      setBootMessage('启动安装…')
    } catch (e) {
      setBootError((e as Error).message)
    }
  }

  const rows: { key: keyof MotionRuntimeStatus; label: string }[] = [
    { key: 'node', label: 'Node.js（22+）' },
    { key: 'node_modules', label: '渲染依赖（@hyperframes/producer）' },
    { key: 'chromium', label: 'Chromium 浏览器' },
    { key: 'ffmpeg', label: 'FFmpeg / FFprobe' },
  ]

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100 flex items-center gap-1.5">
            <Clapperboard className="w-4 h-4 text-fuchsia-400" />
            动效引擎（HyperFrames）
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Agent 动效合成与动效字幕的渲染运行时；不就绪时相关功能自动降级提示，不影响其余功能
          </p>
        </div>
        <div className="flex items-center gap-2">
          {status && (
            <span
              className={clsx(
                'rounded-full border px-2 py-0.5 text-[11px]',
                status.ready
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-300',
              )}
            >
              {status.ready ? '就绪' : '未就绪'}
            </span>
          )}
          <button
            type="button"
            onClick={load}
            title="刷新"
            className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
          >
            <RefreshCw size={13} className={clsx(loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      <div className="px-6 py-5 space-y-3">
        {error && <p className="text-sm text-rose-300">{error}</p>}
        {loading && !status ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-2">
            <Loader2 className="w-4 h-4 animate-spin" />检查运行时…
          </div>
        ) : status ? (
          <>
            <div className="grid gap-2">
              {rows.map(({ key, label }) => {
                const item = status[key] as { ok: boolean; path?: string | null }
                return (
                  <div
                    key={key}
                    className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2"
                  >
                    {item.ok ? (
                      <CheckCircle2 size={14} className="text-emerald-400 shrink-0" />
                    ) : (
                      <XCircle size={14} className="text-rose-400 shrink-0" />
                    )}
                    <span className="text-sm text-slate-200">{label}</span>
                    <span className="ml-auto font-mono text-[10px] text-slate-500 truncate max-w-[45%]" title={item.path || ''}>
                      {item.path || '未找到'}
                    </span>
                  </div>
                )
              })}
            </div>

            {!status.ready && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/[0.04] p-3.5 space-y-2">
                <ul className="text-xs text-amber-200/90 list-disc pl-4 space-y-0.5">
                  {status.missing.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
                {status.node.ok && !status.node_modules.ok && (
                  <div className="space-y-2">
                    <button
                      type="button"
                      onClick={() => void startBootstrap()}
                      disabled={Boolean(bootJobId)}
                      className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 text-white text-xs font-medium disabled:opacity-60 transition-colors"
                    >
                      {bootJobId ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Download className="w-3.5 h-3.5" />
                      )}
                      {bootJobId ? '安装中…' : '自动安装渲染依赖（npm）'}
                    </button>
                    {bootJobId && bootMessage && (
                      <p className="text-[11px] text-slate-400 truncate">{bootMessage}</p>
                    )}
                  </div>
                )}
                {bootError && <p className="text-xs text-rose-300">{bootError}</p>}
                <p className="text-[11px] text-slate-500">
                  打包版随包自带运行时无需安装；开发环境需要 Node 22+（未装时请先安装 Node）。
                </p>
              </div>
            )}
          </>
        ) : null}
      </div>
    </section>
  )
}
