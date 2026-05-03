'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  Clapperboard,
  Copy,
  Download,
  ExternalLink,
  Film,
  Layers,
  Loader2,
  Mic,
  Search,
  Sparkles,
} from 'lucide-react'
import type { Video } from '@/lib/api'
import {
  API_BASE_URL,
  formatFastApiDetail,
  scriptStockApi,
  type ScriptStockAudioMode,
  type ScriptStockMaterialTtsFill,
  type ScriptStockMaterialTtsLonger,
  type ScriptStockPexelsVideoApi,
  type ScriptStockTimelineMode,
  type ScriptStockVideoExtendPolicy,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { DEFAULT_SUBTITLE_STYLE, type SubtitleStyle } from './types'

type SourceTab = 'local' | 'pexels'

type StockSegState = {
  id: string
  text: string
  trimSec: number
  sourceTab: SourceTab
  searchQuery: string
  /** 本地素材库多选，顺序即成片拼接顺序（仅「仅 TTS」允许多条） */
  localVideoIds: string[]
  pexelsResults: ScriptStockPexelsVideoApi[]
  searching: boolean
  downloadingId: number | null
  pexelsStoredPath: string | null
}

function newSeg(text: string): StockSegState {
  return {
    id: `ss_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
    text,
    trimSec: 5,
    sourceTab: 'pexels',
    searchQuery: '',
    localVideoIds: [],
    pexelsResults: [],
    searching: false,
    downloadingId: null,
    pexelsStoredPath: null,
  }
}

export function ScriptStockPanel({
  libraryVideos,
  subtitleEnabled = false,
  subtitleStyle,
}: {
  libraryVideos: Video[]
  /** 与智能剪辑侧栏「字幕成片」一致；开启时合成会硬烧字幕 */
  subtitleEnabled?: boolean
  subtitleStyle?: SubtitleStyle
}) {
  const toast = useToast()
  const [fullScript, setFullScript] = useState('')
  const [topic, setTopic] = useState('')
  const [styleHint, setStyleHint] = useState('')
  const [numParas, setNumParas] = useState(5)
  const [generatingScript, setGeneratingScript] = useState(false)
  const [splitting, setSplitting] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [segments, setSegments] = useState<StockSegState[]>([])
  const [projectName, setProjectName] = useState('文案素材成片')
  const [composing, setComposing] = useState(false)
  /** 最近一次合成成功的完整访问 URL（弹窗被拦时仍可复制） */
  const [lastComposeUrl, setLastComposeUrl] = useState<string | null>(null)
  const [lastComposeFilename, setLastComposeFilename] = useState<string | null>(null)
  const [audioMode, setAudioMode] = useState<ScriptStockAudioMode>('tts_only')
  const [ttsVolumeDb, setTtsVolumeDb] = useState(0)
  const [originalVolumeDb, setOriginalVolumeDb] = useState(-6)
  const [timelineMode, setTimelineMode] = useState<ScriptStockTimelineMode>('follow_narration')
  const [videoExtendPolicy, setVideoExtendPolicy] = useState<ScriptStockVideoExtendPolicy>('loop_video_to_cover')
  const [materialTtsFill, setMaterialTtsFill] = useState<ScriptStockMaterialTtsFill>('pad_silence')
  const [materialTtsLonger, setMaterialTtsLonger] = useState<ScriptStockMaterialTtsLonger>('stretch_audio')

  const handleSplit = async (mode: 'paragraph' | 'line') => {
    const script = fullScript.trim()
    if (!script) {
      toast.error('请先填写文案')
      return
    }
    setSplitting(true)
    try {
      const res = await scriptStockApi.split({ script, mode })
      const segs = (res.segments || []).map((t) => newSeg(t))
      if (!segs.length) {
        toast.error('未能分出有效段落')
        return
      }
      setSegments(segs)
      toast.success(`已分为 ${segs.length} 段`)
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setSplitting(false)
    }
  }

  const handleGenerateScript = async () => {
    const t = topic.trim()
    if (!t) {
      toast.error('请填写主题或关键词')
      return
    }
    setGeneratingScript(true)
    try {
      const res = await scriptStockApi.generateScript({
        topic: t,
        style_hint: styleHint.trim(),
        num_paragraphs: numParas,
      })
      setFullScript(res.script || '')
      toast.success('文案已生成，可继续分段或编辑')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setGeneratingScript(false)
    }
  }

  const handleSuggestAllQueries = async () => {
    if (!segments.length) {
      toast.error('请先分段')
      return
    }
    setSuggesting(true)
    try {
      const res = await scriptStockApi.suggestQueries({ segments: segments.map((s) => s.text) })
      const qs = res.queries || []
      setSegments((prev) =>
        prev.map((s, i) => ({
          ...s,
          searchQuery: (qs[i] || s.searchQuery || '').trim(),
        })),
      )
      toast.success('已为各段生成英文搜索词')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setSuggesting(false)
    }
  }

  const searchPexelsForSeg = async (segId: string) => {
    const seg = segments.find((s) => s.id === segId)
    if (!seg) return
    const q = (seg.searchQuery || seg.text).trim()
    if (!q) {
      toast.error('请填写搜索词')
      return
    }
    setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, searching: true } : s)))
    try {
      const res = await scriptStockApi.pexelsSearch({ query: q, per_page: 12 })
      setSegments((prev) =>
        prev.map((s) => (s.id === segId ? { ...s, searching: false, pexelsResults: res.videos || [] } : s)),
      )
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, searching: false } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  const downloadPexels = async (segId: string, videoId: number) => {
    setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingId: videoId } : s)))
    try {
      const res = await scriptStockApi.pexelsDownload({ pexels_video_id: videoId, preferred_quality: 'hd' })
      setSegments((prev) =>
        prev.map((s) =>
          s.id === segId
            ? {
                ...s,
                downloadingId: null,
                pexelsStoredPath: res.stored_rel_path,
                sourceTab: 'pexels',
              }
            : s,
        ),
      )
      toast.success('已下载到本地隔离目录 stock_media/pexels')
    } catch (e) {
      setSegments((prev) => prev.map((s) => (s.id === segId ? { ...s, downloadingId: null } : s)))
      toast.error(formatFastApiDetail(e))
    }
  }

  const handleCompose = async () => {
    if (!segments.length) {
      toast.error('请先准备分段与素材')
      return
    }
    const payload: Array<{
      kind: 'library' | 'pexels'
      video_id?: string
      library_video_ids?: string[]
      stored_rel_path?: string
      trim_sec: number
      text: string
    }> = []
    for (const s of segments) {
      const trim = Math.max(0, Number(s.trimSec) || 0)
      if (s.sourceTab === 'local') {
        if (!s.localVideoIds.length) {
          toast.error('存在未选择本地视频的段落')
          return
        }
        if (s.localVideoIds.length > 1 && audioMode !== 'tts_only') {
          toast.error('多段本地素材按顺序拼接仅支持「仅 TTS」；请改为单条或切换为仅 TTS。')
          return
        }
        payload.push({
          kind: 'library',
          library_video_ids: s.localVideoIds,
          trim_sec: trim,
          text: (s.text || '').trim(),
        })
      } else {
        if (!s.pexelsStoredPath) {
          toast.error('存在未下载 Pexels 素材的段落（网上素材需先下载到隔离目录）')
          return
        }
        payload.push({
          kind: 'pexels',
          stored_rel_path: s.pexelsStoredPath,
          trim_sec: trim,
          text: (s.text || '').trim(),
        })
      }
    }
    if ((audioMode === 'tts_only' || audioMode === 'mix') && payload.every((p) => !p.text)) {
      toast.error('当前模式需要配音文案：请在各段填写文案，或改用「仅素材原声」')
      return
    }
    setComposing(true)
    try {
      const res = await scriptStockApi.compose({
        segments: payload,
        project_name: projectName.trim() || 'stock_clip',
        audio_mode: audioMode,
        tts_volume_db: ttsVolumeDb,
        original_volume_db: originalVolumeDb,
        timeline_mode: timelineMode,
        video_extend_policy: videoExtendPolicy,
        material_tts_fill: materialTtsFill,
        material_tts_longer: materialTtsLonger,
        include_subtitle: subtitleEnabled,
        subtitle_style: subtitleEnabled ? (subtitleStyle ?? DEFAULT_SUBTITLE_STYLE) : undefined,
      })
      const base = API_BASE_URL.replace(/\/$/, '')
      const path = (res.public_url || '').startsWith('/') ? res.public_url : `/${res.public_url || ''}`
      const fullUrl = `${base}${path}`
      setLastComposeUrl(fullUrl)
      setLastComposeFilename(res.filename || null)
      toast.success('配音成片已完成，链接已显示在下方')
      window.open(fullUrl, '_blank', 'noopener,noreferrer')
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setComposing(false)
    }
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest flex items-center gap-2">
            <Clapperboard className="w-4 h-4 text-sky-400" />
            文案素材成片
          </p>
          <p className="text-[11px] text-slate-500 leading-relaxed max-w-xl">
            为每一段匹配画面并合成<strong className="text-slate-300"> TTS 配音</strong>
            （下方可选仅配音 / 仅原声 / 混合及分贝调节）。可选用<strong className="text-slate-300">素材库整段视频</strong>
            ，或在 <strong className="text-slate-300">Pexels</strong> 下载素材至独立目录。
          </p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0 text-[11px]">
          <Link href="/settings" className="text-sky-400 hover:underline">
            Pexels API Key →
          </Link>
          <Link href="/settings" className="text-emerald-400/90 hover:underline">
            TTS 配音引擎 →
          </Link>
        </div>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 space-y-3">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">AI 写文案（可选）</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="主题或关键词"
            className="sm:col-span-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
          <input
            type="number"
            min={1}
            max={20}
            value={numParas}
            onChange={(e) => setNumParas(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
            className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
          />
        </div>
        <input
          value={styleHint}
          onChange={(e) => setStyleHint(e.target.value)}
          placeholder="风格补充（可选）：如 轻快短视频旁白、纪录片口吻…"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500"
        />
        <button
          type="button"
          disabled={generatingScript}
          onClick={() => void handleGenerateScript()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-medium"
        >
          {generatingScript ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          AI 生成文案
        </button>
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 space-y-2">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">文案正文</p>
        <textarea
          value={fullScript}
          onChange={(e) => setFullScript(e.target.value)}
          rows={8}
          placeholder="粘贴完整文案，或先用上方 AI 生成…"
          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500 resize-y min-h-[140px]"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={splitting}
            onClick={() => void handleSplit('paragraph')}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-sky-500 text-sm text-slate-200"
          >
            {splitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Layers className="w-4 h-4 text-sky-400" />}
            按空行分段
          </button>
          <button
            type="button"
            disabled={splitting}
            onClick={() => void handleSplit('line')}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-sky-500 text-sm text-slate-200"
          >
            按单行分段
          </button>
        </div>
      </div>

      {segments.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold text-slate-400">分段素材（共 {segments.length} 段）</p>
            <button
              type="button"
              disabled={suggesting}
              onClick={() => void handleSuggestAllQueries()}
              className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-white disabled:opacity-50"
            >
              {suggesting ? <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1" /> : null}
              一键生成英文搜索词
            </button>
          </div>

          <div className="space-y-4">
            {segments.map((seg, idx) => (
              <div key={seg.id} className="rounded-xl border border-slate-700 bg-slate-950/50 p-4 space-y-3">
                <div className="space-y-1.5">
                  <p className="text-[11px] text-slate-500">第 {idx + 1} 段 · 配音文案（可改）</p>
                  <textarea
                    value={seg.text}
                    onChange={(e) =>
                      setSegments((prev) =>
                        prev.map((s) => (s.id === seg.id ? { ...s, text: e.target.value } : s)),
                      )
                    }
                    rows={3}
                    placeholder="该段口播/旁白，将用于 TTS…"
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-sky-500 resize-y min-h-[72px]"
                  />
                </div>

                <div className="flex gap-2">
                  <label className="text-[10px] text-slate-500 shrink-0 pt-2">成片截取(秒)</label>
                  <input
                    type="number"
                    min={0}
                    max={600}
                    step={0.5}
                    value={seg.trimSec}
                    onChange={(e) => {
                      const v = Math.max(0, Number(e.target.value) || 0)
                      setSegments((prev) => prev.map((s) => (s.id === seg.id ? { ...s, trimSec: v } : s)))
                    }}
                    className="w-24 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-sm text-slate-200"
                  />
                  <span className="text-[10px] text-slate-600 pt-2">0 = 使用整段素材时长</span>
                </div>

                <div className="flex rounded-lg border border-slate-700 overflow-hidden w-fit">
                  <button
                    type="button"
                    onClick={() =>
                      setSegments((prev) => prev.map((s) => (s.id === seg.id ? { ...s, sourceTab: 'local' } : s)))
                    }
                    className={`px-3 py-1.5 text-xs font-medium ${
                      seg.sourceTab === 'local' ? 'bg-violet-600 text-white' : 'bg-slate-900 text-slate-400'
                    }`}
                  >
                    本地素材库
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setSegments((prev) => prev.map((s) => (s.id === seg.id ? { ...s, sourceTab: 'pexels' } : s)))
                    }
                    className={`px-3 py-1.5 text-xs font-medium ${
                      seg.sourceTab === 'pexels' ? 'bg-sky-600 text-white' : 'bg-slate-900 text-slate-400'
                    }`}
                  >
                    Pexels（先下载）
                  </button>
                </div>

                {seg.sourceTab === 'local' ? (
                  <div className="space-y-2">
                    {libraryVideos.length === 0 ? (
                      <div className="flex items-center gap-2 text-xs text-amber-300">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        暂无可用本地视频，请先上传或在素材处理中完成解析。
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        <select
                          multiple
                          size={Math.min(8, Math.max(4, libraryVideos.length))}
                          value={seg.localVideoIds}
                          onChange={(e) => {
                            const next = Array.from(e.target.selectedOptions, (o) => o.value)
                            setSegments((prev) =>
                              prev.map((s) => (s.id === seg.id ? { ...s, localVideoIds: next } : s)),
                            )
                          }}
                          className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 min-h-[120px]"
                        >
                          {libraryVideos.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.name} · {v.status === 'done' ? '已处理' : v.status}
                            </option>
                          ))}
                        </select>
                        <p className="text-[10px] text-slate-500">
                          按住 Ctrl（Mac：⌘）点选多条，顺序与列表一致；多段仅「仅 TTS」可用。单选一条与原先相同。
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <input
                        value={seg.searchQuery}
                        onChange={(e) =>
                          setSegments((prev) =>
                            prev.map((s) => (s.id === seg.id ? { ...s, searchQuery: e.target.value } : s)),
                          )
                        }
                        placeholder="英文搜索词，如 ocean sunset"
                        className="flex-1 min-w-[160px] rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
                      />
                      <button
                        type="button"
                        disabled={seg.searching}
                        onClick={() => void searchPexelsForSeg(seg.id)}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-600 hover:border-sky-500 text-sm"
                      >
                        {seg.searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                        搜索
                      </button>
                    </div>
                    {seg.pexelsStoredPath ? (
                      <p className="text-[11px] text-emerald-400 flex items-center gap-1">
                        <Film className="w-3.5 h-3.5" />
                        已就绪：{seg.pexelsStoredPath}
                      </p>
                    ) : (
                      <p className="text-[11px] text-slate-500">选中视频后点击下载，文件仅写入 stock_media/pexels</p>
                    )}
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                      {seg.pexelsResults.map((pv) => (
                        <div key={pv.id} className="rounded-lg border border-slate-700 overflow-hidden bg-slate-900/80">
                          <img src={pv.image} alt="" className="w-full h-24 object-cover" />
                          <div className="p-2 space-y-1">
                            <p className="text-[10px] text-slate-500 truncate">{pv.duration}s</p>
                            <button
                              type="button"
                              disabled={seg.downloadingId === pv.id}
                              onClick={() => void downloadPexels(seg.id, pv.id)}
                              className="w-full flex items-center justify-center gap-1 py-1.5 rounded bg-sky-700 hover:bg-sky-600 text-[11px] text-white disabled:opacity-50"
                            >
                              {seg.downloadingId === pv.id ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <Download className="w-3 h-3" />
                              )}
                              下载本段
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-emerald-500/25 bg-emerald-950/30 p-4 space-y-4">
            <div className="flex items-start gap-2">
              <Mic className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
              <div className="space-y-1 min-w-0">
                <p className="text-xs font-semibold text-emerald-200">配音与混音</p>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  <strong className="text-slate-400">仅 TTS</strong>：画面素材静音，只保留配音（默认）。
                  <strong className="text-slate-400"> 仅原声</strong>：保留素材里的录音，不做 TTS。
                  <strong className="text-slate-400"> 混合</strong>：TTS 与素材原声叠加，可用下方两个音量分别精细调节。
                  Pexels 素材多为环境声或无对白，混合时建议压低「原声」。
                </p>
                <p className="text-[10px] text-slate-500 leading-relaxed border-t border-slate-700/50 pt-2 mt-2">
                  <strong className="text-slate-400">字幕</strong>：
                  {subtitleEnabled
                    ? '侧栏已开启「字幕成片」，合成时将按各段配音文案与分段时长硬烧字幕（样式与侧栏字幕一致）。'
                    : '侧栏关闭「字幕成片」时不会烧录字幕；需要字幕请在侧栏打开字幕成片。'}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { id: 'tts_only' as const, label: '仅 TTS 配音' },
                  { id: 'original_only' as const, label: '仅素材原声' },
                  { id: 'mix' as const, label: 'TTS + 原声混合' },
                ]
              ).map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setAudioMode(id)}
                  className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                    audioMode === id
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-800 text-slate-400 hover:bg-slate-700 border border-slate-700'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {(audioMode === 'tts_only' || audioMode === 'mix') && (
              <div className="space-y-3 rounded-lg border border-slate-700/80 bg-slate-950/50 p-3">
                <p className="text-[11px] font-medium text-slate-200">画面与配音时长</p>
                <p className="text-[10px] text-slate-500 leading-relaxed">
                  与手动匹配成片逻辑对齐：<strong className="text-slate-400">以配音为准</strong>
                  时整段时长跟 TTS（短则裁画面、长则补画面）；<strong className="text-slate-400">以素材为准</strong>
                  时整段时长跟素材画面，TTS 在轨上补齐或压缩。
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setTimelineMode('follow_narration')}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-medium ${
                      timelineMode === 'follow_narration'
                        ? 'bg-sky-600 text-white'
                        : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}
                  >
                    以配音为准（推荐）
                  </button>
                  <button
                    type="button"
                    onClick={() => setTimelineMode('follow_material')}
                    className={`px-3 py-1.5 rounded-lg text-[11px] font-medium ${
                      timelineMode === 'follow_material'
                        ? 'bg-sky-600 text-white'
                        : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}
                  >
                    以素材成片为准
                  </button>
                </div>
                {timelineMode === 'follow_narration' && (
                  <div className="space-y-1.5">
                    <p className="text-[10px] text-slate-500">配音长于画面时</p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setVideoExtendPolicy('loop_video_to_cover')}
                        className={`px-3 py-1.5 rounded-lg text-[11px] ${
                          videoExtendPolicy === 'loop_video_to_cover'
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        循环拼接画面
                      </button>
                      <button
                        type="button"
                        onClick={() => setVideoExtendPolicy('freeze_last_frame')}
                        className={`px-3 py-1.5 rounded-lg text-[11px] ${
                          videoExtendPolicy === 'freeze_last_frame'
                            ? 'bg-indigo-600 text-white'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}
                      >
                        尾帧定格
                      </button>
                    </div>
                  </div>
                )}
                {timelineMode === 'follow_material' && (
                  <div className="space-y-2 border-t border-slate-700/60 pt-2">
                    <div className="space-y-1">
                      <p className="text-[10px] text-slate-500">TTS 短于画面时</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setMaterialTtsFill('pad_silence')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsFill === 'pad_silence'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          尾段补静音
                        </button>
                        <button
                          type="button"
                          onClick={() => setMaterialTtsFill('loop_audio')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsFill === 'loop_audio'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          循环该段 TTS
                        </button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] text-slate-500">TTS 长于画面时</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setMaterialTtsLonger('stretch_audio')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsLonger === 'stretch_audio'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          变速压缩配音
                        </button>
                        <button
                          type="button"
                          onClick={() => setMaterialTtsLonger('trim_tts')}
                          className={`px-3 py-1.5 rounded-lg text-[11px] ${
                            materialTtsLonger === 'trim_tts'
                              ? 'bg-violet-600 text-white'
                              : 'bg-slate-800 text-slate-400 border border-slate-700'
                          }`}
                        >
                          裁掉多余配音
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
            {(audioMode === 'tts_only' || audioMode === 'mix') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>TTS 配音音量</span>
                  <span className="tabular-nums text-emerald-300">{ttsVolumeDb} dB</span>
                </div>
                <input
                  type="range"
                  min={-24}
                  max={12}
                  step={1}
                  value={ttsVolumeDb}
                  onChange={(e) => setTtsVolumeDb(Number(e.target.value))}
                  className="w-full accent-emerald-500"
                />
              </div>
            )}
            {(audioMode === 'original_only' || audioMode === 'mix') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-slate-400">
                  <span>素材原声音量</span>
                  <span className="tabular-nums text-violet-300">{originalVolumeDb} dB</span>
                </div>
                <input
                  type="range"
                  min={-48}
                  max={12}
                  step={1}
                  value={originalVolumeDb}
                  onChange={(e) => setOriginalVolumeDb(Number(e.target.value))}
                  className="w-full accent-violet-500"
                />
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/40 p-4 flex flex-col sm:flex-row gap-3 sm:items-end">
            <div className="flex-1 space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-wider">成片文件名前缀</label>
              <input
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200"
              />
            </div>
            <button
              type="button"
              disabled={composing}
              onClick={() => void handleCompose()}
              className="px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 text-white text-sm font-semibold shrink-0"
            >
              {composing ? <Loader2 className="w-5 h-5 animate-spin inline mr-2" /> : null}
              合成配音成片
            </button>
          </div>
        </div>
      )}

      {lastComposeUrl ? (
        <div className="rounded-xl border border-emerald-500/35 bg-emerald-950/15 p-4 space-y-2">
          <p className="text-[11px] font-medium text-emerald-200/95">
            本次成片访问链接（弹窗被拦截或未打开时，可从此复制或点击打开）
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
            <input
              readOnly
              value={lastComposeUrl}
              onFocus={(e) => e.target.select()}
              className="flex-1 min-w-0 rounded-md bg-slate-950 border border-slate-600 px-2 py-2 text-[11px] font-mono text-slate-300"
            />
            <div className="flex gap-2 shrink-0">
              <button
                type="button"
                onClick={() => {
                  void (async () => {
                    try {
                      await navigator.clipboard.writeText(lastComposeUrl)
                      toast.success('链接已复制到剪贴板')
                    } catch {
                      toast.error('复制失败，请手动框选输入框内链接')
                    }
                  })()
                }}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-600 text-[11px] text-slate-200 hover:bg-slate-700"
              >
                <Copy className="w-3.5 h-3.5" />
                复制
              </button>
              <a
                href={lastComposeUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-700/90 hover:bg-emerald-600 text-[11px] text-white"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                打开
              </a>
            </div>
          </div>
          {lastComposeFilename ? (
            <p className="text-[10px] text-slate-500">文件名：{lastComposeFilename}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
