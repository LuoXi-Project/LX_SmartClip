'use client'

import { useState, type ReactNode } from 'react'
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Loader2,
  Router,
  SkipForward,
  XCircle,
} from 'lucide-react'
import type { PlanStepState, PlanStepStatus, StudioMessage } from '@/lib/agent-types'

const STATUS_ICON: Record<PlanStepStatus, ReactNode> = {
  pending: <Circle className="w-3.5 h-3.5 text-slate-600" />,
  running: <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin" />,
  done: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
  failed: <XCircle className="w-3.5 h-3.5 text-red-400" />,
  skipped: <SkipForward className="w-3.5 h-3.5 text-amber-400" />,
}

export function StudioExecutionTrace({ msg }: { msg: Extract<StudioMessage, { type: 'execution_trace' }> }) {
  const [open, setOpen] = useState(true)
  const { route, routeReason, steps, progress } = msg
  const running = steps.some((s) => s.status === 'running')
  const doneCount = steps.filter((s) => s.status === 'done').length

  return (
    <div className="mr-4 rounded-xl border border-indigo-500/25 bg-indigo-500/5 overflow-hidden text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-indigo-500/10 transition-colors"
      >
        <Brain className="w-4 h-4 text-indigo-300 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-indigo-100 flex items-center gap-2">
            执行轨迹
            {running ? (
              <span className="text-[10px] text-violet-300 font-normal flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                进行中
              </span>
            ) : steps.length > 0 ? (
              <span className="text-[10px] text-slate-400 font-normal">
                {doneCount}/{steps.length} 完成
              </span>
            ) : null}
          </p>
          {route ? (
            <p className="text-[11px] text-indigo-200/70 truncate flex items-center gap-1 mt-0.5">
              <Router className="w-3 h-3 shrink-0" />
              {route}
              {routeReason ? ` · ${routeReason}` : ''}
            </p>
          ) : null}
        </div>
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
        )}
      </button>

      {open ? (
        <div className="px-3 pb-3 space-y-2 border-t border-indigo-500/15">
          {progress?.message ? (
            <div className="pt-2 space-y-1">
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span>长任务进度</span>
                {typeof progress.percent === 'number' ? (
                  <span>{progress.percent}%</span>
                ) : null}
              </div>
              {typeof progress.percent === 'number' ? (
                <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full bg-violet-500 transition-all duration-500"
                    style={{ width: `${Math.max(4, progress.percent)}%` }}
                  />
                </div>
              ) : null}
              <p className="text-[11px] text-slate-300 leading-relaxed">{progress.message}</p>
            </div>
          ) : null}

          {steps.length > 0 ? (
            <ol className="space-y-1.5 pt-1">
              {steps.map((step) => (
                <PlanStepRow key={step.id} step={step} />
              ))}
            </ol>
          ) : (
            <p className="text-[11px] text-slate-500 pt-2">等待规划步骤…</p>
          )}
        </div>
      ) : null}
    </div>
  )
}

function PlanStepRow({ step }: { step: PlanStepState }) {
  return (
    <li
      className={`flex items-start gap-2 rounded-lg px-2 py-1.5 border ${
        step.status === 'running'
          ? 'border-violet-500/30 bg-violet-500/10'
          : step.status === 'done'
            ? 'border-emerald-500/20 bg-emerald-500/5'
            : step.status === 'failed'
              ? 'border-red-500/20 bg-red-500/5'
              : 'border-slate-800/80 bg-slate-950/40'
      }`}
    >
      <span className="mt-0.5 shrink-0">{STATUS_ICON[step.status]}</span>
      <div className="min-w-0 flex-1">
        <p className="text-slate-200 font-medium text-[11px]">{step.title}</p>
        <p className="text-[10px] text-slate-500 font-mono">{step.tool}</p>
        {step.message ? (
          <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">{step.message}</p>
        ) : null}
      </div>
    </li>
  )
}

export function ReasoningBlock({
  content,
  streaming,
}: {
  content: string
  streaming?: boolean
}) {
  const [open, setOpen] = useState(true)
  if (!content.trim()) return null
  return (
    <div className="mr-6 rounded-lg border border-slate-800 bg-slate-950/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[10px] text-slate-500 hover:text-slate-400"
      >
        <Brain className="w-3 h-3 text-violet-400/80" />
        <span>思考过程</span>
        {streaming ? <Loader2 className="w-3 h-3 animate-spin text-violet-400" /> : null}
        {open ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
      </button>
      {open ? (
        <pre className="px-2.5 pb-2 text-[11px] text-slate-500 whitespace-pre-wrap font-sans leading-relaxed border-t border-slate-800/80">
          {content}
        </pre>
      ) : null}
    </div>
  )
}

/** mcp__<server>__<tool> → { serverId, tool }；非 MCP 工具返回 null */
export function parseMcpTool(
  name: string,
): { serverId: string; tool: string } | null {
  if (!name.startsWith('mcp__')) return null
  const parts = name.split('__', 3)
  if (parts.length !== 3) return null
  return { serverId: parts[1], tool: parts[2] }
}

export function ToolCallBlock({
  msg,
}: {
  msg: Extract<StudioMessage, { type: 'tool' }>
}) {
  const statusColor =
    msg.status === 'running'
      ? 'text-violet-300 border-violet-500/30 bg-violet-500/10'
      : msg.status === 'done'
        ? 'text-emerald-300 border-emerald-500/25 bg-emerald-500/5'
        : 'text-red-300 border-red-500/25 bg-red-500/5'
  const mcp = parseMcpTool(msg.name)

  return (
    <div className={`mr-4 rounded-lg border px-2.5 py-2 text-xs font-mono ${statusColor}`}>
      <div className="flex items-center gap-2">
        {msg.status === 'running' ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
        ) : msg.status === 'done' ? (
          <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
        ) : (
          <XCircle className="w-3.5 h-3.5 shrink-0" />
        )}
        <span className="font-semibold">{mcp ? mcp.tool : msg.name}</span>
        {mcp && (
          <span
            title={`外部 MCP 服务：${mcp.serverId}`}
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[9px] not-italic text-cyan-300"
          >
            MCP·{mcp.serverId}
          </span>
        )}
        {msg.round ? <span className="text-[10px] opacity-60">R{msg.round}</span> : null}
        <span className="text-[10px] opacity-70 ml-auto">{msg.status}</span>
      </div>
      {msg.summary ? (
        <p className="mt-1 text-[11px] font-sans text-slate-400 leading-snug">{msg.summary}</p>
      ) : msg.status === 'running' ? (
        <p className="mt-1 text-[11px] font-sans text-slate-500">执行中…</p>
      ) : null}
    </div>
  )
}
