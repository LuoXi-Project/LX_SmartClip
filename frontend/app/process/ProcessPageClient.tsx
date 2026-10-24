'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import apiClient, { clipsApi, formatFastApiDetail, jobsApi, processJobsApi, videosApi, type JobSnapshot, type Video } from '@/lib/api'
import { fetchSSE } from '@/lib/stream'
import { useTaskStore } from '@/lib/task-store'
import { ArrowLeft, CheckCircle2, XCircle, Loader2, SkipForward, Play, Film, Search, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Mic, Check, Square } from 'lucide-react'
import { VideoResultDrawer } from '@/app/_components/VideoResultDrawer'
import { VoiceInputControl } from '@/components/ui/voice-input'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'

const STEPS = [
  { key: 'split',          label: '视频切分',       desc: '按镜头或固定时长切分视频' },
  { key: 'extract_frames', label: '图帧提取',       desc: '抽帧后立即进入后续视觉分析' },
  { key: 'asr',            label: '语音识别',       desc: '与抽帧并行转写台词文本' },
  { key: 'vlm',            label: '视觉描述 (VLM)', desc: '按片段流水线生成画面描述' },
  { key: 'enrich',         label: '智能标注',       desc: '生成旁白适配摘要/关键词/情绪，提升旁白检索命中率（需 LLM Key）' },
  { key: 'embed',          label: '向量入库',       desc: '描述产出后立即向量化入库' },
] as const

type StepKey = (typeof STEPS)[number]['key']
type StepStatus = 'idle' | 'running' | 'done' | 'error' | 'skip'
interface SS { status: StepStatus; message: string; detail: Record<string, unknown> }

const blank = (): Record<StepKey, SS> =>
  Object.fromEntries(STEPS.map((s) => [s.key, { status: 'idle' as StepStatus, message: '', detail: {} }])) as Record<StepKey, SS>

function SIcon({ s }: { s: StepStatus }) {
  if (s === 'running') return <Loader2 className="w-5 h-5 text-amber-400 animate-spin" />
  if (s === 'done') return <CheckCircle2 className="w-5 h-5 text-emerald-400" />
  if (s === 'error') return <XCircle className="w-5 h-5 text-red-400" />
  if (s === 'skip') return <SkipForward className="w-5 h-5 text-slate-600" />
  return <div className="w-5 h-5 rounded-full border-2 border-slate-700" />
}

function cardCls(s: StepStatus) {
  if (s === 'running') return 'border-amber-500/50 bg-amber-500/5'
  if (s === 'done') return 'border-emerald-500/50 bg-emerald-500/5'
  if (s === 'error') return 'border-red-500/50 bg-red-500/5'
  if (s === 'skip') return 'border-slate-800 opacity-40'
  return 'border-slate-800 bg-slate-900/30'
}

type SplitPhase = 'detecting' | 'planning' | 'cutting' | 'done' | ''

function splitPhaseLabel(phase: SplitPhase, splitMode?: string) {
  if (phase === 'detecting') return '镜头识别'
  if (phase === 'planning') return splitMode === 'hybrid' ? '超长镜头二次切分' : '切分规划'
  if (phase === 'cutting') return '片段导出'
  if (phase === 'done') return '切分完成'
  return ''
}

function resolveSplitProgress(detail: Record<string, unknown>) {
  const phase = String(detail.phase ?? '') as SplitPhase
  const shots = Number(detail.shots_detected ?? 0)
  const planned = Number(detail.segments_planned ?? 0)
  const ready = Number(detail.clips_ready ?? detail.processed ?? detail.current ?? 0)
  const splitMode = String(detail.split_mode ?? '')
  const total = Number(detail.total ?? 0) || (planned > 0 ? planned : 0)
  const current = Number(detail.current ?? 0) || (phase === 'cutting' && total > 0 ? ready : shots)
  const showBar = phase === 'cutting' && total > 0
  const showIndeterminate = phase === 'detecting' || phase === 'planning' || (phase === 'cutting' && total <= 0)
  return { phase, shots, planned, ready, splitMode, total, current, showBar, showIndeterminate, phaseLabel: splitPhaseLabel(phase, splitMode) }
}

const PAGE_SIZE = 9
/** SSE 断线或漏帧时，轮询 job 快照的间隔（毫秒） */
const TASK_POLL_MS = 3000

