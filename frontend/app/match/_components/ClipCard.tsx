import { CheckCircle2, Play, X } from 'lucide-react'
import { useState } from 'react'
import type { MatchClip } from '@/lib/api'
import { clipStreamUrl, fmt } from './types'

// ── ScoreBar ──────────────────────────────────────────────────────────────────
export function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, (score / 10) * 100))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full bg-slate-800 overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-[10px] tabular-nums text-slate-500 w-6 text-right">{score.toFixed(1)}</span>
    </div>
  )
}

// ── ClipCard ──────────────────────────────────────────────────────────────────
export function ClipCard({
  clip, chosen, order, onChoose, onPreview,
}: {
  clip: MatchClip
  chosen: boolean
  order?: number
  onChoose: () => void
  onPreview: () => void
}) {
  const [thumbErr, setThumbErr] = useState(false)
  const name = clip.clip_path.split(/[/\\]/).pop() ?? clip.clip_path

  return (
    <div
      onClick={onChoose}
      className={`relative flex-shrink-0 w-52 rounded-xl border cursor-pointer select-none transition-all ${
        chosen
          ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/40'
          : 'border-slate-700 bg-slate-900/50 hover:border-slate-500'
      }`}
    >
      {typeof order === 'number' && order > 0 && (
        <div className="absolute top-2 right-2 min-w-5 h-5 px-1 rounded-full bg-indigo-500 flex items-center justify-center z-10">
          <span className="text-[10px] text-white font-semibold tabular-nums">{order}</span>
        </div>
      )}
      {chosen && typeof order !== 'number' && (
        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-indigo-500 flex items-center justify-center z-10">
          <CheckCircle2 className="w-3.5 h-3.5 text-white" />
        </div>
      )}
      <div className="w-full h-24 rounded-t-xl bg-slate-800 relative overflow-hidden flex items-center justify-center">
        {clip.thumbnail_url && !thumbErr ? (
          <img
            src={clip.thumbnail_url}
            alt={name}
            className="absolute inset-0 w-full h-full object-cover"
            loading="lazy"
            onError={() => setThumbErr(true)}
          />
        ) : null}
        <div className="absolute inset-0 bg-black/35" />
        <button
          onClick={(e) => { e.stopPropagation(); onPreview() }}
          className="relative z-10 w-9 h-9 rounded-full bg-black/50 hover:bg-black/70 flex items-center justify-center transition-colors"
        >
          <Play className="w-4 h-4 text-white ml-0.5" />
        </button>
      </div>
      <div className="px-3 py-2.5 space-y-1.5">
        <p className="text-xs text-slate-200 font-medium truncate">{name}</p>
        <p className="text-[10px] text-slate-500">{fmt(clip.start_time)} – {fmt(clip.end_time)} · {clip.duration.toFixed(1)}s</p>
        <ScoreBar score={clip.score} />
        {clip.reason && (
          <p className="text-[10px] text-slate-400 leading-snug line-clamp-2 italic">{clip.reason}</p>
        )}
      </div>
    </div>
  )
}

// ── PreviewModal ──────────────────────────────────────────────────────────────
export function PreviewModal({ clip, onClose }: { clip: MatchClip; onClose: () => void }) {
  const [err, setErr] = useState(false)
  const name = clip.clip_path.split(/[/\\]/).pop() ?? clip.clip_path
  const src = clip.preview_url || clipStreamUrl(clip.clip_id)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="relative w-full max-w-3xl mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <p className="text-slate-100 font-medium truncate max-w-[80%]">
            {name}
            <span className="ml-2 text-xs text-slate-400 font-normal">{fmt(clip.start_time)} – {fmt(clip.end_time)}</span>
          </p>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="rounded-xl overflow-hidden bg-black ring-1 ring-slate-700 min-h-[120px] flex items-center justify-center">
          {err ? (
            <p className="text-slate-400 text-sm px-8 py-10">该片段格式浏览器不支持直接预览。</p>
          ) : (
            <video
              key={clip.clip_id}
              src={src}
              controls autoPlay
              className="w-full max-h-[65vh] object-contain"
              onError={() => setErr(true)}
            >
              <track kind="captions" srcLang="zh" label="中文字幕" />
            </video>
          )}
        </div>
      </div>
    </div>
  )
}
