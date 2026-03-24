'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft,
  ChevronDown,
  Download,
  Loader2,
  Mic2,
  Play,
  RefreshCw,
  Square,
  Volume2,
} from 'lucide-react'
import { ttsApi, type TTSResponse, type VoiceInfo } from '@/lib/api'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function buildAudioUrl(filename: string) {
  return `${API_BASE}/api/tts/audio/${filename}`
}

const RATE_PRESETS = [
  { label: '很慢', value: '-50%' },
  { label: '慢', value: '-20%' },
  { label: '正常', value: '+0%' },
  { label: '快', value: '+20%' },
  { label: '很快', value: '+50%' },
]

const VOLUME_PRESETS = [
  { label: '小', value: '-30%' },
  { label: '正常', value: '+0%' },
  { label: '大', value: '+20%' },
  { label: '最大', value: '+50%' },
]

interface HistoryItem {
  id: string
  text: string
  voice: string
  rate: string
  volume: string
  filename: string
}
function HistoryCard({
  item,
  playing,
  onPlay,
  onStop,
  onDownload,
}: {
  item: HistoryItem
  playing: boolean
  onPlay: () => void
  onStop: () => void
  onDownload: () => void
}) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 flex gap-3 items-start transition-all ${
        playing
          ? 'border-violet-500/50 bg-violet-500/5'
          : 'border-slate-800 bg-slate-900/40'
      }`}
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-200 line-clamp-2">{item.text}</p>
        <p className="text-xs text-slate-500 mt-1">
          {item.voice} · 语速 {item.rate} · 音量 {item.volume}
        </p>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {playing ? (
          <button
            onClick={onStop}
            className="w-7 h-7 rounded-lg bg-violet-500/20 text-violet-300 hover:bg-violet-500/30 flex items-center justify-center transition-colors"
          >
            <Square className="w-3.5 h-3.5" />
          </button>
        ) : (
          <button
            onClick={onPlay}
            className="w-7 h-7 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center justify-center transition-colors"
          >
            <Play className="w-3.5 h-3.5" />
          </button>
        )}
        <button
          onClick={onDownload}
          className="w-7 h-7 rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700 flex items-center justify-center transition-colors"
        >
          <Download className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
export default function TTSPage() {
  const [text, setText] = useState('')
  const [voices, setVoices] = useState<VoiceInfo[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [selectedVoice, setSelectedVoice] = useState('zh-CN-XiaoxiaoNeural')
  const [rate, setRate] = useState('+0%')
  const [volume, setVolume] = useState('+0%')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [showVoiceDropdown, setShowVoiceDropdown] = useState(false)
  const [voiceSearch, setVoiceSearch] = useState('')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setVoicesLoading(true)
    ttsApi
      .listVoices('zh')
      .then((data) => setVoices(data || []))
      .catch(console.error)
      .finally(() => setVoicesLoading(false))
  }, [])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowVoiceDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filteredVoices = voices.filter(
    (v) =>
      v.friendly_name.toLowerCase().includes(voiceSearch.toLowerCase()) ||
      v.name.toLowerCase().includes(voiceSearch.toLowerCase()),
  )
  const selectedVoiceInfo = voices.find((v) => v.name === selectedVoice)

  const handleSynthesize = async () => {
    if (!text.trim() || loading) return
    setLoading(true)
    setError('')
    try {
      const res: TTSResponse = await ttsApi.synthesize({
        text: text.trim(),
        voice: selectedVoice,
        rate,
        volume,
      })
      const item: HistoryItem = {
        id: res.filename,
        text: text.trim(),
        voice: selectedVoice,
        rate,
        volume,
        filename: res.filename,
      }
      setHistory((prev) => [item, ...prev])
      playAudio(item)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'TTS 合成失败，请检查服务配置。')
    } finally {
      setLoading(false)
    }
  }

  const playAudio = (item: HistoryItem) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    const audio = new Audio(buildAudioUrl(item.filename))
    audioRef.current = audio
    setPlayingId(item.id)
    audio.play()
    audio.onended = () => setPlayingId(null)
    audio.onerror = () => setPlayingId(null)
  }

  const stopAudio = () => {
    audioRef.current?.pause()
    audioRef.current = null
    setPlayingId(null)
  }

  const downloadAudio = (item: HistoryItem) => {
    const a = document.createElement('a')
    a.href = buildAudioUrl(item.filename)
    a.download = 'tts_' + item.filename
    a.click()
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* 页头 */}
        <div className="flex items-center gap-3">
          <Link href="/match" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" />文案匹配
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Mic2 className="w-5 h-5 text-violet-400" />TTS 配音
          </h1>
        </div>

        {/* 文本输入 */}
        <section className="space-y-3">
          <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">输入文案</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="输入需要转换为语音的文案，支持中英文混合...（最多 5000 字）"
            rows={6}
            maxLength={5000}
            className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-violet-500 resize-none transition-colors"
          />
          <div className="flex justify-between items-center">
            <span className="text-xs text-slate-600">{text.length} / 5000</span>
            {text.length > 0 && (
              <button onClick={() => setText('')} className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors">
                <RefreshCw className="w-3 h-3" />清空
              </button>
            )}
          </div>
        </section>

        {/* 配置区 */}
        <section className="grid sm:grid-cols-3 gap-4">
          {/* 语音选择 */}
          <div className="sm:col-span-1 space-y-1.5" ref={dropdownRef}>
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">语音角色</label>
            <div className="relative">
              <button
                onClick={() => setShowVoiceDropdown((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-slate-900/60 border border-slate-700 hover:border-slate-500 text-sm transition-colors"
              >
                <span className="truncate text-left">
                  {voicesLoading ? '加载中...' : selectedVoiceInfo?.friendly_name || selectedVoice}
                </span>
                <ChevronDown className="w-4 h-4 text-slate-500 shrink-0 ml-2" />
              </button>
              {showVoiceDropdown && (
                <div className="absolute z-20 mt-1 w-64 rounded-xl border border-slate-700 bg-[#131620] shadow-2xl overflow-hidden">
                  <div className="p-2 border-b border-slate-800">
                    <input
                      type="text"
                      placeholder="搜索语音..."
                      value={voiceSearch}
                      onChange={(e) => setVoiceSearch(e.target.value)}
                      className="w-full bg-slate-800 rounded-lg px-3 py-1.5 text-xs outline-none focus:ring-1 focus:ring-violet-500"
                    />
                  </div>
                  <div className="max-h-52 overflow-y-auto">
                    {filteredVoices.length === 0 ? (
                      <p className="text-xs text-slate-500 px-3 py-3 text-center">无匹配语音</p>
                    ) : (
                      filteredVoices.map((v) => (
                        <button
                          key={v.name}
                          onClick={() => { setSelectedVoice(v.name); setShowVoiceDropdown(false); setVoiceSearch('') }}
                          className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-800 flex items-center justify-between gap-2 ${
                            selectedVoice === v.name ? 'text-violet-300 bg-violet-500/10' : 'text-slate-300'
                          }`}
                        >
                          <span className="truncate">{v.friendly_name}</span>
                          <span className="text-slate-600 shrink-0">{v.gender === 'Female' ? '女' : '男'}</span>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* 语速 */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">语速</label>
            <div className="flex gap-1.5 flex-wrap">
              {RATE_PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setRate(p.value)}
                  className={`px-2.5 py-1 rounded-lg text-xs border transition-colors ${
                    rate === p.value
                      ? 'border-violet-500 bg-violet-500/15 text-violet-300'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* 音量 */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">音量</label>
            <div className="flex gap-1.5 flex-wrap">
              {VOLUME_PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setVolume(p.value)}
                  className={`px-2.5 py-1 rounded-lg text-xs border transition-colors ${
                    volume === p.value
                      ? 'border-violet-500 bg-violet-500/15 text-violet-300'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* 参数摘要 + 合成按钮 */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Volume2 className="w-3.5 h-3.5" />
            <span>{selectedVoiceInfo?.friendly_name || selectedVoice}</span>
            <span className="text-slate-700">·</span>
            <span>语速 {rate}</span>
            <span className="text-slate-700">·</span>
            <span>音量 {volume}</span>
          </div>
          <button
            onClick={handleSynthesize}
            disabled={!text.trim() || loading}
            className="ml-auto px-6 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-500 text-sm font-medium flex items-center gap-2 transition-colors"
          >
            {loading ? (
              <><Loader2 className="w-4 h-4 animate-spin" />合成中...</>
            ) : (
              <><Mic2 className="w-4 h-4" />开始合成</>
            )}
          </button>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="rounded-xl border border-red-600/30 bg-red-500/5 px-5 py-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* 合成历史 */}
        {history.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                合成记录
                <span className="ml-2 normal-case font-normal text-slate-600">{history.length} 条</span>
              </h2>
              <button
                onClick={() => { stopAudio(); setHistory([]) }}
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                清空记录
              </button>
            </div>
            <div className="space-y-2">
              {history.map((item) => (
                <HistoryCard
                  key={item.id}
                  item={item}
                  playing={playingId === item.id}
                  onPlay={() => playAudio(item)}
                  onStop={stopAudio}
                  onDownload={() => downloadAudio(item)}
                />
              ))}
            </div>
          </section>
        )}

        {history.length === 0 && !loading && (
          <div className="rounded-xl border border-slate-800 px-6 py-12 text-center space-y-2">
            <Mic2 className="w-8 h-8 text-slate-700 mx-auto" />
            <p className="text-sm text-slate-500">输入文案后点击「开始合成」，生成的音频会在这里显示。</p>
          </div>
        )}
      </div>
    </main>
  )
}
