'use client'

import type { ConfigItem } from './types'

interface Props {
  cfgKey: string
  item: ConfigItem
  value: string
  onChange: (v: string) => void
}

export function ConfigField({ cfgKey, item, value, onChange }: Props) {
  const isPassword = cfgKey.includes('key') || cfgKey.includes('secret')

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
    <input
      type={isPassword ? 'password' : 'text'}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={isPassword ? '••••••••' : ''}
      className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
    />
  )
}
