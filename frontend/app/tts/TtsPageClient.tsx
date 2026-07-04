'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, Download, Loader2, Play, RefreshCw, Square, Settings } from 'lucide-react'
import { ttsApi, apiClient, type TTSResponse, type VoiceInfo } from '@/lib/api'
import type { ConfigMap } from '@/app/settings/_components/types'
import { useTtsStore, type TtsHistoryItem } from '@/lib/store'
import { VoiceInputControl } from '@/components/ui/voice-input'

function buildAudioUrl(f: string) { return `/api/tts/audio/${f}` }

const RATE_PRESETS = [{label:'很慢',value:'-50%'},{label:'慢',value:'-20%'},{label:'正常',value:'+0%'},{label:'快',value:'+20%'},{label:'很快',value:'+50%'}]
const VOLUME_PRESETS = [{label:'小',value:'-30%'},{label:'正常',value:'+0%'},{label:'大',value:'+20%'},{label:'最大',value:'+50%'}]
const VOICE_INPUT_PROVIDERS = ['openai', 'bailian', 'volcengine']
const NO_PARAM_PROVIDERS = ['gpt-sovits', 'index-tts', 'custom-http']
const PROVIDER_LABELS: Record<string,string> = {
  'edge-tts':'Edge TTS','openai':'OpenAI TTS','bailian':'百炼 (阿里云)',
  'volcengine':'火山引擎','gpt-sovits':'GPT-SoVITS','index-tts':'IndexTTS','custom-http':'自定义 HTTP',
}

// HistoryItem 类型由 store 统一导出，此处直接使用 TtsHistoryItem
type HistoryItem = TtsHistoryItem

function HistoryCard({item,playing,onPlay,onStop,onDownload}:{item:HistoryItem;playing:boolean;onPlay:()=>void;onStop:()=>void;onDownload:()=>void}) {
  return (
    <div className={`rounded-xl border px-4 py-3 flex gap-3 items-start transition-all ${playing?'border-violet-500/50 bg-violet-500/5':'border-slate-800 bg-slate-900/40'}`}>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-200 line-clamp-2">{item.text}</p>
        <p className="text-xs text-slate-500 mt-1">{item.voice?`${item.voice} · `:''}{item.rate?`语速 ${item.rate} · `:''}音量 {item.volume}</p>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {playing
          ?<button onClick={onStop} className="w-7 h-7 rounded-lg bg-violet-500/20 text-violet-300 hover:bg-violet-500/30 flex items-center justify-center"><Square className="w-3.5 h-3.5"/></button>
          :<button onClick={onPlay} className="w-7 h-7 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center justify-center"><Play className="w-3.5 h-3.5"/></button>}
        <button onClick={onDownload} className="w-7 h-7 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center justify-center"><Download className="w-3.5 h-3.5"/></button>
      </div>
    </div>
  )
}

