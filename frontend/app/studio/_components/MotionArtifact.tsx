'use client'

import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { AlertTriangle, Clapperboard, ExternalLink, Loader2, Play } from 'lucide-react'
import { jobsApi, type JobSnapshot } from '@/lib/api'
import { resolveStorageUrl } from '@/lib/studio-media-url'
import type { ArtifactRef } from '@/lib/agent-types'

/**
 * 动效合成产物（HyperFrames）：
 * - 预览态：iframe 直接播放合成（HTML 即视频源码，浏览器原生可跑）
 * - 渲染态：轮询 motion_render job，完成后展示成片 + 合成预览
 */

interface MotionPayload {
  motion_kind?: 'preview' | 'render'
  title?: string
  preview_url?: string | null
  video_url?: string | null
  job_id?: string | null
  status?: string
  fps?: number
  quality?: string
}

export function isMotionArtifact(payload: Record<string, unknown> | undefined): boolean {
  return Boolean(payload && (payload.motion_kind || payload.composition_id))
}

export function MotionArtifact({ artifact }: { artifact: ArtifactRef }) {
  const payload = artifact.payload as unknown as MotionPayload
  const [job, setJob] = useState<JobSnapshot | null>(null)
  const [jobError, setJobError] = useState('')

  const jobId = payload.motion_kind === 'render' ? payload.job_id : null
  const running = Boolean(jobId) && job?.status !== 'done' && job?.status !== 'error' && job?.status !== 'cancelled'

  // 渲染 job 轮询（2.5s；终态停）
  useEffect(() => {
    if (!jobId) return
    let timer: ReturnType<typeof setTimeout> | null = null
    let disposed = false
    const poll = async () => {
      try {
        const snapshot = await jobsApi.get(jobId)
        if (disposed) return
        setJob(snapshot)
        if (snapshot.status === 'running' || snapshot.status === 'pending') {
          timer = setTimeout(poll, 2500)
        }
      } catch (e) {
        if (!disposed) setJobError((e as Error).message)
      }
    }
    void poll()
    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  // job 完成后从 result 取成片与预览
  const result = (job?.result || {}) as Record<string, unknown>
  const videoUrl = useMemo(
    () => resolveStorageUrl(payload.video_url || String(result.video_url || '') || ''),
    [payload.video_url, result.video_url],
  )
  const previewUrl = useMemo(
    () => resolveStorageUrl(payload.preview_url || String(result.preview_url || '') || ''),
    [payload.preview_url, result.preview_url],
  )
  const progressMsg =
    job?.steps?.[job.current_step || 'render']?.message || (running ? '渲染中…' : '')

  return (
    <div className="rounded-2xl border border-fuchsia-500/25 bg-fuchsia-500/[0.04] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
        <div className="flex items-center gap-1.5 min-w-0">
          <Clapperboard className="w-4 h-4 text-fuchsia-400 shrink-0" />
          <span className="text-sm font-medium text-slate-100 truncate">
            {payload.title || '动效合成'}
          </span>
          <span className="rounded border border-fuchsia-500/40 bg-fuchsia-500/10 px-1 py-px text-[10px] text-fuchsia-300 shrink-0">
            HyperFrames
          </span>
          {payload.fps ? (
            <span className="text-[10px] text-slate-500 shrink-0">
              {payload.fps}fps{payload.quality ? ` · ${payload.quality}` : ''}
            </span>
          ) : null}
        </div>
        {previewUrl && (
          <a
            href={previewUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-cyan-300 hover:text-cyan-200 shrink-0"
          >
            <ExternalLink size={11} /> 新窗口预览
          </a>
        )}
      </div>

      <div className="p-4 space-y-3">
        {/* 渲染进行中 */}
        {running && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span className="truncate">{progressMsg || '动效渲染中（Chromium 逐帧捕获）…'}</span>
          </div>
        )}
        {(job?.status === 'error' || jobError) && (
          <div className="flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-200">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span className="break-all">{job?.error_message || jobError || '渲染失败'}</span>
          </div>
        )}

        {/* 合成实时预览（iframe，浏览器直接播放 HTML 合成） */}
        {previewUrl && (
          <div className="rounded-xl overflow-hidden border border-slate-800 bg-slate-950">
            <div className="px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-800/70">
              合成实时预览（渲染前即可在浏览器播放）
            </div>
            <iframe
              src={previewUrl}
              title="动效合成预览"
              className="w-full aspect-video bg-black"
              sandbox="allow-scripts allow-same-origin"
            />
          </div>
        )}

        {/* 成片 */}
        {videoUrl && (
          <div className="rounded-xl overflow-hidden border border-slate-800 bg-slate-950">
            <div className="px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-800/70 flex items-center gap-1">
              <Play size={9} /> 成片 MP4{job?.status === 'done' ? '（渲染完成）' : ''}
            </div>
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video
              src={videoUrl}
              controls
              loop
              className="w-full aspect-video bg-black"
            />
          </div>
        )}

        {/* 预览态提示 */}
        {payload.motion_kind === 'preview' && !running && (
          <p className={clsx('text-[11px] text-slate-500')}>
            以上为合成实时预览；确认效果后可让 Agent 执行 render_composition 渲染成 MP4。
          </p>
        )}
      </div>
    </div>
  )
}
