'use client'

import { Upload, Loader2 } from 'lucide-react'

interface UploadZoneProps {
  uploading: boolean
  importingUrl: boolean
  importUrl: string
  importTitle: string
  dragActive: boolean
  onDrag: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent) => void
  onFileSelect: (files: FileList) => void
  onImportUrlChange: (value: string) => void
  onImportTitleChange: (value: string) => void
  onImportByUrl: () => void
}

export function UploadZone({
  uploading,
  importingUrl,
  importUrl,
  importTitle,
  dragActive,
  onDrag,
  onDrop,
  onFileSelect,
  onImportUrlChange,
  onImportTitleChange,
  onImportByUrl,
}: UploadZoneProps) {
  return (
    <div
      onDragEnter={onDrag}
      onDragLeave={onDrag}
      onDragOver={onDrag}
      onDrop={onDrop}
      className={`relative mb-8 border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 ${
        dragActive
          ? 'border-cyan-400 bg-cyan-500/10 scale-[1.01]'
          : 'border-slate-600/60 bg-slate-800/20 hover:border-slate-500 hover:bg-slate-800/40'
      }`}
    >
      {/* background grid decoration */}
      <div className="absolute inset-0 rounded-xl overflow-hidden pointer-events-none opacity-20">
        <div
          className="w-full h-full"
          style={{
            backgroundImage:
              'linear-gradient(rgba(148,163,184,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.08) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
      </div>

      <div className="relative flex flex-col items-center w-full max-w-2xl mx-auto">
        <div
          className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-4 transition-colors ${
            dragActive ? 'bg-cyan-500/20' : 'bg-slate-700/60'
          }`}
        >
          {uploading ? (
            <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
          ) : (
            <Upload
              className={`w-8 h-8 transition-colors ${
                dragActive ? 'text-cyan-400' : 'text-slate-400'
              }`}
            />
          )}
        </div>

        <h2 className="text-lg font-semibold text-slate-100 mb-1">
          {dragActive ? '松开以上传' : '拖拽视频文件到此处'}
        </h2>
        <p className="text-slate-500 text-sm mb-5">
          支持 MP4格式(MOV、AVI、MKV 等视频格式待测试)
        </p>

        <label className="inline-block cursor-pointer">
          <input
            type="file"
            multiple
            accept="video/*"
            onChange={(e) => e.target.files && onFileSelect(e.target.files)}
            disabled={uploading}
            className="hidden"
          />
          <span
            className={`inline-flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
              uploading
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-cyan-600 text-white hover:bg-cyan-500 active:scale-95 shadow-lg shadow-cyan-900/30'
            }`}
          >
            {uploading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                上传中...
              </>
            ) : (
              '选择文件'
            )}
          </span>
        </label>

        <div className="w-full mt-6 border-t border-slate-700/60 pt-5">
          <p className="text-xs text-slate-500 mb-3">或使用链接下载导入（yt-dlp）</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input
              value={importUrl}
              onChange={(e) => onImportUrlChange(e.target.value)}
              placeholder="输入视频链接（YouTube/B 站等）"
              disabled={importingUrl}
              className="md:col-span-2 h-10 rounded-lg bg-slate-900/80 border border-slate-700 px-3 text-sm text-slate-100 placeholder:text-slate-500 outline-none focus:ring-2 focus:ring-cyan-500/50"
            />
            <input
              value={importTitle}
              onChange={(e) => onImportTitleChange(e.target.value)}
              placeholder="可选：素材名"
              disabled={importingUrl}
              className="h-10 rounded-lg bg-slate-900/80 border border-slate-700 px-3 text-sm text-slate-100 placeholder:text-slate-500 outline-none focus:ring-2 focus:ring-cyan-500/50"
            />
          </div>
          <button
            type="button"
            onClick={onImportByUrl}
            disabled={importingUrl || !importUrl.trim()}
            className={`mt-3 h-10 px-4 rounded-lg text-sm font-medium transition-all ${
              importingUrl || !importUrl.trim()
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-indigo-600 text-white hover:bg-indigo-500 active:scale-95'
            }`}
          >
            {importingUrl ? '下载导入中...' : '下载导入'}
          </button>
        </div>
      </div>
    </div>
  )
}
