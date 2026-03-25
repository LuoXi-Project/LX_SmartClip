'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import {
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  Loader2,
  RefreshCw,
  Save,
  Settings2,
  AlertCircle,
} from 'lucide-react'
import apiClient from '@/lib/api'

interface ConfigItem {
  value: string
  type: string
  label: string
  options: string | null
}

type ConfigMap = Record<string, ConfigItem>

interface ProviderPreset {
  id: string
  name: string
  logo: string
  baseUrl: string
  defaultModel?: string
}

const VLM_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',           logo: '🟢', baseUrl: 'https://api.openai.com/v1',           defaultModel: 'gpt-4o' },
  { id: 'deepseek',    name: 'DeepSeek',          logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',         defaultModel: 'deepseek-chat' },
  { id: 'iflowai',    name: 'iFlow AI',           logo: '🟣', baseUrl: 'https://api.iflow.ai/v1',            defaultModel: '' },
  { id: 'siliconflow', name: 'SiliconFlow',       logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1',      defaultModel: 'Qwen/Qwen2-VL-72B-Instruct' },
  { id: 'zhipuai',    name: '智谱 AI',            logo: '🔴', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', defaultModel: 'glm-4v' },
  { id: 'moonshot',   name: 'Moonshot (Kimi)',    logo: '🌙', baseUrl: 'https://api.moonshot.cn/v1',         defaultModel: 'moonshot-v1-8k' },
  { id: 'custom',     name: '自定义',             logo: '⚙️', baseUrl: '' },
]

const EMBEDDING_PROVIDERS: ProviderPreset[] = [
  { id: 'openai',      name: 'OpenAI',      logo: '🟢', baseUrl: 'https://api.openai.com/v1',      defaultModel: 'text-embedding-3-small' },
  { id: 'siliconflow', name: 'SiliconFlow', logo: '🟠', baseUrl: 'https://api.siliconflow.cn/v1', defaultModel: 'BAAI/bge-m3' },
  { id: 'deepseek',    name: 'DeepSeek',    logo: '🔵', baseUrl: 'https://api.deepseek.com/v1',   defaultModel: '' },
  { id: 'custom',      name: '自定义',      logo: '⚙️', baseUrl: '' },
]

async function fetchModels(baseUrl: string, apiKey: string): Promise<string[]> {
  const data = await apiClient.post<unknown, { models: string[] }>('/api/config/models', {
    base_url: baseUrl,
    api_key: apiKey,
  })
  return Array.isArray(data?.models) ? data.models : []
}

function ProviderSelector({ providers, selectedId, onSelect }: {
  providers: ProviderPreset[]
  selectedId: string
  onSelect: (p: ProviderPreset) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = providers.find((p) => p.id === selectedId) ?? providers[providers.length - 1]
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 hover:border-indigo-500/60 transition-all text-sm"
      >
        <span className="text-base leading-none">{selected.logo}</span>
        <span className="text-slate-200 font-medium">{selected.name}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          className="absolute top-full left-0 mt-1 z-50 bg-[#13151c] border border-slate-700 rounded-xl shadow-2xl py-1 min-w-[200px]"
          onMouseLeave={() => setOpen(false)}
        >
          {providers.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p); setOpen(false) }}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-slate-800 transition-colors ${
                p.id === selectedId ? 'text-indigo-400' : 'text-slate-200'
              }`}
            >
              <span className="text-base leading-none">{p.logo}</span>
              <span>{p.name}</span>
              {p.id === selectedId && <CheckCircle2 className="w-3.5 h-3.5 ml-auto text-indigo-400" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ModelPicker({ value, onChange, baseUrl, apiKey, placeholder }: {
  value: string
  onChange: (v: string) => void
  baseUrl: string
  apiKey: string
  placeholder?: string
}) {
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

  const filtered = filter ? models.filter((m) => m.toLowerCase().includes(filter.toLowerCase())) : models

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
          {fetching ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          <span>获取模型</span>
        </button>
      </div>
      {fetchError && (
        <div className="flex items-center gap-1.5 text-xs text-red-400"><AlertCircle className="w-3 h-3" />{fetchError}</div>
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

function ConfigField({ cfgKey, item, value, onChange }: {
  cfgKey: string
  item: ConfigItem
  value: string
  onChange: (v: string) => void
}) {
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

function SaveBtn({ dirty, saving, saved, onSave }: {
  cfgKey?: string
  dirty: boolean
  saving: boolean
  saved: boolean
  onSave: () => void
}) {
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
      {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
        : saved ? <CheckCircle2 className="w-3.5 h-3.5" />
        : <Save className="w-3.5 h-3.5" />}
      {saved ? '已保存' : '保存'}
    </button>
  )
}

export default function SettingsPage() {
  const [config, setConfig] = useState<ConfigMap>({})
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')
  const [vlmProvider, setVlmProvider] = useState('custom')
  const [embProvider, setEmbProvider] = useState('custom')

  useEffect(() => {
    apiClient.get<unknown, ConfigMap>('/api/config')
      .then((data) => {
        setConfig(data || {})
        const initial: Record<string, string> = {}
        Object.entries(data || {}).forEach(([k, v]) => { initial[k] = v.value })
        setEdits(initial)
        const savedVlmUrl = data?.vlm_base_url?.value ?? ''
        const matchedVlm = VLM_PROVIDERS.find((p) => p.id !== 'custom' && p.baseUrl && savedVlmUrl.startsWith(p.baseUrl.split('/v1')[0]))
        if (matchedVlm) setVlmProvider(matchedVlm.id)
        const savedEmbUrl = data?.embedding_base_url?.value ?? ''
        const matchedEmb = EMBEDDING_PROVIDERS.find((p) => p.id !== 'custom' && p.baseUrl && savedEmbUrl.startsWith(p.baseUrl.split('/v1')[0]))
        if (matchedEmb) setEmbProvider(matchedEmb.id)
      })
      .catch(() => setError('加载配置失败，请检查后端服务。'))
      .finally(() => setLoading(false))
  }, [])

  const set = (key: string, value: string) => setEdits((p) => ({ ...p, [key]: value }))

  const handleSave = async (key: string) => {
    setSaving((p) => ({ ...p, [key]: true }))
    setError('')
    try {
      await apiClient.patch('/api/config', { key, value: edits[key] })
      setConfig((p) => ({ ...p, [key]: { ...p[key], value: edits[key] } }))
      setSaved((p) => ({ ...p, [key]: true }))
      setTimeout(() => setSaved((p) => ({ ...p, [key]: false })), 2000)
    } catch { setError(`保存 "${key}" 失败`) }
    finally { setSaving((p) => ({ ...p, [key]: false })) }
  }

  const handleSaveGroup = async (keys: string[]) => {
    const dirty = keys.filter((k) => edits[k] !== config[k]?.value && config[k])
    if (!dirty.length) return
    setError('')
    try {
      await Promise.all(dirty.map((k) =>
        apiClient.patch('/api/config', { key: k, value: edits[k] }).then(() => {
          setConfig((p) => ({ ...p, [k]: { ...p[k], value: edits[k] } }))
          setSaved((p) => ({ ...p, [k]: true }))
          setTimeout(() => setSaved((p) => ({ ...p, [k]: false })), 2000)
        })
      ))
    } catch { setError('批量保存失败') }
  }

  const isDirty = (key: string) => edits[key] !== config[key]?.value
  const groupDirty = (keys: string[]) => keys.some((k) => isDirty(k) && config[k])
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''

  const applyVlmProvider = (p: ProviderPreset) => {
    setVlmProvider(p.id)
    if (p.baseUrl) set('vlm_base_url', p.baseUrl)
    if (p.defaultModel) set('vlm_model', p.defaultModel)
  }
  const applyEmbProvider = (p: ProviderPreset) => {
    setEmbProvider(p.id)
    if (p.baseUrl) set('embedding_base_url', p.baseUrl)
    if (p.defaultModel) set('embedding_model', p.defaultModel)
  }

  const VLM_KEYS = ['vlm_base_url', 'vlm_api_key', 'vlm_model', 'vlm_provider', 'llm_model']
  const EMB_KEYS = ['embedding_provider', 'embedding_base_url', 'embedding_model', 'embedding_api_key', 'vector_dimension', 'top_k', 'match_top_k', 'match_top_n']
  const VIDEO_KEYS = ['split_mode', 'fixed_duration', 'scene_threshold', 'frame_fps', 'asr_model']
  const TTS_KEYS = ['tts_provider', 'tts_voice', 'tts_rate', 'tts_volume']

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* 页头 */}
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" />首页
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-slate-400" />系统设置
          </h1>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />加载配置中...
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-600/30 bg-red-500/5 px-5 py-4 text-sm text-red-300">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
          </div>
        )}

        {!loading && (
          <div className="space-y-6">

            {/* ── VLM / 大模型 ── */}
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
                <div>
                  <h2 className="font-semibold text-slate-100">API / 大模型</h2>
                  <p className="text-xs text-slate-500 mt-0.5">视觉描述 (VLM) 与文本模型配置</p>
                </div>
                <div className="flex items-center gap-3">
                  <ProviderSelector providers={VLM_PROVIDERS} selectedId={vlmProvider} onSelect={applyVlmProvider} />
                  {groupDirty(VLM_KEYS) && (
                    <button
                      onClick={() => handleSaveGroup(VLM_KEYS)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
                    >
                      <Save className="w-3.5 h-3.5" />保存全部
                    </button>
                  )}
                </div>
              </div>
              <div className="px-6 py-5 space-y-5">
                {config.vlm_base_url && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 地址</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={v('vlm_base_url')}
                        onChange={(e) => set('vlm_base_url', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="https://api.openai.com/v1"
                      />
                      <SaveBtn cfgKey="vlm_base_url" dirty={isDirty('vlm_base_url')} saving={!!saving['vlm_base_url']} saved={!!saved['vlm_base_url']} onSave={() => handleSave('vlm_base_url')} />
                    </div>
                  </div>
                )}
                {config.vlm_api_key && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 密钥</label>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        value={v('vlm_api_key')}
                        onChange={(e) => set('vlm_api_key', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="••••••••"
                      />
                      <SaveBtn cfgKey="vlm_api_key" dirty={isDirty('vlm_api_key')} saving={!!saving['vlm_api_key']} saved={!!saved['vlm_api_key']} onSave={() => handleSave('vlm_api_key')} />
                    </div>
                  </div>
                )}
                {config.vlm_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">VLM 模型</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker
                          value={v('vlm_model')}
                          onChange={(val) => set('vlm_model', val)}
                          baseUrl={v('vlm_base_url')}
                          apiKey={v('vlm_api_key')}
                          placeholder="gpt-4o"
                        />
                      </div>
                      <div className="mt-0"><SaveBtn cfgKey="vlm_model" dirty={isDirty('vlm_model')} saving={!!saving['vlm_model']} saved={!!saved['vlm_model']} onSave={() => handleSave('vlm_model')} /></div>
                    </div>
                  </div>
                )}
                {config.llm_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">LLM 模型 (文本)</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker
                          value={v('llm_model')}
                          onChange={(val) => set('llm_model', val)}
                          baseUrl={v('vlm_base_url')}
                          apiKey={v('vlm_api_key')}
                          placeholder="gpt-4o-mini"
                        />
                      </div>
                      <div className="mt-0"><SaveBtn cfgKey="llm_model" dirty={isDirty('llm_model')} saving={!!saving['llm_model']} saved={!!saved['llm_model']} onSave={() => handleSave('llm_model')} /></div>
                    </div>
                  </div>
                )}

              </div>
            </section>

            {/* ── 向量检索 / Embedding ── */}
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
                <div>
                  <h2 className="font-semibold text-slate-100">向量检索 / Embedding</h2>
                  <p className="text-xs text-slate-500 mt-0.5">嵌入模型与检索参数</p>
                </div>
                <div className="flex items-center gap-3">
                  <ProviderSelector providers={EMBEDDING_PROVIDERS} selectedId={embProvider} onSelect={applyEmbProvider} />
                  {groupDirty(EMB_KEYS) && (
                    <button
                      onClick={() => handleSaveGroup(EMB_KEYS)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
                    >
                      <Save className="w-3.5 h-3.5" />保存全部
                    </button>
                  )}
                </div>
              </div>
              <div className="px-6 py-5 space-y-5">
                {config.embedding_base_url && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 地址</label>
                    <div className="flex gap-2">
                      <input type="text" value={v('embedding_base_url')} onChange={(e) => set('embedding_base_url', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="https://api.openai.com/v1" />
                      <SaveBtn cfgKey="embedding_base_url" dirty={isDirty('embedding_base_url')} saving={!!saving['embedding_base_url']} saved={!!saved['embedding_base_url']} onSave={() => handleSave('embedding_base_url')} />
                    </div>
                  </div>
                )}
                {config.embedding_api_key && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 密钥</label>
                    <div className="flex gap-2">
                      <input type="password" value={v('embedding_api_key')} onChange={(e) => set('embedding_api_key', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="••••••••" />
                      <SaveBtn cfgKey="embedding_api_key" dirty={isDirty('embedding_api_key')} saving={!!saving['embedding_api_key']} saved={!!saved['embedding_api_key']} onSave={() => handleSave('embedding_api_key')} />
                    </div>
                  </div>
                )}
                {config.embedding_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">Embedding 模型</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker
                          value={v('embedding_model')}
                          onChange={(val) => set('embedding_model', val)}
                          baseUrl={v('embedding_base_url')}
                          apiKey={v('embedding_api_key')}
                          placeholder="text-embedding-3-small"
                        />
                      </div>
                      <div className="mt-0"><SaveBtn cfgKey="embedding_model" dirty={isDirty('embedding_model')} saving={!!saving['embedding_model']} saved={!!saved['embedding_model']} onSave={() => handleSave('embedding_model')} /></div>
                    </div>
                  </div>
                )}
                {/* 检索参数 */}
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-slate-800">
                  {['vector_dimension','top_k','match_top_k','match_top_n'].filter((k) => config[k]).map((key) => (
                    <div key={key} className="space-y-1.5">
                      <label className="text-xs text-slate-400">{config[key].label || key}</label>
                      <div className="flex gap-2">
                        <input type="number" value={v(key)} onChange={(e) => set(key, e.target.value)}
                          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors" />
                        <SaveBtn cfgKey={key} dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
                      </div>
                    </div>
                  ))}
                </div>

              </div>
            </section>

            {/* ── 视频处理 ── */}
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
                <div>
                  <h2 className="font-semibold text-slate-100">视频处理</h2>
                  <p className="text-xs text-slate-500 mt-0.5">切分策略与帧提取参数</p>
                </div>
                {groupDirty(VIDEO_KEYS) && (
                  <button onClick={() => handleSaveGroup(VIDEO_KEYS)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
                    <Save className="w-3.5 h-3.5" />保存全部
                  </button>
                )}
              </div>
              <div className="px-6 py-5 space-y-4">
                {VIDEO_KEYS.filter((k) => config[k]).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <label className="text-xs text-slate-400">{config[key].label || key}</label>
                    <div className="flex gap-2">
                      <div className="flex-1"><ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => set(key, val)} /></div>
                      <SaveBtn cfgKey={key} dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* ── TTS 配音 ── */}
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
              <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
                <div>
                  <h2 className="font-semibold text-slate-100">TTS 配音</h2>
                  <p className="text-xs text-slate-500 mt-0.5">文字转语音参数</p>
                </div>
                {groupDirty(TTS_KEYS) && (
                  <button onClick={() => handleSaveGroup(TTS_KEYS)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
                    <Save className="w-3.5 h-3.5" />保存全部
                  </button>
                )}
              </div>
              <div className="px-6 py-5 space-y-4">
                {TTS_KEYS.filter((k) => config[k]).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <label className="text-xs text-slate-400">{config[key].label || key}</label>
                    <div className="flex gap-2">
                      <div className="flex-1"><ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => set(key, val)} /></div>
                      <SaveBtn cfgKey={key} dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
                    </div>
                  </div>
                ))}
              </div>
            </section>

          </div>
        )}
      </div>
    </main>
  )
}