export default function TTSPage() {
  // ── 持久化状态（切换页面后保留）─────────────────────────────────────────
  const {
    ttsHistory: history,
    addTtsHistory,
    ttsText: text,
    setTtsText: setText,
    ttsSelectedVoice: selectedVoice,
    setTtsSelectedVoice: setSelectedVoice,
    ttsRate: rate,
    setTtsRate: setRate,
    ttsVolume: volume,
    setTtsVolume: setVolume,
    clearTtsHistory,
  } = useTtsStore()
  // ─────────────────────────────────────────────────────────────────────────

  const [voices, setVoices] = useState<VoiceInfo[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [showVoiceDropdown, setShowVoiceDropdown] = useState(false)
  const [voiceSearch, setVoiceSearch] = useState('')
  const [ttsProvider, setTtsProvider] = useState('')
  const [configLoading, setConfigLoading] = useState(true)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    apiClient.get<unknown, ConfigMap>('/api/config')
      .then((data) => {
        const provider = data?.tts_provider?.value || 'edge-tts'
        setTtsProvider(provider)
        // 只在 store 中尚无值时才用配置覆盖，保留用户上次的选择
        if (!useTtsStore.getState().ttsSelectedVoice && data?.tts_voice?.value)
          setSelectedVoice(data.tts_voice.value)
        if (useTtsStore.getState().ttsRate === '+0%' && data?.tts_rate?.value)
          setRate(data.tts_rate.value)
        if (useTtsStore.getState().ttsVolume === '+0%' && data?.tts_volume?.value)
          setVolume(data.tts_volume.value)
      })
      .catch(console.error)
      .finally(() => setConfigLoading(false))
  }, [])

  useEffect(() => {
    if (ttsProvider !== 'edge-tts') return
    setVoicesLoading(true)
    ttsApi.listVoices('zh')
      .then((data) => setVoices(data || []))
      .catch(console.error)
      .finally(() => setVoicesLoading(false))
  }, [ttsProvider])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setShowVoiceDropdown(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filteredVoices = voices.filter(
    (v) => v.friendly_name.toLowerCase().includes(voiceSearch.toLowerCase()) || v.name.toLowerCase().includes(voiceSearch.toLowerCase())
  )
  const selectedVoiceInfo = voices.find((v) => v.name === selectedVoice)

  const handleSynthesize = async () => {
    if (!text.trim() || loading) return
    setLoading(true); setError('')
    try {
      const payload: { text: string; voice?: string; rate?: string; volume?: string } = { text: text.trim() }
      if (ttsProvider === 'edge-tts') { payload.voice = selectedVoice; payload.rate = rate; payload.volume = volume }
      else if (VOICE_INPUT_PROVIDERS.includes(ttsProvider) && selectedVoice) { payload.voice = selectedVoice }
      const res: TTSResponse = await ttsApi.synthesize(payload)
      const item: HistoryItem = { id: res.filename, text: text.trim(), voice: res.voice || selectedVoice, rate: res.rate || rate, volume: res.volume || volume, filename: res.filename }
      addTtsHistory(item)
      playAudio(item)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'TTS 合成失败，请检查服务配置。')
    } finally { setLoading(false) }
  }

  const playAudio = (item: HistoryItem) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    const audio = new Audio(buildAudioUrl(item.filename))
    audioRef.current = audio; setPlayingId(item.id)
    audio.play(); audio.onended = () => setPlayingId(null); audio.onerror = () => setPlayingId(null)
  }
  const stopAudio = () => { audioRef.current?.pause(); audioRef.current = null; setPlayingId(null) }
  const downloadAudio = (item: HistoryItem) => {
    const a = document.createElement('a'); a.href = buildAudioUrl(item.filename); a.download = 'tts_' + item.filename; a.click()
  }

  const isEdgeTts = ttsProvider === 'edge-tts'
  const isVoiceInput = VOICE_INPUT_PROVIDERS.includes(ttsProvider)
  const isNoParam = NO_PARAM_PROVIDERS.includes(ttsProvider)
  const providerLabel = PROVIDER_LABELS[ttsProvider] || ttsProvider

  if (configLoading) return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200 flex items-center justify-center">
      <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin"/>加载配置中...</div>
    </main>
  )

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-2xl mx-auto px-6 py-10 space-y-6">

        {/* 页头 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
              <ArrowLeft className="w-4 h-4"/>首页
            </Link>
            <div className="w-px h-4 bg-slate-700"/>
            <h1 className="text-xl font-semibold">TTS 配音</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 bg-slate-800 border border-slate-700 px-2.5 py-1 rounded-full">{providerLabel}</span>
            <Link href="/settings" className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700 hover:border-indigo-500/50 flex items-center justify-center text-slate-400 hover:text-slate-200 transition-all" title="配置 TTS">
              <Settings className="w-3.5 h-3.5"/>
            </Link>
          </div>
        </div>

        {error && <div className="rounded-xl border border-red-600/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">{error}</div>}

        {/* 输入 + 参数 + 合成按钮 */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
          <div className="relative">
            <textarea value={text} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSynthesize() }}
              placeholder="输入要合成的文本（Ctrl+Enter 合成）" rows={5}
              className="w-full bg-transparent px-5 pt-12 pb-2 pr-14 text-sm text-slate-200 placeholder-slate-600 outline-none resize-none" />
            <div className="absolute right-3 top-3 z-10">
              <VoiceInputControl
                intent="这是 TTS 配音要朗读的正文：把口述整理成适合语音合成的中文书面稿，可分段但不要输出合成指令或引号包裹。"
                value={text}
                onTextChange={setText}
                merge="append"
                disabled={loading}
              />
            </div>
          </div>

          {/* 按引擎显示参数 */}
          {isNoParam ? (
            <div className="px-5 pb-3 pt-2 border-t border-slate-800/60">
              <p className="text-xs text-slate-600">{providerLabel} 的参数在<Link href="/settings" className="text-indigo-400 hover:text-indigo-300 ml-1">系统设置</Link>中配置</p>
            </div>
          ) : (
            <div className="px-5 pb-4 pt-3 border-t border-slate-800/60 space-y-3">

              {/* Edge TTS — 语音角色下拉 */}
              {isEdgeTts && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs text-slate-500">语音角色</label>
                    {voicesLoading && <RefreshCw className="w-3 h-3 text-slate-600 animate-spin"/>}
                  </div>
                  <div className="relative" ref={dropdownRef}>
                    <button onClick={() => setShowVoiceDropdown((v) => !v)}
                      className="w-full flex items-center justify-between rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm hover:border-indigo-500/50 transition-colors">
                      <span className="text-slate-200 truncate">{selectedVoiceInfo ? selectedVoiceInfo.friendly_name : (selectedVoice || '选择语音角色')}</span>
                      <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showVoiceDropdown?'rotate-180':''}`}/>
                    </button>
                    {showVoiceDropdown && (
                      <div className="absolute top-full left-0 right-0 mt-1 z-50 bg-[#13151c] border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
                        <div className="p-2 border-b border-slate-800">
                          <input value={voiceSearch} onChange={(e) => setVoiceSearch(e.target.value)} placeholder="搜索语音..."
                            className="w-full bg-slate-800 rounded-lg px-3 py-1.5 text-xs outline-none placeholder-slate-600" />
                        </div>
                        <div className="max-h-48 overflow-y-auto styled-scrollbar py-1">
                          {filteredVoices.map((voice) => (
                            <button key={voice.name} onClick={() => { setSelectedVoice(voice.name); setShowVoiceDropdown(false) }}
                              className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-800 transition-colors ${voice.name===selectedVoice?'text-indigo-400':'text-slate-300'}`}>
                              <span className="font-medium">{voice.friendly_name}</span>
                              <span className="text-slate-600 ml-1.5">{voice.locale} · {voice.gender}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* OpenAI / 百炼 / 火山 — 语音角色文本输入 */}
              {isVoiceInput && (
                <div className="space-y-1.5">
                  <label className="text-xs text-slate-500">语音角色 <span className="text-slate-600">(可选，留空使用设置中的默认值)</span></label>
                  <input type="text" value={selectedVoice} onChange={(e) => setSelectedVoice(e.target.value)}
                    className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                    placeholder={ttsProvider==='openai'?'alloy':ttsProvider==='bailian'?'longxiaochun':'zh_female_qiaoyuanzongcai_moon_bigtts'} />
                </div>
              )}

              {/* Edge TTS — 语速 / 音量 */}
              {isEdgeTts && (
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-500">语速</label>
                    <div className="flex flex-wrap gap-1.5">
                      {RATE_PRESETS.map((p) => (
                        <button key={p.value} onClick={() => setRate(p.value)}
                          className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${rate===p.value?'bg-indigo-600 text-white':'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}>{p.label}</button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs text-slate-500">音量</label>
                    <div className="flex flex-wrap gap-1.5">
                      {VOLUME_PRESETS.map((p) => (
                        <button key={p.value} onClick={() => setVolume(p.value)}
                          className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${volume===p.value?'bg-indigo-600 text-white':'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}>{p.label}</button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 合成按钮 */}
          <div className="px-5 pb-4">
            <button onClick={handleSynthesize} disabled={!text.trim() || loading}
              className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center justify-center gap-2">
              {loading ? <Loader2 className="w-4 h-4 animate-spin"/> : null}
              {loading ? '合成中...' : '开始合成'}
            </button>
          </div>
        </div>

        {/* 历史记录 */}
        {history.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs text-slate-500 font-medium uppercase tracking-wider">合成历史</h2>
              <button onClick={clearTtsHistory} className="text-xs text-slate-600 hover:text-red-400 transition-colors">清空历史</button>
            </div>
            {history.map((item) => (
              <HistoryCard key={item.id} item={item} playing={playingId===item.id}
                onPlay={() => playAudio(item)} onStop={stopAudio} onDownload={() => downloadAudio(item)} />
            ))}
          </div>
        )}
      </div>
    </main>
  )
}
