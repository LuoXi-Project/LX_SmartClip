'use client'

import clsx from 'clsx'
import Link from 'next/link'
import { Loader2, ChevronUp, ChevronDown, X, ListChecks, Download } from 'lucide-react'

import { useTaskStore } from '@/lib/task-store'
import { StreamingProgress } from '@/components/ui/streaming-progress'

/**
 * 全局后台任务面板。
 *
 * 挂载在 app/layout.tsx（ToastProvider 内）。订阅 lib/task-store，把所有后台 job 的
 * 实时进度集中展示在右下角：支持多任务并行、折叠为角标、展开看流式日志、终止/清除。
 * 无任务时不渲染。
 */
export function TaskHub() {
  const tasks = useTaskStore((s) => s.tasks)
  const collapsed = useTaskStore((s) => s.collapsed)
  const setCollapsed = useTaskStore((s) => s.setCollapsed)
  const clearFinished = useTaskStore((s) => s.clearFinished)
  const remove = useTaskStore((s) => s.remove)
  const patch = useTaskStore((s) => s.patch)

  const list = Object.values(tasks).sort((a, b) => b.createdAt - a.createdAt)
  const runningCount = list.filter((t) => t.status === 'running').length

  if (list.length === 0) return null

  // 折叠态：右下角角标
  if (collapsed) {
    return (
      <div className="fixed bottom-6 right-6 z-[1000]">
        <button
          onClick={() => setCollapsed(false)}
          className="group flex items-center gap-2 rounded-full border border-cyan-500/40 bg-[#161922]/95 px-3.5 py-2 text-sm text-cyan-200 shadow-xl shadow-black/40 backdrop-blur-md hover:border-cyan-400 transition-colors"
          title="展开任务面板"
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
        </button>
      </div>
    )
  }

  // 展开态：面板
  return (
    <div className="fixed bottom-6 right-6 z-[1000] w-[340px] max-w-[calc(100vw-3rem)]">
      <div className="rounded-2xl border border-slate-700/60 bg-[#161922]/95 shadow-2xl shadow-black/60 backdrop-blur-md overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between gap-2 border-b border-slate-700/50 px-3.5 py-2.5">
          <div className="flex items-center gap-2 text-sm text-slate-200">
            {runningCount > 0 && <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />}
            <span className="font-medium">
              {runningCount > 0 ? `后台任务 · ${runningCount} 进行中` : '后台任务'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={clearFinished}
              disabled={runningCount === list.length}
              className="rounded-md px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 disabled:opacity-40 disabled:hover:bg-transparent transition-colors"
              title="清除已完成"
            >
              清除已完成
            </button>
            <button
              onClick={() => setCollapsed(true)}
              className="rounded-md p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
              title="折叠"
            >
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 任务列表 */}
        <div className="max-h-[60vh] overflow-y-auto px-3 py-2.5 space-y-2.5">
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
                  {t.status !== 'running' && (
                    <button
                      onClick={() => remove(t.id)}
                      className="shrink-0 text-slate-500 hover:text-slate-300 transition-colors"
                      title="移除"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
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
    burn: 'bg-cyan-400',
    export_original: 'bg-cyan-400',
    realize: 'bg-emerald-400',
    jianying: 'bg-amber-400',
    transcribe: 'bg-sky-400',
    slice: 'bg-sky-400',
    tts: 'bg-pink-400',
  }
  return <span className={clsx('w-1.5 h-1.5 rounded-full shrink-0', color[kind] ?? 'bg-slate-400')} />
}
