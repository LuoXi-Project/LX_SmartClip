'use client'

import type { ChangeEvent, ReactNode } from 'react'
import { SaveBtn } from './SaveBtn'

interface Props {
  label: ReactNode
  type?: 'text' | 'password' | 'email' | 'number'
  value: string
  placeholder?: string
  onChange: (v: string) => void
  dirty: boolean
  saving: boolean
  saved: boolean
  onSave: () => void
}

export function LabeledInputRow({
  label,
  type = 'text',
  value,
  placeholder,
  onChange,
  dirty,
  saving,
  saved,
  onSave,
}: Props) {
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)

  return (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2">
        <input
          type={type}
          value={value}
          onChange={handleChange}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
          placeholder={placeholder}
        />
        <SaveBtn dirty={dirty} saving={saving} saved={saved} onSave={onSave} />
      </div>
    </div>
  )
}

