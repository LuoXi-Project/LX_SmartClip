'use client'

import { useEffect, useMemo, useRef, type ComponentPropsWithRef, type RefObject } from 'react'
import { Copy, Eye, FileCode, FileDown, Loader2 } from 'lucide-react'
import { SummaryNotePreview } from '@/components/summary/summary-note-preview'
import { API_BASE_URL } from '@/lib/runtime-config'

type NoteContentPanelProps = {
  notePanelRef: ComponentPropsWithRef<'div'>['ref']
  markdownRef: ComponentPropsWithRef<'textarea'>['ref']
  noteView: 'preview' | 'edit'
  onNoteViewChange: (v: 'preview' | 'edit') => void
  markdown: string
  onMarkdownChange: (v: string) => void
  videoId: string
  loading: boolean
  streamStatus: string
  stageProgress: { idx: number; total: number } | null
  onCopy: () => void
  onExport: () => void
}

export function NoteContentPanel({
  notePanelRef,
  markdownRef,
  noteView,
  onNoteViewChange,
  markdown,
  onMarkdownChange,
  videoId,
  loading,
  streamStatus,
  stageProgress,
  onCopy,
  onExport,
}: NoteContentPanelProps) {
  const previewScrollRef = useRef<HTMLDivElement>(null)
  const summaryVideoRef = useRef<HTMLVideoElement>(null)

  const streamUrl = useMemo(() => {
    if (!videoId) return ''
    const base = (API_BASE_URL || '').replace(/\/$/, '')
    return `${base}/api/videos/${videoId}/stream`
  }, [videoId])

  useEffect(() => {
    if (!loading) return
    const wrap = previewScrollRef.current
    if (wrap) wrap.scrollTop = wrap.scrollHeight
    const ta = (markdownRef as RefObject<HTMLTextAreaElement | null> | undefined)?.current
    if (ta) ta.scrollTop = ta.scrollHeight
  }, [loading, markdown, markdownRef])

  return (
    <div
      ref={notePanelRef}
      className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4 flex flex-col min-h-[560px] lg:flex-1 lg:min-h-0"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-200">笔记内容</div>
        <div className="flex flex-wrap items-center gap-1.5">
          <div className="inline-flex rounded-lg border border-slate-700 p-0.5 bg-slate-950/80 mr-1">
            <button
              type="button"
              onClick={() => onNoteViewChange('preview')}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs ${
                noteView === 'preview' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Eye className="w-3.5 h-3.5" />
              预览
            </button>
            <button
              type="button"
              onClick={() => onNoteViewChange('edit')}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs ${
                noteView === 'edit' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileCode className="w-3.5 h-3.5" />
              Markdown
            </button>
          </div>
          <button
            type="button"
            onClick={onCopy}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-200 hover:border-slate-500"
          >
            <Copy className="w-3.5 h-3.5" />
            复制
          </button>
          <button
            type="button"
            onClick={onExport}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-slate-700 text-xs text-slate-200 hover:border-slate-500"
          >
            <FileDown className="w-3.5 h-3.5" />
            导出 MD
          </button>
        </div>
      </div>
      {loading ? (
        <div className="mt-2 rounded-lg border border-cyan-500/25 bg-cyan-950/30 px-3 py-2.5">
          <div className="flex items-center gap-2 text-sm text-cyan-100">
            <Loader2 className="w-4 h-4 shrink-0 animate-spin text-cyan-400" />
            <span>{streamStatus || '生成中…'}</span>
          </div>
          {stageProgress && stageProgress.total > 0 ? (
            <div className="mt-2">
              <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                <span>分段分析进度</span>
                <span>
                  {stageProgress.idx}/{stageProgress.total}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full bg-cyan-500 transition-all duration-500"
                  style={{
                    width: `${Math.min(100, (stageProgress.idx / stageProgress.total) * 100)}%`,
                  }}
                />
              </div>
            </div>
          ) : null}
          <p className="text-[11px] text-slate-500 mt-1.5 leading-relaxed">
            {markdown.trim()
              ? '下方预览会随分段完成或笔记流式输出实时更新。'
              : '正在准备素材与分段，完成后将在此展示分析摘要。'}
          </p>
        </div>
      ) : (
        <p className="text-xs text-slate-500 mt-1">
          预览中时间点链接可跳转上方视频；截图占位在正文中以引用块展示。
        </p>
      )}

      <div className="mt-3 shrink-0">
        {streamUrl ? (
          <video
            ref={summaryVideoRef}
            src={streamUrl}
            controls
            className="w-full max-h-[min(280px,40vh)] rounded-lg border border-slate-800 bg-black object-contain"
            preload="metadata"
          />
        ) : (
          <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/50 p-6 text-center text-sm text-slate-500">
            选择素材视频后，此处可预览画面；笔记里带时间点的链接可点击跳转。
          </div>
        )}
      </div>

      <div className="mt-3 flex-1 min-h-0 flex flex-col">
        {loading ? (
          <div className="flex flex-col gap-3 flex-1 min-h-0">
            <div className="text-[11px] uppercase tracking-wide text-slate-500 shrink-0">预览</div>
            <div
              ref={previewScrollRef}
              className="flex-1 min-h-[160px] max-h-[min(36vh,380px)] overflow-auto styled-scrollbar rounded-lg border border-slate-800/80 bg-slate-950/40 px-3 py-3"
            >
              <SummaryNotePreview
                markdown={markdown}
                videoId={videoId || null}
                scrollContainerRef={previewScrollRef}
                externalVideoRef={summaryVideoRef}
              />
            </div>
            <div className="text-[11px] uppercase tracking-wide text-slate-500 shrink-0">Markdown 源码</div>
            <textarea
              ref={markdownRef}
              readOnly
              value={markdown}
              className="flex-1 min-h-[160px] max-h-[min(36vh,380px)] w-full rounded-lg bg-slate-950 border border-slate-800 px-3 py-2 text-sm text-slate-200 font-mono"
              placeholder="流式输出中…"
              aria-label="流式 Markdown 源码"
            />
          </div>
        ) : noteView === 'preview' ? (
          <div
            ref={previewScrollRef}
            className="flex-1 overflow-auto styled-scrollbar rounded-lg border border-slate-800/80 bg-slate-950/40 px-3 py-3 max-h-[min(70vh,720px)]"
          >
            <SummaryNotePreview
              markdown={markdown}
              videoId={videoId || null}
              scrollContainerRef={previewScrollRef}
              externalVideoRef={summaryVideoRef}
            />
          </div>
        ) : (
          <textarea
            ref={markdownRef}
            value={markdown}
            onChange={(e) => onMarkdownChange(e.target.value)}
            className="flex-1 w-full min-h-[420px] rounded-lg bg-slate-950 border border-slate-800 px-3 py-2 text-sm text-slate-200 font-mono"
            placeholder="生成的 Markdown 源码；保存前可在此编辑。"
          />
        )}
      </div>
    </div>
  )
}
