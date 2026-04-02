'use client'

import Link from 'next/link'
import { ArrowLeft, Sparkles, ListVideo } from 'lucide-react'

type MatchPageHeaderProps = {
  mode: 'manual' | 'auto'
  onModeChange: (mode: 'manual' | 'auto') => void
  onOpenVideoResult?: () => void
}

export function MatchPageHeader({ mode, onModeChange, onOpenVideoResult }: MatchPageHeaderProps) {
  return (
    <div className="flex items-center gap-3">
      <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
        <ArrowLeft className="w-4 h-4" />
        首页
      </Link>
      <div className="w-px h-4 bg-slate-700" />
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-400" />
          文案匹配 · 配音 · 成片
        </h1>
        <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 border border-slate-700 px-1 py-1 text-xs">
          <button
            onClick={() => onModeChange('manual')}
            className={`px-3 py-0.5 rounded-full transition-colors ${
              mode === 'manual' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            手动匹配
          </button>
          <button
            onClick={() => onModeChange('auto')}
            className={`px-3 py-0.5 rounded-full transition-colors ${
              mode === 'auto' ? 'bg-emerald-500 text-slate-900' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            自动一键成片（实验）
          </button>
        </div>
      </div>
      {!!onOpenVideoResult && (
        <button
          onClick={onOpenVideoResult}
          className="ml-auto flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-800 bg-slate-900/30 hover:border-slate-600 text-sm text-slate-200 transition-colors"
        >
          <ListVideo className="w-4 h-4 text-indigo-300" />
          查看处理结果
        </button>
      )}
    </div>
  )
}
