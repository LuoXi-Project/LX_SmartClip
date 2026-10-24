'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
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
  /** 密钥申请入口：按当前厂商预设传入，展示「获取密钥 →」链接 */
  keyLink?: { label: string; href: string }
}

export function ApiSecretField({
  label,
  value,
  placeholder,
  onChange,
  dirty,
  saving,
  saved,
  onSave,
  description,
  keyLink,
}: Props) {
  const [showSecret, setShowSecret] = useState(false)

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs text-slate-400">{label}</label>
        {keyLink && (
          <a
            href={keyLink.href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-cyan-400 hover:text-cyan-300 hover:underline transition-colors"
          >
            获取密钥（{keyLink.label}）↗
          </a>
        )}
      </div>
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            type={showSecret ? 'text' : 'password'}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 pr-10 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
            placeholder={placeholder}
          />
          <button
            type="button"
            onClick={() => setShowSecret((s) => !s)}
            className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
            aria-label={showSecret ? '隐藏明文密钥' : '显示明文密钥'}
          >
            {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        </div>
        <SaveBtn dirty={dirty} saving={saving} saved={saved} onSave={onSave} />
      </div>
      {description ? <p className="text-xs text-slate-500">{description}</p> : null}
    </div>
  )
}

