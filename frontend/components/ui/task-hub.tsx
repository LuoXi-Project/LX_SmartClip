'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import Link from 'next/link'
import { Loader2, ChevronUp, ChevronDown, Trash2, ListChecks, Download, GripHorizontal } from 'lucide-react'

import { jobsApi, type JobSnapshot } from '@/lib/api'
import { fetchSSE } from '@/lib/stream'
import { useTaskStore } from '@/lib/task-store'
import type { StreamStatus } from '@/lib/stream'
import { StreamingProgress } from '@/components/ui/streaming-progress'

/**
 * 全局后台任务面板（可拖拽）。
 *
 * 挂载在 app/layout.tsx（ToastProvider 内）。订阅 lib/task-store，把所有后台 job 的
 * 实时进度集中展示在右下角：支持多任务并行、折叠为角标、展开看流式日志、终止/清除。
 * 无任务时不渲染。面板和角标均可拖拽移动，避免遮挡页面按钮。
 */

/** 回正按钮：回到默认右下角位置 */
function ResetPositionBtn({ onClick, onPointerDown }: { onClick: () => void; onPointerDown?: (e: React.PointerEvent) => void }) {
  return (
    <button
      onClick={onClick}
      onPointerDown={onPointerDown}
      className="rounded-md p-1 text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
      title="回到右下角"
    >
      <ChevronDown className="w-3.5 h-3.5 rotate-[-135deg]" />
    </button>
  )
}

const PROCESS_STEPS = ['split', 'extract_frames', 'asr', 'vlm', 'enrich', 'embed'] as const

/** 从 process job 的 steps 推导百分比（与 ProcessPage 总进度口径一致）。*/
function percentFromProcessJob(job: JobSnapshot): number {
  const steps = job.steps || {}
  const done = PROCESS_STEPS.filter((k) => {
    const s = steps[k]
    return s && (s.status === 'done' || s.status === 'skip')
  }).length
  return Math.round((done / PROCESS_STEPS.length) * 100)
}

/** 订阅一个 process job 的 SSE 流，实时把进度/终态推入 task-store（流自结束于终态，无需手动关闭）。*/
function subscribeProcessJob(
  jobId: string,
  patch: (id: string, p: Partial<import('@/lib/task-store').TaskEntry>) => void,
) {
  const fullUrl = `${window.location.origin}${jobsApi.streamUrl(jobId)}`
  fetchSSE(fullUrl, undefined, {
    onEvent(event, data) {
      if (event === 'progress') {
        const m = data as { step?: string; detail?: { percent?: number; current?: number; total?: number } }
        let pct = typeof m?.detail?.percent === 'number' ? m.detail.percent : null
        if (pct === null && typeof m?.detail?.current === 'number' && typeof m?.detail?.total === 'number' && m.detail.total > 0) {
          pct = Math.round((m.detail.current / m.detail.total) * 100)
        }
        patch(jobId, { stage: m?.step, percent: pct })
      } else if (event === 'result') {
        patch(jobId, { status: 'done', percent: 100, resultLabel: '预处理完成' })
      } else if (event === 'failed') {
        const f = data as { message?: string; cancelled?: boolean }
        patch(jobId, { status: f?.cancelled ? 'cancelled' : 'error', error: f?.message || '预处理失败' })
      }
    },
    onError() {
      /* 下次 list 轮询兜底 */
    },
  }).catch(() => undefined)
}

