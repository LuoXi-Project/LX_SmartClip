'use client'

import { useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  XCircle,
  Loader2,
  SkipForward,
  X,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'

/**
 * 统一的流式进度展示组件。
 *
 * 从 app/match/_components/AutoEditPlannerSection.tsx:576-676 的「黄金标准」面板抽出，
 * 同时融合 app/process/ProcessPageClient.tsx 的多步卡片形态。两种用法：
 *
 *  - 单流线性：传入 `stages`（阶段 chips）+ `percent` + `logs` + `hint`。
 *  - 多步并行：传入 `steps` + `stepStates`（每步独立状态）。
 *
 * 设计目标：让等待感觉像在推进 —— 滚动日志、阶段推进、计时、indeterminate 动画（而非
 * 假百分比卡死）、可取消。`variant="compact"` 供 toast / task-hub 紧凑卡片使用。
 */

export type ProgressStatus = 'idle' | 'running' | 'done' | 'error' | 'cancelled'

export interface StageDef {
  key: string
  label: string
}

export interface StepDef extends StageDef {
  desc?: string
}

export interface StepState {
  status: ProgressStatus | 'skip'
  message?: string
  detail?: Record<string, unknown>
}

export interface StreamingProgressProps {
  status: ProgressStatus
  /** 当前阶段 key（单流模式下高亮对应 stage chip）*/
  stage?: string
  /** 阶段定义（单流模式）。若提供则渲染阶段 chips 行。*/
  stages?: StageDef[]
  /** 多步定义（多步模式）。提供后渲染为每步一张状态卡。*/
  steps?: StepDef[]
  /** 多步模式下各步的状态。*/
  stepStates?: Record<string, StepState>
  /** 百分比；null 表示无真实进度，渲染 indeterminate 动画。*/
  percent?: number | null
  /** 流式日志行（核心「流式感」来源）。*/
  logs?: string[]
  /** 已耗时（秒）。*/
  elapsedSec?: number
  /** 人话描述：当前在干嘛（比百分比更有效）。*/
  hint?: string
  /** 取消回调；提供则渲染取消按钮。*/
  onCancel?: () => void
  /** inline（完整面板，默认）/ compact（toast、task-hub 紧凑卡）。*/
  variant?: 'inline' | 'compact'
  /** 主色：cyan（默认，对齐 confirm-dialog 主操作）/ emerald。*/
  accent?: 'cyan' | 'emerald'
  /** compact 模式下是否默认展开日志。*/
  defaultLogOpen?: boolean
  className?: string
}

const ACCENT = {
  cyan: {
    bar: 'bg-cyan-500',
    border: 'border-cyan-500/30',
    chipActive: 'border-cyan-400 bg-cyan-500/20 text-cyan-200',
    text: 'text-cyan-300',
  },
  emerald: {
    bar: 'bg-emerald-500',
    border: 'border-emerald-500/30',
    chipActive: 'border-emerald-400 bg-emerald-500/20 text-emerald-200',
    text: 'text-emerald-300',
  },
} as const

const PASSED_CHIP = 'border-cyan-400/60 bg-cyan-500/10 text-cyan-200'
const PENDING_CHIP = 'border-slate-700 bg-slate-900/70 text-slate-500'

const STATUS_LABEL: Record<ProgressStatus, string> = {
  idle: '待开始',
  running: '进行中',
  done: '已完成',
  error: '失败',
  cancelled: '已取消',
}

function StepIcon({ s }: { s: StepState['status'] }) {
  if (s === 'running') return <Loader2 className="w-4 h-4 text-amber-400 animate-spin shrink-0" />
  if (s === 'done') return <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
  if (s === 'error') return <XCircle className="w-4 h-4 text-red-400 shrink-0" />
  if (s === 'skip') return <SkipForward className="w-4 h-4 text-slate-600 shrink-0" />
  return <div className="w-4 h-4 rounded-full border-2 border-slate-700 shrink-0" />
}

/** 百分比条：有真实值走渐增填充，无值走 indeterminate 亮带循环。*/
function ProgressBar({
  percent,
  failed,
  accent,
}: {
  percent: number | null
  failed: boolean
  accent: keyof typeof ACCENT
}) {
  const fill = failed ? 'bg-red-500' : ACCENT[accent].bar
  if (percent === null || percent === undefined) {
    return (
      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden relative">
        <div
          className={clsx('absolute top-0 h-full rounded-full animate-hf-indeterminate', fill)}
        />
      </div>
    )
  }
  return (
    <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
      <div
        className={clsx('h-full transition-all duration-500', fill)}
        style={{ width: `${Math.max(0, Math.min(100, percent))}%` }}
      />
    </div>
  )
}

export function StreamingProgress({
  status,
  stage,
  stages,
  steps,
  stepStates,
  percent = null,
  logs = [],
  elapsedSec = 0,
  hint,
  onCancel,
  variant = 'inline',
  accent = 'cyan',
  defaultLogOpen = false,
  className,
}: StreamingProgressProps) {
  const [logOpen, setLogOpen] = useState(defaultLogOpen)
  const isRunning = status === 'running'
  const failed = status === 'error'
  const a = ACCENT[accent]

  // ── compact：紧凑卡片（toast / task-hub）────────────────────────────────
  if (variant === 'compact') {
    const lastLog = logs.length ? logs[logs.length - 1] : ''
    return (
      <div className={clsx('w-full space-y-2', className)}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            {isRunning && <Loader2 className={clsx('w-3.5 h-3.5 animate-spin shrink-0', a.text)} />}
            {status === 'done' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
            {failed && <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />}
            <span className="text-xs text-slate-300 truncate">
              {hint || STATUS_LABEL[status]}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {percent !== null && (
              <span className={clsx('text-[11px]', failed ? 'text-red-400' : 'text-slate-400')}>
                {failed ? '失败' : `${percent}%`}
              </span>
            )}
            {logs.length > 0 && (
              <button
                onClick={() => setLogOpen((v) => !v)}
                className="text-slate-500 hover:text-slate-300 transition-colors"
              >
                {logOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>
            )}
            {onCancel && isRunning && (
              <button onClick={onCancel} className="text-slate-500 hover:text-red-400 transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
        {(isRunning || status === 'done' || failed) && (
          <ProgressBar percent={percent} failed={failed} accent={accent} />
        )}
        {logOpen && logs.length > 0 && (
          <div className="max-h-24 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1.5 space-y-0.5">
            {logs.map((line, i) => (
              <p key={`${line}-${i}`} className="text-[11px] text-slate-400 leading-5 truncate">
                {line}
              </p>
            ))}
          </div>
        )}
        {!logOpen && lastLog && (
          <p className="text-[11px] text-slate-500 truncate">{lastLog}</p>
        )}
      </div>
    )
  }

  // ── inline：完整面板 ────────────────────────────────────────────────────
  return (
    <div
      className={clsx(
        'rounded-xl border bg-slate-950/60 px-4 py-3 space-y-2',
        failed ? 'border-red-500/30' : a.border,
        className,
      )}
    >
      {/* 阶段标签 + 百分比 + 进度条 */}
      <div className="space-y-1.5 text-[11px]">
        <div className="flex items-center justify-between">
          <span className="text-slate-300">
            {stages && stages.length
              ? stages.find((s) => s.key === stage)?.label || STATUS_LABEL[status]
              : stage || STATUS_LABEL[status]}
          </span>
          <span className={failed ? 'text-red-400' : 'text-slate-400'}>
            {failed ? '失败' : percent !== null ? `${percent}%` : isRunning ? '处理中' : ''}
          </span>
        </div>
        {(isRunning || status === 'done' || failed) && (
          <ProgressBar percent={percent} failed={failed} accent={accent} />
        )}
      </div>

      {/* 计时 + 实时进度 / 取消 */}
      <div className="flex items-center justify-between text-xs">
        <span className={clsx('flex items-center gap-1.5', a.text)}>
          {isRunning && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {isRunning ? '实时进度' : status === 'done' ? '已完成' : failed ? '出错' : '记录'}
        </span>
        <div className="flex items-center gap-3">
          <span className="text-slate-500">
            {isRunning ? `已等待 ${elapsedSec}s` : `总耗时约 ${elapsedSec}s`}
          </span>
          {onCancel && isRunning && (
            <button
              onClick={onCancel}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-0.5 text-[11px] text-slate-400 hover:text-red-300 hover:border-red-500/50 transition-colors"
            >
              <X className="w-3 h-3" /> 取消
            </button>
          )}
        </div>
      </div>

      {/* 阶段 chips（单流模式）*/}
      {stages && stages.length > 0 && (
        <StepChips stages={stages} currentStage={stage} status={status} accentActive={a.chipActive} />
      )}

      {/* 多步卡片（多步模式）*/}
      {steps && steps.length > 0 && stepStates && (
        <div className="space-y-1.5">
          {steps.map((s) => {
            const ss = stepStates[s.key] ?? { status: 'idle' as const }
            return (
              <div
                key={s.key}
                className={clsx(
                  'flex items-start gap-2 rounded-lg border px-2.5 py-1.5',
                  ss.status === 'running' && 'border-amber-500/40 bg-amber-500/5',
                  ss.status === 'done' && 'border-emerald-500/40 bg-emerald-500/5',
                  ss.status === 'error' && 'border-red-500/40 bg-red-500/5',
                  (ss.status === 'idle' || ss.status === 'skip') && 'border-slate-800 bg-slate-900/30',
                )}
              >
                <div className="pt-0.5">
                  <StepIcon s={ss.status} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-slate-200">{s.label}</span>
                    {ss.message && <span className="text-[11px] text-slate-500 truncate">{ss.message}</span>}
                  </div>
                  {s.desc && <p className="text-[11px] text-slate-500">{s.desc}</p>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 人话 hint */}
      {hint && <p className="text-[11px] text-slate-400">{hint}</p>}

      {/* 流式日志盒 */}
      {logs.length > 0 && (
        <div className="max-h-28 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
          {logs.map((line, i) => (
            <p key={`${line}-${i}`} className="text-[11px] text-slate-400 leading-5">
              {line}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

/** 阶段 chips：根据当前 stage 计算 active/passed/pending。*/
function StepChips({
  stages,
  currentStage,
  status,
  accentActive,
}: {
  stages: StageDef[]
  currentStage?: string
  status: ProgressStatus
  accentActive: string
}) {
  const currentIdx = stages.findIndex((s) => s.key === currentStage)
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stages.map((s, idx) => {
        const active = idx === currentIdx && status === 'running'
        const passed =
          (currentIdx >= 0 && idx < currentIdx) || status === 'done' || status === 'cancelled'
        return (
          <span
            key={s.key}
            className={clsx(
              'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] transition-colors',
              active ? accentActive : passed ? PASSED_CHIP : PENDING_CHIP,
            )}
          >
            {idx + 1}. {s.label}
          </span>
        )
      })}
      {status === 'error' && (
        <span className="inline-flex items-center rounded-full border border-red-400/60 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300">
          失败
        </span>
      )}
    </div>
  )
}
