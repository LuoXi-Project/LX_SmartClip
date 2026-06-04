'use client'

import { useState } from 'react'
import { ChevronDown, ChevronUp, CircleHelp, Sparkles } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import {
  getExportPathsForPlan,
  getPlanModeGuide,
  STUDIO_WORKFLOW_HINT,
} from '@/lib/studio-export-guide'

type StudioExportGuideProps = {
  plan?: AutoEditPlanApi | null
  /** 无方案时展示总览 */
  variant?: 'overview' | 'plan'
  compact?: boolean
}

export function StudioExportGuide({
  plan,
  variant = plan ? 'plan' : 'overview',
  compact = false,
}: StudioExportGuideProps) {
  const [open, setOpen] = useState(!compact)

  if (variant === 'overview') {
    return (
      <div className="rounded-xl border border-slate-700/80 bg-slate-900/50 p-3 space-y-2 text-xs text-slate-400">
        <p className="text-slate-300 font-medium flex items-center gap-1.5">
          <CircleHelp className="w-3.5 h-3.5 text-violet-400" />
          成片前先看：方案类型决定听感
        </p>
        <p className="leading-relaxed whitespace-pre-line">{STUDIO_WORKFLOW_HINT}</p>
        <div className="grid gap-2 sm:grid-cols-3 pt-1">
          {(['voiceover', 'original', 'auto'] as const).map((m) => {
            const g = getPlanModeGuide(m)
            return (
              <div
                key={m}
                className="rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-2"
              >
                <p className="text-slate-200 font-medium text-[11px]">{g.label}</p>
                <p className="text-[10px] text-slate-500 mt-0.5 leading-snug">{g.short}</p>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  if (!plan) return null

  const modeGuide = getPlanModeGuide(plan.mode)
  const paths = getExportPathsForPlan(plan)

  return (
    <div className="rounded-xl border border-indigo-500/25 bg-indigo-500/5 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-indigo-500/10 transition-colors"
      >
        <Sparkles className="w-4 h-4 text-indigo-300 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-indigo-100">成片怎么选？</p>
          <p className="text-[11px] text-indigo-200/70 truncate">
            当前方案：{modeGuide.label} · {modeGuide.short}
          </p>
        </div>
        {open ? (
          <ChevronUp className="w-4 h-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
        )}
      </button>

      {open ? (
        <div className="px-3 pb-3 space-y-3 border-t border-indigo-500/15">
          <section className="text-xs space-y-1.5">
            <p className="text-slate-400 uppercase tracking-wider text-[10px]">本方案成片逻辑</p>
            <ol className="list-decimal list-inside text-slate-300/90 space-y-0.5">
              {modeGuide.pipeline.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
            <p className="text-[11px] text-emerald-400/90">
              适合：{modeGuide.bestFor.join('、')}
            </p>
            {modeGuide.avoidWhen.length > 0 ? (
              <p className="text-[11px] text-amber-400/80">
                不太适合：{modeGuide.avoidWhen.join('、')}
              </p>
            ) : null}
          </section>

          <section className="space-y-2">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">导出路径对比</p>
            {paths.map((path) => (
              <div
                key={`${path.id}-${path.title}`}
                className={`rounded-lg border px-2.5 py-2 text-xs ${
                  path.recommended
                    ? 'border-violet-500/40 bg-violet-500/10'
                    : 'border-slate-700/80 bg-slate-900/40'
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-slate-100 font-medium flex items-center gap-1.5 flex-wrap">
                      {path.title}
                      {path.recommended ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-600/40 text-violet-100 border border-violet-500/30">
                          推荐
                        </span>
                      ) : null}
                    </p>
                    <p className="text-slate-500 text-[11px] mt-0.5">{path.subtitle}</p>
                  </div>
                </div>
                <ul className="mt-1.5 text-[11px] text-slate-400 list-disc list-inside space-y-0.5">
                  {path.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
                <p className="text-[10px] text-slate-500 mt-1">产出：{path.output}</p>
                {path.caution ? (
                  <p className="text-[10px] text-amber-400/90 mt-1.5 leading-relaxed">{path.caution}</p>
                ) : null}
              </div>
            ))}
          </section>
        </div>
      ) : null}
    </div>
  )
}
