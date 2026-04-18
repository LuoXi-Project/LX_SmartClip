'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
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
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})
  const anchorRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Cache models per (baseUrl, apiKey) to reduce repeated requests.
  const cacheRef = useRef<Map<string, string[]>>(new Map())
  // Abort in-flight request to prevent old results overwriting new ones.
  const abortRef = useRef<AbortController | null>(null)
  // Monotonic request id to fully guard against race conditions.
  const requestIdRef = useRef(0)

  const handleFetch = useCallback(async () => {
    const safeBaseUrl = baseUrl?.trim() ?? ''
    const safeApiKey = apiKey?.trim() ?? ''
    if (!safeBaseUrl || !safeApiKey) { setFetchError('请先填写 API 地址和密钥'); return }

    const isVolcArkMultimodalEmb =
      safeBaseUrl.includes('volces.com') && safeBaseUrl.includes('embeddings/multimodal')
    if (isVolcArkMultimodalEmb) {
      setFetchError('火山方舟多模态向量无通用「模型列表」接口，请在控制台复制模型 ID 后手动输入')
      setModels([])
      setOpen(false)
      return
    }

    const cacheKey = `${safeBaseUrl}::${safeApiKey}`
    const cached = cacheRef.current.get(cacheKey)
    if (cached) {
      setModels(cached)
      setFetchError('')
      setOpen(true)
      setFilter('')
      return
    }

    const requestId = ++requestIdRef.current
    setFetching(true)
    setFetchError('')
    setOpen(false)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const list = await fetchModels(safeBaseUrl, safeApiKey, { signal: controller.signal })
      if (requestId !== requestIdRef.current) return

      if (list.length === 0) {
        setFetchError('未获取到模型列表')
        setModels([])
        setOpen(false)
      } else {
        cacheRef.current.set(cacheKey, list)
        setModels(list)
        setOpen(true)
        setFilter('')
      }
    } catch (e: unknown) {
      if (requestId !== requestIdRef.current) return

      // Ignore abort errors silently; they are expected when user retries quickly.
      if (e instanceof Error && (e.name === 'AbortError' || e.message.toLowerCase().includes('aborted'))) {
        return
      }

      setFetchError(`获取失败: ${e instanceof Error ? e.message : String(e)}`)
      setModels([])
      setOpen(false)
    } finally {
      if (requestId === requestIdRef.current) setFetching(false)
    }
  }, [baseUrl, apiKey])

  // Recalculate dropdown position whenever it opens
  useEffect(() => {
    if (!open || !anchorRef.current) return

    const updatePosition = () => {
      const rect = anchorRef.current?.getBoundingClientRect()
      if (!rect) return
      setDropdownStyle({
        position: 'fixed',
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        zIndex: 9999,
      })
    }

    updatePosition()
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('resize', updatePosition)
    return () => {
      window.removeEventListener('scroll', updatePosition, true)
      window.removeEventListener('resize', updatePosition)
    }
  }, [open])

  // Close on outside click — exclude both anchor and portal dropdown
  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node
      const inAnchor = anchorRef.current?.contains(target) ?? false
      const inDropdown = dropdownRef.current?.contains(target) ?? false
      if (!inAnchor && !inDropdown) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const f = filter.trim().toLowerCase()
  const filtered = f ? models.filter((m) => m.toLowerCase().includes(f)) : models

  const dropdown = open && models.length > 0 ? (
    <div
      ref={dropdownRef}
      style={dropdownStyle}
      className="bg-[#13151c] border border-slate-700 rounded-xl shadow-2xl"
    >
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
  ) : null

  return (
    <div className="space-y-1">
      <div ref={anchorRef} className="flex gap-2">
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

      {typeof document !== 'undefined' && createPortal(dropdown, document.body)}
    </div>
  )
}
