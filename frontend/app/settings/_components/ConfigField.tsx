'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import type { ConfigItem } from './types'

interface Props {
  cfgKey: string
  item: ConfigItem
  value: string
  onChange: (v: string) => void
}

export function ConfigField({ cfgKey, item, value, onChange }: Props) {
  const isPassword = cfgKey.includes('key') || cfgKey.includes('secret')
  const [showSecret, setShowSecret] = useState(false)

  if (item.type === 'select' && item.options) {
    let opts: string[] = []
    try { opts = JSON.parse(item.options) } catch { opts = [] }
    return (
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
      >
        {opts.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  }

  if (item.type === 'number') {
    return (
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
      />
    )
  }

  return (
    <div className="relative">
      <input
        type={isPassword ? (showSecret ? 'text' : 'password') : 'text'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isPassword ? '••••••••' : ''}
        className={`w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono ${isPassword ? 'pr-10' : ''}`}
      />
      {isPassword && (
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
  )
}
