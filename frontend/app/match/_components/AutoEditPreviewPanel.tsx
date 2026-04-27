'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { type ClipMetaByClip, type PreviewTimeline, type SelectedPreviewState } from './autoEditTypes'
import { clipStreamUrl, fmt, videoStreamUrl } from './types'

export type AutoEditPreviewPanelProps = {
  selectedPreview: SelectedPreviewState | null
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>
  clipMetaByClip: ClipMetaByClip
}

export function AutoEditPreviewPanel({ selectedPreview, setSelectedPreview, clipMetaByClip }: AutoEditPreviewPanelProps) {
  const previewVideoRef = useRef<HTMLVideoElement | null>(null)
  const [previewVideoErr, setPreviewVideoErr] = useState(false)

  /** 仅使用库中 clip→video；方案 JSON 里的 video_id 不得用于 /stream */
  const resolvedVideoId = useMemo(() => {
    if (!selectedPreview) return null
    if (selectedPreview.clipId) {
      const byClip = clipMetaByClip[selectedPreview.clipId]?.video_id
      if (byClip) return byClip
    }
    return selectedPreview.videoId ?? null
  }, [clipMetaByClip, selectedPreview])

  /** 预览/成片对齐：原视频轴用库内绝对时间；片段文件轴为 [0, end−start] */
  const previewTimeline = useMemo<PreviewTimeline | null>(() => {
    if (!selectedPreview) return null
    const meta = selectedPreview.clipId ? clipMetaByClip[selectedPreview.clipId] : undefined
    const planStart = Number(selectedPreview.startSec) || 0
    const planEnd = Number(selectedPreview.endSec) || planStart
    // 旧逻辑会优先用整段 clip 元数据作为“播放轴”，这对句子级 quick-cut 不成立；
    // 当方案标注的 start/end 明显偏离整段边界时，改用方案的句子级时间轴。
    const eps = 0.05
    const absStart = meta && Math.abs(planStart - meta.start_time) < eps ? meta.start_time : planStart
    const absEnd = meta && Math.abs(planEnd - meta.end_time) < eps ? meta.end_time : planEnd
    const clipLocalEnd = Math.max(0, absEnd - absStart)
    const clipDuration = meta ? Math.max(0, Number(meta.end_time) - Number(meta.start_time)) : null
    const windowDur = Math.max(0, planEnd - planStart)
    const overClipRange =
      clipDuration != null &&
      clipDuration > 0 &&
      (planStart < -eps || planEnd > clipDuration + eps || windowDur > clipDuration + eps)
    const windowSemantic: PreviewTimeline['windowSemantic'] = overClipRange ? 'timeline_like' : 'clip_like'
    return { meta, planStart, planEnd, absStart, absEnd, clipLocalEnd, windowSemantic }
  }, [selectedPreview, clipMetaByClip])

  const previewSrc = useMemo(() => {
    if (!selectedPreview) return ''
    if (selectedPreview.source === 'video') {
      if (!resolvedVideoId) return ''
      return videoStreamUrl(resolvedVideoId)
    }
    if (!selectedPreview.clipId) return ''
    return clipStreamUrl(selectedPreview.clipId)
  }, [resolvedVideoId, selectedPreview])

  useEffect(() => {
    const video = previewVideoRef.current
    if (!video) return
    if (!selectedPreview) return
    if (!previewTimeline) return

    setPreviewVideoErr(false)

    const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))
    const target = selectedPreview.source === 'video' ? Math.max(0, previewTimeline.absStart) : 0

    const trySeek = () => {
      try {
        const duration = Number.isFinite(video.duration) ? video.duration : NaN
        if (Number.isFinite(duration) && duration > 0) {
          video.currentTime = clamp(target, 0, Math.max(0, duration - 0.05))
        } else {
          video.currentTime = Math.max(0, target)
        }
        void video.play().catch(() => {})
      } catch {
        // ignore seek/play errors
      }
    }

    if (video.readyState >= 1) {
      trySeek()
      return
    }
    video.addEventListener('loadedmetadata', trySeek, { once: true })
    return () => video.removeEventListener('loadedmetadata', trySeek)
  }, [selectedPreview, previewSrc, previewTimeline])

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-300">片段预览播放器</p>
          {selectedPreview && previewTimeline ? (
            <p className="text-[11px] text-slate-500 mt-0.5">
              <span className="block truncate">
                {selectedPreview.planTitle} · #{selectedPreview.order} · 成片对应素材（库内时间） {fmt(previewTimeline.absStart)} –{' '}
                {fmt(previewTimeline.absEnd)}
                {!previewTimeline.meta && <span className="text-slate-600">（库内元数据加载完成后会校正）</span>}
              </span>
              {previewTimeline.meta &&
                (Math.abs(previewTimeline.planStart - previewTimeline.absStart) > 0.25 ||
                  Math.abs(previewTimeline.planEnd - previewTimeline.absEnd) > 0.25) && (
                  <span className="block text-slate-600 mt-0.5 truncate">
                    方案里标注的 {fmt(previewTimeline.planStart)} – {fmt(previewTimeline.planEnd)} 仅为规划时间窗；当前成片管线使用整段素材文件，与上面对齐。
                  </span>
                )}
              <span className="block text-slate-600 mt-0.5 truncate">
                {selectedPreview.source === 'video' ? (
                  <>原视频预览 · video_id: {resolvedVideoId || '解析中…'}</>
                ) : previewTimeline.windowSemantic === 'timeline_like' ? (
                  <>
                    片段文件预览（窗口疑似为时间轴坐标，不是片段内坐标）· clip_id: {selectedPreview.clipId || '-'}
                  </>
                ) : (
                  <>片段文件预览（0 – {fmt(previewTimeline.clipLocalEnd)}）· clip_id: {selectedPreview.clipId || '-'}</>
                )}
              </span>
            </p>
          ) : (
            <p className="text-[11px] text-slate-500 mt-0.5">点击下方任意“片段预览”按钮，在这里跳转到对应时间点播放。</p>
          )}
        </div>

        {selectedPreview && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="flex items-center gap-1.5 mr-1">
              <button
                type="button"
                onClick={() => {
                  setPreviewVideoErr(false)
                  setSelectedPreview((prev) => (prev && resolvedVideoId ? { ...prev, source: 'video' } : prev))
                }}
                disabled={!resolvedVideoId}
                className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
                  selectedPreview.source === 'video'
                    ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-200'
                    : 'border-slate-700 bg-slate-950/40 text-slate-300 hover:bg-slate-950/70 disabled:opacity-50'
                }`}
                title={resolvedVideoId ? '按原视频绝对时间预览/跳转（video_id 以片段在库中的记录为准）' : '正在解析或缺少可用的原视频 ID'}
              >
                原视频
              </button>

              <button
                type="button"
                onClick={() => {
                  setPreviewVideoErr(false)
                  setSelectedPreview((prev) => (prev ? { ...prev, source: 'clip' } : prev))
                }}
                className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
                  selectedPreview.source === 'clip'
                    ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                    : 'border-slate-700 bg-slate-950/40 text-slate-300 hover:bg-slate-950/70'
                }`}
                title="按片段文件时间轴预览/跳转"
              >
                片段
              </button>
            </div>

            <button
              type="button"
              onClick={() => {
                const v = previewVideoRef.current
                if (!v || !previewTimeline) return
                v.currentTime = selectedPreview.source === 'video' ? Math.max(0, previewTimeline.absStart) : 0
                void v.play().catch(() => {})
              }}
              className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-200 hover:bg-slate-950/70"
            >
              跳到起点
            </button>

            <button
              type="button"
              onClick={() => {
                const v = previewVideoRef.current
                if (!v || !previewTimeline) return
                v.currentTime = selectedPreview.source === 'video' ? Math.max(0, previewTimeline.absEnd) : Math.max(0, previewTimeline.clipLocalEnd)
                void v.play().catch(() => {})
              }}
              className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-200 hover:bg-slate-950/70"
            >
              跳到终点
            </button>

            <button
              type="button"
              onClick={() => setSelectedPreview(null)}
              className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70"
            >
              清空
            </button>
          </div>
        )}
      </div>

      <div className="rounded-xl overflow-hidden border border-slate-800 bg-black">
        {selectedPreview && !previewVideoErr ? (
          previewSrc ? (
            <video
              key={`${selectedPreview.source}:${selectedPreview.source === 'video' ? resolvedVideoId || selectedPreview.clipId : selectedPreview.clipId}`}
              ref={previewVideoRef}
              src={previewSrc}
              controls
              className="w-full max-h-[45vh] object-contain"
              onError={() => {
                // raw_* 是“未预处理视频”的虚拟片段 ID，本身没有 /clips/{id}/stream。
                // 若用户切到片段预览触发错误，自动回退到原视频预览，避免界面卡在错误态。
                if (
                  selectedPreview?.source === 'clip' &&
                  selectedPreview.clipId?.startsWith('raw_') &&
                  resolvedVideoId
                ) {
                  setPreviewVideoErr(false)
                  setSelectedPreview((prev) => (prev ? { ...prev, source: 'video' } : prev))
                  return
                }
                setPreviewVideoErr(true)
              }}
            />
          ) : (
            <div className="px-4 py-10 text-center text-sm text-slate-500">
              {selectedPreview.source === 'video' ? '正在从片段解析原视频 ID…' : '无法构建预览地址。'}
            </div>
          )
        ) : (
          <div className="px-4 py-10 text-center text-sm text-slate-500">
            {selectedPreview ? (selectedPreview.source === 'video' ? '原视频无法直接预览（接口 404 / 编码或格式不支持）。' : '该片段浏览器无法直接预览（视频编码或格式不支持）。') : '未选择片段。'}
          </div>
        )}
      </div>
    </div>
  )
}

