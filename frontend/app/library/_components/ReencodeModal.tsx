'use client'

import { X } from 'lucide-react'

export type ReencodeOptions = {
  vcodec: 'libx264' | 'libx265'
  crf: number
  preset: 'ultrafast' | 'superfast' | 'veryfast' | 'faster' | 'fast' | 'medium' | 'slow'
  fps: '' | '24' | '30' | '60'
  maxHeight: '' | '480' | '720' | '1080'
  audioBitrateK: number
}

export type ReencodePreset = 'preview_compatible' | 'balanced' | 'small_size' | 'custom'

interface ReencodeModalProps {
  open: boolean
  videoName: string
  preset: ReencodePreset
  options: ReencodeOptions
  loading: boolean
  onClose: () => void
  onPresetChange: (preset: ReencodePreset) => void
  onOptionsChange: (next: ReencodeOptions) => void
  onSubmit: () => void
}

export function ReencodeModal({
  open,
  videoName,
  preset,
  options,
  loading,
  onClose,
  onPresetChange,
  onOptionsChange,
  onSubmit,
}: ReencodeModalProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-100">素材重编码</h3>
            <p className="text-xs text-slate-400 mt-1 line-clamp-1">{videoName}</p>
          </div>
          <button onClick={onClose} disabled={loading} className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <select
            value={preset}
            onChange={(e) => onPresetChange(e.target.value as ReencodePreset)}
            className="h-10 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100"
          >
            <option value="preview_compatible">预设：预览兼容优先</option>
            <option value="balanced">预设：均衡推荐</option>
            <option value="small_size">预设：体积优先</option>
            <option value="custom">预设：自定义</option>
          </select>
          <select
            value={options.vcodec}
            onChange={(e) => onOptionsChange({ ...options, vcodec: e.target.value as ReencodeOptions['vcodec'] })}
            className="h-10 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100"
          >
            <option value="libx264">视频编码：H.264 (兼容优先)</option>
            <option value="libx265">视频编码：H.265 (体积优先)</option>
          </select>
          <select
            value={options.preset}
            onChange={(e) => onOptionsChange({ ...options, preset: e.target.value as ReencodeOptions['preset'] })}
            className="h-10 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100"
          >
            <option value="veryfast">预设：veryfast</option>
            <option value="faster">预设：faster</option>
            <option value="fast">预设：fast</option>
            <option value="medium">预设：medium</option>
            <option value="slow">预设：slow</option>
          </select>

          <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100">
            CRF
            <input
              type="number"
              min={18}
              max={35}
              value={options.crf}
              onChange={(e) => onOptionsChange({ ...options, crf: Number(e.target.value || 23) })}
              className="h-8 w-full bg-transparent outline-none"
            />
          </label>

          <select
            value={options.maxHeight}
            onChange={(e) => onOptionsChange({ ...options, maxHeight: e.target.value as ReencodeOptions['maxHeight'] })}
            className="h-10 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100"
          >
            <option value="">分辨率：保持原始</option>
            <option value="1080">分辨率：1080p</option>
            <option value="720">分辨率：720p</option>
            <option value="480">分辨率：480p</option>
          </select>

          <select
            value={options.fps}
            onChange={(e) => onOptionsChange({ ...options, fps: e.target.value as ReencodeOptions['fps'] })}
            className="h-10 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100"
          >
            <option value="">FPS：保持原始</option>
            <option value="60">FPS：60</option>
            <option value="30">FPS：30</option>
            <option value="24">FPS：24</option>
          </select>

          <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 text-sm text-slate-100">
            音频 kbps
            <input
              type="number"
              min={64}
              max={320}
              value={options.audioBitrateK}
              onChange={(e) => onOptionsChange({ ...options, audioBitrateK: Number(e.target.value || 128) })}
              className="h-8 w-full bg-transparent outline-none"
            />
          </label>
        </div>

        <p className="mt-3 text-xs text-slate-400">默认会转为浏览器更易预览的 MP4(H.264/H.265 + AAC + faststart)。</p>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="h-9 rounded-lg border border-slate-700 px-4 text-sm text-slate-300 hover:bg-slate-800"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={loading}
            className="h-9 rounded-lg bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
          >
            {loading ? '重编码中...' : '开始重编码'}
          </button>
        </div>
      </div>
    </div>
  )
}
