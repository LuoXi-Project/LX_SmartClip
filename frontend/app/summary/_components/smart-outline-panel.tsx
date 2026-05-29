'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, Loader2 } from 'lucide-react'
import {
  summaryApi,
  type SmartOutlineBundle,
  type SmartOutlineClipScore,
  type SmartOutlineResponse,
  type Video,
} from '@/lib/api'
import { clipStreamUrl, fmt, videoStreamUrl } from '@/app/match/_components/types'
import { useToast } from '@/components/ui/toast-provider'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ScrollArea } from '@/components/ui/scroll-area'

type PlayMode = 'video' | 'clip'

/** 解析大纲中的 m:ss 或 m:ss.xxx（与 fmt 输出一致） */
function parseOutlineTimeToSec(raw: string): number | null {
  const m = /^(\d+):(\d{2})(?:\.(\d{1,3}))?$/.exec(raw.trim())
  if (!m) return null
  const min = Number(m[1])
  const sec = Number(m[2])
  let frac = 0
  if (m[3]) {
    const ms = m[3].padEnd(3, '0').slice(0, 3)
    frac = Number(ms) / 1000
  }
  const t = min * 60 + sec + frac
  return Number.isFinite(t) ? t : null
}

interface OutlineRangeMatch {
  start: number
  end: number
  raw: string
  a: string
  b: string
  kind: 'bracket' | 'plain'
}

function findBracketTimeRanges(text: string): OutlineRangeMatch[] {
  const re = /\[\s*(\d+:\d{2}(?:\.\d+)?)\s*[–\-~～—]\s*(\d+:\d{2}(?:\.\d+)?)\s*\]/g
  const out: OutlineRangeMatch[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    out.push({
      start: m.index,
      end: m.index + m[0].length,
      raw: m[0],
      a: m[1],
      b: m[2],
      kind: 'bracket',
    })
  }
  return out
}

function overlapsBlock(start: number, end: number, blocks: OutlineRangeMatch[]) {
  return blocks.some((b) => !(end <= b.start || start >= b.end))
}

function findPlainTimeRanges(text: string, brackets: OutlineRangeMatch[]): OutlineRangeMatch[] {
  const re = /(\d+:\d{2}(?:\.\d+)?)\s*[~～–\-—]\s*(\d+:\d{2}(?:\.\d+)?)/g
  const out: OutlineRangeMatch[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    const start = m.index
    const end = m.index + m[0].length
    if (overlapsBlock(start, end, brackets)) continue
    out.push({ start, end, raw: m[0], a: m[1], b: m[2], kind: 'plain' })
  }
  return out
}

function OutlineMarkdownWithSeek({
  markdown,
  onSeek,
}: {
  markdown: string
  onSeek: (sec: number) => void
}) {
  const parts = useMemo(() => {
    const brackets = findBracketTimeRanges(markdown)
    const plains = findPlainTimeRanges(markdown, brackets)
    const ranges = [...brackets, ...plains].sort((x, y) => x.start - y.start || x.end - y.end)
    type Part = { kind: 'text'; text: string } | { kind: 'range'; r: OutlineRangeMatch }
    const merged: Part[] = []
    let cursor = 0
    for (const r of ranges) {
      if (r.start < cursor) continue
      if (r.start > cursor) merged.push({ kind: 'text', text: markdown.slice(cursor, r.start) })
      merged.push({ kind: 'range', r })
      cursor = r.end
    }
    if (cursor < markdown.length) merged.push({ kind: 'text', text: markdown.slice(cursor) })
    return merged
  }, [markdown])

  return (
    <ScrollArea className="whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950/70 p-2.5 text-[11px] text-slate-200 leading-relaxed max-h-[min(42vh,360px)]">
      {parts.map((p, i) => {
        if (p.kind === 'text') {
          return (
            <span key={i} className="text-slate-200">
              {p.text}
            </span>
          )
        }
        const sa = parseOutlineTimeToSec(p.r.a)
        const sb = parseOutlineTimeToSec(p.r.b)
        const showBrackets = p.r.kind === 'bracket'
        return (
          <span
            key={i}
            className="inline-flex flex-wrap items-baseline gap-0.5 align-baseline rounded-md border border-violet-900/45 bg-violet-950/35 px-1 py-0.5 mx-0.5"
            title="点击时间跳转原片对应位置"
          >
            {showBrackets && <span className="text-slate-500 select-none">[</span>}
            {sa != null ? (
              <button
                type="button"
                onClick={() => onSeek(sa)}
                className="text-violet-300 hover:text-violet-200 hover:underline font-medium tabular-nums"
              >
                {p.r.a}
              </button>
            ) : (
              <span>{p.r.a}</span>
            )}
            <span className="text-slate-500 select-none">–</span>
            {sb != null ? (
              <button
                type="button"
                onClick={() => onSeek(sb)}
                className="text-violet-300 hover:text-violet-200 hover:underline font-medium tabular-nums"
              >
                {p.r.b}
              </button>
            ) : (
              <span>{p.r.b}</span>
            )}
            {showBrackets && <span className="text-slate-500 select-none">]</span>}
          </span>
        )
      })}
    </ScrollArea>
  )
}

