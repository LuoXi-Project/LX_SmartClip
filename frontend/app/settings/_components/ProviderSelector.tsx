'use client'

import { useState } from 'react'
import { ChevronDown, CheckCircle2 } from 'lucide-react'
import type { ProviderPreset } from './types'

interface Props {
  providers: ProviderPreset[]
  selectedId: string
  onSelect: (p: ProviderPreset) => void
}

export function ProviderSelector({ providers, selectedId, onSelect }: Props) {
  const [open, setOpen] = useState(false)
  const selected = providers.find((p) => p.id === selectedId) ?? providers[providers.length - 1]

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 hover:border-indigo-500/60 transition-all text-sm"
      >
        <span className="text-base leading-none">{selected.logo}</span>
        <span className="text-slate-200 font-medium">{selected.name}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          className="absolute top-full left-0 mt-1 z-50 bg-[#13151c] border border-slate-700 rounded-xl shadow-2xl py-1 min-w-[200px]"
          onMouseLeave={() => setOpen(false)}
        >
          {providers.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p); setOpen(false) }}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-slate-800 transition-colors ${
                p.id === selectedId ? 'text-indigo-400' : 'text-slate-200'
              }`}
            >
              <span className="text-base leading-none">{p.logo}</span>
              <span>{p.name}</span>
              {p.id === selectedId && <CheckCircle2 className="w-3.5 h-3.5 ml-auto text-indigo-400" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
