'use client'

import { Download, ExternalLink, Film } from 'lucide-react'
import type { ArtifactRef } from '@/lib/agent-types'
import {
  isJianyingExport,
  isVideoExport,
  resolveStudioMediaUrl,
} from '@/lib/studio-media-url'

type ExportResultPanelProps = {
  artifact: ArtifactRef
  compact?: boolean
}

export function ExportResultPanel({ artifact, compact = false }: ExportResultPanelProps) {
  const payload = artifact.payload || {}
  const downloadUrl = resolveStudioMediaUrl(String(payload.url || ''))
  const filename = String(payload.filename || artifact.id || 'download')
  const localPath = String(payload.local_path || '').trim()
  const isVideo = isVideoExport(payload)
  const isJy = isJianyingExport(payload)

  return (
    <div
      className={`rounded-xl border border-emerald-500/30 bg-emerald-500/5 space-y-3 ${
        compact ? 'p-3' : 'p-4'
      }`}
    >
      <div className="flex items-center gap-2 text-sm font-medium text-emerald-200">
        <Film className="w-4 h-4 shrink-0" />
        {isJy ? '剪映草稿已导出' : isVideo ? '成片已生成' : '导出完成'}
      </div>

      {isVideo && downloadUrl ? (
        <video
          src={downloadUrl}
          controls
          playsInline
          className={`w-full rounded-lg bg-black border border-slate-700 ${
            compact ? 'max-h-40' : 'max-h-[320px]'
          }`}
          preload="metadata"
        />
      ) : null}

      <p className="text-xs text-slate-400 break-all">{filename}</p>

      {localPath ? (
        <p className="text-xs text-emerald-400/90 break-all">本地路径：{localPath}</p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {downloadUrl ? (
          <>
            <a
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm"
            >
              <Download className="w-4 h-4" />
              {isJy ? '下载剪映 ZIP' : '下载成片'}
            </a>
            <a
              href={downloadUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-600 text-slate-200 text-sm hover:border-slate-500"
            >
              <ExternalLink className="w-4 h-4" />
              新窗口打开
            </a>
          </>
        ) : (
          <span className="text-xs text-amber-400">未拿到下载地址，请检查后端 storage 挂载</span>
        )}
      </div>
    </div>
  )
}
