'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { type AutoEditMode, type AutoEditPlanApi } from '@/lib/api'
import { API_BASE_URL } from '@/lib/runtime-config'
import { type AutoPlanStage } from './autoEditTypes'
import { clipStreamUrl, fmt, videoStreamUrl } from './types'

type AutoEditPanelProps = {
  autoPrompt: string
  onAutoPromptChange: (value: string) => void
  autoMode: AutoEditMode
  onAutoModeChange: (value: AutoEditMode) => void
  autoTargetDuration: number | ''
  onAutoTargetDurationChange: (value: number | '') => void
  autoNumPlans: number
  onAutoNumPlansChange: (value: number) => void
  autoLoading: boolean
  autoError: string
  autoPlans: AutoEditPlanApi[]
  autoExpandedPlanIds: string[]
  onTogglePlanExpand: (planId: string) => void
  autoRealizingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoPlanLogs: string[]
  autoPlanElapsedSec: number
  autoPlanStage: AutoPlanStage
  autoPlanStagePercent: Record<AutoPlanStage, number>
  subtitleEnabled: boolean
  onGeneratePlans: () => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void
}

export function AutoEditPanel({
  autoPrompt,
  onAutoPromptChange,
  autoMode,
  onAutoModeChange,
  autoTargetDuration,
  onAutoTargetDurationChange,
  autoNumPlans,
  onAutoNumPlansChange,
  autoLoading,
  autoError,
  autoPlans,
  autoExpandedPlanIds,
  onTogglePlanExpand,
  autoRealizingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  autoPlanLogs,
  autoPlanElapsedSec,
  autoPlanStage,
  autoPlanStagePercent,
  subtitleEnabled,
  onGeneratePlans,
  onRealizePlan,
}: AutoEditPanelProps) {
  const [expandedPreviewPlanIds, setExpandedPreviewPlanIds] = useState<string[]>([])
  const [detailPlan, setDetailPlan] = useState<{
    plan: AutoEditPlanApi
    index: number
  } | null>(null)
  const [selectedPreview, setSelectedPreview] = useState<{
    planId: string
    planTitle: string
    segmentId: string
    order: number
    clipId: string
    videoId: string | null
    source: 'video' | 'clip'
    startSec: number
    endSec: number
  } | null>(null)
  const previewVideoRef = useRef<HTMLVideoElement | null>(null)
  const [previewVideoErr, setPreviewVideoErr] = useState(false)
  /** 与后端 clips 表一致；成片 realize 按整段 clip 拼接，不裁方案里的时间窗 */
  const [clipMetaByClip, setClipMetaByClip] = useState<
    Record<string, { video_id: string; start_time: number; end_time: number }>
  >({})

  useEffect(() => {
    if (!detailPlan) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDetailPlan(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [detailPlan])

  const togglePreviewExpand = (planId: string) => {
    setExpandedPreviewPlanIds((prev) =>
      prev.includes(planId) ? prev.filter((id) => id !== planId) : [...prev, planId]
    )
  }

  /** 仅使用库中 clip→video；方案 JSON 里的 video_id 不得用于 /stream */
  const resolvedVideoId = useMemo(() => {
    if (!selectedPreview?.clipId) return null
    return clipMetaByClip[selectedPreview.clipId]?.video_id ?? null
  }, [clipMetaByClip, selectedPreview])

  /** 预览/成片对齐：原视频轴用库内绝对时间；片段文件轴为 [0, end−start] */
  const previewTimeline = useMemo(() => {
    if (!selectedPreview) return null
    const meta = selectedPreview.clipId ? clipMetaByClip[selectedPreview.clipId] : undefined
    const planStart = Number(selectedPreview.startSec) || 0
    const planEnd = Number(selectedPreview.endSec) || planStart
    const absStart = meta ? meta.start_time : planStart
    const absEnd = meta ? meta.end_time : planEnd
    const clipLocalEnd = Math.max(0, absEnd - absStart)
    return { meta, planStart, planEnd, absStart, absEnd, clipLocalEnd }
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
    if (!autoPlans.length) return
    const ids = new Set<string>()
    for (const p of autoPlans) {
      for (const s of p.segments ?? []) {
        const cid = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id
        if (cid) ids.add(cid)
      }
    }
    const ac = new AbortController()
    for (const cid of ids) {
      void fetch(`${API_BASE_URL}/api/videos/clips/${cid}`, { signal: ac.signal })
        .then(async (r) => {
          if (!r.ok) return
          const data = (await r.json()) as { video_id: string; start_time: number; end_time: number }
          if (!data?.video_id) return
          setClipMetaByClip((prev) => {
            if (prev[cid]) return prev
            return {
              ...prev,
              [cid]: {
                video_id: data.video_id,
                start_time: Number(data.start_time),
                end_time: Number(data.end_time),
              },
            }
          })
        })
        .catch(() => {})
    }
    return () => ac.abort()
  }, [autoPlans])

  useEffect(() => {
    const video = previewVideoRef.current
    if (!video) return
    if (!selectedPreview) return
    if (!previewTimeline) return

    setPreviewVideoErr(false)

    const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v))
    const target =
      selectedPreview.source === 'video'
        ? Math.max(0, previewTimeline.absStart)
        : 0

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
    <>
      <section className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 space-y-4">
        <p className="text-xs font-semibold text-emerald-300 uppercase tracking-widest flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          自动一键成片 · 方案规划
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-xs text-slate-300 flex items-center justify-between">
              目标时长（秒）
              <span className="text-[11px] text-slate-500">10 - 600</span>
            </label>
            <input
              type="number"
              min={10}
              max={600}
              value={autoTargetDuration}
              onChange={(e) => onAutoTargetDurationChange(e.target.value ? Number(e.target.value) : '')}
              className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
            />
          </div>
          <div className="space-y-2">
            <label className="text-xs text-slate-300">候选方案数量</label>
            <select
              value={autoNumPlans}
              onChange={(e) => onAutoNumPlansChange(Number(e.target.value))}
              className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
            >
              {[1, 2, 3, 5].map((n) => (
                <option key={n} value={n}>
                  {n} 个方案
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <label className="text-xs text-slate-300">成片模式</label>
            <select
              value={autoMode}
              onChange={(e) => onAutoModeChange(e.target.value as AutoEditMode)}
              className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
            >
              <option value="auto">自动（智能选择原声/配音）</option>
              <option value="voiceover">配音剪辑</option>
              <option value="original">原声剪辑</option>
            </select>
          </div>
        </div>
        <div className="space-y-2">
          <label className="text-xs text-slate-300">创作提示词 / 文案 / 提纲</label>
          <textarea
            value={autoPrompt}
            onChange={(e) => onAutoPromptChange(e.target.value)}
            placeholder="例如：做一个 60 秒的搞笑职场翻车集锦，节奏轻快，适合短视频平台..."
            rows={4}
            className="w-full rounded-xl bg-slate-950/80 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-emerald-400 placeholder-slate-600 resize-none"
          />
        </div>
        {autoError && (
          <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {autoError}
          </div>
        )}
        <div className="flex items-center gap-3">
          <button
            onClick={onGeneratePlans}
            disabled={autoLoading || !autoPrompt.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-sm font-medium text-slate-950 transition-colors"
          >
            {autoLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {autoLoading ? '方案生成中...' : '生成自动成片方案'}
          </button>
          {autoPlans.length > 0 && (
            <span className="text-xs text-emerald-300/80">已生成 {autoPlans.length} 个方案，可进一步与成片管线打通。</span>
          )}
        </div>
        {(autoLoading || autoPlanLogs.length > 0) && (
          <div className="rounded-xl border border-emerald-500/30 bg-slate-950/60 px-4 py-3 space-y-2">
            <div className="space-y-1 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-300">
                  当前阶段：
                  {autoPlanStage === 'idle'
                    ? '待开始'
                    : autoPlanStage === 'preparing'
                      ? '准备中'
                      : autoPlanStage === 'connecting'
                        ? '连接中'
                        : autoPlanStage === 'planning'
                          ? '规划中'
                          : autoPlanStage === 'done'
                            ? '已完成'
                            : '失败'}
                </span>
                <span className={autoPlanStage === 'failed' ? 'text-red-400' : 'text-slate-400'}>
                  {autoPlanStage === 'failed' ? '失败' : `${autoPlanStagePercent[autoPlanStage]}%`}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-500 ${autoPlanStage === 'failed' ? 'bg-red-500' : 'bg-emerald-500'}`}
                  style={{ width: `${autoPlanStagePercent[autoPlanStage]}%` }}
                />
              </div>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-emerald-300 flex items-center gap-1.5">
                {autoLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {autoLoading ? '实时生成进度' : '最近一次生成记录'}
              </span>
              <span className="text-slate-500">{autoLoading ? `已等待 ${autoPlanElapsedSec}s` : `总耗时约 ${autoPlanElapsedSec}s`}</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {[
                { key: 'init', label: '初始化' },
                { key: 'context', label: '素材分析' },
                { key: 'llm', label: '方案生成' },
                { key: 'post', label: '结果整理' },
              ].map((step, idx) => {
                const stepRankMap: Record<string, number> = { init: 1, context: 2, llm: 3, post: 4 }
                const stageRankMap: Record<AutoPlanStage, number> = {
                  idle: 0,
                  preparing: 1,
                  connecting: 2,
                  planning: 3,
                  done: 4,
                  failed: 0,
                }
                const currentRank = stageRankMap[autoPlanStage] ?? 0
                const stepRank = stepRankMap[step.key]
                const active = currentRank === stepRank && autoLoading
                const passed = currentRank > stepRank || autoPlanStage === 'done'
                return (
                  <span
                    key={step.key}
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                      active
                        ? 'border-emerald-400 bg-emerald-500/20 text-emerald-200'
                        : passed
                          ? 'border-cyan-400/60 bg-cyan-500/10 text-cyan-200'
                          : 'border-slate-700 bg-slate-900/70 text-slate-500'
                    }`}
                  >
                    {idx + 1}. {step.label}
                  </span>
                )
              })}
              {autoPlanStage === 'failed' && (
                <span className="inline-flex items-center rounded-full border border-red-400/60 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300">
                  失败
                </span>
              )}
            </div>
            {autoLoading && (
              <p className="text-[11px] text-slate-400">
                {autoPlanElapsedSec < 3
                  ? '正在初始化模型与策略...'
                  : autoPlanElapsedSec < 10
                    ? '正在分析提示词并筛选素材...'
                    : '正在生成候选方案，请稍候...'}
              </p>
            )}
            <div className="max-h-28 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
              {autoPlanLogs.length === 0 ? (
                <p className="text-[11px] text-slate-500">等待日志...</p>
              ) : (
                autoPlanLogs.map((line, idx) => (
                  <p key={`${line}-${idx}`} className="text-[11px] text-slate-400 leading-5">
                    {line}
                  </p>
                ))
              )}
            </div>
          </div>
        )}
      </section>

      {autoPlans.length > 0 && (
        <section className="space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">候选方案 · {autoPlans.length} 个</p>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-semibold text-slate-300">片段预览播放器</p>
                {selectedPreview && previewTimeline ? (
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    <span className="block truncate">
                      {selectedPreview.planTitle} · #{selectedPreview.order} · 成片对应素材（库内时间）{' '}
                      {fmt(previewTimeline.absStart)} – {fmt(previewTimeline.absEnd)}
                      {!previewTimeline.meta && (
                        <span className="text-slate-600">（库内元数据加载完成后会校正）</span>
                      )}
                    </span>
                    {previewTimeline.meta &&
                      (Math.abs(previewTimeline.planStart - previewTimeline.absStart) > 0.25 ||
                        Math.abs(previewTimeline.planEnd - previewTimeline.absEnd) > 0.25) && (
                      <span className="block text-slate-600 mt-0.5 truncate">
                        方案里标注的 {fmt(previewTimeline.planStart)} – {fmt(previewTimeline.planEnd)}{' '}
                        仅为规划时间窗；当前成片管线使用整段素材文件，与上面对齐。
                      </span>
                    )}
                    <span className="block text-slate-600 mt-0.5 truncate">
                      {selectedPreview.source === 'video' ? (
                        <>原视频预览 · video_id: {resolvedVideoId || '解析中…'}</>
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
                      onClick={() =>
                        setSelectedPreview((prev) =>
                          prev && resolvedVideoId ? { ...prev, source: 'video' } : prev
                        )
                      }
                      disabled={!resolvedVideoId}
                      className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
                        selectedPreview.source === 'video'
                          ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-200'
                          : 'border-slate-700 bg-slate-950/40 text-slate-300 hover:bg-slate-950/70 disabled:opacity-50'
                      }`}
                      title={
                        resolvedVideoId
                          ? '按原视频绝对时间预览/跳转（video_id 以片段在库中的记录为准）'
                          : '正在解析或缺少可用的原视频 ID'
                      }
                    >
                      原视频
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedPreview((prev) => (prev ? { ...prev, source: 'clip' } : prev))}
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
                      v.currentTime =
                        selectedPreview.source === 'video'
                          ? Math.max(0, previewTimeline.absStart)
                          : 0
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
                      v.currentTime =
                        selectedPreview.source === 'video'
                          ? Math.max(0, previewTimeline.absEnd)
                          : Math.max(0, previewTimeline.clipLocalEnd)
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
                    onError={() => setPreviewVideoErr(true)}
                  />
                ) : (
                  <div className="px-4 py-10 text-center text-sm text-slate-500">
                    {selectedPreview.source === 'video'
                      ? '正在从片段解析原视频 ID…'
                      : '无法构建预览地址。'}
                  </div>
                )
              ) : (
                <div className="px-4 py-10 text-center text-sm text-slate-500">
                  {selectedPreview
                    ? selectedPreview.source === 'video'
                      ? '原视频无法直接预览（接口 404 / 编码或格式不支持）。'
                      : '该片段浏览器无法直接预览（视频编码或格式不支持）。'
                    : '未选择片段。'}
                </div>
              )}
            </div>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            {autoPlans.map((p, idx) => (
              <div key={p.plan_id || idx} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-100 truncate">{p.title || `方案 ${idx + 1}`}</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      模式：{p.mode === 'auto' ? '自动' : p.mode === 'voiceover' ? '配音剪辑' : '原声剪辑'}
                    </p>
                  </div>
                  <div className="text-right text-[11px] text-slate-500 space-y-0.5">
                    {p.target_duration_sec && <p>目标：{Math.round(p.target_duration_sec)}s</p>}
                    {p.estimated_duration_sec && <p>预估：{Math.round(p.estimated_duration_sec)}s</p>}
                    <p>段落：{p.segments?.length ?? 0}</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setDetailPlan({ plan: p, index: idx })}
                    className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-200 hover:bg-slate-950/70"
                    title="查看本方案的字幕、音频模式、片段选择等详情"
                  >
                    字幕详情 / 更多信息
                  </button>
                  {p.segments?.some((s) => s.subtitle?.text?.trim()) && (
                    <span className="text-[11px] text-emerald-300/80">含字幕</span>
                  )}
                </div>
                {p.summary && (
                  <div className="space-y-1">
                    <p className={`text-xs text-slate-300 ${autoExpandedPlanIds.includes(p.plan_id) ? '' : 'line-clamp-3'}`}>{p.summary}</p>
                    {p.summary.length > 80 && (
                      <button
                        type="button"
                        onClick={() => onTogglePlanExpand(p.plan_id)}
                        className="text-[11px] text-cyan-300 hover:text-cyan-200"
                      >
                        {autoExpandedPlanIds.includes(p.plan_id) ? '收起详情' : '展开详情'}
                      </button>
                    )}
                  </div>
                )}
                <div className="text-[11px] text-slate-500 space-y-1">
                  <p>
                    输出：
                    {p.mode === 'original'
                      ? subtitleEnabled
                        ? '原声 + 字幕'
                        : '原声（无字幕）'
                      : subtitleEnabled
                        ? '配音 + 字幕'
                        : '配音（无字幕）'}
                  </p>
                  <p>
                    片段预览：
                    <span className="ml-1 text-slate-600">（共 {p.segments?.length ?? 0} 段）</span>
                  </p>
                  <div
                    className={`mt-1 flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950/40 px-2 py-2 ${
                      expandedPreviewPlanIds.includes(p.plan_id) ? 'max-h-none' : 'max-h-24 overflow-y-auto'
                    }`}
                  >
                    {(p.segments ?? []).map((s) => {
                      const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id
                      const videoId = s.clip_group?.[0]?.video_id || null
                      const planTitle = p.title || `方案 ${idx + 1}`
                      const cm = clipId ? clipMetaByClip[clipId] : undefined
                      const t0 = cm ? cm.start_time : s.start_time_sec
                      const t1 = cm ? cm.end_time : s.end_time_sec
                      return (
                        <button
                          key={s.id}
                          type="button"
                          onClick={() => {
                            if (!clipId) return
                            setSelectedPreview({
                              planId: p.plan_id,
                              planTitle,
                              segmentId: s.id,
                              order: s.order,
                              clipId,
                              videoId,
                              source: videoId ? 'video' : 'clip',
                              startSec: s.start_time_sec,
                              endSec: s.end_time_sec,
                            })
                          }}
                          disabled={!clipId}
                          className="inline-flex items-center rounded-md border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-900/50 disabled:text-slate-500"
                          title={
                            clipId
                              ? cm
                                ? `成片使用库内整段：${fmt(cm.start_time)}–${fmt(cm.end_time)}（方案标注 ${fmt(s.start_time_sec)}–${fmt(s.end_time_sec)} 可能不同）`
                                : `加载库内时间中… 方案标注 ${fmt(s.start_time_sec)}–${fmt(s.end_time_sec)}`
                              : '该片段缺少 clip_id，暂不可预览'
                          }
                        >
                          #{s.order}（{fmt(t0)}-{fmt(t1)}）
                        </button>
                      )
                    })}
                  </div>
                  {(p.segments?.length ?? 0) > 12 && (
                    <button
                      type="button"
                      onClick={() => togglePreviewExpand(p.plan_id)}
                      className="mt-1 text-[11px] text-cyan-300 hover:text-cyan-200"
                    >
                      {expandedPreviewPlanIds.includes(p.plan_id) ? '折叠列表' : '展开列表'}
                    </button>
                  )}
                </div>
                <div className="pt-1 space-y-1">
                  <button
                    onClick={() => onRealizePlan(p, idx)}
                    disabled={autoRealizingId !== null}
                    className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/50 bg-emerald-500/10 text-[11px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60 transition-colors"
                  >
                    {autoRealizingId === p.plan_id ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        成片生成中...
                      </>
                    ) : (
                      <>一键成片</>
                    )}
                  </button>
                  {autoRealizeMsg && <p className="text-[11px] text-emerald-300/80">{autoRealizeMsg}</p>}
                  {autoRealizeDownloads[p.plan_id] && (
                    <a
                      href={autoRealizeDownloads[p.plan_id].url}
                      download={autoRealizeDownloads[p.plan_id].filename}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-[11px] text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
                    >
                      下载成片：{autoRealizeDownloads[p.plan_id].filename}
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {detailPlan && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="方案详情"
        >
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            onClick={() => setDetailPlan(null)}
            aria-label="关闭"
          />
          <div className="relative w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl overflow-hidden">
            <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-100 truncate">
                  {detailPlan.plan.title || `方案 ${detailPlan.index + 1}`} · 字幕详情 / 更多信息
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  plan_id: {detailPlan.plan.plan_id} · 段落：{detailPlan.plan.segments?.length ?? 0} · 模式：
                  {detailPlan.plan.mode === 'auto'
                    ? '自动'
                    : detailPlan.plan.mode === 'voiceover'
                      ? '配音剪辑'
                      : '原声剪辑'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setDetailPlan(null)}
                className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 flex-shrink-0"
              >
                关闭（Esc）
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto px-4 py-3 space-y-3">
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
                <p className="text-[11px] text-slate-400">方案摘要</p>
                <p className="text-xs text-slate-200 mt-1 whitespace-pre-wrap">
                  {detailPlan.plan.summary?.trim() ? detailPlan.plan.summary : '（无）'}
                </p>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
                <p className="text-[11px] text-slate-400">段落明细（字幕/音频/片段选择）</p>
                <div className="mt-2 space-y-2">
                  {(detailPlan.plan.segments ?? []).map((s) => {
                    const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id || ''
                    const cm = clipId ? clipMetaByClip[clipId] : undefined
                    const abs0 = cm ? cm.start_time : s.start_time_sec
                    const abs1 = cm ? cm.end_time : s.end_time_sec
                    const subtitleText = s.subtitle?.text?.trim() || ''
                    return (
                      <div key={s.id} className="rounded-xl border border-slate-800 bg-slate-950/30 px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-slate-200">
                            #{s.order} · {fmt(abs0)}–{fmt(abs1)}
                          </p>
                          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                            <span>audio: {s.audio_mode}</span>
                            <span>clip_id: {clipId || '-'}</span>
                            {cm?.video_id && <span>video_id: {cm.video_id}</span>}
                            {s.subtitle?.strategy && <span>subtitle: {s.subtitle.strategy}</span>}
                            {s.subtitle?.source && <span>source: {s.subtitle.source}</span>}
                          </div>
                        </div>

                        <div className="mt-2 grid gap-2 md:grid-cols-2">
                          <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-2 py-2">
                            <p className="text-[11px] text-slate-400">字幕文本</p>
                            <p className={`text-xs text-slate-200 mt-1 whitespace-pre-wrap ${subtitleText ? '' : 'text-slate-500'}`}>
                              {subtitleText || '（无字幕/策略为 none）'}
                            </p>
                          </div>
                          <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-2 py-2">
                            <p className="text-[11px] text-slate-400">候选片段</p>
                            <div className="mt-1 text-[11px] text-slate-300 space-y-1">
                              <p className="text-slate-400">
                                selected_clip_ids：
                                {(s.selected_clip_ids ?? []).length
                                  ? (s.selected_clip_ids ?? []).join(', ')
                                  : '（无）'}
                              </p>
                              <p className="text-slate-400">
                                clip_group：{(s.clip_group ?? []).length ? '' : '（无）'}
                              </p>
                              {(s.clip_group ?? []).slice(0, 6).map((c) => (
                                <p key={c.clip_id} className="truncate">
                                  - {c.clip_id} · video_id: {c.video_id}
                                  {typeof c.weight === 'number' ? ` · weight: ${c.weight}` : ''}
                                </p>
                              ))}
                              {(s.clip_group ?? []).length > 6 && <p className="text-slate-500">… 其余 {(s.clip_group ?? []).length - 6} 条已省略</p>}
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
