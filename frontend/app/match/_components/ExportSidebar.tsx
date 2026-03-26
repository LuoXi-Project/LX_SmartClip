import { Loader2 } from 'lucide-react'
import type { ExportMode, Segment } from './types'

export function ExportSidebar({
  segments,
  exportMode,
  setExportMode,
  exporting,
  exportError,
  onExport,
}: {
  segments: Segment[]
  exportMode: ExportMode
  setExportMode: (m: ExportMode) => void
  exporting: boolean
  exportError: string
  onExport: () => void
}) {
  const readySegs = segments.filter((s) => s.clips.length > 0)
  const doneCount = readySegs.length
  const ttsCount = readySegs.filter((s) => s.ttsFilename).length
  const totalCount = segments.length

  return (
    <div className="fixed right-0 top-0 h-screen w-64 bg-[#0b0d12] border-l border-slate-800 flex flex-col z-40 shadow-2xl">
      {/* header */}
      <div className="px-5 pt-6 pb-4 border-b border-slate-800">
        <p className="text-xs font-semibold text-slate-300 uppercase tracking-widest">导出成片</p>
      </div>

      {/* progress summary */}
      <div className="px-5 py-4 space-y-3 border-b border-slate-800">
        <StatRow label="总段落" value={totalCount} total={totalCount} color="slate" />
        <StatRow label="已匹配" value={doneCount} total={totalCount} color="indigo" />
        <StatRow label="配音就绪" value={ttsCount} total={totalCount} color="violet" />
      </div>

      {/* mode toggle */}
      <div className="px-5 py-4 space-y-2 border-b border-slate-800">
        <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">导出格式</p>
        <button
          onClick={() => setExportMode('zip')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-sm transition-colors ${
            exportMode === 'zip'
              ? 'border-indigo-500 bg-indigo-500/10 text-indigo-200'
              : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
          }`}
        >
          <span className="text-lg leading-none">📦</span>
          <div className="text-left">
            <p className="text-xs font-medium">素材压缩包</p>
            <p className="text-[10px] text-slate-500 mt-0.5">视频切片 + 音频 ZIP</p>
          </div>
        </button>
        <button
          onClick={() => setExportMode('merged')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-sm transition-colors ${
            exportMode === 'merged'
              ? 'border-violet-500 bg-violet-500/10 text-violet-200'
              : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
          }`}
        >
          <span className="text-lg leading-none">🎬</span>
          <div className="text-left">
            <p className="text-xs font-medium">完整带配音视频</p>
            <p className="text-[10px] text-slate-500 mt-0.5">ffmpeg 合成 MP4</p>
          </div>
        </button>
      </div>

      {/* spacer */}
      <div className="flex-1" />

      {/* export button pinned to bottom */}
      <div className="px-5 py-5 space-y-3">
        {exportError && (
          <p className="text-[11px] text-red-400 leading-snug">{exportError}</p>
        )}
        <button
          onClick={onExport}
          disabled={exporting || doneCount === 0}
          className={`w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all ${
            exportMode === 'zip'
              ? 'bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600'
              : 'bg-violet-600 hover:bg-violet-500 disabled:bg-slate-800 disabled:text-slate-600'
          }`}
        >
          {exporting ? (
            <><Loader2 className="w-4 h-4 animate-spin" />导出中...</>
          ) : exportMode === 'zip' ? (
            <><span>📦</span> 导出压缩包 ({doneCount} 段)</>
          ) : (
            <><span>🎬</span> 导出成片 ({doneCount} 段)</>
          )}
        </button>
        {doneCount === 0 && (
          <p className="text-[10px] text-slate-600 text-center">请先匹配并选择片段</p>
        )}
      </div>
    </div>
  )
}

function StatRow({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total === 0 ? 0 : (value / total) * 100
  const barColor =
    color === 'indigo' ? 'bg-indigo-500' :
    color === 'violet' ? 'bg-violet-500' :
    'bg-slate-600'
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-500">{label}</span>
        <span className="text-[11px] text-slate-300 tabular-nums">{value}/{total}</span>
      </div>
      <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
