'use client'

import type { ReactNode, SyntheticEvent } from 'react'
import { ChevronDown } from 'lucide-react'

interface Props {
  title: ReactNode
  hint: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children: ReactNode
}

export function SettingsDetails({ title, hint, open, onOpenChange, children }: Props) {
  const controlled =
    typeof open === 'boolean' && typeof onOpenChange === 'function'
      ? {
          open,
          onToggle: (e: SyntheticEvent<HTMLDetailsElement>) => {
            const el = e.currentTarget
            onOpenChange(el.open)
          },
        }
      : {}

  return (
    <details
      className="group rounded-xl border border-slate-800 bg-slate-900/30 overflow-hidden"
      {...controlled}
    >
      <summary className="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none px-4 py-3 flex items-center justify-between bg-slate-900/20 hover:bg-slate-900/30">
        <span className="text-sm font-medium text-slate-200">{title}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">{hint}</span>
          <ChevronDown className="w-4 h-4 text-slate-500 transition-transform group-open:rotate-180" />
        </div>
      </summary>
      <div className="px-4 pb-4 pt-1 space-y-5">
        {children}
      </div>
    </details>
  )
}