export default function ProcessPage() {
  const searchParams = useSearchParams()
  const videoFromUrl = (searchParams.get('video') ?? '').trim()

  const [videos, setVideos] = useState<Video[]>([])
  const [selId, setSelId] = useState('')
  const appliedUrlVideoIdRef = useRef('')
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [steps, setSteps] = useState<Record<StepKey, SS>>(blank)
  const [finalMetrics, setFinalMetrics] = useState<Record<string, unknown> | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [resultOpen, setResultOpen] = useState(false)
  const [recoverOpen, setRecoverOpen] = useState(false)
  /** 默认 true：重跑 ASR/VLM 后同步写入向量；关闭则 skip embed（检索可能不一致） */
  const [syncVectorOnRecover, setSyncVectorOnRecover] = useState(true)
  const [statusUpdating, setStatusUpdating] = useState(false)
  const [statusFixMsg, setStatusFixMsg] = useState('')
  /** 最近一次主入口任务模式：用于完成文案区分（恢复区重跑不改变此值） */
  const [runPreset, setRunPreset] = useState<'full' | 'asr_only'>('full')
  /** 当前选中视频所展示的 process job id（来自 async_jobs，前端唯一追踪键）*/
  const [selJobId, setSelJobId] = useState('')
  /** 多选模式开关：开启后视频卡片改为复选，底部出现批量启动按钮 */
  const [multiSelect, setMultiSelect] = useState(false)
  /** 多选模式下已勾选的视频 id 集合（跨页保留）*/
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  /** 批量提交进行中（顺序提交多个 create 期间禁用按钮）*/
  const [batchSubmitting, setBatchSubmitting] = useState(false)
  /** SSE 连接的 AbortController（切视频/停止/卸载时中止，避免旧流污染新视图）*/
  const sseAbortRef = useRef<AbortController | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const runningRef = useRef(running)
  const doneRef = useRef(done)
  runningRef.current = running
  doneRef.current = done

  const taskStoreUpsert = useTaskStore((s) => s.upsert)
  const taskStorePatch = useTaskStore((s) => s.patch)
  const toast = useToast()
  const confirm = useConfirm()
  /** 单视频任务提交中（POST create 到返回前，主按钮显示 spinner）*/
  const [starting, setStarting] = useState(false)

  /** 把 process job 同步到 TaskHub 的 task-store（带视频名 + 停止/删除回调）*/
  const bridgeToTaskHub = (
    created: { task_id?: string; job_id?: string; job_stream_url?: string; video_id?: string; video_name?: string },
    baseTitle: string,
  ) => {
    const jid = created.job_id
    const streamUrl = created.job_stream_url
    if (!jid || !streamUrl) return
    const videoName = created.video_name || ''
    const title = videoName ? `${baseTitle} · ${videoName}` : baseTitle
    const fullUrl = streamUrl.startsWith('/') ? `${window.location.origin}${streamUrl}` : streamUrl
    taskStoreUpsert({
      id: jid, title, kind: 'process', status: 'running',
      percent: null, logs: [], elapsedSec: 0, createdAt: Date.now(),
      videoName, videoId: created.video_id,
      onCancel: () => { jobsApi.cancel(jid).catch(() => undefined) },
      onRemove: () => { jobsApi.remove(jid).catch(() => undefined) },
    })
    // 用 SSE 订阅 async_job 进度，实时推入 task-store
    fetchSSE(fullUrl, undefined, {
      onEvent(event, data) {
        if (event === 'progress') {
          const m = data as { step?: string; message?: string; detail?: { percent?: number; current?: number; total?: number } }
          let pct = typeof m?.detail?.percent === 'number' ? m.detail.percent : null
          if (pct === null && typeof m?.detail?.current === 'number' && typeof m?.detail?.total === 'number' && m.detail.total > 0) {
            pct = Math.round((m.detail.current / m.detail.total) * 100)
          }
          taskStorePatch(jid, { stage: m?.step, percent: pct })
        }
        if (event === 'result') {
          taskStorePatch(jid, { status: 'done', percent: 100, resultLabel: '预处理完成' })
        }
        if (event === 'failed') {
          const f = data as { message?: string; cancelled?: boolean }
          taskStorePatch(jid, { status: f?.cancelled ? 'cancelled' : 'error', error: f?.message || '预处理失败' })
        }
      },
      onError(err) {
        taskStorePatch(jid, { status: 'error', error: err.message })
      },
    }).catch(() => undefined)
  }

  const stopTaskPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }

  /** 中止当前 SSE 订阅（切视频/停止/卸载时调用，避免旧流把新视图污染）*/
  const closeStreamQuietly = () => {
    if (sseAbortRef.current) {
      sseAbortRef.current.abort()
      sseAbortRef.current = null
    }
  }

  useEffect(() => {
    const loadAllVideos = async () => {
      try {
        const first = await apiClient.get<unknown, {
          items?: Video[]
          total_pages?: number
          page?: number
          page_size?: number
        } | Video[]>('/api/videos')

        if (Array.isArray(first)) {
          setVideos(first)
          return
        }

        const firstItems = first?.items || []
        const totalPages = Number(first?.total_pages || 1)
        const currentPage = Number(first?.page || 1)
        const pageSize = Number(first?.page_size || firstItems.length || PAGE_SIZE)

        if (totalPages <= currentPage) {
          setVideos(firstItems)
          return
        }

        const restPages = await Promise.all(
          Array.from({ length: totalPages - currentPage }, (_, i) => currentPage + i + 1).map((p) =>
            apiClient.get<unknown, { items?: Video[] }>('/api/videos', {
              params: { page: p, page_size: pageSize },
            }),
          ),
        )

        const merged = [
          ...firstItems,
          ...restPages.flatMap((res) => res?.items || []),
        ]
        setVideos(merged)
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }

    void loadAllVideos()
  }, [])

  /** 处理进度更新时仅当用户已在页面底部附近才跟随滚动，避免打断向上查看步骤/选视频 */
  useEffect(() => {
    if (!runningRef.current && !doneRef.current) return
    const doc = document.documentElement
    const nearBottom = window.innerHeight + window.scrollY >= doc.scrollHeight - 160
    if (nearBottom) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [steps])

  const refreshVideoMeta = async (videoId: string, videoStatus?: Video['status']) => {
    if (!videoId) return
    try {
      const clips = await clipsApi.listByVideo(videoId)
      setVideos((prev) =>
        prev.map((v) =>
          v.id === videoId
            ? {
                ...v,
                total_clips: clips.length,
                ...(videoStatus ? { status: videoStatus } : {}),
              }
            : v,
        ),
      )
    } catch {
      /* 列表刷新失败不阻断 UI 解锁 */
    }
  }

  /** 当前展示的 job id（用于忽略切视频后旧 SSE/轮询的回调，避免污染新视图）*/
  const activeJobRef = useRef('')

  const applyJobSnapshot = (job: JobSnapshot) => {
    const next = blank()
    STEPS.forEach((s) => {
      const val = job.steps?.[s.key]
      if (val) next[s.key] = {
        status: val.status as StepStatus,
        message: val.message || '',
        detail: (val.detail || {}) as Record<string, unknown>,
      }
    })
    setSteps(next)
    setFinalMetrics(job.metrics || null)
    setDone(job.status === 'done')
    setRunning(job.status === 'running' || job.status === 'pending')
  }

  const finishJobFromSnapshot = (job: JobSnapshot, vid: string) => {
    applyJobSnapshot(job)
    if (job.status === 'done') {
      setRunning(false)
      setDone(true)
      setSteps((p) => {
        const n = { ...p }
        STEPS.forEach((s) => {
          if (n[s.key].status === 'idle') n[s.key] = { status: 'skip', message: '已跳过', detail: {} }
        })
        return n
      })
      stopTaskPolling()
      closeStreamQuietly()
      void refreshVideoMeta(vid, 'done')
      return
    }
    if (job.status === 'cancelled') {
      setRunning(false)
      setDone(false)
      normalizeRunningStepsAsStopped()
      stopTaskPolling()
      closeStreamQuietly()
      void refreshVideoMeta(vid, 'pending')
      return
    }
    if (job.status === 'error') {
      setRunning(false)
      stopTaskPolling()
      closeStreamQuietly()
      void refreshVideoMeta(vid, 'error')
    }
  }

  const pollJobOnce = async (jobId: string, vid: string) => {
    if (activeJobRef.current !== jobId) return
    try {
      const job = await jobsApi.get(jobId)
      if (activeJobRef.current !== jobId) return
      applyJobSnapshot(job)
      if (job.status === 'done' || job.status === 'error' || job.status === 'cancelled') {
        finishJobFromSnapshot(job, vid)
      }
    } catch {
      stopTaskPolling()
      setRunning(false)
    }
  }

  const startJobPolling = (jobId: string, vid: string) => {
    stopTaskPolling()
    void pollJobOnce(jobId, vid)
    pollTimerRef.current = setInterval(() => void pollJobOnce(jobId, vid), TASK_POLL_MS)
  }

  /** 订阅 job 的 SSE 流（async_jobs），实时推进步骤卡片 */
  const openJobStream = (jobId: string, vid: string) => {
    closeStreamQuietly()
    const ctrl = new AbortController()
    sseAbortRef.current = ctrl
    const fullUrl = `${window.location.origin}${jobsApi.streamUrl(jobId)}`
    fetchSSE(fullUrl, undefined, {
      onEvent(event, data) {
        if (activeJobRef.current !== jobId) return
        if (event === 'progress') {
          const m = data as { step?: string; status?: string; message?: string; detail?: Record<string, unknown> }
          if (!m) return
          // step 级 done/error 由 result/failed 终态事件统一收尾，这里不重复处理
          if (m.step === 'done' || m.step === 'error') return
          if (m.step) {
            setSteps((p) => ({
              ...p,
              [m.step as StepKey]: {
                status: (m.status || 'running') as StepStatus,
                message: m.message || '',
                detail: (m.detail || {}) as Record<string, unknown>,
              },
            }))
          }
          const met = (m.detail as { metrics?: Record<string, unknown> } | undefined)?.metrics
          if (met && typeof met === 'object') setFinalMetrics(met)
        } else if (event === 'result') {
          setRunning(false)
          setDone(true)
          setSteps((p) => {
            const n = { ...p }
            STEPS.forEach((s) => { if (n[s.key].status === 'idle') n[s.key] = { status: 'skip', message: '已跳过', detail: {} } })
            return n
          })
          stopTaskPolling()
          closeStreamQuietly()
          void refreshVideoMeta(vid, 'done')
        } else if (event === 'failed') {
          const f = data as { message?: string; cancelled?: boolean }
          setRunning(false)
          setDone(false)
          if (f?.cancelled) normalizeRunningStepsAsStopped()
          stopTaskPolling()
          closeStreamQuietly()
          void refreshVideoMeta(vid, f?.cancelled ? 'pending' : 'error')
        }
      },
      onError() {
        /* 轮询兜底继续，不打断 */
      },
    }, ctrl.signal).catch(() => undefined)
  }

  /** 接管一个 job：设为当前展示 + 轮询 + SSE */
  const adoptJob = (jobId: string, vid: string) => {
    activeJobRef.current = jobId
    setSelJobId(jobId)
    startJobPolling(jobId, vid)
    openJobStream(jobId, vid)
  }

  const clearJobView = () => {
    activeJobRef.current = ''
    setSelJobId('')
    setSteps(blank())
    setRunning(false)
    setDone(false)
    setFinalMetrics(null)
  }

  /** 切换选中视频：加载该视频的活跃 process job（运行/排队），无则清空 */
  const loadJobForSelectedVideo = async (videoId: string) => {
    closeStreamQuietly()
    stopTaskPolling()
    if (!videoId) {
      clearJobView()
      return
    }
    try {
      const res = await jobsApi.list({ kind: 'process', active: true, ref_id: videoId })
      const job = res.items?.[0]
      if (job) {
        applyJobSnapshot(job)
        adoptJob(job.id, videoId)
      } else {
        clearJobView()
      }
    } catch {
      clearJobView()
    }
  }

  // 卸载时清理 SSE 与轮询
  useEffect(() => {
    return () => {
      activeJobRef.current = ''
      closeStreamQuietly()
      stopTaskPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 选中视频变化时，加载该视频的活跃 process job
  useEffect(() => {
    void loadJobForSelectedVideo(selId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selId])

  useEffect(() => {
    appliedUrlVideoIdRef.current = ''
  }, [videoFromUrl])

  const filteredVideos = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? videos.filter((v) => v.name.toLowerCase().includes(q)) : videos
  }, [videos, search])

  useEffect(() => {
    if (loading || !videoFromUrl) return
    if (!videos.some((v) => v.id === videoFromUrl)) return
    if (appliedUrlVideoIdRef.current === videoFromUrl) return

    appliedUrlVideoIdRef.current = videoFromUrl
    setSelId(videoFromUrl)
    const idx = filteredVideos.findIndex((v) => v.id === videoFromUrl)
    if (idx >= 0) setPage(Math.floor(idx / PAGE_SIZE) + 1)
  }, [loading, videoFromUrl, videos, filteredVideos])

  const totalPages = Math.max(1, Math.ceil(filteredVideos.length / PAGE_SIZE))
  const pagedVideos = filteredVideos.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  const handleSearch = (val: string) => {
    setSearch(val)
    setPage(1)
  }

  const normalizeRunningStepsAsStopped = () => {
    setSteps((p) => {
      const n = { ...p }
      STEPS.forEach((s) => {
        if (n[s.key].status === 'running') {
          n[s.key] = { status: 'skip', message: '已停止', detail: n[s.key].detail }
        }
      })
      return n
    })
  }

  /** 口播快轨：只做切分（若尚无片段）+ ASR，跳过抽帧 / VLM / 智能标注 / 向量，显著快于全流程 */
  const asrOnlySkipSteps = (hasExistingClips: boolean): string[] =>
    hasExistingClips
      ? ['split', 'extract_frames', 'vlm', 'enrich', 'embed']
      : ['extract_frames', 'vlm', 'enrich', 'embed']

  /** 统一入口：启动/排队一个预处理任务。新 job 立即接管显示（排队/运行均展示）。*/
  const submitProcessJob = async (
    createFn: () => Promise<{ task_id?: string; job_id?: string; job_stream_url?: string; video_id?: string; video_name?: string; status: string }>,
    title: string,
  ) => {
    if (!selId) return
    setStarting(true)
    try {
      const created = await createFn()
      bridgeToTaskHub(created, title)
      // 切换到新 job 的显示（无论立即执行还是排队）
      setSteps(blank())
      setRunning(true)
      setDone(false)
      setFinalMetrics(null)
      setRunPreset('full')
      const jid = created.job_id
      if (jid) {
        try {
          const job = await jobsApi.get(jid)
          applyJobSnapshot(job)
        } catch {
          /* 忽略：adoptJob 仍会订阅实时进度 */
        }
        adoptJob(jid, created.video_id || selId)
      }
    } catch (e) {
      setRunning(false)
      toast.error(`任务提交失败：${formatFastApiDetail(e)}`)
    } finally {
      setStarting(false)
    }
  }

  const handleStart = async () => {
    await submitProcessJob(
      () => processJobsApi.create(selId),
      '视频预处理',
    )
  }

  const handleStartAsrOnly = async () => {
    const hasClips = (videos.find((v) => v.id === selId)?.total_clips ?? 0) > 0
    setRunPreset('asr_only')
    await submitProcessJob(
      () => processJobsApi.create(selId, { skip_steps: asrOnlySkipSteps(hasClips) }),
      '视频预处理(ASR)',
    )
  }

  /** 切换多选开关：进入多选时清空单选视图（避免两套选择态打架），退出时清空多选勾选 */
  const toggleMultiSelect = (next: boolean) => {
    setMultiSelect(next)
    setSelectedIds(new Set())
    if (next) {
      closeStreamQuietly()
      stopTaskPolling()
      activeJobRef.current = ''
      setSelId('')
      setSelJobId('')
      setSteps(blank())
      setRunning(false)
      setDone(false)
      setFinalMetrics(null)
    }
  }

  /** 多选模式下勾选/取消某个视频 */
  const toggleSelectVideo = (videoId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(videoId)) next.delete(videoId)
      else next.add(videoId)
      return next
    })
  }

  /**
   * 多选批量提交预处理任务：顺序调用 processJobsApi.create，让后端按入队顺序串行执行。
   * 每个 job 通过 bridgeToTaskHub 注入全局任务面板（右下角 TaskHub 逐个展示进度/排队位置）。
   * 单个失败不阻断其余；完成后用 toast 汇总成功数并清空选择。
   */
  const handleBatchStart = async (preset: 'full' | 'asr_only') => {
    const ids = Array.from(selectedIds)
    if (ids.length === 0 || batchSubmitting) return
    setBatchSubmitting(true)
    let okCount = 0
    for (const vid of ids) {
      try {
        let created
        if (preset === 'full') {
          created = await processJobsApi.create(vid)
        } else {
          const v = videos.find((x) => x.id === vid)
          const hasClips = (v?.total_clips ?? 0) > 0
          created = await processJobsApi.create(vid, { skip_steps: asrOnlySkipSteps(hasClips) })
        }
        const videoName = created.video_name || videos.find((x) => x.id === vid)?.name || ''
        bridgeToTaskHub(
          { ...created, video_name: videoName },
          preset === 'full' ? '视频预处理' : '视频预处理(ASR)',
        )
        okCount++
      } catch {
        /* 单个失败不阻断其余，继续提交下一个 */
      }
    }
    setBatchSubmitting(false)
    if (okCount > 0) {
      toast.success(`已提交 ${okCount} / ${ids.length} 个预处理任务，将在队列中依次执行`)
      // 提交后清空选择，方便用户继续选下一批
      setSelectedIds(new Set())
    } else {
      toast.error('批量提交失败，请稍后重试')
    }
  }

  const recoverSkipSteps = (preset: 'asr_only' | 'vlm_only' | 'asr_vlm' | 'embed_only' | 'enrich_only' | 'multivec'): string[] => {
    let base: string[]
    if (preset === 'asr_only') base = ['split', 'extract_frames', 'vlm', 'enrich']                // 仅补 ASR：画面未变，跳过 enrich
    else if (preset === 'vlm_only') base = ['split', 'asr']                                        // 重跑 VLM：画面描述变了，需重跑 enrich 更新摘要
    else if (preset === 'asr_vlm') base = ['split']                                                // 重跑 ASR+VLM：画面描述变了，需重跑 enrich 更新摘要
    else if (preset === 'embed_only') base = ['split', 'extract_frames', 'asr', 'vlm', 'enrich']   // 仅重新入库：enrich 数据已存在，跳过
    else if (preset === 'enrich_only') base = ['split', 'extract_frames', 'asr', 'vlm']            // 重跑智能标注：标注改了必须重算 embed（与旧 /process-enrich 链式语义一致）
    else if (preset === 'multivec') base = ['split', 'extract_frames', 'asr', 'vlm', 'enrich', 'replica']  // 增量多向量化：只跑 embed，且仅补缺失子空间
    else base = ['split', 'enrich']                                                                 // 兜底：仅重跑 ASR 时跳过 enrich
    // 约束：重跑 VLM / 智能标注 / 仅 embed / 增量多向量化 时必须走 embed，否则语义检索不一致。
    if (preset === 'vlm_only' || preset === 'asr_vlm' || preset === 'embed_only' || preset === 'enrich_only' || preset === 'multivec') return base
    // 仅重跑 ASR 才允许选择是否 skip embed（高级选项）
    return syncVectorOnRecover ? base : [...base, 'embed']
  }

  const handleRecoverStart = async (preset: 'asr_only' | 'vlm_only' | 'asr_vlm' | 'embed_only' | 'enrich_only' | 'multivec') => {
    if (!selId) return
    const v = videos.find((x) => x.id === selId)
    if (!v || v.total_clips <= 0) return
    await submitProcessJob(
      () => processJobsApi.create(selId, {
        skip_steps: recoverSkipSteps(preset),
        // 增量多向量化：只补缺失子空间，已存在的子空间不重 embed，省 API 调用。
        embed_incremental: preset === 'multivec',
      }),
      '视频预处理(恢复)',
    )
  }

  const handleManualStatusFix = async (status: Video['status']) => {
    if (!selId || statusUpdating) return
    setStatusUpdating(true)
    setStatusFixMsg('')
    try {
      await videosApi.updateStatus(selId, status)
      setVideos((prev) => prev.map((v) => (v.id === selId ? { ...v, status } : v)))
      setStatusFixMsg(`状态已更新为「${{ pending: '待处理', processing: '处理中', done: '已完成', error: '错误' }[status]}」`)
    } catch {
      setStatusFixMsg('状态更新失败，请稍后重试。')
    } finally {
      setStatusUpdating(false)
    }
  }

  const fmtMs = (ms?: unknown) => {
    const n = typeof ms === 'number' ? ms : (typeof ms === 'string' ? Number(ms) : NaN)
    if (!Number.isFinite(n) || n < 0) return '-'
    if (n < 1000) return `${Math.round(n)}ms`
    return `${(n / 1000).toFixed(1)}s`
  }

  const getMetricsFromDetail = (detail: Record<string, unknown> | undefined) => {
    if (!detail || typeof detail !== 'object') return null
    const m = (detail as any).metrics
    return m && typeof m === 'object' ? m : null
  }

  const getTimingForStep = (step: StepKey, m: any) => m?.timing_ms?.[step]
  const getVlmTotalTokens = (m: any) => m?.tokens?.vlm?.total_tokens ?? 0
  const getVlmEstimatedTokens = (m: any) => m?.tokens?.vlm?.estimated_total_tokens ?? 0
  const getEmbedTotalTokens = (m: any) => m?.tokens?.embed?.total_tokens ?? 0
  const getLlmTotalTokens = (m: any) => m?.tokens?.llm?.total_tokens ?? 0

  const handleStop = async () => {
    if (!selJobId) return
    const ok = await confirm({
      title: '停止当前处理任务？',
      description: '将终止进行中的步骤；已完成切片的部分会保留，可稍后在「恢复 / 重跑」中继续。',
      confirmLabel: '停止任务',
      variant: 'danger',
    })
    if (!ok) return
    void jobsApi.cancel(selJobId).catch(() => {})
    activeJobRef.current = ''
    closeStreamQuietly()
    stopTaskPolling()
    setRunning(false)
    setDone(false)
    normalizeRunningStepsAsStopped()
    void refreshVideoMeta(selId, 'pending')
  }
  const selVideo = videos.find((v) => v.id === selId)
  const canRecover = Boolean(selId && selVideo && selVideo.total_clips > 0)
  const pct = Math.round(STEPS.filter((s) => ['done', 'skip'].includes(steps[s.key].status)).length / STEPS.length * 100)

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <header className="border-b border-slate-800 px-6 py-4 flex items-center gap-4">
        <Link href="/library" className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm transition-colors">
          <ArrowLeft className="w-4 h-4" />素材库
        </Link>
        <div className="h-4 w-px bg-slate-700" />
        <h1 className="text-lg font-semibold">素材处理</h1>
        <Link href="/" className="ml-auto text-sm text-slate-500 hover:text-slate-300 transition-colors">首页</Link>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">选择视频</h2>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {!loading && videos.length > 0 && (
                <span className="text-xs text-slate-600">
                  {search ? `${filteredVideos.length} / ${videos.length}` : videos.length} 个视频
                </span>
              )}
              {!loading && videos.length > 0 && (
                <button
                  type="button"
                  onClick={() => toggleMultiSelect(!multiSelect)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs transition-colors ${
                    multiSelect
                      ? 'border-indigo-500 bg-indigo-500/10 text-indigo-200'
                      : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                  }`}
                  title={multiSelect ? '退出多选模式' : '开启多选模式，可批量提交预处理任务'}
                >
                  {multiSelect ? <Check className="w-3.5 h-3.5" /> : <Square className="w-3.5 h-3.5" />}
                  多选
                </button>
              )}
            </div>
          </div>

          {!loading && videos.length > 0 && (
            <div className="flex items-stretch rounded-lg border border-slate-700 bg-slate-800/60 focus-within:border-indigo-500 transition-colors overflow-hidden">
              <div className="relative flex-1 min-w-0">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => handleSearch(e.target.value)}
                  placeholder="搜索视频名称..."
                  className="w-full pl-9 pr-3 py-2 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none"
                />
              </div>
              <div className="flex items-center gap-1 pr-2 border-l border-slate-700/50 shrink-0">
                <VoiceInputControl
                  intent="在素材处理页按名称筛选待处理视频：把口述整理成应填入搜索框的简短关键字。"
                  value={search}
                  onTextChange={handleSearch}
                  merge="replace"
                  className="relative"
                />
                {search ? (
                  <button
                    type="button"
                    onClick={() => handleSearch('')}
                    className="text-slate-500 hover:text-slate-300 text-xs px-1"
                  >
                    ✕
                  </button>
                ) : null}
              </div>
            </div>
          )}

          {loading ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin" />加载中...</div>
          ) : videos.length === 0 ? (
            <p className="text-slate-500 text-sm">暂无视频，请先前往<Link href="/library" className="text-indigo-400 hover:underline ml-1">素材库</Link>上传。</p>
          ) : filteredVideos.length === 0 ? (
            <p className="text-slate-500 text-sm">未找到匹配「{search}」的视频。</p>
          ) : (
            <>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {pagedVideos.map((v) => {
                  const checked = selectedIds.has(v.id)
                  return (
                    <button
                      key={v.id}
                      onClick={() => (multiSelect ? toggleSelectVideo(v.id) : setSelId(v.id))}
                      className={`text-left px-4 py-3 rounded-lg border transition-all disabled:opacity-50 disabled:cursor-not-allowed relative ${
                        (multiSelect ? checked : selId === v.id)
                          ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30'
                          : 'border-slate-700 bg-slate-800/40 hover:border-slate-500'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        {multiSelect ? (
                          <span
                            className={`mt-0.5 shrink-0 w-4 h-4 rounded border flex items-center justify-center transition-colors ${
                              checked ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-slate-600 bg-slate-900/60 text-transparent'
                            }`}
                          >
                            <Check className="w-3 h-3" />
                          </span>
                        ) : (
                          <Film className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" />
                        )}
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">{v.name}</p>
                          <p className="text-xs text-slate-500 mt-0.5">
                            {{ pending: '待处理', processing: '处理中', done: '已完成', error: '错误' }[v.status]}
                            {v.total_clips > 0 && ` · ${v.total_clips} 片段`}
                          </p>
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>

              {totalPages > 1 && (
                <div className="flex items-center justify-between pt-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />上一页
                  </button>
                  <span className="text-xs text-slate-500">{page} / {totalPages}</span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page === totalPages}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-400 hover:border-slate-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    下一页<ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {!multiSelect && (
          <section className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              data-tour="page-process-start"
              onClick={handleStart}
              disabled={!selId || starting}
              className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {starting ? <><Loader2 className="w-4 h-4 animate-spin" />提交中...</> : <><Play className="w-4 h-4" />开始处理（全流程）</>}
            </button>
            <button
              type="button"
              onClick={() => void handleStartAsrOnly()}
              disabled={!selId || starting}
              title="跳过抽帧、视觉描述与向量入库；无现成片段时会先切分再识别。适合口播剪气口。"
              className="flex items-center gap-2 px-5 py-2.5 border border-amber-600/50 bg-amber-500/10 hover:bg-amber-500/15 disabled:opacity-40 disabled:cursor-not-allowed text-amber-100 text-sm font-medium rounded-lg transition-colors"
            >
              {starting ? <Loader2 className="w-4 h-4 animate-spin text-amber-300" /> : <Mic className="w-4 h-4 text-amber-300" />}
              口播快轨（仅 ASR）
            </button>
            {selJobId && running && <button onClick={() => void handleStop()} className="px-4 py-2.5 border border-slate-700 hover:border-red-500 hover:text-red-400 text-slate-300 text-sm rounded-lg transition-colors">停止</button>}
            {selVideo && running && (
              <span className="text-sm text-amber-200/90">正在处理：<span className="text-slate-100">{selVideo!.name}</span></span>
            )}
            {selVideo && <span className="text-sm text-slate-500">已选：<span className="text-slate-300">{selVideo.name}</span></span>}
            {selVideo && (
              <span className="w-full sm:w-auto text-[11px] text-slate-500 leading-relaxed sm:ml-0 basis-full">
                全流程含抽帧与 VLM，较慢；若只依赖台词剪口播，优先用「口播快轨」。
                {selVideo.total_clips > 0
                  ? ` 当前已有 ${selVideo.total_clips} 个片段，快轨不会重切分，仅刷新 ASR。`
                  : ' 当前尚无片段，快轨会先切分再只跑语音识别。'}
              </span>
            )}
            <button
              type="button"
              onClick={() => setRecoverOpen((o) => !o)}
              disabled={!selId}
              className="flex items-center gap-1 px-3 py-2.5 border border-slate-700 bg-slate-800/40 hover:border-slate-500 disabled:opacity-40 text-slate-300 text-sm rounded-lg transition-colors"
            >
              {recoverOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              恢复 / 重跑 / 状态修改
            </button>
            <button
              onClick={() => setResultOpen(true)}
              disabled={!selId}
              className="ml-auto px-4 py-2.5 border border-slate-700 bg-slate-800/40 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 text-sm rounded-lg transition-colors"
            >
              查看处理结果/纠错
            </button>
          </section>
        )}

        {multiSelect && (
          <section className="flex flex-wrap items-center gap-3 rounded-lg border border-indigo-500/30 bg-indigo-500/5 px-5 py-4">
            <span className="text-sm text-slate-300">
              已选 <span className="text-indigo-300 font-medium">{selectedIds.size}</span> 个视频
            </span>
            <button
              type="button"
              onClick={() => void handleBatchStart('full')}
              disabled={selectedIds.size === 0 || batchSubmitting}
              className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {batchSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              批量开始处理（全流程）
            </button>
            <button
              type="button"
              onClick={() => void handleBatchStart('asr_only')}
              disabled={selectedIds.size === 0 || batchSubmitting}
              title="跳过抽帧、视觉描述与向量入库；无现成片段时会先切分再识别。适合口播剪气口。"
              className="flex items-center gap-2 px-5 py-2.5 border border-amber-600/50 bg-amber-500/10 hover:bg-amber-500/15 disabled:opacity-40 disabled:cursor-not-allowed text-amber-100 text-sm font-medium rounded-lg transition-colors"
            >
              {batchSubmitting ? <Loader2 className="w-4 h-4 animate-spin text-amber-300" /> : <Mic className="w-4 h-4 text-amber-300" />}
              批量口播快轨（仅 ASR）
            </button>
            {selectedIds.size > 0 && (
              <button
                type="button"
                onClick={() => setSelectedIds(new Set())}
                disabled={batchSubmitting}
                className="px-3 py-2.5 border border-slate-700 bg-slate-800/40 hover:border-slate-500 disabled:opacity-40 text-slate-300 text-sm rounded-lg transition-colors"
              >
                清空选择
              </button>
            )}
            <span className="w-full text-[11px] text-slate-500 leading-relaxed basis-full">
              任务将自动排队、串行执行；可在右下角任务面板查看每个任务的进度，或单独取消。
            </span>
          </section>
        )}

        {recoverOpen && !multiSelect && (
          <section className="rounded-lg border border-slate-800 bg-slate-900/40 px-5 py-4 space-y-3">
            <p className="text-xs text-slate-400">
              针对<strong className="text-slate-300">已切片的素材</strong>，跳过切分并重跑 ASR / VLM / Embed（全片段）。需在「素材库」中已有片段（total_clips &gt; 0）。
            </p>
            <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={syncVectorOnRecover}
                onChange={(e) => setSyncVectorOnRecover(e.target.checked)}
                className="rounded border-slate-600"
              />
              重跑 ASR 后同步更新向量检索（推荐；取消则 skip embed，语义检索可能仍是旧文本；VLM 重跑默认必带 embed）
            </label>
            <div className="grid gap-2 sm:grid-cols-2">
              {([
                {
                  label: '重跑 ASR + 向量（全片段）',
                  hint: '重新识别全部片段的台词文本，并同步更新检索向量',
                  preset: 'asr_only' as const,
                  hoverCls: 'hover:border-amber-600/50',
                },
                {
                  label: '重跑 VLM + 向量（全片段）',
                  hint: '重新生成全部片段的画面描述，并同步更新检索向量',
                  preset: 'vlm_only' as const,
                  hoverCls: 'hover:border-cyan-600/50',
                },
                {
                  label: '重跑 ASR + VLM + 向量（不切分）',
                  hint: '台词与画面描述一起重做，不重新切分视频',
                  preset: 'asr_vlm' as const,
                  hoverCls: 'hover:border-indigo-600/50',
                },
                {
                  label: '重跑智能标注 + 向量（全片段）',
                  hint: '用 LLM 重新生成摘要/关键词/情绪，提升检索命中率（需 LLM Key）',
                  preset: 'enrich_only' as const,
                  hoverCls: 'hover:border-indigo-500/60',
                },
                {
                  label: '重跑向量（全片段）',
                  hint: '只重建检索向量，不重跑识别；更换 Embedding 模型或密钥后使用',
                  preset: 'embed_only' as const,
                  hoverCls: 'hover:border-emerald-600/50',
                },
                {
                  label: '多维向量化（增量补齐）',
                  hint: '按台词/画面/主题拆成多路子向量提升命中率；只补缺失部分，已处理片段秒过',
                  preset: 'multivec' as const,
                  hoverCls: 'hover:border-violet-500/60',
                },
              ]).map(({ label, hint, preset, hoverCls }) => (
                <div key={preset} className="min-w-0">
                  <button
                    type="button"
                    disabled={!canRecover}
                    onClick={() => void handleRecoverStart(preset)}
                    className={`w-full text-left px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/60 text-xs text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed ${hoverCls}`}
                  >
                    {label}
                  </button>
                  <p className="mt-1 px-1 text-[11px] leading-4 text-slate-500">{hint}</p>
                </div>
              ))}
            </div>
            <div className="pt-2 border-t border-slate-800/80 space-y-2">
              <p className="text-xs text-slate-400">
                重跑后若素材状态未自动同步，可在这里手动修正：
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={!selId || statusUpdating}
                  onClick={() => void handleManualStatusFix('pending')}
                  className="px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/60 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  设为待处理
                </button>
                <button
                  type="button"
                  disabled={!selId || statusUpdating}
                  onClick={() => void handleManualStatusFix('processing')}
                  className="px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/60 text-xs text-slate-200 hover:border-amber-600/50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  设为处理中
                </button>
                <button
                  type="button"
                  disabled={!selId || statusUpdating}
                  onClick={() => void handleManualStatusFix('done')}
                  className="px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/60 text-xs text-slate-200 hover:border-emerald-600/50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  设为已完成
                </button>
                <button
                  type="button"
                  disabled={!selId || statusUpdating}
                  onClick={() => void handleManualStatusFix('error')}
                  className="px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/60 text-xs text-slate-200 hover:border-red-600/50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  设为错误
                </button>
              </div>
              {statusFixMsg && (
                <p className={`text-[11px] ${statusFixMsg.includes('失败') ? 'text-red-400/90' : 'text-emerald-400/90'}`}>
                  {statusFixMsg}
                </p>
              )}
            </div>
            {!canRecover && selId && (selVideo?.total_clips ?? 0) <= 0 && (
              <p className="text-[11px] text-amber-500/90">
                该视频尚无切片，请先「开始处理」完成切分，或使用已完成切片的素材。
              </p>
            )}
          </section>
        )}

        {(running || done || !!selJobId) && !multiSelect && (
          <section className="space-y-1.5">
            <div className="flex justify-between text-xs text-slate-400"><span>总进度</span><span>{pct}%</span></div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
            </div>
          </section>
        )}

        {!multiSelect && (
        <section className="space-y-2">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">处理步骤</h2>
          {STEPS.map((step) => {
            const st = steps[step.key]
            const splitProg = step.key === 'split' ? resolveSplitProgress(st.detail) : null
            const cur = splitProg
              ? (splitProg.showBar ? splitProg.current : undefined)
              : (st.detail.current as number | undefined)
            const tot = splitProg
              ? (splitProg.showBar ? splitProg.total : undefined)
              : (st.detail.total as number | undefined)
            const sp = cur && tot ? Math.round(cur / tot * 100) : 0
            const metrics = getMetricsFromDetail(st.detail)
            const tStep = getTimingForStep(step.key, metrics)
            const vlmTok = getVlmTotalTokens(metrics)
            const vlmEst = getVlmEstimatedTokens(metrics)
            const embTok = getEmbedTotalTokens(metrics)
            const llmTok = getLlmTotalTokens(metrics)
            let stepMetricText = `耗时: ${fmtMs(tStep)}`
            if (step.key === 'vlm') {
              stepMetricText += ` · VLM tokens: ${vlmTok}${vlmEst > 0 ? ` (估算+${vlmEst})` : ''}`
            } else if (step.key === 'enrich') {
              stepMetricText += llmTok > 0 ? ` · LLM tokens: ${llmTok}` : ' · LLM 不统计 token'
            } else if (step.key === 'embed') {
              stepMetricText += ` · Embedding tokens: ${embTok}`
            } else if (step.key === 'asr') {
              stepMetricText += ' · ASR 不统计 token'
            } else if (step.key === 'split' || step.key === 'extract_frames') {
              stepMetricText += ' · 本步骤无 token 消耗'
            }
            return (
              <div key={step.key} className={`border rounded-lg px-5 py-4 transition-all duration-300 ${cardCls(st.status)}`}>
                <div className="flex items-start gap-3">
                  <div className="pt-0.5 shrink-0"><SIcon s={st.status} /></div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                      <span className="text-sm font-medium">{step.label}</span>
                      {st.status === 'running' && splitProg?.phaseLabel && (
                        <span className="text-xs text-amber-300/90 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/25">
                          {splitProg.phaseLabel}
                        </span>
                      )}
                      {st.status === 'running' && <span className="text-xs text-amber-400/80">进行中</span>}
                      {st.status === 'done' && <span className="text-xs text-emerald-400/80">完成</span>}
                      {st.status === 'error' && <span className="text-xs text-red-400/80">失败</span>}
                    </div>
                    <p className="text-xs text-slate-500 mb-2">{step.desc}</p>
                    {step.key === 'split' && st.status === 'running' && splitProg && (splitProg.shots > 0 || splitProg.planned > 0) && (
                      <p className="text-[11px] text-slate-500 mb-2">
                        {splitProg.shots > 0 && <span>镜头 {splitProg.shots}</span>}
                        {splitProg.planned > 0 && (
                          <span>
                            {splitProg.shots > 0 ? ' · ' : ''}
                            规划 {splitProg.planned} 段
                            {splitProg.ready > 0 ? ` · 已导出 ${splitProg.ready}` : ''}
                          </span>
                        )}
                        {splitProg.planned > splitProg.shots && splitProg.shots > 0 && (
                          <span className="text-amber-400/80">（含二次切分）</span>
                        )}
                      </p>
                    )}
                    <p className="text-[11px] text-slate-500 mb-2">
                      {stepMetricText}
                    </p>
                    {st.status === 'running' && splitProg?.showIndeterminate && (
                      <div className="mb-2 h-1 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full w-1/3 bg-amber-500/80 rounded-full animate-pulse" />
                      </div>
                    )}
                    {st.status === 'running' && !(splitProg?.showIndeterminate) && cur && tot && (
                      <div className="mb-2 space-y-1">
                        <div className="flex justify-between text-xs text-slate-500"><span>{cur}/{tot}</span><span>{sp}%</span></div>
                        <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                          <div className="h-full bg-amber-500 rounded-full transition-all" style={{ width: `${sp}%` }} />
                        </div>
                      </div>
                    )}
                    {st.message && <p className="text-xs font-mono text-slate-400 bg-black/30 rounded px-2 py-1 truncate">{st.message}</p>}
                  </div>
                </div>
              </div>
            )
          })}
        </section>
        )}

        {finalMetrics && !multiSelect && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">耗时 / Token 汇总</h2>
            <div className="rounded-lg border border-slate-800 bg-slate-900/30 px-5 py-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="text-slate-400">
                  <div className="text-slate-500 mb-1">阶段耗时</div>
                  <div>切分: {fmtMs((finalMetrics as any)?.timing_ms?.split)}</div>
                  <div>抽帧: {fmtMs((finalMetrics as any)?.timing_ms?.extract_frames)}</div>
                  <div>语音识别: {fmtMs((finalMetrics as any)?.timing_ms?.asr)}</div>
                  <div>视觉理解: {fmtMs((finalMetrics as any)?.timing_ms?.vlm)}</div>
                  <div>向量化: {fmtMs((finalMetrics as any)?.timing_ms?.embed)}</div>
                  <div className="mt-1 text-slate-300">总计: {fmtMs((finalMetrics as any)?.timing_ms?.total)}</div>
                </div>
                <div className="text-slate-400">
                  <div className="text-slate-500 mb-1">Token 用量（usage 优先）</div>
                  <div>VLM 调用次数: {(finalMetrics as any)?.tokens?.vlm?.calls ?? 0}</div>
                  <div>VLM 输入 Token: {(finalMetrics as any)?.tokens?.vlm?.prompt_tokens ?? 0}</div>
                  <div>VLM 输出 Token: {(finalMetrics as any)?.tokens?.vlm?.completion_tokens ?? 0}</div>
                  <div className="text-slate-300">VLM 总 Token: {(finalMetrics as any)?.tokens?.vlm?.total_tokens ?? 0}</div>
                  {((finalMetrics as any)?.tokens?.vlm?.estimated_total_tokens ?? 0) > 0 && (
                    <div className="text-slate-500 mt-1">VLM 估算 Token（仅 usage 缺失时）: {(finalMetrics as any)?.tokens?.vlm?.estimated_total_tokens}</div>
                  )}
                  <div className="mt-2">LLM 调用次数: {(finalMetrics as any)?.tokens?.llm?.calls ?? 0}</div>
                  <div>LLM 输入 Token: {(finalMetrics as any)?.tokens?.llm?.prompt_tokens ?? 0}</div>
                  <div>LLM 输出 Token: {(finalMetrics as any)?.tokens?.llm?.completion_tokens ?? 0}</div>
                  <div className="text-slate-300">LLM 总 Token: {(finalMetrics as any)?.tokens?.llm?.total_tokens ?? 0}</div>
                  <div className="mt-2">Embedding 调用次数: {(finalMetrics as any)?.tokens?.embed?.calls ?? 0}</div>
                  <div>Embedding 输入 Token: {(finalMetrics as any)?.tokens?.embed?.prompt_tokens ?? 0}</div>
                  <div className="text-slate-300">Embedding 总 Token: {(finalMetrics as any)?.tokens?.embed?.total_tokens ?? 0}</div>
                </div>
              </div>
              {Array.isArray((finalMetrics as any)?.errors) && (finalMetrics as any).errors.length > 0 && (
                <div className="mt-3 text-[11px] text-slate-600">
                  统计异常（不影响处理）: {(finalMetrics as any).errors.join(', ')}
                </div>
              )}
            </div>
          </section>
        )}

        {done && !multiSelect && (
          <section className="border border-emerald-600/30 bg-emerald-500/5 rounded-lg px-6 py-5 flex items-center gap-4">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 shrink-0" />
            <div>
              <p className="font-semibold text-emerald-300">处理完成！</p>
              <p className="text-sm text-slate-400 mt-0.5">
                {runPreset === 'asr_only'
                  ? '已完成切分（若需要）与语音识别。若还要画面描述或素材语义检索，请使用「开始处理（全流程）」或下方恢复区补跑 VLM / 向量。'
                  : '视频已完成全部处理步骤，现在可以进行智能剪辑。'}
              </p>
            </div>
          </section>
        )}
        <div ref={endRef} />
      </div>

      <VideoResultDrawer
        open={resultOpen}
        onClose={() => setResultOpen(false)}
        videoId={selId}
        videoOptions={videos.map((v) => ({ id: v.id, name: v.name }))}
        title="素材处理结果（ASR / VLM / 预览 / 可编辑）"
      />
    </main>
  )
}