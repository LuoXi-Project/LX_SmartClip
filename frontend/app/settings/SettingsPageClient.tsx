'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Settings2, AlertCircle, ChevronUp } from 'lucide-react'
import apiClient, { formatFastApiDetail } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import type { ConfigMap, ProviderPreset } from './_components/types'
import { VLM_PROVIDERS, LLM_PROVIDERS, EMBEDDING_PROVIDERS, ASR_PROVIDERS } from './_components/constants'
import { VlmSection } from './_components/VlmSection'
import { LlmSection } from './_components/LlmSection'
import { EmbeddingSection } from './_components/EmbeddingSection'
import { VideoSection } from './_components/VideoSection'
import { StockMediaSection } from './_components/StockMediaSection'
import { TtsSection } from './_components/TtsSection'
import { AsrSection } from './_components/AsrSection'
export default function SettingsPage() {
  const toast = useToast()
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
        const matchedEmb = EMBEDDING_PROVIDERS.find((p) => {
          if (p.id === 'custom' || !p.baseUrl) return false
          const prefix = p.baseUrl.includes('/v1') ? p.baseUrl.split('/v1')[0] : p.baseUrl
          return savedEmbUrl.startsWith(prefix)
        })
        if (matchedEmb) setEmbProvider(matchedEmb.id)
        const savedTtsProv = data?.tts_provider?.value ?? ''
        if (savedTtsProv) setTtsProvider(savedTtsProv)
        const savedAsrProv = data?.asr_provider?.value ?? ''
        if (savedAsrProv) {
          const hasProvider = ASR_PROVIDERS.some((p) => p.id === savedAsrProv)
          if (hasProvider) {
            setAsrProvider(savedAsrProv)
          } else {
            // 隐藏旧 provider 时，UI 自动回落到 openai 兼容模式
            initial.asr_provider = 'openai'
            setAsrProvider('openai')
          }
        }
      })
      .catch(() => setError('加载配置失败，请检查后端服务。'))
      .finally(() => setLoading(false))
  }, [])

  const sections = useMemo(() => ([
    { id: 'llm', label: 'LLM 文本模型', group: 'models' },
    { id: 'vlm', label: 'VLM 视觉模型', group: 'models' },
    { id: 'embedding', label: '向量检索', group: 'models' },
    { id: 'asr', label: '语音识别', group: 'models' },
    { id: 'tts', label: 'TTS 配音', group: 'models' },
    { id: 'video', label: '视频处理', group: 'media' },
    { id: 'stock-media', label: '在线素材', group: 'media' },
  ]), [])

  /** 各服务配置就绪状态：ok=已配置 / local=本地或内置免配置 / missing=待配置 */
  const serviceStatuses = useMemo(() => {
    const val = (k: string) => (config[k]?.value ?? '').trim()
    const has = (k: string) => val(k).length > 0
    return [
      { id: 'llm', name: 'LLM 文本', state: has('llm_api_key') ? ('ok' as const) : ('missing' as const), label: has('llm_api_key') ? '已配置' : '待配置 Key' },
      { id: 'vlm', name: 'VLM 视觉', state: has('vlm_api_key') ? ('ok' as const) : ('missing' as const), label: has('vlm_api_key') ? '已配置' : '待配置 Key' },
      { id: 'embedding', name: '向量检索', state: has('embedding_api_key') ? ('ok' as const) : ('missing' as const), label: has('embedding_api_key') ? '已配置' : '待配置 Key' },
      {
        id: 'asr',
        name: '语音识别',
        state: val('asr_provider') === 'whisper' ? ('local' as const) : has('asr_api_key') ? ('ok' as const) : ('missing' as const),
        label: val('asr_provider') === 'whisper' ? '本地 Whisper' : has('asr_api_key') ? '已配置' : '待配置 Key',
      },
      {
        id: 'tts',
        name: 'TTS 配音',
        state: val('tts_provider') === 'edge-tts' ? ('local' as const) : has('tts_api_key') ? ('ok' as const) : ('missing' as const),
        label: val('tts_provider') === 'edge-tts' ? '内置免费' : has('tts_api_key') ? '已配置' : '待配置 Key',
      },
    ]
  }, [config])

  const statusById = useMemo(() => {
    const m: Record<string, { state: string }> = {}
    serviceStatuses.forEach((s) => { m[s.id] = { state: s.state } })
    return m
  }, [serviceStatuses])

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
    try {
      await apiClient.patch('/api/config', { key, value: edits[key] })
      setConfig((p) => ({ ...p, [key]: { ...p[key], value: edits[key] } }))
      setSaved((p) => ({ ...p, [key]: true }))
      setTimeout(() => setSaved((p) => ({ ...p, [key]: false })), 2000)
    } catch (e) {
      // toast 在任何滚动位置都可见，避免顶部横幅被长页滚动挡住
      toast.error(`保存「${key}」失败：${formatFastApiDetail(e)}`)
    } finally { setSaving((p) => ({ ...p, [key]: false })) }
  }

  const handleSaveGroup = async (keys: string[]) => {
    const dirty = keys.filter((k) => edits[k] !== config[k]?.value && config[k])
    if (!dirty.length) return
    const results = await Promise.allSettled(
      dirty.map((k) =>
        apiClient.patch('/api/config', { key: k, value: edits[k] }).then(() => {
          setConfig((p) => ({ ...p, [k]: { ...p[k], value: edits[k] } }))
          setSaved((p) => ({ ...p, [k]: true }))
          setTimeout(() => setSaved((p) => ({ ...p, [k]: false })), 2000)
        })
      )
    )
    const failed = results.filter((r) => r.status === 'rejected')
    if (failed.length === 0) {
      toast.success(`已保存 ${dirty.length} 项配置`)
    } else if (failed.length === dirty.length) {
      toast.error(`批量保存失败：${formatFastApiDetail((failed[0] as PromiseRejectedResult).reason)}`)
    } else {
      const okCount = dirty.length - failed.length
      toast.error(`部分保存失败：成功 ${okCount} 项、失败 ${failed.length} 项，失败项的「保存」按钮仍可重试`)
    }
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
    set('embedding_provider', p.id)
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

        {/* 配置就绪状态总览：缺什么一眼可见，点击直达对应配置节 */}
        {!loading && !error && (
          <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">配置就绪状态</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              {serviceStatuses.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => jumpTo(s.id)}
                  className={`flex flex-col gap-1 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                    s.state === 'missing'
                      ? 'border-amber-500/35 bg-amber-500/5 hover:border-amber-500/60'
                      : 'border-slate-800 bg-slate-900/50 hover:border-slate-600'
                  }`}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        s.state === 'ok' ? 'bg-emerald-400' : s.state === 'local' ? 'bg-cyan-400' : 'bg-amber-400'
                      }`}
                    />
                    <span className="text-xs text-slate-200 font-medium">{s.name}</span>
                  </span>
                  <span className={`text-[11px] ${s.state === 'missing' ? 'text-amber-300/90' : 'text-slate-500'}`}>
                    {s.label}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

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

            {/* desktop nav：按「模型与语音 / 处理与素材」分组，导航项带配置状态点 */}
            <div className="hidden lg:block rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/70">
                <p className="text-xs font-medium text-slate-400">快速导航</p>
              </div>
              <div className="p-2">
                {([['models', '模型与语音'], ['media', '处理与素材']] as const).map(([groupKey, groupLabel]) => (
                  <div key={groupKey} className="mb-1 last:mb-0">
                    <p className="px-3 pt-2 pb-1 text-[10px] text-slate-600 uppercase tracking-wider">{groupLabel}</p>
                    {sections.filter((s) => s.group === groupKey).map((s) => {
                      const active = activeSection === s.id
                      const st = statusById[s.id]?.state
                      return (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => jumpTo(s.id)}
                          className={`w-full flex items-center text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                            active
                              ? 'bg-indigo-500/10 text-indigo-200'
                              : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                          }`}
                        >
                          <span className={`inline-block w-1.5 h-1.5 rounded-full mr-2 ${active ? 'bg-indigo-400' : 'bg-slate-700'}`} />
                          <span className="flex-1">{s.label}</span>
                          {st === 'ok' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" title="已配置" />}
                          {st === 'local' && <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" title="本地/内置，免配置" />}
                          {st === 'missing' && <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="待配置 Key" />}
                        </button>
                      )
                    })}
                  </div>
                ))}
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
                <div id="llm" data-tour="page-settings-llm" className="scroll-mt-28">
                  <LlmSection {...sharedProps} llmProvider={llmProvider} onApplyProvider={applyLlmProvider} />
                </div>
                <div id="vlm" className="scroll-mt-28">
                  <VlmSection {...sharedProps} vlmProvider={vlmProvider} onApplyProvider={applyVlmProvider} />
                </div>
                <div id="embedding" className="scroll-mt-28">
                  <EmbeddingSection {...sharedProps} embProvider={embProvider} onApplyProvider={applyEmbProvider} />
                </div>
                <div id="asr" className="scroll-mt-28">
                  <AsrSection {...sharedProps} asrProvider={asrProvider} onApplyProvider={applyAsrProvider} />
                </div>
                <div id="tts" className="scroll-mt-28">
                  <TtsSection {...sharedProps} ttsProvider={ttsProvider} onApplyProvider={applyTtsProvider} />
                </div>
                <div id="video" className="scroll-mt-28">
                  <VideoSection {...sharedProps} />
                </div>
                <StockMediaSection {...sharedProps} />
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  )
}
