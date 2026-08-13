'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight, Loader2, XCircle } from 'lucide-react'
import type { AudioTaskResp } from '@/lib/api'

interface TaskListProps {
  tasks: AudioTaskResp[]
  onCancel: (taskId: string) => void
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  pending: { label: '排队中', cls: 'text-zinc-400' },
  running: { label: '进行中', cls: 'text-emerald-400' },
  succeeded: { label: '成功', cls: 'text-emerald-400' },
  failed: { label: '失败', cls: 'text-red-400' },
  partial: { label: '部分成功', cls: 'text-amber-400' },
  cancelled: { label: '已取消', cls: 'text-zinc-500' },
}

const JOB_TYPE_LABEL: Record<string, string> = {
  search: '搜索',
  download: '下载',
}

// 解析 progress_json 拿当前进度文案
function parseProgress(task: AudioTaskResp): { pct?: number; message?: string } {
  if (!task.progress_json) return {}
  try {
    const p = JSON.parse(task.progress_json)
    return { pct: p.pct, message: p.message }
  } catch {
    return {}
  }
}

// 解析 result_json 拿下载汇总
function parseDownloadResult(task: AudioTaskResp): string {
  if (!task.result_json) return ''
  try {
    const r = JSON.parse(task.result_json)
    if (r.downloaded !== undefined) {
      return `成功 ${r.downloaded}，失败 ${r.failed}，跳过 ${r.skipped || 0}`
    }
    if (Array.isArray(r.songs)) {
      return `找到 ${r.songs.length} 首`
    }
    return ''
  } catch {
    return ''
  }
}

export function TaskList({ tasks, onCancel }: TaskListProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const recent = tasks.slice(0, 10)

  const toggle = (id: string) => {
    setExpanded((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="rounded-xl border border-slate-700/50 bg-[#161922] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-200">爬取任务</h2>
        <span className="text-xs text-zinc-500">最近 {recent.length} 条</span>
      </div>

      {recent.length === 0 ? (
        <div className="py-6 text-center text-xs text-zinc-500">暂无任务</div>
      ) : (
        <div className="space-y-2">
          {recent.map((task) => {
            const sm = STATUS_META[task.status] || STATUS_META.pending
            const prog = parseProgress(task)
            const summary = parseDownloadResult(task)
            const isRunning = task.status === 'running' || task.status === 'pending'
            const isOpen = expanded.has(task.id)
            const payload = (() => {
              try {
                return JSON.parse(task.payload_json)
              } catch {
                return {}
              }
            })()
            return (
              <div
                key={task.id}
                className="rounded-md border border-slate-700/40 bg-[#0d0f14]/60 p-3"
              >
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggle(task.id)}
                    className="text-zinc-500 hover:text-zinc-300"
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] text-zinc-300">
                        {JOB_TYPE_LABEL[task.job_type] || task.job_type}
                      </span>
                      <span className="truncate text-sm text-zinc-200">
                        {payload.keyword || `${payload.songs?.length || 0} 首歌曲`}
                      </span>
                      <span className="text-[10px] text-zinc-500">{task.source}</span>
                      {isRunning && prog.pct !== undefined && (
                        <span className="text-[10px] text-emerald-400">{prog.pct}%</span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-zinc-500">
                      {isRunning
                        ? prog.message || '处理中…'
                        : summary || sm.label}
                      {' · '}
                      {new Date(task.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-medium ${sm.cls}`}>{sm.label}</span>
                    {isRunning && (
                      <>
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-400" />
                        <button
                          onClick={() => onCancel(task.id)}
                          title="取消"
                          className="rounded p-1 text-zinc-400 hover:bg-red-500/20 hover:text-red-400"
                        >
                          <XCircle className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* 进度条 */}
                {isRunning && prog.pct !== undefined && (
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-700/50">
                    <div
                      className="h-full bg-emerald-500 transition-all"
                      style={{ width: `${prog.pct}%` }}
                    />
                  </div>
                )}

                {/* 展开日志 */}
                {isOpen && task.log && (
                  <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-black/40 p-2 text-[10px] leading-relaxed text-zinc-400">
                    {task.log.slice(-2000)}
                  </pre>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
