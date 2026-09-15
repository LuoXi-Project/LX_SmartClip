'use client'

import { useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
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
  const [showSecret, setShowSecret] = useState(false)
  const isSecret = type === 'password'
  const handleChange = (e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)

  return (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            type={isSecret && !showSecret ? 'password' : isSecret ? 'text' : type}
            value={value}
            onChange={handleChange}
            className={`w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono ${isSecret ? 'pr-10' : ''}`}
            placeholder={placeholder}
          />
          {isSecret && (
            <button
              type="button"
              onClick={() => setShowSecret((s) => !s)}
              className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
              aria-label={showSecret ? '隐藏明文密钥' : '显示明文密钥'}
            >
              {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          )}
        </div>
        <SaveBtn dirty={dirty} saving={saving} saved={saved} onSave={onSave} />
      </div>
    </div>
  )
}
