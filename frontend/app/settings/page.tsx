'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Settings2, AlertCircle } from 'lucide-react'
import apiClient from '@/lib/api'
import type { ConfigMap, ProviderPreset } from './_components/types'
import { VLM_PROVIDERS, EMBEDDING_PROVIDERS } from './_components/constants'
import { VlmSection } from './_components/VlmSection'
import { EmbeddingSection } from './_components/EmbeddingSection'
import { VideoSection } from './_components/VideoSection'
import { TtsSection } from './_components/TtsSection'
import { AsrSection } from './_components/AsrSection'

export default function SettingsPage() {
  const [config, setConfig] = useState<ConfigMap>({})
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')
  const [vlmProvider, setVlmProvider] = useState('custom')
  const [embProvider, setEmbProvider] = useState('custom')
  const [ttsProvider, setTtsProvider] = useState('edge-tts')
  const [asrProvider, setAsrProvider] = useState('whisper')

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
        const savedTtsProv = data?.tts_provider?.value ?? ''
        if (savedTtsProv) setTtsProvider(savedTtsProv)
        const savedAsrProv = data?.asr_provider?.value ?? ''
        if (savedAsrProv) setAsrProvider(savedAsrProv)
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
  const applyAsrProvider = (p: ProviderPreset) => {
    setAsrProvider(p.id)
    set('asr_provider', p.id)
    if (p.baseUrl) set('asr_base_url', p.baseUrl)
    if (p.defaultModel) set('asr_openai_model', p.defaultModel)
  }
  const applyTtsProvider = (p: ProviderPreset) => {
    setTtsProvider(p.id)
    set('tts_provider', p.id)
    if (p.baseUrl) set('tts_base_url', p.baseUrl)
    if (p.defaultModel) set('tts_model', p.defaultModel)
  }

  const sharedProps = { config, edits, saving, saved, onSet: set, onSave: handleSave, onSaveGroup: handleSaveGroup }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
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
            <VlmSection {...sharedProps} vlmProvider={vlmProvider} onApplyProvider={applyVlmProvider} />
            <EmbeddingSection {...sharedProps} embProvider={embProvider} onApplyProvider={applyEmbProvider} />
            <AsrSection {...sharedProps} asrProvider={asrProvider} onApplyProvider={applyAsrProvider} />
            <VideoSection {...sharedProps} />
            <TtsSection {...sharedProps} ttsProvider={ttsProvider} onApplyProvider={applyTtsProvider} />
          </div>
        )}
      </div>
    </main>
  )
}
