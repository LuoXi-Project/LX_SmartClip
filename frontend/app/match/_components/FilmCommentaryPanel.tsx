'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronUp, Film, Info, Loader2, RefreshCw, RotateCcw, Sparkles, XCircle } from 'lucide-react'
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
import { StreamingProgress, type ProgressStatus } from '@/components/ui/streaming-progress'

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

/** 影视解说方案生成阶段（按顺序，与 auto-edit 的 PLAN_STAGES chips 风格对齐） */
const COMMENTARY_STAGES = [
  { key: 'parsing', label: '理解原片' },
  { key: 'scripting', label: '撰写剧本' },
  { key: 'aligning', label: '匹配画面' },
  { key: 'planning', label: '生成方案' },
  { key: 'rendering', label: '配音出片' },
]

const ACTIVE_STAGES: FilmJobStatus[] = ['pending', 'parsing', 'scripting', 'aligning', 'planning', 'rendering']

/** FilmJobStatus → StreamingProgress 的 stage key（高亮对应 chip） */
function statusToStageKey(status: FilmJobStatus): string {
  if (status === 'pending') return 'parsing'
  if (ACTIVE_STAGES.includes(status)) return status
  return 'rendering' // done/failed — 最后一个 stage
}

function statusToProgressStatus(status: FilmJobStatus): ProgressStatus {
  if (status === 'done') return 'done'
  if (status === 'failed') return 'error'
  if (status === 'cancelled') return 'cancelled'
  return 'running'
}

/** 从 FilmJobStatus 和 progress dict 推算百分比（基于阶段序号） */
function derivePercent(status: FilmJobStatus, progress: Record<string, { status: string; message: string }>): number | null {
  if (status === 'done') return 100
  if (status === 'failed' || status === 'cancelled') return null
  if (status === 'pending') return 0
  const idx = ACTIVE_STAGES.indexOf(status)
  const total = COMMENTARY_STAGES.length
  if (idx < 0) return null
  // 当前阶段内部有 progress 条目说明有产出，给阶段内 50%；否则 0%
  const stepKeys = Object.keys(progress || {})
  const inStepProgress = stepKeys.length > 0 ? 0.5 : 0
  return Math.round(((idx + inStepProgress) / total) * 100)
}

const STYLE_OPTIONS: { id: FilmStyle; label: string }[] = [
  { id: 'suspense', label: '悬疑爆款' },
  { id: 'humor', label: '吐槽幽默' },
  { id: 'deep', label: '深度解析' },
  { id: 'fast', label: '快节奏' },
  { id: 'wilderness', label: '荒野作死' },
]

