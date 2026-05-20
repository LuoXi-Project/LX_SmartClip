'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { Film, Info, Loader2, RefreshCw, Sparkles, XCircle } from 'lucide-react'
import {
  filmCommentaryApi,
  formatFastApiDetail,
  type AutoEditPlanApi,
  type FilmCommentaryJob,
  type FilmJobStatus,
  type FilmMode,
  type FilmStyle,
  type Video,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'

const STATUS_LABEL: Record<FilmJobStatus, string> = {
  pending: '排队中',
  parsing: '理解原片',
  scripting: '撰写剧本',
  aligning: '匹配画面',
  planning: '生成方案',
  rendering: '配音出片',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const STYLE_OPTIONS: { id: FilmStyle; label: string }[] = [
  { id: 'suspense', label: '悬疑爆款' },
  { id: 'humor', label: '吐槽幽默' },
  { id: 'deep', label: '深度解析' },
  { id: 'fast', label: '快节奏' },
]

const ACTIVE: FilmJobStatus[] = [
  'pending',
  'parsing',
  'scripting',
  'aligning',
  'planning',
  'rendering',
]

function isActive(status: FilmJobStatus) {
  return ACTIVE.includes(status)
}

type FilmCommentaryPanelProps = {
  selectedVideoIds: string[]
  doneVideos: Video[]
  /** 与页面「字幕设置」共用，成片/剪映导出亦读取该开关 */
  subtitleEnabled?: boolean
  onPlanReady?: (plan: AutoEditPlanApi) => void
}

export function FilmCommentaryPanel({
  selectedVideoIds,
  doneVideos,
  subtitleEnabled = true,
  onPlanReady,
}: FilmCommentaryPanelProps) {
  const toast = useToast()
  const primaryVideoId = selectedVideoIds[0] ?? ''
  const [parseMode, setParseMode] = useState<FilmMode>('precise')
  const [style, setStyle] = useState<FilmStyle>('suspense')
  const [targetMin, setTargetMin] = useState(5)
  const [submitting, setSubmitting] = useState(false)
  const [jobs, setJobs] = useState<FilmCommentaryJob[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  const primaryVideo = useMemo(
    () => doneVideos.find((x) => x.id === primaryVideoId),
    [doneVideos, primaryVideoId],
  )

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) ?? jobs[0] ?? null,
    [jobs, selectedJobId],
  )

  const loadJobs = useCallback(async () => {
    try {
      const res = await filmCommentaryApi.list(40)
      const items = (res.items ?? []).filter(
        (j) => !primaryVideoId || j.video_id === primaryVideoId,
      )
      setJobs(items)
      if (!selectedJobId && items.length) {
        setSelectedJobId(items[0].id)
      }
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    }
  }, [primaryVideoId, selectedJobId, toast])

  useEffect(() => {
    loadJobs()
  }, [loadJobs])

  useEffect(() => {
    const tick = setInterval(() => {
      if (jobs.some((j) => isActive(j.status))) {
        loadJobs()
      }
    }, 2500)
    return () => clearInterval(tick)
  }, [jobs, loadJobs])

  const lastSyncedPlanKey = useRef<string | null>(null)
  useEffect(() => {
    if (!selectedJob?.plan || !onPlanReady) return
    const plan = selectedJob.plan as AutoEditPlanApi
    const key = `${selectedJob.id}:${plan.plan_id ?? ''}:${selectedJob.updated_at}`
    if (lastSyncedPlanKey.current === key) return
    lastSyncedPlanKey.current = key
    onPlanReady(plan)
  }, [selectedJob, onPlanReady])

  const handleStart = async () => {
    if (!primaryVideoId) {
      toast.error('请先在上方选择一部原片')
      return
    }
    setSubmitting(true)
    try {
      const job = await filmCommentaryApi.create({
        video_id: primaryVideoId,
        mode: parseMode,
        style,
        target_duration_sec: Math.max(60, Math.min(1800, targetMin * 60)),
        auto_render: false,
        include_subtitle: subtitleEnabled,
      })
      toast.success('流水线已启动，完成后请在下方预览并手动成片')
      setSelectedJobId(job.id)
      await loadJobs()
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (jobId: string) => {
    try {
      await filmCommentaryApi.cancel(jobId)
      toast.success('已请求取消')
      await loadJobs()
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    }
  }

  const handleRetry = async (jobId: string) => {
    try {
      await filmCommentaryApi.retry(jobId)
      toast.success('已重新排队')
      await loadJobs()
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    }
  }

  return (
    <section className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5 space-y-5">
      <div className="flex gap-2 text-xs text-slate-400">
        <Info className="w-4 h-4 text-violet-400 shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          步骤：① 上方选择原片 → ② 生成分句解说并对齐镜头 → ③ 下方配置 BGM → ④ 方案预览后手动合成或导出剪映。
          未处理过的原片会在流水线中自动切片解析；也可先到
          <Link href="/process" className="mx-1 text-indigo-400 hover:underline">
            素材处理
          </Link>
          预处理。
        </p>
      </div>

      <div>
        <p className="text-xs font-semibold text-violet-300 uppercase tracking-widest flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          影视解说 · 生成方案
        </p>
        {primaryVideo ? (
          <p className="text-[11px] text-slate-500 mt-1 truncate">{primaryVideo.name}</p>
        ) : (
          <p className="text-[11px] text-amber-400/90 mt-1">请先在上方点击选择一部原片</p>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">解析模式</label>
          <select
            value={parseMode}
            onChange={(e) => setParseMode(e.target.value as FilmMode)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          >
            <option value="precise">精准（VLM + ASR）</option>
            <option value="lightweight">轻量（ASR + 通识）</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">解说风格</label>
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value as FilmStyle)}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          >
            {STYLE_OPTIONS.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1">目标成片：约 {targetMin} 分钟</label>
        <input
          type="range"
          min={2}
          max={30}
          value={targetMin}
          onChange={(e) => setTargetMin(Number(e.target.value))}
          className="w-full"
        />
      </div>

      <button
        type="button"
        onClick={handleStart}
        disabled={submitting || !primaryVideoId}
        className="inline-flex items-center justify-center gap-2 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 px-5 py-2.5 text-sm font-medium text-white"
      >
        {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Film className="w-4 h-4" />}
        生成解说方案（不自动出片）
      </button>

      {(jobs.length > 0 || selectedJob) && (
        <div className="border-t border-violet-500/15 pt-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-slate-500">任务进度</p>
            <button
              type="button"
              onClick={() => loadJobs()}
              className="p-1 text-slate-500 hover:text-slate-300"
              aria-label="刷新"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
          {jobs.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {jobs.map((j) => (
                <button
                  key={j.id}
                  type="button"
                  onClick={() => setSelectedJobId(j.id)}
                  className={`rounded-md border px-2 py-1 text-[10px] ${
                    selectedJob?.id === j.id
                      ? 'border-violet-500/50 bg-violet-500/10 text-slate-200'
                      : 'border-slate-800 text-slate-500'
                  }`}
                >
                  {STATUS_LABEL[j.status]}
                </button>
              ))}
            </div>
          )}
          {selectedJob && (
            <>
              <p className="text-sm text-slate-300">{STATUS_LABEL[selectedJob.status]}</p>
              {selectedJob.error_message && (
                <div className="flex gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg p-2">
                  <XCircle className="w-3.5 h-3.5 shrink-0" />
                  {selectedJob.error_message}
                </div>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {Object.entries(selectedJob.progress || {}).map(([key, val]) => (
                  <div key={key} className="rounded border border-slate-800 px-2 py-1 text-[10px]">
                    <div className="text-slate-600">{key}</div>
                    <div className="text-slate-400 truncate">{val.message || val.status}</div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                {isActive(selectedJob.status) && (
                  <button
                    type="button"
                    onClick={() => handleCancel(selectedJob.id)}
                    className="text-[11px] border border-slate-600 rounded-lg px-2.5 py-1 text-slate-400"
                  >
                    取消
                  </button>
                )}
                {(selectedJob.status === 'failed' || selectedJob.status === 'cancelled') && (
                  <button
                    type="button"
                    onClick={() => handleRetry(selectedJob.id)}
                    className="text-[11px] border border-violet-600 rounded-lg px-2.5 py-1 text-violet-300"
                  >
                    重试
                  </button>
                )}
              </div>
              {selectedJob.plan && (
                <p className="text-[11px] text-emerald-400/90">
                  方案已同步至下方预览区，请配置 BGM 后手动合成或导出剪映。
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
