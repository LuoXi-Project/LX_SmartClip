'use client'

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Check, Pause, Play, Search } from 'lucide-react'
import type { BgmTrack } from '@/lib/api'
import {
  BGM_MOOD_LABELS,
  filterBgmTracks,
  findBgmTrackByValue,
  formatBgmTrackSubtitle,
  getBgmTrackValue,
  type BgmTrackValueField,
} from '@/lib/bgmUtils'
import { VoiceInputControl } from '@/components/ui/voice-input'

const MOOD_FILTER_KEYS = [
  '',
  'happy',
  'calm',
  'epic',
  'tech',
  'suspense',
  'action',
  'romantic',
] as const

function formatAudioTime(sec: number) {
  if (!Number.isFinite(sec) || sec < 0) return '00:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export type BgmTrackPickerProps = {
  tracks: BgmTrack[]
  value: string
  onChange: (value: string) => void
  trackValueField?: BgmTrackValueField
  disabled?: boolean
  allowAuto?: boolean
  autoOptionLabel?: string
  listError?: string
  emptyHint?: ReactNode
  className?: string
}

export function BgmTrackPicker({
  tracks,
  value,
  onChange,
  trackValueField = 'filename',
  disabled = false,
  allowAuto = true,
  autoOptionLabel = '自动（方案推荐 / 曲库匹配）',
  listError,
  emptyHint,
  className = '',
}: BgmTrackPickerProps) {
  const [keyword, setKeyword] = useState('')
  const [moodFilter, setMoodFilter] = useState('')
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewTime, setPreviewTime] = useState(0)
  const [previewDuration, setPreviewDuration] = useState(0)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const selected = useMemo(
    () => findBgmTrackByValue(tracks, value, trackValueField),
    [tracks, value, trackValueField]
  )

  const filtered = useMemo(
    () => filterBgmTracks(tracks, { query: keyword, mood: moodFilter }),
    [tracks, keyword, moodFilter]
  )

  const listTracks = useMemo(() => {
    if (!selected || filtered.some((t) => t.id === selected.id)) return filtered
    return [selected, ...filtered]
  }, [filtered, selected])

  useEffect(
    () => () => {
      audioRef.current?.pause()
    },
    []
  )

  const stopPreview = () => {
    audioRef.current?.pause()
    setPreviewId(null)
    setPreviewTime(0)
    setPreviewDuration(0)
  }

  const togglePreview = (track: BgmTrack) => {
    if (disabled) return
    const audio = audioRef.current
    if (!audio) return
    if (previewId === track.id) {
      stopPreview()
      return
    }
    audio.src = track.url
    setPreviewId(track.id)
    void audio.play()
  }

  const isAuto = allowAuto && !value

  return (
    <div className={`space-y-2 ${className}`}>
      {allowAuto && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            stopPreview()
            onChange('')
          }}
          className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 ${
            isAuto
              ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-100'
              : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-600'
          }`}
        >
          <span className="flex items-center gap-2">
            {isAuto ? <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" /> : null}
            {autoOptionLabel}
          </span>
        </button>
      )}

      {selected && (
        <p className="text-[11px] text-slate-400">
          已选：
          <span className="text-slate-200">{selected.title || selected.filename}</span>
          {formatBgmTrackSubtitle(selected) ? (
            <span className="text-slate-500"> · {formatBgmTrackSubtitle(selected)}</span>
          ) : null}
        </p>
      )}

      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          disabled={disabled || tracks.length === 0}
          placeholder="搜索曲目：名称 / 标签 / 情绪 / BPM"
          className="w-full rounded-lg border border-slate-700 bg-slate-900/80 py-1.5 pl-8 pr-20 text-xs text-slate-200 placeholder:text-slate-500 focus:border-emerald-500/60 focus:outline-none disabled:opacity-50"
        />
        <div className="absolute right-1 top-1/2 -translate-y-1/2">
          <VoiceInputControl
            intent="在 BGM 曲库中搜索：把口述整理成适合匹配标题/文件名/标签/情绪的关键字，不要完整句子说明。"
            value={keyword}
            onTextChange={setKeyword}
            merge="replace"
            disabled={disabled || tracks.length === 0}
            className="relative"
          />
        </div>
      </div>

      {tracks.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {MOOD_FILTER_KEYS.map((key) => {
            const active = moodFilter === key
            const label = key ? BGM_MOOD_LABELS[key] ?? key : '全部'
            return (
              <button
                key={key || 'all'}
                type="button"
                disabled={disabled}
                onClick={() => setMoodFilter(key)}
                className={`rounded-full px-2 py-0.5 text-[10px] border transition-colors disabled:opacity-50 ${
                  active
                    ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-200'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
      )}

      {listError && <p className="text-[11px] text-amber-400/90">{listError}</p>}

      {tracks.length === 0 && !listError && emptyHint}

      {tracks.length > 0 && (
        <>
          <p className="text-[10px] text-slate-500">
            {keyword.trim() || moodFilter
              ? `匹配 ${listTracks.length} / ${tracks.length} 首`
              : `共 ${tracks.length} 首，可搜索或按情绪筛选`}
          </p>
          <div className="max-h-44 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/40 divide-y divide-slate-800/80 pr-0.5">
            {listTracks.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-slate-500">无匹配曲目，试试换个关键词或选「全部」</p>
            ) : (
              listTracks.map((t) => {
                const trackValue = getBgmTrackValue(t, trackValueField)
                const picked = value === trackValue
                const isPreviewing = previewId === t.id
                const subtitle = formatBgmTrackSubtitle(t)
                return (
                  <div
                    key={t.id}
                    className={`flex items-center gap-2 px-2 py-1.5 ${
                      picked ? 'bg-emerald-500/10' : 'hover:bg-slate-900/60'
                    }`}
                  >
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => {
                        stopPreview()
                        onChange(trackValue)
                      }}
                      className="min-w-0 flex-1 text-left disabled:opacity-50"
                    >
                      <span className="block truncate text-xs text-slate-200">
                        {t.title || t.filename}
                      </span>
                      {subtitle ? (
                        <span className="block truncate text-[10px] text-slate-500">{subtitle}</span>
                      ) : null}
                    </button>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => togglePreview(t)}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-700 bg-slate-800 text-slate-200 hover:border-emerald-500/50 hover:text-emerald-300 disabled:opacity-50"
                      title="试听"
                    >
                      {isPreviewing ? (
                        <Pause className="h-3 w-3" />
                      ) : (
                        <Play className="h-3 w-3 ml-0.5" />
                      )}
                    </button>
                    {picked ? <Check className="h-3.5 w-3.5 shrink-0 text-emerald-400" /> : null}
                  </div>
                )
              })
            )}
          </div>
        </>
      )}

      <audio
        ref={audioRef}
        className="hidden"
        onLoadedMetadata={(e) => setPreviewDuration(e.currentTarget.duration || 0)}
        onTimeUpdate={(e) => setPreviewTime(e.currentTarget.currentTime || 0)}
        onEnded={stopPreview}
        onPause={() => {
          if (previewId) setPreviewTime(audioRef.current?.currentTime ?? 0)
        }}
      />
      {previewId && previewDuration > 0 && (
        <p className="text-[10px] text-slate-500 tabular-nums">
          试听 {formatAudioTime(previewTime)} / {formatAudioTime(previewDuration)}
        </p>
      )}
    </div>
  )
}
