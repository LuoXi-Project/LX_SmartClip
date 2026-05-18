'use client'

import { buildRulerTicks, fmtTimeShort, pickTickStep } from './utils'

export function TimelineRuler({
  totalDuration,
  pxPerSec,
  labelWidth = 88,
}: {
  totalDuration: number
  pxPerSec: number
  labelWidth?: number
}) {
  const step = pickTickStep(totalDuration, pxPerSec)
  const ticks = buildRulerTicks(totalDuration, step)
  const width = Math.max(totalDuration * pxPerSec, 120)

  return (
    <div className="flex border-b border-slate-800/90 bg-slate-950/80" style={{ minHeight: 28 }}>
      <div
        className="flex-shrink-0 border-r border-slate-800/80 text-[10px] text-slate-600 flex items-end pb-1 pl-2"
        style={{ width: labelWidth }}
      >
        时间
      </div>
      <div className="relative flex-1 overflow-hidden" style={{ height: 28 }}>
        <div className="relative h-full" style={{ width }}>
          {ticks.map((t) => (
            <div
              key={t}
              className="absolute top-0 bottom-0 border-l border-slate-700/50"
              style={{ left: t * pxPerSec }}
            >
              <span className="absolute top-1 left-1 text-[9px] tabular-nums text-slate-500 whitespace-nowrap">
                {fmtTimeShort(t)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
