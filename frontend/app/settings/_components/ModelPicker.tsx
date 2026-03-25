'use client'

import { useState, useCallback } from 'react'
import { Loader2, RefreshCw, AlertCircle } from 'lucide-react'
import { fetchModels } from './api'

interface Props {
  value: string
  onChange: (v: string) => void
  baseUrl: string
  apiKey: string
  placeholder?: string
}

export function ModelPicker({ value, onChange, baseUrl, apiKey, placeholder }: Props) {
  const [models, setModels] = useState<string[]>([])
  const [fetching, setFetching] = useState(false)
  const [fetchError, setFetchError] = useState('')
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')

  const handleFetch = useCallback(async () => {
    if (!baseUrl || !apiKey) { setFetchError('请先填写 API 地址和密钥'); return }
    setFetching(true); setFetchError('')
    try {
      const list = await fetchModels(baseUrl, apiKey)
      if (list.length === 0) { setFetchError('未获取到模型列表') }
      else { setModels(list); setOpen(true); setFilter('') }
    } catch (e: unknown) {
      setFetchError(`获取失败: ${e instanceof Error ? e.message : String(e)}`)
    } finally { setFetching(false) }
  }, [baseUrl, apiKey])

  const filtered = filter
    ? models.filter((m) => m.toLowerCase().includes(filter.toLowerCase()))
    : models

  return (
    <div className="relative space-y-1">
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? '输入或选择模型 ID'}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
        />
        <button
          onClick={handleFetch}
          disabled={fetching}
          title="从 API 获取支持的模型列表"
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 hover:border-indigo-500 hover:text-indigo-300 text-slate-300 text-xs transition-all disabled:opacity-50 whitespace-nowrap"
        >
          {fetching
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <RefreshCw className="w-3.5 h-3.5" />}
          <span>获取模型</span>
        </button>
      </div>

      {fetchError && (
        <div className="flex items-center gap-1.5 text-xs text-red-400">
          <AlertCircle className="w-3 h-3" />{fetchError}
        </div>
      )}

      {open && models.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-[#13151c] border border-slate-700 rounded-xl shadow-2xl">
          <div className="sticky top-0 bg-[#13151c] px-3 py-2 border-b border-slate-800 flex items-center gap-2">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索模型..."
              className="flex-1 bg-slate-800 rounded-md px-2 py-1 text-xs outline-none focus:ring-1 ring-indigo-500 font-mono"
            />
            <span className="text-xs text-slate-500">{filtered.length}/{models.length}</span>
            <button onClick={() => setOpen(false)} className="text-xs text-slate-500 hover:text-slate-300 ml-1">✕</button>
          </div>
          <div className="max-h-52 overflow-y-auto">
            {filtered.map((m) => (
              <button
                key={m}
                onClick={() => { onChange(m); setOpen(false) }}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-800 transition-colors font-mono ${
                  m === value ? 'text-indigo-400 bg-indigo-500/5' : 'text-slate-300'
                }`}
              >
                {m === value && <span className="mr-1 text-indigo-400">✓</span>}{m}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