/** 模板默认成片时长（秒）；用户可在「解说编剧 · System」中自行修改时长与分句数 */
const DEFAULT_TARGET_DURATION_SEC = 300

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
  const [promptsOpen, setPromptsOpen] = useState(false)
  const [promptsLoading, setPromptsLoading] = useState(false)
  const [styleHint, setStyleHint] = useState('')
  const [screenplaySystem, setScreenplaySystem] = useState('')
  const [promptsDirty, setPromptsDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [jobs, setJobs] = useState<FilmCommentaryJob[]>([])
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  const loadPromptTemplates = useCallback(async () => {
    setPromptsLoading(true)
    try {
      const tpl = await filmCommentaryApi.promptTemplates({
        style,
        mode: parseMode,
        target_duration_sec: DEFAULT_TARGET_DURATION_SEC,
      })
      setStyleHint(tpl.style_hint)
      setScreenplaySystem(tpl.screenplay_system_prompt)
    } catch (e) {
      toast.error(formatFastApiDetail(e))
    } finally {
      setPromptsLoading(false)
    }
  }, [parseMode, style, toast])

  useEffect(() => {
    if (promptsDirty) return
    loadPromptTemplates()
  }, [loadPromptTemplates, promptsDirty])

  const resetPromptTemplates = () => {
    setPromptsDirty(false)
    loadPromptTemplates()
  }

  const markPromptsDirty = () => {
    setPromptsDirty(true)
  }

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
      if (jobs.some((j) => ACTIVE_STAGES.includes(j.status))) {
        loadJobs()
      }
    }, 2500)
    return () => clearInterval(tick)
  }, [jobs, loadJobs])

  const lastSyncedPlanKey = useRef<string | null>(null)
  useEffect(() => {
    if (!selectedJob?.plan || !onPlanReady) return
    const plan = selectedJob.plan
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
        target_duration_sec: DEFAULT_TARGET_DURATION_SEC,
        auto_render: false,
        include_subtitle: subtitleEnabled,
        prompt_overrides:
          promptsDirty && screenplaySystem.trim()
            ? { screenplay_system_prompt: screenplaySystem.trim() }
            : undefined,
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

      <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 overflow-hidden">
        <button
          type="button"
          onClick={() => setPromptsOpen((v) => !v)}
          className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-900/50"
        >
          <span>编剧提示词微调（可选）</span>
          <span className="flex items-center gap-2 text-[10px] text-slate-600">
            {promptsDirty ? '已自定义' : '使用模板默认'}
            {promptsOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </span>
        </button>
        {promptsOpen && (
          <div className="border-t border-slate-800 px-3 py-3 space-y-3">
            {styleHint && (
              <p className="text-[10px] text-violet-400/80 leading-relaxed">风格说明：{styleHint}</p>
            )}
            <div className="flex justify-end">
              <button
                type="button"
                onClick={resetPromptTemplates}
                disabled={promptsLoading}
                className="inline-flex items-center gap-1 text-[10px] text-slate-500 hover:text-violet-300 disabled:opacity-50"
              >
                <RotateCcw className="w-3 h-3" />
                恢复模板默认
              </button>
            </div>
            {promptsLoading ? (
              <p className="text-[11px] text-slate-500 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                加载模板…
              </p>
            ) : (
              <div>
                <label className="block text-[10px] text-slate-500 mb-1">
                  解说编剧 · System（切换风格会刷新，已编辑则保留）
                </label>
                <p className="text-[10px] text-slate-600 mb-2 leading-relaxed">
                  剧情摘要与输出格式由系统固定；成片时长与分句数量可在本提示中修改（如「目标成片约
                  …秒，解说分句约 …句」），亦可调整人设、语气与叙事要求。
                </p>
                <textarea
                  value={screenplaySystem}
                  onChange={(e) => {
                    markPromptsDirty()
                    setScreenplaySystem(e.target.value)
                  }}
                  rows={10}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-[11px] text-slate-300 font-mono leading-relaxed resize-y min-h-[160px]"
                />
              </div>
            )}
          </div>
        )}
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
          {selectedJob && (() => {
            const elapsed = selectedJob.created_at
              ? Math.max(0, Math.floor((Date.now() - Date.parse(selectedJob.created_at)) / 1000))
              : 0
            const derivedLogs = Object.entries(selectedJob.progress || {})
              .filter(([, v]) => v.message)
              .map(([k, v]) => `[${k}] ${v.message}`)
            const st = selectedJob.status
            return (
              <>
                <StreamingProgress
                  status={statusToProgressStatus(st)}
                  stage={statusToStageKey(st)}
                  stages={COMMENTARY_STAGES}
                  percent={derivePercent(st, selectedJob.progress || {})}
                  elapsedSec={elapsed}
                  logs={derivedLogs}
                  accent="violet"
                  hint={ACTIVE_STAGES.includes(st) ? `正在${STATUS_LABEL[st]}…` : undefined}
                  onCancel={ACTIVE_STAGES.includes(st) ? () => handleCancel(selectedJob.id) : undefined}
                />
                {selectedJob.error_message && (
                  <div className="flex gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg p-2">
                    <XCircle className="w-3.5 h-3.5 shrink-0" />
                    {selectedJob.error_message}
                  </div>
                )}
                <div className="flex gap-2">
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
            )
          })()}
        </div>
      )}
    </section>
  )
}
