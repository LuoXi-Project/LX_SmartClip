'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Settings2, AlertCircle, ChevronUp, Music2, ExternalLink } from 'lucide-react'
import apiClient from '@/lib/api'
import type { ConfigMap, ProviderPreset } from './_components/types'
import { VLM_PROVIDERS, LLM_PROVIDERS, EMBEDDING_PROVIDERS } from './_components/constants'
import { VlmSection } from './_components/VlmSection'
import { LlmSection } from './_components/LlmSection'
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
  const [llmProvider, setLlmProvider] = useState('custom')
  const [embProvider, setEmbProvider] = useState('custom')
  const [ttsProvider, setTtsProvider] = useState('edge-tts')
  const [asrProvider, setAsrProvider] = useState('whisper')
  const [activeSection, setActiveSection] = useState('vlm')
  const observeIdsRef = useRef<string[]>([])

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
        const savedLlmUrl = data?.llm_base_url?.value ?? ''
        const matchedLlm = LLM_PROVIDERS.find(
          (p) => p.id !== 'custom' && p.baseUrl && savedLlmUrl.startsWith(p.baseUrl.split('/v1')[0])
        )
        if (matchedLlm) setLlmProvider(matchedLlm.id)
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

  const sections = useMemo(() => ([
    { id: 'vlm', label: 'VLM 视觉模型' },
    { id: 'llm', label: 'LLM 文本模型' },
    { id: 'embedding', label: '向量检索' },
    { id: 'asr', label: '语音识别' },
    { id: 'video', label: '视频处理' },
    { id: 'tts', label: 'TTS 配音' },
  ]), [])

  useEffect(() => {
    if (loading) return
    observeIdsRef.current = sections.map((s) => s.id)

    const els = observeIdsRef.current
      .map((id) => document.getElementById(id))
      .filter(Boolean) as HTMLElement[]

    if (!els.length) return

    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => (b.intersectionRatio || 0) - (a.intersectionRatio || 0))
        const top = visible[0]
        const id = top?.target?.id
        if (id) setActiveSection(id)
      },
      {
        root: null,
        threshold: [0.2, 0.35, 0.5, 0.65],
        // 顶部留出标题区高度，避免刚进入就切换
        rootMargin: '-96px 0px -60% 0px',
      }
    )

    els.forEach((el) => io.observe(el))

    // 初次进入支持 hash 定位
    const hash = decodeURIComponent(window.location.hash || '').replace(/^#/, '')
    if (hash && observeIdsRef.current.includes(hash)) {
      document.getElementById(hash)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }

    return () => io.disconnect()
  }, [loading, sections])

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
  const applyLlmProvider = (p: ProviderPreset) => {
    setLlmProvider(p.id)
    if (p.baseUrl) set('llm_base_url', p.baseUrl)
    if (p.defaultModel) set('llm_model', p.defaultModel)
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

  const jumpTo = (id: string) => {
    const el = document.getElementById(id)
    if (!el) return
    history.replaceState(null, '', `#${encodeURIComponent(id)}`)
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setActiveSection(id)
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-6xl mx-auto px-6 py-10">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" />首页
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-slate-400" />系统设置
          </h1>
        </div>

        <div className="mt-8 grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-8 items-start">
          {/* Nav */}
          <aside className="lg:sticky lg:top-6 space-y-3">
            {/* mobile nav */}
            <div className="lg:hidden -mx-6 px-6 py-2 border-y border-slate-800 bg-slate-950/30">
              <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
                {sections.map((s) => {
                  const active = activeSection === s.id
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => jumpTo(s.id)}
                      className={`shrink-0 px-3 py-1.5 rounded-full text-xs border transition-colors ${
                        active
                          ? 'border-indigo-500/50 bg-indigo-500/10 text-indigo-200'
                          : 'border-slate-800 bg-slate-900/40 text-slate-400 hover:text-slate-200 hover:border-slate-600'
                      }`}
                    >
                      {s.label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* desktop nav */}
            <div className="hidden lg:block rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/70">
                <p className="text-xs font-medium text-slate-400">快速导航</p>
              </div>
              <div className="p-2">
                {sections.map((s) => {
                  const active = activeSection === s.id
                  return (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => jumpTo(s.id)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                        active
                          ? 'bg-indigo-500/10 text-indigo-200'
                          : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                      }`}
                    >
                      <span className={`inline-block w-1.5 h-1.5 rounded-full mr-2 ${active ? 'bg-indigo-400' : 'bg-slate-700'}`} />
                      {s.label}
                    </button>
                  )
                })}
                <div className="mt-2 pt-2 border-t border-slate-800">
                  <button
                    type="button"
                    onClick={() => {
                      history.replaceState(null, '', '#')
                      window.scrollTo({ top: 0, behavior: 'smooth' })
                    }}
                    className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs text-slate-400 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
                  >
                    <ChevronUp className="w-4 h-4" />回到顶部
                  </button>
                </div>
              </div>
            </div>
          </aside>

          {/* Content */}
          <div className="space-y-6">
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
              <>
                <div id="vlm" className="scroll-mt-28">
                  <VlmSection {...sharedProps} vlmProvider={vlmProvider} onApplyProvider={applyVlmProvider} />
                </div>
                <div id="llm" className="scroll-mt-28">
                  <LlmSection {...sharedProps} llmProvider={llmProvider} onApplyProvider={applyLlmProvider} />
                </div>
                <div id="embedding" className="scroll-mt-28">
                  <EmbeddingSection {...sharedProps} embProvider={embProvider} onApplyProvider={applyEmbProvider} />
                </div>
                <div id="asr" className="scroll-mt-28">
                  <AsrSection {...sharedProps} asrProvider={asrProvider} onApplyProvider={applyAsrProvider} />
                </div>
                <div id="video" className="scroll-mt-28">
                  <VideoSection {...sharedProps} />
                </div>
                <div id="tts" className="scroll-mt-28">
                  <TtsSection {...sharedProps} ttsProvider={ttsProvider} onApplyProvider={applyTtsProvider} />
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
