'use client'

import { Upload, Loader2 } from 'lucide-react'

interface UploadZoneProps {
  uploading: boolean
  dragActive: boolean
  onDrag: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent) => void
  onFileSelect: (files: FileList) => void
}

export function UploadZone({
  uploading,
  dragActive,
  onDrag,
  onDrop,
  onFileSelect,
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

      <div className="relative flex flex-col items-center">
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
      </div>
    </div>
  )
}
