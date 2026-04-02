'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { X, Loader2, Save, Search, Check, Film, Subtitles } from 'lucide-react'
import { API_BASE_URL, clipsApi, type ClipResult } from '@/lib/api'
import { videoStreamUrl, clipStreamUrl, fmt } from '@/app/match/_components/types'

type VideoOption = { id: string; name: string }

export type VideoResultDrawerProps = {
  open: boolean
  onClose: () => void
  /** 优先展示的视频 */
  videoId?: string
  /** 可选：让用户在抽屉内切换视频 */
  videoOptions?: VideoOption[]
  title?: string
}

type EditState = {
  asr_text: string
  vlm_description: string
  dirty: boolean
  saving: boolean
  error: string
}

function safeStr(v: string | null | undefined) {
  return (v ?? '').toString()
}

export function VideoResultDrawer({
  open,
  onClose,
  videoId,
  videoOptions,
  title = '处理结果',
}: VideoResultDrawerProps) {
  const initialVideoId = useMemo(() => {
    const v = (videoId || '').trim()
    if (v) return v
    const first = videoOptions?.[0]?.id || ''
    return first
  }, [videoId, videoOptions])

  const [curVideoId, setCurVideoId] = useState(initialVideoId)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [clips, setClips] = useState<ClipResult[]>([])
  const [q, setQ] = useState('')
  const [activeClipId, setActiveClipId] = useState<string>('')
  const [playerMode, setPlayerMode] = useState<'video' | 'clip'>('video')

  const [editing, setEditing] = useState<Record<string, EditState>>({})

  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    if (!open) return
    setCurVideoId(initialVideoId)
  }, [open, initialVideoId])

  useEffect(() => {
    if (!open) return
    if (!curVideoId) return
    setLoading(true)
    setErr('')
    clipsApi
      .listByVideo(curVideoId)
      .then((rows) => {
        setClips(rows || [])
        // 初始化编辑缓存（避免首次点击编辑时闪烁）
        const map: Record<string, EditState> = {}
        ;(rows || []).forEach((c) => {
          map[c.id] = {
            asr_text: safeStr(c.asr_text),
            vlm_description: safeStr(c.vlm_description),
            dirty: false,
            saving: false,
            error: '',
          }
        })
        setEditing(map)
        const first = rows?.[0]?.id || ''
        setActiveClipId(first)
      })
      .catch((e: unknown) => {
        setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载失败')
      })
      .finally(() => setLoading(false))
  }, [open, curVideoId])

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    if (!kw) return clips
    return clips.filter((c) => {
      const a = safeStr(c.asr_text).toLowerCase()
      const v = safeStr(c.vlm_description).toLowerCase()
      return a.includes(kw) || v.includes(kw) || c.id.toLowerCase().includes(kw)
    })
  }, [clips, q])

  const activeClip = clips.find((c) => c.id === activeClipId) || null

  const seekTo = (t: number) => {
    const el = videoRef.current
    if (!el) return
    try {
      el.currentTime = Math.max(0, t)
      void el.play().catch(() => {})
    } catch {
      // ignore
    }
  }

  const jumpToClip = (clip: ClipResult) => {
    setActiveClipId(clip.id)
    if (playerMode === 'video') {
      seekTo(clip.start_time || 0)
    }
  }

  const setEditField = (clipId: string, field: 'asr_text' | 'vlm_description', value: string) => {
    setEditing((prev) => {
      const cur = prev[clipId] || {
        asr_text: '',
        vlm_description: '',
        dirty: false,
        saving: false,
        error: '',
      }
      return {
        ...prev,
        [clipId]: {
          ...cur,
          [field]: value,
          dirty: true,
          error: '',
        },
      }
    })
  }

  const saveClip = async (clipId: string) => {
    const st = editing[clipId]
    if (!st || st.saving) return
    setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: true, error: '' } }))
    try {
      await clipsApi.update(clipId, { asr_text: st.asr_text, vlm_description: st.vlm_description })
      setClips((prev) =>
        prev.map((c) =>
          c.id === clipId ? { ...c, asr_text: st.asr_text, vlm_description: st.vlm_description } : c
        )
      )
      setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: false, dirty: false, error: '' } }))
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败'
      setEditing((p) => ({ ...p, [clipId]: { ...p[clipId], saving: false, error: msg } }))
    }
  }

  if (!open) return null

  const playerSrc =
    playerMode === 'video'
      ? videoStreamUrl(curVideoId)
      : activeClipId
        ? clipStreamUrl(activeClipId)
        : ''

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="absolute right-0 top-0 h-full w-full max-w-5xl bg-[#0d0f14] border-l border-slate-800 shadow-2xl flex flex-col">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center gap-3">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-slate-200 truncate">{title}</div>
            <div className="text-xs text-slate-500 truncate">
              {curVideoId ? `video_id: ${curVideoId}` : '未选择视频'}
              {playerMode === 'clip' && activeClip ? ` · clip: ${fmt(activeClip.start_time)}-${fmt(activeClip.end_time)}` : ''}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {videoOptions && videoOptions.length > 0 && (
              <select
                value={curVideoId}
                onChange={(e) => setCurVideoId(e.target.value)}
                className="max-w-[280px] px-2 py-1.5 rounded-md bg-slate-900/60 border border-slate-700 text-xs text-slate-200 outline-none focus:border-indigo-500"
              >
                {videoOptions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-lg border border-slate-800 bg-slate-900/40 hover:border-slate-600 transition-colors"
              aria-label="关闭"
            >
              <X className="w-4 h-4 text-slate-300" />
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2">
          {/* Player */}
          <div className="border-b lg:border-b-0 lg:border-r border-slate-800 min-h-0 flex flex-col">
            <div className="px-5 py-3 flex items-center gap-2 border-b border-slate-800">
              <div className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 border border-slate-700 px-1 py-1 text-xs">
                <button
                  onClick={() => setPlayerMode('video')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    playerMode === 'video' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Film className="inline w-3.5 h-3.5 mr-1" />
                  原片预览
                </button>
                <button
                  onClick={() => setPlayerMode('clip')}
                  className={`px-3 py-0.5 rounded-full transition-colors ${
                    playerMode === 'clip' ? 'bg-emerald-500 text-slate-900' : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Subtitles className="inline w-3.5 h-3.5 mr-1" />
                  片段预览
                </button>
              </div>

              {activeClip && playerMode === 'video' && (
                <button
                  onClick={() => seekTo(activeClip.start_time || 0)}
                  className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-slate-200 hover:border-slate-500 transition-colors"
                >
                  跳到当前片段起点（{fmt(activeClip.start_time || 0)}）
                </button>
              )}
            </div>

            <div className="p-5 flex-1 min-h-0">
              {!curVideoId ? (
                <div className="h-full flex items-center justify-center text-sm text-slate-500">请选择一个视频</div>
              ) : (
                <div className="h-full rounded-xl border border-slate-800 bg-black/40 overflow-hidden">
                  <video
                    ref={videoRef}
                    src={playerSrc}
                    controls
                    className="w-full h-full object-contain bg-black"
                    crossOrigin="anonymous"
                  />
                </div>
              )}
              <div className="text-[11px] text-slate-600 mt-3">
                播放源：{playerSrc ? playerSrc.replace(API_BASE_URL, '') : '-'}
              </div>
            </div>
          </div>

          {/* Results */}
          <div className="min-h-0 flex flex-col">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="搜索 ASR / VLM ..."
                  className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors"
                />
              </div>
              <div className="text-xs text-slate-500 shrink-0">{filtered.length}/{clips.length}</div>
            </div>

            <div className="flex-1 min-h-0 overflow-auto">
              {loading ? (
                <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />加载中...
                </div>
              ) : err ? (
                <div className="p-6 text-sm text-red-400">{err}</div>
              ) : filtered.length === 0 ? (
                <div className="p-6 text-sm text-slate-500">没有匹配的片段</div>
              ) : (
                <div className="divide-y divide-slate-800">
                  {filtered.map((c) => {
                    const isActive = c.id === activeClipId
                    const st = editing[c.id]
                    const canSave = !!st?.dirty && !st?.saving
                    return (
                      <div
                        key={c.id}
                        className={`px-5 py-4 transition-colors ${isActive ? 'bg-indigo-500/5' : 'hover:bg-slate-900/30'}`}
                      >
                        <div className="flex items-start gap-3">
                          <button
                            onClick={() => jumpToClip(c)}
                            className={`shrink-0 mt-0.5 px-2 py-1 rounded-md border text-[11px] transition-colors ${
                              isActive ? 'border-indigo-500/50 text-indigo-300 bg-indigo-500/10' : 'border-slate-700 text-slate-400 hover:border-slate-500'
                            }`}
                          >
                            {fmt(c.start_time || 0)}-{fmt(c.end_time || 0)}
                          </button>
                          <div className="min-w-0 flex-1 space-y-2">
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-slate-500 truncate">{c.id}</span>
                              <div className="ml-auto flex items-center gap-2">
                                <button
                                  onClick={() => saveClip(c.id)}
                                  disabled={!canSave}
                                  className="text-xs px-2 py-1 rounded-md border border-slate-700 bg-slate-900/40 text-slate-300 hover:border-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                >
                                  {st?.saving ? <Loader2 className="inline w-3.5 h-3.5 mr-1 animate-spin" /> : <Save className="inline w-3.5 h-3.5 mr-1" />}
                                  保存
                                </button>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 gap-2">
                              <div>
                                <div className="text-[11px] text-slate-500 mb-1">ASR</div>
                                <textarea
                                  value={st?.asr_text ?? safeStr(c.asr_text)}
                                  onChange={(e) => setEditField(c.id, 'asr_text', e.target.value)}
                                  rows={3}
                                  className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                />
                              </div>
                              <div>
                                <div className="text-[11px] text-slate-500 mb-1">VLM</div>
                                <textarea
                                  value={st?.vlm_description ?? safeStr(c.vlm_description)}
                                  onChange={(e) => setEditField(c.id, 'vlm_description', e.target.value)}
                                  rows={4}
                                  className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-800 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-colors"
                                />
                              </div>
                            </div>

                            {st?.dirty && (
                              <div className="text-[11px] text-amber-400/80 flex items-center gap-1">
                                <Check className="w-3.5 h-3.5" />
                                有未保存修改
                              </div>
                            )}
                            {st?.error && <div className="text-[11px] text-red-400">{st.error}</div>}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