export function TaskHub() {
  const tasks = useTaskStore((s) => s.tasks)
  const collapsed = useTaskStore((s) => s.collapsed)
  const setCollapsed = useTaskStore((s) => s.setCollapsed)
  const clearFinished = useTaskStore((s) => s.clearFinished)
  const remove = useTaskStore((s) => s.remove)
  const patch = useTaskStore((s) => s.patch)
  const upsert = useTaskStore((s) => s.upsert)

  const list = Object.values(tasks).sort((a, b) => b.createdAt - a.createdAt)
  const runningCount = list.filter((t) => t.status === 'running').length

  // ── 重载：刷新后从后端恢复「运行/排队中」的 process 任务，并订阅其实时进度 ──
  const subscribedRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    let cancelled = false
    const sync = async () => {
      try {
        const res = await jobsApi.list({ kind: 'process', active: true })
        if (cancelled || !res?.items) return
        const existing = useTaskStore.getState().tasks
        for (const job of res.items) {
          // 已由页面（bridgeToTaskHub）注入并实时订阅的，不覆盖其进度
          if (existing[job.id]) {
            patch(job.id, {
              videoName: job.video_name || undefined,
              videoId: job.ref_id || undefined,
              queueIndex: job.queue_index,
            })
            continue
          }
          upsert({
            id: job.id,
            title: job.video_name ? `视频预处理 · ${job.video_name}` : '视频预处理',
            kind: 'process',
            status: job.status === 'pending' ? 'running' : (job.status as StreamStatus),
            stage:
              job.status === 'pending'
                ? `排队中${typeof job.queue_index === 'number' ? `（第 ${job.queue_index} 位）` : ''}`
                : (job.current_step || undefined),
            percent: percentFromProcessJob(job),
            videoName: job.video_name || undefined,
            videoId: job.ref_id || undefined,
            queueIndex: job.queue_index,
            logs: [],
            elapsedSec: 0,
            createdAt: Date.now(),
            onCancel: () => { jobsApi.cancel(job.id).catch(() => undefined) },
            onRemove: () => { jobsApi.remove(job.id).catch(() => undefined) },
          })
          if (!subscribedRef.current.has(job.id)) {
            subscribedRef.current.add(job.id)
            void subscribeProcessJob(job.id, patch)
          }
        }
      } catch {
        /* 后端不可用时静默；下次轮询重试 */
      }
    }
    void sync()
    const timer = setInterval(() => void sync(), 4000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [upsert, patch])

  // ── 拖拽 ──────────────────────────────────────────────────────────────
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const origin = useRef({ x: 0, y: 0 })
  const offset = useRef({ x: 0, y: 0 })
  const containerRef = useRef<HTMLDivElement>(null)
  const DRAG_THRESHOLD = 4

  const resetPos = useCallback(() => setPos({ x: 0, y: 0 }), [])

  const onPointerDown = useCallback((e: React.PointerEvent, onClick?: () => void) => {
    const el = containerRef.current
    if (!el) return
    el.setPointerCapture(e.pointerId)
    const rect = el.getBoundingClientRect()
    origin.current = { x: e.clientX, y: e.clientY }
    offset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }

    let dragging = false

    const onMove = (ev: PointerEvent) => {
      if (!dragging) {
        if (Math.abs(ev.clientX - origin.current.x) > DRAG_THRESHOLD || Math.abs(ev.clientY - origin.current.y) > DRAG_THRESHOLD) {
          dragging = true
        } else {
          return
        }
      }
      const vw = window.innerWidth
      const vh = window.innerHeight
      const w = el.offsetWidth || 340
      const h = el.offsetHeight || 60
      const x = vw - (ev.clientX - offset.current.x) - w
      const y = vh - (ev.clientY - offset.current.y) - h
      setPos({ x: Math.max(0, Math.min(vw - w, x)), y: Math.max(0, Math.min(vh - h, y)) })
    }

    const onUp = () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      if (!dragging && onClick) onClick()
    }

    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
  }, [])

  /** 阻止按钮上的事件冒泡到拖拽把手 */
  const stopDrag = useCallback((e: React.PointerEvent) => { e.stopPropagation() }, [])

  const expand = useCallback(() => setCollapsed(false), [setCollapsed])

  if (list.length === 0) return null

  // ── 折叠态：可拖拽角标（无移动 = 点击展开）────────────────────────────
  if (collapsed) {
    return (
      <div
        ref={containerRef}
        className="fixed z-[1000] select-none touch-none"
        style={{ right: `${pos.x}px`, bottom: `${pos.y}px` }}
        onPointerDown={(e) => onPointerDown(e, expand)}
      >
        <div
          className="group flex items-center gap-2 rounded-full border border-cyan-500/40 bg-[#161922]/95 px-3.5 py-2 text-sm text-cyan-200 shadow-xl shadow-black/40 backdrop-blur-md hover:border-cyan-400 transition-colors cursor-grab active:cursor-grabbing pointer-events-none"
        >
          {runningCount > 0 ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <ListChecks className="w-4 h-4" />
          )}
          <span>
            {runningCount > 0 ? `${runningCount} 个任务进行中` : `${list.length} 个任务`}
          </span>
          <ChevronUp className="w-3.5 h-3.5 opacity-70 group-hover:opacity-100" />
        </div>
      </div>
    )
  }

  // ── 展开态：可拖拽面板 ────────────────────────────────────────────────
  return (
    <div
      ref={containerRef}
      className="fixed z-[1000] w-[340px] max-w-[calc(100vw-3rem)] select-none"
      style={{ right: `${pos.x}px`, bottom: `${pos.y}px` }}
    >
      <div className="rounded-2xl border border-slate-700/60 bg-[#161922]/95 shadow-2xl shadow-black/60 backdrop-blur-md overflow-hidden">
        {/* 头部（拖拽把手） */}
        <div
          className="flex items-center justify-between gap-2 border-b border-slate-700/50 px-3.5 py-2.5 cursor-grab active:cursor-grabbing"
          onPointerDown={onPointerDown}
        >
          <div className="flex items-center gap-2 text-sm text-slate-200">
            {runningCount > 0 && <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />}
            <span className="font-medium">
              {runningCount > 0 ? `后台任务 · ${runningCount} 进行中` : '后台任务'}
            </span>
            <GripHorizontal className="w-3 h-3 text-slate-600" />
          </div>
          <div className="flex items-center gap-1">
            <ResetPositionBtn onClick={resetPos} onPointerDown={stopDrag} />
            <button
              onPointerDown={stopDrag}
              onClick={clearFinished}
              disabled={runningCount === list.length}
              className="rounded-md px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
              title="清除已完成"
            >
              清除已完成
            </button>
            <button
              onPointerDown={stopDrag}
              onClick={() => setCollapsed(true)}
              className="rounded-md p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
              title="折叠"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 任务列表 */}
        <div className="max-h-[60vh] overflow-y-auto styled-scrollbar px-3 py-2.5 space-y-2.5">
          {list.map((t) => {
            const titleEl = t.href ? (
              <Link
                href={t.href}
                className="hover:text-cyan-300 transition-colors truncate"
                title={t.title}
              >
                {t.title}
              </Link>
            ) : (
              <span className="truncate" title={t.title}>
                {t.title}
              </span>
            )
            return (
              <div key={t.id} className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-2.5">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5 min-w-0 text-xs font-medium text-slate-100">
                    <KindDot kind={t.kind} />
                    {titleEl}
                  </div>
                  <button
                    onClick={() => {
                      // 删除=停止后移除：有后端 onRemove（停止+删行）则先调用，再从面板移除
                      if (t.onRemove) void t.onRemove()
                      remove(t.id)
                    }}
                    className="shrink-0 text-slate-500 hover:text-red-400 transition-colors"
                    title={t.status === 'running' ? '停止并删除' : '删除'}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                <StreamingProgress
                  variant="compact"
                  status={t.status}
                  percent={t.percent}
                  logs={t.logs}
                  hint={t.stage}
                  onCancel={
                    t.onCancel
                      ? () => {
                          t.onCancel?.()
                          patch(t.id, { status: 'cancelled' })
                        }
                      : undefined
                  }
                />

                {t.status === 'error' && t.error && (
                  <p className="mt-1.5 text-[11px] text-red-300/90 leading-snug whitespace-pre-line">
                    {t.error}
                  </p>
                )}
                {t.status === 'done' && t.resultLabel && (
                  <p className="mt-1.5 text-[11px] text-emerald-300/80 truncate">{t.resultLabel}</p>
                )}
                {t.status === 'done' && !!((t.result as Record<string, unknown> | null)?.url) && (
                  <a
                    href={String((t.result as Record<string, unknown>).url)}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1.5 inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20 transition-colors"
                    download={(t.result as Record<string, unknown>).filename as string | undefined}
                  >
                    <Download className="w-3 h-3" />
                    下载成片
                  </a>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/** 任务种类的色点，快速区分不同类型后台任务。*/
function KindDot({ kind }: { kind: string }) {
  const color: Record<string, string> = {
    reencode: 'bg-violet-400',
    process: 'bg-amber-400',
    burn: 'bg-cyan-400',
    export_original: 'bg-cyan-400',
    realize: 'bg-emerald-400',
    jianying: 'bg-amber-400',
    transcribe: 'bg-sky-400',
    slice: 'bg-sky-400',
    tts: 'bg-pink-400',
    script_stock_compose: 'bg-cyan-400',
    workflow: 'bg-violet-400',
    external_ingest: 'bg-teal-400',
  }
  return <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', color[kind] ?? 'bg-slate-400')} />
}
