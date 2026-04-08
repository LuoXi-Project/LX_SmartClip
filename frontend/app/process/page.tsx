'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import apiClient, { createProcessWebSocket, videosApi, type ProcessMessage, type Video } from '@/lib/api'
import { ArrowLeft, CheckCircle2, XCircle, Loader2, SkipForward, Play, Film, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { VideoResultDrawer } from '@/app/_components/VideoResultDrawer'

const STEPS = [
  { key: 'split',          label: '视频切分',       desc: '按镜头或固定时长切分视频' },
  { key: 'extract_frames', label: '图帧提取',       desc: '抽帧后立即进入后续视觉分析' },
  { key: 'asr',            label: '语音识别',       desc: '与抽帧并行转写台词文本' },
  { key: 'vlm',            label: '视觉描述 (VLM)', desc: '按片段流水线生成画面描述' },
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

const PAGE_SIZE = 9

export default function ProcessPage() {
  const [videos, setVideos] = useState<Video[]>([])
  const [selId, setSelId] = useState('')
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [done, setDone] = useState(false)
  const [steps, setSteps] = useState<Record<StepKey, SS>>(blank)
  const [finalMetrics, setFinalMetrics] = useState<Record<string, unknown> | null>(null)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [resultOpen, setResultOpen] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    apiClient.get<unknown, { items: Video[] } | Video[]>('/api/videos')
      .then((d) => {
        if (Array.isArray(d)) setVideos(d)
        else setVideos((d as { items: Video[] })?.items || [])
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [steps])

  const filteredVideos = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? videos.filter((v) => v.name.toLowerCase().includes(q)) : videos
  }, [videos, search])

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

  const applyMsg = (msg: ProcessMessage) => {
    if (msg.step === 'done' || msg.step === 'error') return
    setSteps((p) => ({ ...p, [msg.step as StepKey]: { status: msg.status as StepStatus, message: msg.message, detail: msg.detail } }))
  }

  const handleStart = () => {
    if (!selId || running) return
    setSteps(blank())
    setRunning(true)
    setDone(false)
    setFinalMetrics(null)
    const ws = createProcessWebSocket(selId)
    wsRef.current = ws
    ws.onmessage = (e) => {
      try {
        const msg: ProcessMessage = JSON.parse(e.data)
        applyMsg(msg)
        if (msg.step === 'done') {
          setRunning(false)
          const m = (msg.detail && typeof msg.detail === 'object' && 'metrics' in msg.detail)
            ? (msg.detail as { metrics?: Record<string, unknown> }).metrics
            : null
          if (m && typeof m === 'object') setFinalMetrics(m)
          const cancelled = Boolean(msg.detail && typeof msg.detail === 'object' && 'cancelled' in msg.detail && (msg.detail as { cancelled?: boolean }).cancelled)
          if (cancelled) {
            setDone(false)
            normalizeRunningStepsAsStopped()
          } else {
            setDone(true)
            setSteps((p) => {
              const n = { ...p }
              STEPS.forEach((s) => { if (n[s.key].status === 'idle') n[s.key] = { status: 'skip', message: '已跳过', detail: {} } })
              return n
            })
          }
        }
        if (msg.step === 'error') setRunning(false)
      } catch { /* noop */ }
    }
    ws.onerror = () => setRunning(false)
    ws.onclose = () => {
      setRunning(false)
      normalizeRunningStepsAsStopped()
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

  const handleStop = () => {
    if (!selId) return
    void videosApi.processCancel(selId).catch(() => {})
    wsRef.current?.close()
    setRunning(false)
    setDone(false)
    normalizeRunningStepsAsStopped()
  }
  const selVideo = videos.find((v) => v.id === selId)
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
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">选择视频</h2>
            {!loading && videos.length > 0 && (
              <span className="text-xs text-slate-600">
                {search ? `${filteredVideos.length} / ${videos.length}` : videos.length} 个视频
              </span>
            )}
          </div>

          {!loading && videos.length > 0 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
              <input
                type="text"
                value={search}
                onChange={(e) => handleSearch(e.target.value)}
                placeholder="搜索视频名称..."
                className="w-full pl-9 pr-9 py-2 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors"
              />
              {search && (
                <button
                  onClick={() => handleSearch('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-xs"
                >
                  ✕
                </button>
              )}
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
                {pagedVideos.map((v) => (
                  <button key={v.id} disabled={running} onClick={() => !running && setSelId(v.id)}
                    className={`text-left px-4 py-3 rounded-lg border transition-all disabled:opacity-50 disabled:cursor-not-allowed ${
                      selId === v.id ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30' : 'border-slate-700 bg-slate-800/40 hover:border-slate-500'
                    }`}>
                    <div className="flex items-start gap-3">
                      <Film className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" />
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{v.name}</p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {{ pending: '待处理', processing: '处理中', done: '已完成', error: '错误' }[v.status]}
                          {v.total_clips > 0 && ` · ${v.total_clips} 片段`}
                        </p>
                      </div>
                    </div>
                  </button>
                ))}
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

        <section className="flex items-center gap-3">
          <button onClick={handleStart} disabled={!selId || running}
            className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors">
            {running ? <><Loader2 className="w-4 h-4 animate-spin" />处理中...</> : <><Play className="w-4 h-4" />开始处理</>}
          </button>
          {running && <button onClick={handleStop} className="px-4 py-2.5 border border-slate-700 hover:border-red-500 hover:text-red-400 text-slate-300 text-sm rounded-lg transition-colors">停止</button>}
          {selVideo && !running && <span className="text-sm text-slate-500">已选：<span className="text-slate-300">{selVideo.name}</span></span>}
          <button
            onClick={() => setResultOpen(true)}
            disabled={!selId}
            className="ml-auto px-4 py-2.5 border border-slate-700 bg-slate-800/40 hover:border-slate-500 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 text-sm rounded-lg transition-colors"
          >
            查看处理结果/纠错
          </button>
        </section>

        {(running || done) && (
          <section className="space-y-1.5">
            <div className="flex justify-between text-xs text-slate-400"><span>总进度</span><span>{pct}%</span></div>
            <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
            </div>
          </section>
        )}

        <section className="space-y-2">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest">处理步骤</h2>
          {STEPS.map((step) => {
            const st = steps[step.key]
            const cur = st.detail.current as number | undefined
            const tot = st.detail.total as number | undefined
            const sp = cur && tot ? Math.round(cur / tot * 100) : 0
            const metrics = getMetricsFromDetail(st.detail)
            const tStep = getTimingForStep(step.key, metrics)
            const vlmTok = getVlmTotalTokens(metrics)
            const vlmEst = getVlmEstimatedTokens(metrics)
            const embTok = getEmbedTotalTokens(metrics)
            let stepMetricText = `耗时: ${fmtMs(tStep)}`
            if (step.key === 'vlm') {
              stepMetricText += ` · VLM tokens: ${vlmTok}${vlmEst > 0 ? ` (估算+${vlmEst})` : ''}`
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
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium">{step.label}</span>
                      {st.status === 'running' && <span className="text-xs text-amber-400/80">进行中</span>}
                      {st.status === 'done' && <span className="text-xs text-emerald-400/80">完成</span>}
                      {st.status === 'error' && <span className="text-xs text-red-400/80">失败</span>}
                    </div>
                    <p className="text-xs text-slate-500 mb-2">{step.desc}</p>
                    <p className="text-[11px] text-slate-500 mb-2">
                      {stepMetricText}
                    </p>
                    {st.status === 'running' && cur && tot && (
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

        {finalMetrics && (
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

        {done && (
          <section className="border border-emerald-600/30 bg-emerald-500/5 rounded-lg px-6 py-5 flex items-center gap-4">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 shrink-0" />
            <div>
              <p className="font-semibold text-emerald-300">处理完成！</p>
              <p className="text-sm text-slate-400 mt-0.5">视频已完成全部处理步骤，现在可以进行智能剪辑。</p>
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