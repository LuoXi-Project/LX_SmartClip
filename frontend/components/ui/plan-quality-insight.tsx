'use client'

import type { AutoEditPlanQualityApi } from '@/lib/api'
import { HoverTruncatedTooltip } from '@/components/ui/hover-truncated-tooltip'

const METRIC_LABELS: { key: keyof AutoEditPlanQualityApi['scores']; label: string; hint: string }[] = [
  { key: 'hook', label: 'Hook', hint: '开场 3 秒抓注意力能力' },
  { key: 'info_density', label: '信息密度', hint: '单位时长内有效信息传递' },
  { key: 'emotion_curve', label: '情绪波动', hint: '段落间情绪起伏与记忆点' },
  { key: 'rhythm', label: '节奏', hint: '段落时长与结构完整性' },
  { key: 'repetition', label: '新颖度', hint: '素材与文案重复越少越高' },
  { key: 'platform_fit', label: '平台适配', hint: '时长与结构贴近短视频传播习惯' },
]

function gradeTone(grade: string): string {
  if (grade === 'S') return 'text-amber-200 border-amber-400/50 bg-amber-500/10'
  if (grade === 'A') return 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10'
  if (grade === 'B') return 'text-cyan-200 border-cyan-500/40 bg-cyan-500/10'
  if (grade === 'C') return 'text-slate-300 border-slate-600/50 bg-slate-800/60'
  return 'text-orange-200 border-orange-500/40 bg-orange-500/10'
}

function MetricBar({ label, hint, value }: { label: string; hint: string; value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100)
  return (
    <div className="space-y-0.5" title={hint}>
      <div className="flex items-center justify-between gap-1">
        <span className="text-[10px] text-slate-400 truncate">{label}</span>
        <span className="text-[10px] tabular-nums text-slate-500">{pct}%</span>
      </div>
      <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-500 to-cyan-400"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export function PlanQualityInsightPanel({ quality }: { quality: AutoEditPlanQualityApi }) {
  const overallPct = Math.round(Math.max(0, Math.min(1, quality.overall)) * 100)

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2.5 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium text-slate-300">成片质量评分</p>
          <HoverTruncatedTooltip
            text={quality.summary}
            tooltipTitle="评分摘要"
            clamp={1}
            anchorClassName="text-[10px] text-slate-500 mt-0.5 cursor-help"
          />
        </div>
        <div
          className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 ${gradeTone(quality.grade)}`}
          title="综合分与等级（S/A/B/C/D）"
        >
          <span className="text-sm font-semibold tabular-nums">{overallPct}</span>
          <span className="text-[10px] font-semibold">{quality.grade}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        {METRIC_LABELS.map(({ key, label, hint }) => (
          <MetricBar
            key={key}
            label={label}
            hint={hint}
            value={quality.scores[key] ?? 0}
          />
        ))}
      </div>

      {quality.reasons?.length > 0 && (
        <div className="space-y-1 pt-0.5 border-t border-slate-800/80">
          <p className="text-[10px] text-slate-500">推荐理由</p>
          <ul className="space-y-1">
            {quality.reasons.map((reason, i) => (
              <li key={i} className="text-[10px] text-slate-400 leading-snug flex gap-1.5">
                <span className="text-cyan-500/70 flex-shrink-0">•</span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
