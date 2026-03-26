'use client'

import { Search, X, SlidersHorizontal } from 'lucide-react'

export type SortKey = 'upload_at_desc' | 'upload_at_asc' | 'name_asc' | 'name_desc'
export type StatusFilter = 'all' | 'pending' | 'processing' | 'done' | 'error'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'upload_at_desc', label: '最新上传' },
  { value: 'upload_at_asc', label: '最早上传' },
  { value: 'name_asc', label: '名称 A→Z' },
  { value: 'name_desc', label: '名称 Z→A' },
]

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: '全部状态' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'done', label: '已完成' },
  { value: 'error', label: '错误' },
]

interface SearchBarProps {
  query: string
  onQueryChange: (v: string) => void
  sort: SortKey
  onSortChange: (v: SortKey) => void
  statusFilter: StatusFilter
  onStatusFilterChange: (v: StatusFilter) => void
  total: number
  filtered: number
}

export function SearchBar({
  query,
  onQueryChange,
  sort,
  onSortChange,
  statusFilter,
  onStatusFilterChange,
  total,
  filtered,
}: SearchBarProps) {
  return (
    <div className="mb-6 space-y-3">
      {/* Search input row */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="搜索素材名称…"
            className="w-full pl-9 pr-8 py-2.5 bg-slate-800/60 border border-slate-700/60 rounded-lg text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500/60 focus:bg-slate-800 transition-colors"
          />
          {query && (
            <button
              onClick={() => onQueryChange('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Sort */}
        <div className="relative">
          <SlidersHorizontal className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <select
            value={sort}
            onChange={(e) => onSortChange(e.target.value as SortKey)}
            className="pl-9 pr-8 py-2.5 bg-slate-800/60 border border-slate-700/60 rounded-lg text-sm text-slate-300 focus:outline-none focus:border-cyan-500/60 transition-colors appearance-none cursor-pointer"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value} className="bg-slate-900">
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Status filter tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_OPTIONS.map((o) => (
          <button
            key={o.value}
            onClick={() => onStatusFilterChange(o.value)}
            className={`px-3 py-1 text-xs rounded-full border transition-all ${
              statusFilter === o.value
                ? 'bg-cyan-600/80 border-cyan-500/60 text-white font-medium'
                : 'bg-slate-800/40 border-slate-700/40 text-slate-400 hover:border-slate-600 hover:text-slate-300'
            }`}
          >
            {o.label}
          </button>
        ))}

        {/* result count */}
        <span className="ml-auto text-xs text-slate-500">
          {query || statusFilter !== 'all' ? (
            <>
              找到 <span className="text-slate-300 font-medium">{filtered}</span> / {total} 个素材
            </>
          ) : (
            <>共 <span className="text-slate-300 font-medium">{total}</span> 个素材</>
          )}
        </span>
      </div>
    </div>
  )
}