interface SmartOutlinePanelProps {
  videoId: string
  selectedVideo: Video | null
  onOutlineChange?: (hasOutline: boolean) => void
}

export function SmartOutlinePanel({ videoId, selectedVideo, onOutlineChange }: SmartOutlinePanelProps) {
  const toast = useToast()
  const [bundle, setBundle] = useState<SmartOutlineBundle | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [maxClips, setMaxClips] = useState(120)
  const [playMode, setPlayMode] = useState<PlayMode>('video')
  const [pickClip, setPickClip] = useState<SmartOutlineClipScore | null>(null)
  const [playerDur, setPlayerDur] = useState(0)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const outline = bundle?.outline ?? null

  useEffect(() => {
    onOutlineChange?.(!!outline)
  }, [outline, onOutlineChange])

  const load = useCallback(async () => {
    if (!videoId) {
      setBundle(null)
      return
    }
    setLoading(true)
    try {
      const b = await summaryApi.smartOutlineGet(videoId)
      setBundle(b)
    } catch {
      setBundle(null)
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setPickClip(null)
    setPlayMode('video')
    setPlayerDur(0)
  }, [videoId])

  const seekFullVideo = useCallback((sec: number) => {
    setPlayMode('video')
    setPickClip(null)
    window.setTimeout(() => {
      const el = videoRef.current
      if (!el) return
      try {
        el.currentTime = Math.max(0, sec || 0)
        void el.play().catch(() => {})
      } catch {
        // ignore
      }
    }, 100)
  }, [])

  const playerSrc = useMemo(() => {
    if (!videoId) return ''
    if (playMode === 'clip' && pickClip) return clipStreamUrl(pickClip.clip_id)
    return videoStreamUrl(videoId)
  }, [videoId, playMode, pickClip])

  const timelineDur = useMemo(() => {
    if (playerDur > 0) return playerDur
    const d = selectedVideo?.duration
    if (typeof d === 'number' && Number.isFinite(d) && d > 0) return d
    const ends = outline?.clip_scores.map((c) => c.end_time) ?? []
    const m = Math.max(0, ...ends)
    return m > 0 ? m : 0
  }, [playerDur, selectedVideo?.duration, outline?.clip_scores])

  const runGenerate = async () => {
    if (!videoId) {
      toast.error('请先选择视频')
      return
    }
    setGenerating(true)
    try {
      const res = await summaryApi.smartOutlineGenerate(videoId, { max_clips: maxClips })
      const { updated_at, ...outline } = res as SmartOutlineResponse & { updated_at: string }
      setBundle({ outline, updated_at })
      toast.success('已生成并保存智能大纲')
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '生成失败'
      toast.error(String(msg))
    } finally {
      setGenerating(false)
      setConfirmOpen(false)
    }
  }

  const onClickGenerate = () => {
    if (bundle?.outline) {
      setConfirmOpen(true)
      return
    }
    void runGenerate()
  }

  return (
    <div className="flex flex-col min-h-[420px] rounded-2xl border border-violet-900/40 bg-[#12141c]/90 overflow-hidden">
      <div className="px-4 py-3 border-b border-violet-900/35 flex flex-wrap items-center gap-2 justify-between shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <BookOpen className="w-4 h-4 text-violet-400 shrink-0" />
          <div className="min-w-0">
            <div className="text-sm font-medium text-slate-100">智能视频大纲</div>
            <div className="text-[11px] text-slate-500 truncate">
              ASR 为主、可选 VLM；结果自动保存，与左侧「生成笔记」互不干扰。
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[11px] text-slate-500 flex items-center gap-1">
            片段上限
            <input
              type="number"
              min={1}
              max={200}
              value={maxClips}
              onChange={(e) => setMaxClips(Math.min(200, Math.max(1, Number(e.target.value) || 120)))}
              className="w-16 rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[11px] text-slate-200"
            />
          </label>
          <button
            type="button"
            disabled={!videoId || generating}
            onClick={onClickGenerate}
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-500 disabled:opacity-40"
          >
            {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BookOpen className="w-3.5 h-3.5" />}
            {bundle?.outline ? '重新生成' : '生成大纲'}
          </button>
        </div>
      </div>

      {bundle?.updated_at && (
        <div className="px-4 py-1.5 text-[10px] text-slate-500 border-b border-slate-800/80 shrink-0">
          已保存 · 更新时间 {bundle.updated_at}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)] gap-0 lg:divide-x lg:divide-violet-900/25 flex-1 min-h-0">
        <ScrollArea className="p-3 min-h-[200px] min-w-0 lg:max-h-[min(88vh,920px)]">
          {loading ? (
            <div className="flex items-center justify-center gap-2 text-sm text-slate-400 py-16">
              <Loader2 className="w-4 h-4 animate-spin" />
              加载中…
            </div>
          ) : !outline ? (
            <div className="flex flex-col items-center justify-center text-center text-sm text-slate-500 gap-2 py-16 px-4">
              <BookOpen className="w-10 h-10 text-violet-900/70" />
              <p>当前视频尚无已保存的大纲。配置好 LLM 后点击「生成大纲」。</p>
            </div>
          ) : (
            <div className="space-y-3 text-[10px] text-slate-300">
              <div className="flex flex-wrap justify-between gap-1.5 text-slate-500">
                <span className="text-slate-200 font-medium truncate text-[11px]">{outline.video_title}</span>
                <span className="shrink-0 text-[9px] leading-tight text-right max-w-[min(100%,11rem)]">
                  上下文 {outline.meta.context_clip_count} 片 · ASR {outline.meta.clips_with_asr} · VLM{' '}
                  {outline.meta.clips_with_vlm}
                </span>
              </div>
              <p className="text-[9px] text-slate-500 leading-snug">{outline.meta.note}</p>

              {outline.topics.length > 0 && (
                <div>
                  <div className="text-[9px] uppercase tracking-wide text-violet-400/90 mb-1">话题时间点</div>
                  <div className="flex flex-wrap gap-1.5">
                    {outline.topics.map((t, i) => (
                      <button
                        key={`${t.title}-${i}`}
                        type="button"
                        onClick={() => seekFullVideo(t.start_sec)}
                        className="text-left px-1.5 py-1 rounded-lg border border-violet-800/40 bg-slate-950/50 hover:border-violet-500/50"
                      >
                        <div className="text-slate-100 truncate max-w-[10rem] text-[10px]">{t.title}</div>
                        <div className="text-[10px] text-slate-500">
                          {fmt(t.start_sec)} ~ {fmt(t.end_sec)}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <div className="text-[9px] uppercase tracking-wide text-violet-400/90 mb-1">视频大纲</div>
                <OutlineMarkdownWithSeek markdown={outline.outline_markdown} onSeek={seekFullVideo} />
              </div>

              {outline.clip_scores.length > 0 && (
                <div>
                  <div className="text-[9px] uppercase tracking-wide text-violet-400/90 mb-1">片段精彩度</div>
                  <ScrollArea className="max-h-48 rounded-xl border border-slate-800 divide-y divide-slate-800">
                    {[...outline.clip_scores]
                      .sort((a, b) => b.excitement - a.excitement)
                      .map((row) => (
                        <div key={row.clip_id} className="flex items-start gap-2 px-2 py-1.5 hover:bg-slate-900/40">
                          <div className="min-w-0 flex-1">
                            <div className="text-slate-200">
                              {fmt(row.start_time)} ~ {fmt(row.end_time)}
                            </div>
                            {row.reason && (
                              <div className="text-[10px] text-slate-500 line-clamp-2">{row.reason}</div>
                            )}
                          </div>
                          <div className="shrink-0 flex flex-col items-end gap-1">
                            <span className="text-violet-300 font-semibold">{row.excitement.toFixed(2)}</span>
                            <div className="flex gap-1">
                              <button
                                type="button"
                                className="px-1.5 py-0.5 rounded border border-slate-600 text-[10px] text-slate-300 hover:border-slate-400"
                                onClick={() => seekFullVideo(row.start_time)}
                              >
                                跳转
                              </button>
                              <button
                                type="button"
                                className="px-1.5 py-0.5 rounded border border-slate-600 text-[10px] text-slate-300 hover:border-slate-400"
                                onClick={() => {
                                  setPlayMode('clip')
                                  setPickClip(row)
                                }}
                              >
                                切片
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                  </ScrollArea>
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className="p-3 lg:p-4 bg-slate-950/25 flex flex-col min-h-[260px] lg:min-h-0 lg:h-full min-w-0">
          <div className="flex items-center justify-between gap-2 mb-2 shrink-0">
            <span className="text-[11px] text-slate-500">预览</span>
            <div className="inline-flex rounded-lg border border-slate-700 p-0.5">
              <button
                type="button"
                onClick={() => {
                  setPlayMode('video')
                  setPickClip(null)
                }}
                className={`px-2 py-0.5 rounded text-[10px] ${
                  playMode === 'video' ? 'bg-slate-200 text-slate-900' : 'text-slate-400'
                }`}
              >
                原片
              </button>
              <button
                type="button"
                onClick={() => setPlayMode('clip')}
                className={`px-2 py-0.5 rounded text-[10px] ${
                  playMode === 'clip' ? 'bg-slate-200 text-slate-900' : 'text-slate-400'
                }`}
              >
                切片
              </button>
            </div>
          </div>
          <div className="flex-1 flex min-h-[240px] w-full min-w-0 rounded-xl overflow-hidden bg-black ring-1 ring-slate-800 lg:min-h-[min(52vh,560px)] lg:max-h-[min(78vh,920px)]">
            {videoId && playerSrc ? (
              <video
                key={playerSrc}
                ref={videoRef}
                src={playerSrc}
                onLoadedMetadata={(e) => {
                  const next = e.currentTarget.duration
                  setPlayerDur(Number.isFinite(next) && next > 0 ? next : 0)
                }}
                controls
                className="w-full h-full max-h-[min(78vh,920px)] object-contain bg-black"
              />
            ) : (
              <div className="h-full min-h-[200px] w-full flex items-center justify-center text-sm text-slate-500">
                选择视频后预览
              </div>
            )}
          </div>
          {playMode === 'video' && outline && timelineDur > 0 && (
            <div className="mt-3 space-y-1 shrink-0">
              <div className="flex justify-between text-[10px] text-slate-500">
                <span>精彩度</span>
                <span>{fmt(timelineDur)}</span>
              </div>
              <div className="relative h-2 rounded-full bg-slate-800 overflow-hidden">
                {outline.clip_scores.map((row) => {
                  const left = Math.max(0, Math.min(1, (row.start_time || 0) / timelineDur))
                  const right = Math.max(0, Math.min(1, (row.end_time || 0) / timelineDur))
                  const w = Math.max(0.003, right - left)
                  const hi = row.excitement >= 0.65
                  return (
                    <button
                      key={row.clip_id}
                      type="button"
                      title={`${fmt(row.start_time)} · ${row.excitement.toFixed(2)}`}
                      onClick={() => seekFullVideo(row.start_time)}
                      className={`absolute top-0 h-full ${hi ? 'bg-violet-400' : 'bg-slate-500/70'} opacity-90 hover:brightness-110`}
                      style={{ left: `${left * 100}%`, width: `${w * 100}%` }}
                    />
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="重新生成智能大纲？"
        description="将调用 LLM 重新分析并覆盖当前视频已保存的大纲与精彩度评分。"
        confirmLabel="覆盖生成"
        cancelLabel="取消"
        variant="default"
        onConfirm={() => void runGenerate()}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  )
}
