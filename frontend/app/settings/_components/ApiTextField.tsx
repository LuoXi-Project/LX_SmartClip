'use client'

import type { ReactNode } from 'react'
import { SaveBtn } from './SaveBtn'

interface Props {
  label: string
  value: string
  placeholder?: string
  onChange: (v: string) => void
  dirty: boolean
  saving: boolean
  saved: boolean
  onSave: () => void
  description?: ReactNode
}

export function ApiTextField({
  label,
  value,
  placeholder,
  onChange,
  dirty,
  saving,
  saved,
  onSave,
  description,
}: Props) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
          placeholder={placeholder}
        />
        <SaveBtn dirty={dirty} saving={saving} saved={saved} onSave={onSave} />
      </div>
      {description ? <p className="text-xs text-slate-500">{description}</p> : null}
    </div>
  )
}

