'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Save, Settings2, AlertCircle } from 'lucide-react'
import apiClient from '@/lib/api'
import type { ConfigMap, ProviderPreset } from './_components/types'
import { VLM_PROVIDERS, EMBEDDING_PROVIDERS, VLM_KEYS, EMB_KEYS, VIDEO_KEYS, TTS_KEYS } from './_components/constants'
import { ProviderSelector } from './_components/ProviderSelector'
import { ModelPicker } from './_components/ModelPicker'
import { ConfigField } from './_components/ConfigField'
import { SaveBtn } from './_components/SaveBtn'

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
        const matchedVlm = VLM_PROVIDERS.find(
          (p) => p.id !== 'custom' && p.baseUrl && savedVlmUrl.startsWith(p.baseUrl.split('/v1')[0])
        )
        if (matchedVlm) setVlmProvider(matchedVlm.id)
        const savedEmbUrl = data?.embedding_base_url?.value ?? ''
        const matchedEmb = EMBEDDING_PROVIDERS.find(
          (p) => p.id !== 'custom' && p.baseUrl && savedEmbUrl.startsWith(p.baseUrl.split('/v1')[0])
        )
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
      await Promise.all(
        dirty.map((k) =>
          apiClient.patch('/api/config', { key: k, value: edits[k] }).then(() => {
            setConfig((p) => ({ ...p, [k]: { ...p[k], value: edits[k] } }))
            setSaved((p) => ({ ...p, [k]: true }))
            setTimeout(() => setSaved((p) => ({ ...p, [k]: false })), 2000)
          })
        )
      )
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

  const SaveGroupBtn = ({ keys }: { keys: string[] }) =>
    groupDirty(keys) ? (
      <button
        onClick={() => handleSaveGroup(keys)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
      >
        <Save className="w-3.5 h-3.5" />保存全部
      </button>
    ) : null

  // ── JSX ──────────────────────────────────────────────────────────────────
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
                  <SaveGroupBtn keys={VLM_KEYS} />
                </div>
              </div>
              <div className="px-6 py-5 space-y-5">
                {config.vlm_base_url && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 地址</label>
                    <div className="flex gap-2">
                      <input type="text" value={v('vlm_base_url')} onChange={(e) => set('vlm_base_url', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="https://api.openai.com/v1" />
                      <SaveBtn dirty={isDirty('vlm_base_url')} saving={!!saving['vlm_base_url']} saved={!!saved['vlm_base_url']} onSave={() => handleSave('vlm_base_url')} />
                    </div>
                  </div>
                )}
                {config.vlm_api_key && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">API 密钥</label>
                    <div className="flex gap-2">
                      <input type="password" value={v('vlm_api_key')} onChange={(e) => set('vlm_api_key', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                        placeholder="••••••••" />
                      <SaveBtn dirty={isDirty('vlm_api_key')} saving={!!saving['vlm_api_key']} saved={!!saved['vlm_api_key']} onSave={() => handleSave('vlm_api_key')} />
                    </div>
                  </div>
                )}
                {config.vlm_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">VLM 模型</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker value={v('vlm_model')} onChange={(val) => set('vlm_model', val)}
                          baseUrl={v('vlm_base_url')} apiKey={v('vlm_api_key')} placeholder="gpt-4o" />
                      </div>
                      <SaveBtn dirty={isDirty('vlm_model')} saving={!!saving['vlm_model']} saved={!!saved['vlm_model']} onSave={() => handleSave('vlm_model')} />
                    </div>
                  </div>
                )}
                {config.llm_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">LLM 模型 (文本)</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker value={v('llm_model')} onChange={(val) => set('llm_model', val)}
                          baseUrl={v('vlm_base_url')} apiKey={v('vlm_api_key')} placeholder="gpt-4o-mini" />
                      </div>
                      <SaveBtn dirty={isDirty('llm_model')} saving={!!saving['llm_model']} saved={!!saved['llm_model']} onSave={() => handleSave('llm_model')} />
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
                  <SaveGroupBtn keys={EMB_KEYS} />
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
                      <SaveBtn dirty={isDirty('embedding_base_url')} saving={!!saving['embedding_base_url']} saved={!!saved['embedding_base_url']} onSave={() => handleSave('embedding_base_url')} />
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
                      <SaveBtn dirty={isDirty('embedding_api_key')} saving={!!saving['embedding_api_key']} saved={!!saved['embedding_api_key']} onSave={() => handleSave('embedding_api_key')} />
                    </div>
                  </div>
                )}
                {config.embedding_model && (
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-400">Embedding 模型</label>
                    <div className="flex gap-2 items-start">
                      <div className="flex-1">
                        <ModelPicker value={v('embedding_model')} onChange={(val) => set('embedding_model', val)}
                          baseUrl={v('embedding_base_url')} apiKey={v('embedding_api_key')} placeholder="text-embedding-3-small" />
                      </div>
                      <SaveBtn dirty={isDirty('embedding_model')} saving={!!saving['embedding_model']} saved={!!saved['embedding_model']} onSave={() => handleSave('embedding_model')} />
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-slate-800">
                  {['vector_dimension', 'top_k', 'match_top_k', 'match_top_n'].filter((k) => config[k]).map((key) => (
                    <div key={key} className="space-y-1.5">
                      <label className="text-xs text-slate-400">{config[key].label || key}</label>
                      <div className="flex gap-2">
                        <input type="number" value={v(key)} onChange={(e) => set(key, e.target.value)}
                          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors" />
                        <SaveBtn dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
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
                <SaveGroupBtn keys={VIDEO_KEYS} />
              </div>
              <div className="px-6 py-5 space-y-4">
                {VIDEO_KEYS.filter((k) => config[k]).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <label className="text-xs text-slate-400">{config[key].label || key}</label>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => set(key, val)} />
                      </div>
                      <SaveBtn dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
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
                <SaveGroupBtn keys={TTS_KEYS} />
              </div>
              <div className="px-6 py-5 space-y-4">
                {TTS_KEYS.filter((k) => config[k]).map((key) => (
                  <div key={key} className="space-y-1.5">
                    <label className="text-xs text-slate-400">{config[key].label || key}</label>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <ConfigField cfgKey={key} item={config[key]} value={v(key)} onChange={(val) => set(key, val)} />
                      </div>
                      <SaveBtn dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => handleSave(key)} />
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
