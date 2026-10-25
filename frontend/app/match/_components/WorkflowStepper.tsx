'use client'

import { Check, Lock, Loader2, ChevronRight } from 'lucide-react'
import clsx from 'clsx'

export type StepperStepStatus = 'todo' | 'active' | 'done' | 'locked'

export type StepperStep = {
  key: string
  label: string
  status: StepperStepStatus
  /** 状态摘要，如「12/14 段已匹配」 */
  detail?: string
  /** 当前步主按钮（仅 active 步显示） */
  ctaLabel?: string
  ctaLoading?: boolean
  ctaDisabled?: boolean
  onCta?: () => void
  /** 点击步骤滚动到的区块 id */
  anchorId?: string
}

/**
 * 五步向导条：把「文案 → 匹配 → 配音 → 字幕 → 导出」的工序外化为可见编排。
 * 状态由页面数据推导（非手动高亮）；已完成步骤可点击回看；当前步带唯一主 CTA。
 */
export function WorkflowStepper({ steps }: { steps: StepperStep[] }) {
  const scrollTo = (id?: string) => {
    if (!id) return
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3">
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-3">
        {steps.map((s, i) => {
          const done = s.status === 'done'
          const active = s.status === 'active'
          const locked = s.status === 'locked'
          return (
            <li key={s.key} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => scrollTo(s.anchorId)}
                title={locked ? '完成前置步骤后解锁' : s.detail}
                className={clsx(
                  'flex items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors',
                  s.anchorId && !locked && 'cursor-pointer hover:bg-slate-800/60',
                  locked && 'cursor-default opacity-45',
                )}
              >
                <span
                  className={clsx(
                    'w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 border',
                    done && 'bg-emerald-500/15 border-emerald-500/50 text-emerald-300',
                    active && 'bg-indigo-600 border-indigo-400 text-white',
                    !done && !active && 'border-slate-700 text-slate-500',
                  )}
                >
                  {done ? <Check className="w-3.5 h-3.5" /> : locked ? <Lock className="w-3 h-3" /> : i + 1}
                </span>
                <span className="flex flex-col gap-0.5">
                  <span
                    className={clsx(
                      'text-xs whitespace-nowrap',
                      active ? 'text-slate-100 font-medium' : done ? 'text-slate-300' : 'text-slate-500',
                    )}
                  >
                    {s.label}
                  </span>
                  {s.detail && (
                    <span className={clsx('text-[10px] whitespace-nowrap', active ? 'text-indigo-300' : 'text-slate-600')}>
                      {s.detail}
                    </span>
                  )}
                </span>
              </button>

              {active && s.ctaLabel && s.onCta && (
                <button
                  type="button"
                  onClick={s.onCta}
                  disabled={s.ctaLoading || s.ctaDisabled}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-medium transition-colors whitespace-nowrap"
                >
                  {s.ctaLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {s.ctaLabel}
                </button>
              )}

              {i < steps.length - 1 && (
                <ChevronRight className="w-3.5 h-3.5 text-slate-700 mx-0.5 hidden md:block shrink-0" />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
