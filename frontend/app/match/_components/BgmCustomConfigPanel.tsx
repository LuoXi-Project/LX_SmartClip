'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import type { BgmTrack } from '@/lib/api'

type TimelineSeg = { id: string; startSec: number; endSec: number; trackId?: string; volumeDb?: number }

function formatAudioTime(sec: number) {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function BgmCustomConfigPanel(props: {
  title: string
  enabled: boolean
  onEnabledChange: (value: boolean) => void
  enabledHint?: string
  showConfig?: boolean
  hiddenHint?: string
  bgmTracks: BgmTrack[]
  bgmListError?: string
  selectedTrackIds: string[]
  onToggleTrack: (trackId: string) => void
  volumeByTrackId: Record<string, number>
  onTrackVolumeChange: (trackId: string, volumeDb: number) => void
  timelineSegments: TimelineSeg[]
  onAddTimelineSegment: () => void
  onRemoveTimelineSegment: (id: string) => void
  onUpdateTimelineSegment: (id: string, patch: Partial<TimelineSeg>) => void
}) {
  const {
    title,
    enabled,
    onEnabledChange,
    enabledHint = '支持自选多首、按顺序循环、单曲响度、时间轴片段',
    showConfig = true,
    hiddenHint = '请先在上方选择自定义，再配置本模块。',
    bgmTracks,
    bgmListError,
    selectedTrackIds,
    onToggleTrack,
    volumeByTrackId,
    onTrackVolumeChange,
    timelineSegments,
    onAddTimelineSegment,
    onRemoveTimelineSegment,
    onUpdateTimelineSegment,
  } = props
  const [keyword, setKeyword] = useState('')
  const [previewTrackId, setPreviewTrackId] = useState<string | null>(null)
  const [previewCurrentTime, setPreviewCurrentTime] = useState(0)
  const [previewDuration, setPreviewDuration] = useState(0)
  const audioRefs = useRef<Record<string, HTMLAudioElement | null>>({})
  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase()
    if (!q) return bgmTracks
    return bgmTracks.filter((track) =>
      [track.title, track.filename, track.mood ?? '', String(track.bpm ?? ''), ...(track.tags ?? [])]
        .join(' ')
        .toLowerCase()
        .includes(q)
    )
  }, [bgmTracks, keyword])

  useEffect(() => () => {
    Object.values(audioRefs.current).forEach((a) => a?.pause())
  }, [])

  return (
    <div className="space-y-2 rounded-xl border border-slate-700/70 bg-slate-950/50 px-4 py-3">
      <label className="flex items-center gap-2 text-[11px] font-medium text-slate-200">{title}</label>
      {!showConfig ? (
        <p className="text-xs text-slate-500">{hiddenHint}</p>
      ) : (
        <>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => onEnabledChange(e.target.checked)}
              className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40"
            />
            <span className="text-xs text-slate-300">{enabledHint}</span>
          </label>
          {enabled && (
            <div className="space-y-2">
              {bgmTracks.length === 0 ? (
                <p className="text-xs text-slate-500">{bgmListError || '暂无 BGM，请先去 BGM 页面上传。'}</p>
              ) : (
                <>
                  <input
                    type="text"
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    placeholder="搜索 BGM：名称 / 文件名 / 标签 / 心情 / BPM"
                    className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                  <div className="space-y-1.5 max-h-72 overflow-auto pr-1">
                    {filtered.map((t) => {
                      const picked = selectedTrackIds.includes(t.filename)
                      const isPreviewing = previewTrackId === t.id
                      return (
                        <div key={t.id} className="rounded-lg border border-slate-800 px-2 py-1.5">
                          <div className="flex items-center gap-2 rounded-md bg-slate-900/70">
                            <input type="checkbox" checked={picked} onChange={() => onToggleTrack(t.filename)} className="rounded border-slate-600 bg-slate-900 text-emerald-500 focus:ring-emerald-500/40" />
                            <span className="text-xs text-slate-200 w-40 shrink-0 truncate">
                              {t.title || t.filename}
                              {picked ? <span className="ml-1 text-[10px] text-emerald-400/90">#{selectedTrackIds.indexOf(t.filename) + 1}</span> : null}
                            </span>
                            <input type="number" step={0.5} min={-40} max={12} value={volumeByTrackId[t.filename] ?? -14} onChange={(e) => onTrackVolumeChange(t.filename, Number(e.target.value))} className="w-16 rounded bg-slate-900 border border-slate-700 px-1.5 py-0.5 text-[11px] text-slate-200" />
                            <button type="button" onClick={() => {
                              const current = audioRefs.current[t.id]
                              if (!current) return
                              if (isPreviewing) { current.pause(); setPreviewTrackId(null); return }
                              if (previewTrackId && previewTrackId !== t.id) audioRefs.current[previewTrackId]?.pause()
                              void current.play(); setPreviewTrackId(t.id)
                            }} className="h-7 w-7 shrink-0 rounded-full border border-slate-700 bg-slate-800 text-slate-200 hover:border-indigo-500 hover:text-indigo-300 flex items-center justify-center">
                              {isPreviewing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 ml-0.5" />}
                            </button>
                            <input type="range" min={0} max={isPreviewing && previewDuration > 0 ? previewDuration : 0} step={0.01} value={isPreviewing ? Math.min(previewCurrentTime, previewDuration || 0) : 0} onChange={(e) => {
                              const audio = audioRefs.current[t.id]
                              if (!audio) return
                              const next = Number(e.target.value)
                              audio.currentTime = next
                              if (isPreviewing) setPreviewCurrentTime(next)
                            }} className="flex-1 min-w-24 accent-indigo-500" />
                            <span className="w-20 text-right text-[10px] text-slate-400 tabular-nums">{isPreviewing ? `${formatAudioTime(previewCurrentTime)} / ${formatAudioTime(previewDuration)}` : '--:-- / --:--'}</span>
                            <audio
                              ref={(el) => { audioRefs.current[t.id] = el }}
                              preload="metadata"
                              src={t.url}
                              onLoadedMetadata={(e) => { if (previewTrackId === t.id) setPreviewDuration(e.currentTarget.duration || 0) }}
                              onTimeUpdate={(e) => { if (previewTrackId === t.id) setPreviewCurrentTime(e.currentTarget.currentTime || 0) }}
                              onPlay={(e) => { if (previewTrackId && previewTrackId !== t.id) audioRefs.current[previewTrackId]?.pause(); setPreviewTrackId(t.id); setPreviewDuration(e.currentTarget.duration || 0) }}
                              onPause={() => { if (previewTrackId === t.id) setPreviewTrackId(null) }}
                              onEnded={() => { if (previewTrackId === t.id) { setPreviewTrackId(null); setPreviewCurrentTime(0) } }}
                              className="hidden"
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </>
              )}
              <div className="rounded-xl border border-slate-700/70 bg-slate-950/50 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-slate-400">时间轴片段（留空则按顺序自动循环整条时间轴）</p>
                  <button type="button" onClick={onAddTimelineSegment} className="text-xs px-2 py-1 rounded border border-slate-700 text-slate-300 hover:border-slate-500">添加片段</button>
                </div>
                {timelineSegments.length === 0 ? <p className="text-xs text-slate-500">未设置片段：导出时会自动按所选 BGM 顺序循环。</p> : (
                  <div className="space-y-1.5">
                    {timelineSegments.map((seg) => (
                      <div key={seg.id} className="grid grid-cols-12 gap-2 items-center">
                        <input type="number" step={0.1} min={0} value={seg.startSec} onChange={(e) => onUpdateTimelineSegment(seg.id, { startSec: Number(e.target.value) })} className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200" />
                        <input type="number" step={0.1} min={0.1} value={seg.endSec} onChange={(e) => onUpdateTimelineSegment(seg.id, { endSec: Number(e.target.value) })} className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200" />
                        <select value={seg.trackId ?? ''} onChange={(e) => onUpdateTimelineSegment(seg.id, { trackId: e.target.value || undefined })} className="col-span-4 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200">
                          <option value="">自动循环</option>
                          {selectedTrackIds.map((trackId) => <option key={trackId} value={trackId}>{trackId}</option>)}
                        </select>
                        <input type="number" step={0.5} min={-40} max={12} value={seg.volumeDb ?? ''} onChange={(e) => onUpdateTimelineSegment(seg.id, { volumeDb: e.target.value === '' ? undefined : Number(e.target.value) })} className="col-span-2 rounded bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-200" />
                        <button type="button" onClick={() => onRemoveTimelineSegment(seg.id)} className="col-span-2 text-xs rounded border border-slate-700 px-2 py-1 text-slate-400 hover:text-red-300 hover:border-red-400/40">删除</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
