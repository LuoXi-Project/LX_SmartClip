'use client'

import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from 'lucide-react'
import clsx from 'clsx'
import type { PublishTask } from './types'

interface TaskListProps {
  tasks: PublishTask[]
  onCancel: (taskId: string) => void
}

const STATUS_META: Record<
  string,
  { label: string; icon: typeof CheckCircle2; className: string }
> = {
  pending: { label: '排队中', icon: Clock, className: 'text-slate-400' },
  running: { label: '执行中', icon: Loader2, className: 'text-indigo-300' },
  succeeded: { label: '全部成功', icon: CheckCircle2, className: 'text-emerald-400' },
  failed: { label: '失败', icon: XCircle, className: 'text-red-400' },
  partial: { label: '部分成功', icon: AlertCircle, className: 'text-amber-400' },
  cancelled: { label: '已取消', icon: XCircle, className: 'text-slate-500' },
}

/** 从 progress_json 提取当前进度文案。 */
function extractProgress(task: PublishTask): string {
  const prog = task.progress_json
  if (!prog || typeof prog !== 'object') return ''
  const p = prog as Record<string, unknown>
  const msg = typeof p.message === 'string' ? p.message : ''
  const platform = typeof p.platform === 'string' ? p.platform : ''
  const account = typeof p.account === 'string' ? p.account : ''
  const pct = typeof p.pct === 'number' ? p.pct : null
  const parts: string[] = []
  if (platform) parts.push(platform)
  if (account) parts.push(account)
  if (pct !== null) parts.push(`${pct}%`)
  if (msg) parts.push(msg)
  return parts.join(' · ')
}

export function TaskList({ tasks, onCancel }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-center">
        <p className="text-sm text-slate-500">暂无发布任务</p>
        <p className="text-xs text-slate-600 mt-1">完成账号登录后，在左侧创建发布任务</p>
      </section>
    )
  }

  return (
    <section className="flex flex-col rounded-lg border border-slate-800 bg-slate-900/40">
      <h2 className="text-sm font-semibold text-slate-200 px-3 py-2.5 border-b border-slate-800 shrink-0">
        发布记录
        <span className="text-xs text-slate-500 font-normal ml-1.5">{tasks.length}</span>
      </h2>
      <div className="flex-1 overflow-y-auto styled-scrollbar p-2 space-y-2 max-h-[400px]">
      {tasks.map((task) => {
        const meta = STATUS_META[task.status] || STATUS_META.pending
        const isRunning = task.running || task.status === 'running' || task.status === 'pending'
        const progressText = extractProgress(task)
        // 解析 result 各账号结果（platform/account: ✓/⊘/✗）
        let resultSummary = ''
        if (task.result_json && typeof task.result_json === 'object') {
          const r = task.result_json as {
            items?: Array<{ platform: string; account?: string; status: string; message?: string }>
          }
          if (r.items?.length) {
            resultSummary = r.items
              .map((it) => {
                const target = it.account ? `${it.platform}/${it.account}` : it.platform
                return `${target}: ${it.status === 'success' ? '✓' : it.status === 'skipped' ? '⊘' : '✗'}`
              })
              .join('  ')
          }
        }
        return (
          <div
            key={task.id}
            className="rounded-md border border-slate-800 bg-slate-900/40 p-3 space-y-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <meta.icon
                    className={clsx('w-3.5 h-3.5 shrink-0', meta.className, isRunning && 'animate-spin')}
                  />
                  <span className={clsx('text-xs font-medium', meta.className)}>{meta.label}</span>
                  {task.video_name && (
                    <span className="text-xs text-slate-400 truncate">{task.video_name}</span>
                  )}
                </div>
                {progressText && (
                  <div className="text-xs text-slate-400 mt-1 pl-5">{progressText}</div>
                )}
                {resultSummary && (
                  <div className="text-xs text-slate-500 mt-0.5 pl-5 font-mono">{resultSummary}</div>
                )}
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {isRunning && (
                  <button
                    type="button"
                    onClick={() => onCancel(task.id)}
                    className="inline-flex items-center gap-1 text-xs px-1.5 py-1 rounded border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-300 transition-colors"
                    title="取消该发布任务"
                  >
                    <XCircle className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>
            {task.log && (
              <pre className="text-[11px] text-slate-500 bg-slate-950/40 rounded p-2 max-h-24 overflow-auto styled-scrollbar whitespace-pre-wrap font-mono leading-relaxed">
                {task.log.slice(-500)}
              </pre>
            )}
            <div className="text-[10px] text-slate-600">
              {new Date(task.created_at).toLocaleString()}
            </div>
          </div>
        )
      })}
      </div>
    </section>
  )
}
