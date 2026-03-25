'use client'

import { Loader2, CheckCircle2, Save } from 'lucide-react'

interface Props {
  cfgKey?: string
  dirty: boolean
  saving: boolean
  saved: boolean
  onSave: () => void
}

export function SaveBtn({ dirty, saving, saved, onSave }: Props) {
  return (
    <button
      onClick={onSave}
      disabled={!dirty || saving}
      className={`px-3 py-2 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-all ${
        saved
          ? 'bg-emerald-600/20 text-emerald-300 border border-emerald-600/30'
          : dirty
          ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-900/30'
          : 'bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700'
      }`}
    >
      {saving
        ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
        : saved
        ? <CheckCircle2 className="w-3.5 h-3.5" />
        : <Save className="w-3.5 h-3.5" />}
      {saved ? '已保存' : '保存'}
    </button>
  )
}
