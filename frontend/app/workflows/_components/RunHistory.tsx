'use client'

import { useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  ChevronDown,
  Download,
  History,
  Loader2,
  RotateCcw,
  Square,
  XCircle,
} from 'lucide-react'
import type { WorkflowRunSummary } from '@/lib/api'

const STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'border-slate-600 text-slate-300' },
  running: { label: '运行中', cls: 'border-cyan-500/60 text-cyan-300 bg-cyan-500/10' },
  done: { label: '已完成', cls: 'border-emerald-500/60 text-emerald-300 bg-emerald-500/10' },
  error: { label: '失败', cls: 'border-rose-500/60 text-rose-300 bg-rose-500/10' },
  cancelled: { label: '已取消', cls: 'border-amber-500/60 text-amber-300 bg-amber-500/10' },
}

function fmtTime(iso?: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

/** 运行历史列表：状态徽标 / 步骤链 / 成片下载 / 重跑 / 取消 */
export function RunHistory({
  runs,
  onRetry,
  onCancel,
  retrying,
}: {
  runs: WorkflowRunSummary[]
  onRetry: (runId: string) => void
  onCancel: (runId: string) => void
  retrying: string | null
}) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (!runs.length) {
    return (
      <div className="rounded-lg border border-dashed border-slate-800 p-6 text-center text-sm text-slate-500">
        暂无运行记录，选择一个工作流点击「一键运行」开始
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {runs.map((run) => {
        const meta = STATUS_META[run.status] || STATUS_META.pending
        const open = expanded === run.id
        return (
          <div key={run.id} className="rounded-lg border border-slate-800 bg-slate-900/50">
            <button
              type="button"
              className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left"
              onClick={() => setExpanded(open ? null : run.id)}
            >
              <History size={14} className="shrink-0 text-slate-500" />
              <span className="min-w-0 flex-1 truncate text-sm text-slate-200">
                {run.workflow_name || run.workflow_id}
              </span>
              <span className="hidden shrink-0 text-xs text-slate-500 sm:inline">
                {fmtTime(run.created_at)}
              </span>
              <span
                className={clsx(
                  'shrink-0 rounded-md border px-1.5 py-0.5 text-[11px]',
                  meta.cls,
                )}
              >
                {run.status === 'running' && (
                  <Loader2 size={10} className="mr-0.5 inline animate-spin" />
                )}
                {meta.label}
              </span>
              <ChevronDown
                size={14}
                className={clsx('shrink-0 text-slate-500 transition-transform', open && 'rotate-180')}
              />
            </button>

            {open && (
              <div className="space-y-2.5 border-t border-slate-800/70 px-3.5 py-3">
                {/* 步骤链 */}
                <div className="flex flex-wrap items-center gap-1.5">
                  {Object.entries(run.steps || {}).map(([name, status]) => (
                    <span
                      key={name}
                      className={clsx(
                        'flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px]',
                        status === 'done'
                          ? 'border-emerald-500/50 text-emerald-300'
                          : status === 'running'
                            ? 'border-cyan-500/50 text-cyan-300'
                            : status === 'error'
                              ? 'border-rose-500/50 text-rose-300'
                              : 'border-slate-700 text-slate-500',
                      )}
                    >
                      {status === 'done' ? (
                        <CheckCircle2 size={10} />
                      ) : status === 'error' ? (
                        <XCircle size={10} />
                      ) : null}
                      {name}
                    </span>
                  ))}
                </div>

                {!!run.error_message && (
                  <p className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1.5 text-xs text-rose-300">
                    {run.error_message}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-2">
                  {!!run.render_url && (
                    <a
                      href={run.render_url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1 rounded-md border border-emerald-500/50 bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-200 transition-colors hover:bg-emerald-500/25"
                    >
                      <Download size={12} /> 下载成片
                    </a>
                  )}
                  {run.status !== 'running' && run.status !== 'pending' && (
                    <button
                      type="button"
                      onClick={() => onRetry(run.id)}
                      disabled={retrying === run.id}
                      className="flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-slate-100 disabled:opacity-50"
                    >
                      {retrying === run.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <RotateCcw size={12} />
                      )}
                      同参数重跑
                    </button>
                  )}
                  {(run.status === 'running' || run.status === 'pending') && (
                    <button
                      type="button"
                      onClick={() => onCancel(run.id)}
                      className="flex items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200 transition-colors hover:bg-amber-500/20"
                    >
                      <Square size={11} /> 取消
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
