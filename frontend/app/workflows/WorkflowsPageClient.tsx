'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  Clapperboard,
  Clock3,
  CloudDownload,
  History,
  Loader2,
  Play,
  Search,
  Settings2,
  Sparkles,
  Square,
  Store,
  Trash2,
  WandSparkles,
  Workflow as WorkflowIcon,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import {
  formatFastApiDetail,
  workflowApi,
  type WorkflowDefinition,
  type WorkflowRunSummary,
} from '@/lib/api'
import { fetchSSE } from '@/lib/stream'
import { useTaskStore } from '@/lib/task-store'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'
import { useWorkflowPrefStore } from '@/lib/workflow-store'
import { ParamForm } from './_components/ParamForm'
import { RunHistory } from './_components/RunHistory'

/** 单次运行的前端状态（SSE 驱动） */
interface ActiveRun {
  runId: string
  jobId: string
  workflowId: string
  workflowName: string
  stepStates: Record<string, { status: string; message: string }>
  status: 'running' | 'done' | 'error' | 'cancelled'
  renderUrl: string
  startedAt: number
}

function fmtRelative(iso?: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(ms)) return ''
  const min = Math.floor(ms / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

/** 分类视觉（图标 + 配色），未收录分类回退通用样式 */
const CATEGORY_META: Record<string, { icon: LucideIcon; chipCls: string; ringCls: string }> = {
  内容生产: {
    icon: Clapperboard,
    chipCls: 'border-violet-500/40 bg-violet-500/10 text-violet-300',
    ringCls: 'hover:border-violet-500/50',
  },
  智能成片: {
    icon: WandSparkles,
    chipCls: 'border-indigo-500/40 bg-indigo-500/10 text-indigo-300',
    ringCls: 'hover:border-indigo-500/50',
  },
  素材采集: {
    icon: CloudDownload,
    chipCls: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
    ringCls: 'hover:border-cyan-500/50',
  },
  通用: {
    icon: WorkflowIcon,
    chipCls: 'border-slate-600 bg-slate-800/60 text-slate-300',
    ringCls: 'hover:border-slate-500',
  },
}

function categoryMeta(category: string) {
  return CATEGORY_META[category] || CATEGORY_META['通用']
}

/** 必填参数是否已全部有值（决定卡片 CTA 是直接运行还是进配置） */
function canQuickStart(def: WorkflowDefinition, values: Record<string, unknown>): boolean {
  return def.params
    .filter((p) => p.required)
    .every((p) => {
      const v = values[p.name]
      if (v == null) return false
      if (typeof v === 'string') return v.trim().length > 0
      if (Array.isArray(v)) return v.length > 0
      return true
    })
}

export default function WorkflowsPageClient() {
  const toast = useToast()
  const confirm = useConfirm()
  const upsertTask = useTaskStore((s) => s.upsert)
  const patchTask = useTaskStore((s) => s.patch)
  const prefValues = useWorkflowPrefStore((s) => s.values)
  const setPrefParam = useWorkflowPrefStore((s) => s.setParam)

  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([])
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null)
  const [starting, setStarting] = useState<string | null>(null)
  const [retrying, setRetrying] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [paramErrors, setParamErrors] = useState<Record<string, string>>({})

  // 市场：搜索 / 分类 / 选中详情
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<WorkflowDefinition | null>(null)
  const [showHistory, setShowHistory] = useState(true)

  const abortRef = useRef<AbortController | null>(null)
  // 按 jobId 管理 task toast 句柄：并发运行多个工作流时互不覆盖
  const toastHandlesRef = useRef<Map<string, ReturnType<typeof toast.task>>>(new Map())

  const refresh = useCallback(async (withRuns = true) => {
    try {
      const defs = await workflowApi.listDefinitions()
      setDefinitions(defs.items)
      if (withRuns) {
        const rs = await workflowApi.listRuns({ limit: 30 })
        setRuns(rs.items)
      }
      setError('')
    } catch (e) {
      setError(formatFastApiDetail(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 运行中计时
  useEffect(() => {
    if (activeRun?.status !== 'running') return
    const t = setInterval(() => {
      setElapsed(Math.floor((Date.now() - activeRun.startedAt) / 1000))
    }, 1000)
    return () => clearInterval(t)
  }, [activeRun])

  // 分类目录（按数量降序）
  const categories = useMemo(() => {
    const map = new Map<string, number>()
    for (const d of definitions) map.set(d.category, (map.get(d.category) || 0) + 1)
    return [...map.entries()].sort((a, b) => b[1] - a[1])
  }, [definitions])

  // 最近使用：有运行记录的定义，按 last_run_at 倒序取前 4
  const recentDefs = useMemo(
    () =>
      definitions
        .filter((d) => d.last_run_at)
        .sort((a, b) => String(b.last_run_at).localeCompare(String(a.last_run_at)))
        .slice(0, 4),
    [definitions],
  )

  // 市场列表：搜索（名称/描述/动作/分类）+ 分类过滤
  const marketDefs = useMemo(() => {
    const q = search.trim().toLowerCase()
    return definitions.filter((d) => {
      if (category && d.category !== category) return false
      if (!q) return true
      const hay = [
        d.name, d.description, d.category,
        ...d.steps.map((s) => `${s.title} ${s.action}`),
      ].join('\n').toLowerCase()
      return hay.includes(q)
    })
  }, [definitions, search, category])

  /** 订阅工作流 job 的 SSE，驱动 activeRun 与 TaskHub */
  const subscribeRun = useCallback(
    async (run: ActiveRun) => {
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      upsertTask({
        id: run.jobId,
        title: `工作流：${run.workflowName}`,
        kind: 'workflow',
        status: 'running',
        percent: null,
        logs: [],
        elapsedSec: 0,
        createdAt: Date.now(),
        onCancel: () => {
          workflowApi.cancelRun(run.runId).catch(() => undefined)
        },
      })
      await fetchSSE(
        `/api/jobs/${run.jobId}/stream`,
        undefined,
        {
          onEvent: (event, data) => {
            const m = data as Record<string, unknown> | null
            if (!m || event === 'done') return
            if (event === 'progress') {
              const step = String(m.step || '')
              const status = String(m.status || 'running')
              const message = String(m.message || '')
              if (!step || step === 'done' || step === 'error') return
              setActiveRun((prev) =>
                prev
                  ? { ...prev, stepStates: { ...prev.stepStates, [step]: { status, message } } }
                  : prev,
              )
              patchTask(run.jobId, { stage: message })
            } else if (event === 'result') {
              const result = (m || {}) as Record<string, unknown>
              const renderUrl = String(result.render_url || '')
              setActiveRun((prev) => (prev ? { ...prev, status: 'done', renderUrl } : prev))
              patchTask(run.jobId, { status: 'done', percent: 100, result })
              const handle = toastHandlesRef.current.get(run.jobId)
              handle?.done('工作流已完成' + (renderUrl ? '，可在历史中下载成片' : ''))
              toastHandlesRef.current.delete(run.jobId)
              refresh()
            } else if (event === 'failed') {
              const cancelled = !!(m as Record<string, unknown>)?.cancelled
              const message = String((m as Record<string, unknown>)?.message || '运行失败')
              setActiveRun((prev) =>
                prev ? { ...prev, status: cancelled ? 'cancelled' : 'error' } : prev,
              )
              patchTask(run.jobId, { status: cancelled ? 'cancelled' : 'error', error: message })
              const handle = toastHandlesRef.current.get(run.jobId)
              toastHandlesRef.current.delete(run.jobId)
              if (cancelled) handle?.done('工作流已取消')
              else handle?.fail(message)
              refresh()
            }
          },
          onError: () => {
            // SSE 断开不视为运行失败：运行历史轮询兜底恢复状态
          },
        },
        ac.signal,
      ).catch(() => undefined)
    },
    [upsertTask, patchTask, refresh],
  )

  /** 使用工作流：收集表单 → POST → 订阅 SSE */
  const handleStart = useCallback(
    async (def: WorkflowDefinition) => {
      const values = prefValues[def.id] || {}
      const missing = def.params.filter(
        (p) =>
          p.required &&
          (values[p.name] == null ||
            (Array.isArray(values[p.name]) && (values[p.name] as unknown[]).length === 0) ||
            (typeof values[p.name] === 'string' && !(values[p.name] as string).trim())),
      )
      if (missing.length) {
        toast.error(`请填写必填参数：${missing.map((p) => p.label).join('、')}`)
        setParamErrors(Object.fromEntries(missing.map((p) => [p.name, '该项为必填'])))
        setSelected(def)   // 打开详情让用户补参数
        return
      }
      setStarting(def.id)
      try {
        const inputs: Record<string, unknown> = {}
        for (const p of def.params) {
          const v = values[p.name]
          inputs[p.name] = v == null ? undefined : v
        }
        const created = await workflowApi.startRun(def.id, inputs)
        toastHandlesRef.current.set(created.job_id, toast.task(`工作流：${def.name}`))
        const run: ActiveRun = {
          runId: created.run_id,
          jobId: created.job_id,
          workflowId: def.id,
          workflowName: def.name,
          stepStates: Object.fromEntries(def.steps.map((s) => [s.name, { status: 'pending', message: '' }])),
          status: 'running',
          renderUrl: '',
          startedAt: Date.now(),
        }
        setElapsed(0)
        setActiveRun(run)
        setSelected(null)
        void subscribeRun(run)
        refresh()
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      } finally {
        setStarting(null)
      }
    },
    [prefValues, toast, subscribeRun, refresh],
  )

  /** 快速重跑：用最近一次运行的参数直接再跑 */
  const handleQuickRerun = useCallback(
    async (def: WorkflowDefinition) => {
      if (!def.last_run_id) return
      setStarting(def.id)
      try {
        const created = await workflowApi.retryRun(def.last_run_id)
        toastHandlesRef.current.set(created.job_id, toast.task(`工作流：${def.name}`))
        const run: ActiveRun = {
          runId: created.run_id,
          jobId: created.job_id,
          workflowId: def.id,
          workflowName: def.name,
          stepStates: Object.fromEntries(def.steps.map((s) => [s.name, { status: 'pending', message: '' }])),
          status: 'running',
          renderUrl: '',
          startedAt: Date.now(),
        }
        setElapsed(0)
        setActiveRun(run)
        void subscribeRun(run)
        refresh()
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      } finally {
        setStarting(null)
      }
    },
    [toast, subscribeRun, refresh],
  )

  const handleCancel = useCallback(
    async (runId: string) => {
      try {
        await workflowApi.cancelRun(runId)
        abortRef.current?.abort()
        toast.success('已发送取消请求，正在终止子任务…')
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      }
    },
    [toast],
  )

  const handleRetry = useCallback(
    async (runId: string) => {
      setRetrying(runId)
      try {
        const created = await workflowApi.retryRun(runId)
        const original = runs.find((r) => r.id === created.retried_from)
        const def = definitions.find((d) => d.id === original?.workflow_id) || null
        const name = def?.name || original?.workflow_name || '重跑'
        toastHandlesRef.current.set(created.job_id, toast.task(`工作流：${name}`))
        const run: ActiveRun = {
          runId: created.run_id,
          jobId: created.job_id,
          workflowId: def?.id || '',
          workflowName: name,
          stepStates: def
            ? Object.fromEntries(def.steps.map((s) => [s.name, { status: 'pending', message: '' }]))
            : {},
          status: 'running',
          renderUrl: '',
          startedAt: Date.now(),
        }
        setElapsed(0)
        setActiveRun(run)
        void subscribeRun(run)
        refresh()
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      } finally {
        setRetrying(null)
      }
    },
    [runs, definitions, toast, subscribeRun, refresh],
  )

  const handleDelete = useCallback(
    async (def: WorkflowDefinition) => {
      const ok = await confirm({
        title: '删除该工作流？',
        description: `「${def.name}」将被永久删除，且不可恢复；其历史运行记录不受影响。`,
        confirmLabel: '删除',
        variant: 'danger',
      })
      if (!ok) return
      try {
        await workflowApi.deleteDefinition(def.id)
        toast.success('已删除该工作流')
        if (selected?.id === def.id) setSelected(null)
        refresh(false)
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      }
    },
    [confirm, toast, refresh, selected],
  )

  // 页面加载时恢复仍在运行的运行记录（刷新/切页回来续看进度）
  useEffect(() => {
    const running = runs.find((r) => r.status === 'running' || r.status === 'pending')
    if (running && !activeRun && running.job_id) {
      const restored: ActiveRun = {
        runId: running.id,
        jobId: running.job_id,
        workflowId: running.workflow_id,
        workflowName: running.workflow_name || running.workflow_id,
        stepStates: Object.fromEntries(
          Object.entries(running.steps || {}).map(([k, v]) => [k, { status: v || 'pending', message: '' }]),
        ),
        status: 'running',
        renderUrl: '',
        startedAt: new Date(running.created_at).getTime() || Date.now(),
      }
      setActiveRun(restored)
      void subscribeRun(restored)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, activeRun === null, subscribeRun])

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="animate-spin text-cyan-400" size={28} />
      </main>
    )
  }

  const builtinCount = definitions.filter((d) => d.is_builtin).length

  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      {/* 页头 */}
      <div className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-violet-500/30 bg-gradient-to-br from-violet-500/25 to-indigo-500/10">
              <WorkflowIcon size={22} className="text-violet-300" />
            </div>
            <div>
              <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold text-slate-100">
                工作流
                <span className="rounded-md border border-violet-500/40 bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-normal text-violet-300">
                  后台自动执行
                </span>
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                选一个工作流，填好参数一键出片；全程后台执行，可离开页面，任务中心看进度。
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className={clsx(
              'flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs transition-colors',
              showHistory
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                : 'border-slate-700 text-slate-300 hover:border-slate-500 hover:text-slate-100',
            )}
          >
            <History size={12} /> 运行历史
          </button>
        </div>

        {/* 搜索 + 分类筛选 */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索工作流：名称 / 描述 / 分类 / 步骤动作…"
              className="w-full rounded-md border border-slate-700 bg-slate-900/70 py-1.5 pl-8 pr-3 text-sm text-slate-100 placeholder:text-slate-600 focus:border-cyan-500/60 focus:outline-none"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <CategoryChip label="全部" active={category === ''} count={definitions.length} onClick={() => setCategory('')} />
            {categories.map(([cat, n]) => (
              <CategoryChip
                key={cat}
                label={cat}
                active={category === cat}
                count={n}
                onClick={() => setCategory(category === cat ? '' : cat)}
              />
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          <span className="min-w-0 break-all">{error}</span>
          <button
            type="button"
            onClick={() => refresh()}
            className="shrink-0 rounded-md border border-rose-500/50 px-2.5 py-1 text-xs text-rose-200 transition-colors hover:bg-rose-500/20"
          >
            重试
          </button>
        </div>
      )}

      {/* 运行中面板 */}
      {activeRun && (
        <ActiveRunPanel
          run={activeRun}
          elapsed={elapsed}
          stepTitles={stepTitleMap(definitions, activeRun.workflowId)}
          onCancel={handleCancel}
        />
      )}

      {/* 最近使用 */}
      {recentDefs.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-200">
            <Clock3 size={14} className="text-amber-400" />
            最近使用
          </h2>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {recentDefs.map((def) => (
              <RecentCard
                key={def.id}
                def={def}
                busy={starting === def.id}
                onOpen={() => setSelected(def)}
                onQuickRerun={() => handleQuickRerun(def)}
              />
            ))}
          </div>
        </section>
      )}

      {/* 工作流市场 */}
      <section className="mb-8">
        <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-200">
          <Store size={14} className="text-cyan-400" />
          工作流市场
          <span className="text-xs font-normal text-slate-500">
            共 {definitions.length} 个 · 内置 {builtinCount}
          </span>
        </h2>
        {marketDefs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-800 p-8 text-center">
            <p className="text-sm text-slate-500">
              没有匹配的工作流{search ? `（搜索「${search}」无结果）` : ''}
            </p>
            {(search || category) && (
              <button
                type="button"
                onClick={() => {
                  setSearch('')
                  setCategory('')
                }}
                className="mt-2 text-xs text-cyan-300 transition-colors hover:text-cyan-200"
              >
                清除筛选条件
              </button>
            )}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {marketDefs.map((def) => (
              <MarketCard
                key={def.id}
                def={def}
                quickStartable={canQuickStart(def, prefValues[def.id] || {})}
                busy={starting === def.id}
                onOpen={() => setSelected(def)}
                onStart={() => handleStart(def)}
              />
            ))}
          </div>
        )}
      </section>

      {/* 运行历史 */}
      {showHistory && (
        <section className="mb-7">
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-200">
            <History size={14} className="text-emerald-400" />
            运行历史
          </h2>
          <RunHistory runs={runs} onRetry={handleRetry} onCancel={handleCancel} retrying={retrying} />
        </section>
      )}

      {/* 工作流详情（选中后使用） */}
      {selected && (
        <WorkflowDetailModal
          def={selected}
          values={prefValues[selected.id] || {}}
          errors={paramErrors}
          onParam={(name, value) => {
            setPrefParam(selected.id, name, value)
            if (paramErrors[name]) {
              setParamErrors((prev) => {
                const next = { ...prev }
                delete next[name]
                return next
              })
            }
          }}
          onStart={() => handleStart(selected)}
          starting={starting === selected.id}
          onClose={() => setSelected(null)}
          onDelete={!selected.is_builtin ? () => handleDelete(selected) : undefined}
        />
      )}
    </main>
  )
}

/** 步骤名 → 显示标题映射（运行面板用；找不到定义时回退步骤名） */
function stepTitleMap(
  definitions: WorkflowDefinition[],
  workflowId: string,
): Record<string, string> {
  const def = definitions.find((d) => d.id === workflowId)
  if (!def) return {}
  return Object.fromEntries(def.steps.map((s) => [s.name, s.title]))
}

// ── 分类筛选 chip ─────────────────────────────────────────────────────────

function CategoryChip({
  label,
  active,
  count,
  onClick,
}: {
  label: string
  active: boolean
  count: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'rounded-md border px-2 py-1 text-xs transition-colors',
        active
          ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
          : 'border-slate-700 bg-slate-900/50 text-slate-400 hover:border-slate-600 hover:text-slate-200',
      )}
    >
      {label}
      <span className="ml-1 text-[10px] text-slate-500">{count}</span>
    </button>
  )
}

// ── 最近使用卡片 ──────────────────────────────────────────────────────────

const RUN_STATUS_CLS: Record<string, string> = {
  done: 'text-emerald-400',
  error: 'text-rose-400',
  cancelled: 'text-amber-400',
  running: 'text-cyan-400',
  pending: 'text-slate-400',
}

function RecentCard({
  def,
  busy,
  onOpen,
  onQuickRerun,
}: {
  def: WorkflowDefinition
  busy: boolean
  onOpen: () => void
  onQuickRerun: () => void
}) {
  const meta = categoryMeta(def.category)
  const CatIcon = meta.icon
  return (
    <div className="group flex items-center gap-2.5 rounded-lg border border-amber-500/25 bg-gradient-to-r from-amber-500/[0.07] to-transparent p-3 transition-colors hover:border-amber-500/40">
      <span className={clsx('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border', meta.chipCls)}>
        <CatIcon size={15} />
      </span>
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-slate-100">{def.name}</span>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-500">
          {fmtRelative(def.last_run_at)}运行 ·{' '}
          <span className={RUN_STATUS_CLS[def.last_run_status || ''] || 'text-slate-500'}>
            {def.last_run_status === 'done'
              ? '成功'
              : def.last_run_status === 'error'
                ? '失败'
                : def.last_run_status === 'cancelled'
                  ? '已取消'
                  : def.last_run_status || ''}
          </span>
          {' · '}累计 {def.run_count || 0} 次
        </p>
      </button>
      <button
        type="button"
        onClick={onQuickRerun}
        disabled={busy || !def.last_run_id}
        title="用上次参数一键重跑"
        className="flex shrink-0 items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-200 transition-colors hover:bg-amber-500/20 disabled:opacity-40"
      >
        {busy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        再跑
      </button>
    </div>
  )
}

// ── 市场卡片 ──────────────────────────────────────────────────────────────

function MarketCard({
  def,
  quickStartable,
  busy,
  onOpen,
  onStart,
}: {
  def: WorkflowDefinition
  quickStartable: boolean
  busy: boolean
  onOpen: () => void
  onStart: () => void
}) {
  const meta = categoryMeta(def.category)
  const CatIcon = meta.icon
  return (
    <div
      className={clsx(
        'flex flex-col rounded-xl border bg-slate-900/50 p-4 transition-all',
        def.is_builtin
          ? 'border-violet-500/20 hover:border-violet-500/50 hover:shadow-lg hover:shadow-violet-500/5'
          : clsx('border-slate-800', meta.ringCls),
      )}
    >
      <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="flex items-start gap-2.5">
          <span className={clsx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border', meta.chipCls)}>
            <CatIcon size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="truncate text-sm font-medium text-slate-100">{def.name}</span>
              {def.is_builtin ? (
                <span className="inline-flex shrink-0 items-center gap-0.5 rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
                  <Sparkles size={8} />
                  内置
                </span>
              ) : (
                <span className="shrink-0 rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[10px] text-cyan-300">
                  自定义
                </span>
              )}
            </div>
            <span className="mt-0.5 block text-[10px] text-slate-500">{def.category}</span>
          </div>
        </div>
        {def.description && (
          <p className="mt-2.5 line-clamp-2 text-xs leading-5 text-slate-400">{def.description}</p>
        )}
        {/* 步骤链（编号） */}
        <div className="mt-3 flex flex-wrap items-center gap-x-1 gap-y-1">
          {def.steps.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1">
              {i > 0 && <span className="mx-0.5 h-px w-2 bg-slate-700" />}
              <span className="flex items-center gap-1 rounded-md border border-slate-700/80 bg-slate-950/60 px-1.5 py-0.5 text-[11px] text-slate-300">
                <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-slate-800 text-[9px] font-medium text-slate-400">
                  {i + 1}
                </span>
                {s.title}
              </span>
            </span>
          ))}
        </div>
      </button>
      {/* 底部：统计 + 快捷运行 */}
      <div className="mt-3.5 flex items-center justify-between gap-2 border-t border-slate-800/80 pt-3">
        <span className="min-w-0 truncate text-[11px] text-slate-500">
          {def.last_run_at
            ? `最近 ${fmtRelative(def.last_run_at)} · 累计 ${def.run_count} 次`
            : '尚未使用'}
        </span>
        <button
          type="button"
          onClick={onStart}
          disabled={busy}
          className={clsx(
            'flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors disabled:opacity-50',
            quickStartable
              ? 'border-violet-500/50 bg-violet-500/15 text-violet-100 hover:bg-violet-500/25'
              : 'border-slate-700 bg-slate-900 text-slate-300 hover:border-slate-500 hover:text-slate-100',
          )}
        >
          {busy ? (
            <Loader2 size={12} className="animate-spin" />
          ) : quickStartable ? (
            <Play size={12} />
          ) : (
            <Settings2 size={12} />
          )}
          {quickStartable ? '一键运行' : '配置参数'}
        </button>
      </div>
    </div>
  )
}

// ── 详情弹层（选中后使用） ────────────────────────────────────────────────

function WorkflowDetailModal({
  def,
  values,
  errors,
  onParam,
  onStart,
  starting,
  onClose,
  onDelete,
}: {
  def: WorkflowDefinition
  values: Record<string, unknown>
  errors?: Record<string, string>
  onParam: (name: string, value: unknown) => void
  onStart: () => void
  starting: boolean
  onClose: () => void
  onDelete?: () => void
}) {
  // Esc 关闭弹层；有更高层的确认弹窗打开时把 Esc 留给它，避免一次 Esc 连关两层
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (document.querySelector('[data-confirm-open]')) return
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const meta = categoryMeta(def.category)
  const CatIcon = meta.icon

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center sm:p-6"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="max-h-[88vh] w-full max-w-xl overflow-y-auto rounded-t-xl border border-slate-700 bg-slate-900 shadow-2xl sm:rounded-xl">
        {/* 头部 */}
        <div className="sticky top-0 z-10 border-b border-slate-800 bg-slate-900/95 px-5 py-3.5 backdrop-blur">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-start gap-2.5">
              <span className={clsx('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border', meta.chipCls)}>
                <CatIcon size={16} />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <h3 className="text-base font-semibold text-slate-100">{def.name}</h3>
                  {def.is_builtin && (
                    <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
                      内置
                    </span>
                  )}
                  <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
                    {def.category}
                  </span>
                </div>
                {def.description && (
                  <p className="mt-1 text-xs leading-5 text-slate-400">{def.description}</p>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {onDelete && (
                <IconBtn title="删除该工作流" onClick={onDelete} danger>
                  <Trash2 size={13} />
                </IconBtn>
              )}
              <IconBtn title="关闭" onClick={onClose}>
                <X size={14} />
              </IconBtn>
            </div>
          </div>
        </div>

        <div className="px-5 py-4">
          {/* 步骤时间线 */}
          <div className="mb-4 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
            <ol>
              {def.steps.map((s, i) => (
                <li key={s.name} className="flex gap-2.5">
                  <div className="flex flex-col items-center">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-slate-700 bg-slate-900 text-[10px] font-medium text-slate-400">
                      {i + 1}
                    </span>
                    {i < def.steps.length - 1 && <span className="w-px flex-1 bg-slate-800" />}
                  </div>
                  <div className={clsx('min-w-0 pb-2.5', i === def.steps.length - 1 && 'pb-0')}>
                    <p className="text-xs font-medium text-slate-200">{s.title}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-slate-600">{s.action}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {/* 参数表单 */}
          <ParamForm params={def.params} values={values} errors={errors} onChange={onParam} />

          <div className="mt-5 flex items-center justify-between gap-2 border-t border-slate-800 pt-4">
            <span className="text-[11px] text-slate-500">
              {def.last_run_at ? `最近使用 ${fmtRelative(def.last_run_at)} · 累计 ${def.run_count} 次` : '尚未使用过'}
            </span>
            <button
              type="button"
              onClick={onStart}
              disabled={starting}
              className="flex items-center gap-1.5 rounded-md border border-violet-500/50 bg-gradient-to-r from-violet-500/25 to-indigo-500/20 px-5 py-2 text-sm font-medium text-violet-100 transition-colors hover:from-violet-500/35 hover:to-indigo-500/30 disabled:opacity-50"
            >
              {starting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              一键运行
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function IconBtn({
  title,
  onClick,
  danger,
  children,
}: {
  title: string
  onClick: () => void
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={clsx(
        'rounded-md border border-slate-700/70 p-1.5 text-slate-400 transition-colors',
        danger
          ? 'hover:border-rose-500/60 hover:text-rose-300'
          : 'hover:border-slate-500 hover:text-slate-200',
      )}
    >
      {children}
    </button>
  )
}

// ── 运行中面板（步骤进度条）───────────────────────────────────────────────

const STEP_STATUS_META: Record<string, { dotCls: string; textCls: string }> = {
  done: { dotCls: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300', textCls: 'text-emerald-200' },
  running: { dotCls: 'border-cyan-400/70 bg-cyan-500/15 text-cyan-200', textCls: 'text-cyan-100' },
  error: { dotCls: 'border-rose-500/60 bg-rose-500/15 text-rose-300', textCls: 'text-rose-200' },
  skip: { dotCls: 'border-slate-700 bg-slate-900 text-slate-600', textCls: 'text-slate-600' },
  pending: { dotCls: 'border-slate-700 bg-slate-900 text-slate-500', textCls: 'text-slate-500' },
}

function ActiveRunPanel({
  run,
  elapsed,
  stepTitles,
  onCancel,
}: {
  run: ActiveRun
  elapsed: number
  stepTitles: Record<string, string>
  onCancel: (runId: string) => void
}) {
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
  const ss = String(elapsed % 60).padStart(2, '0')
  const steps = Object.entries(run.stepStates)
  const runningMessage = Object.values(run.stepStates).find((s) => s.status === 'running')?.message
  const doneCount = steps.filter(([, s]) => s.status === 'done').length

  return (
    <div
      className={clsx(
        'mb-7 rounded-xl border p-4',
        run.status === 'running'
          ? 'border-cyan-500/30 bg-cyan-500/[0.04]'
          : run.status === 'done'
            ? 'border-emerald-500/30 bg-emerald-500/[0.04]'
            : run.status === 'cancelled'
              ? 'border-amber-500/30 bg-amber-500/[0.04]'
              : 'border-rose-500/30 bg-rose-500/[0.04]',
      )}
    >
      {/* 头部 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-100">
          {run.status === 'running' ? (
            <Loader2 size={15} className="animate-spin text-cyan-400" />
          ) : run.status === 'done' ? (
            <CheckCircle2 size={15} className="text-emerald-400" />
          ) : (
            <XCircle size={15} className={run.status === 'cancelled' ? 'text-amber-400' : 'text-rose-400'} />
          )}
          {run.workflowName}
          <span className="font-mono text-xs text-slate-400">
            {mm}:{ss}
          </span>
          {run.status === 'running' && steps.length > 0 && (
            <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-px text-[11px] text-cyan-300">
              {doneCount}/{steps.length} 步 · 后台运行中，可离开本页
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {run.status === 'running' ? (
            <button
              type="button"
              onClick={() => onCancel(run.runId)}
              className="flex items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200 transition-colors hover:bg-amber-500/20"
            >
              <Square size={11} /> 取消（含子任务）
            </button>
          ) : (
            run.renderUrl && (
              <a
                href={run.renderUrl}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-emerald-500/50 bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-200 transition-colors hover:bg-emerald-500/25"
              >
                下载成片
              </a>
            )
          )}
        </div>
      </div>

      {/* 步骤进度 */}
      {steps.length > 0 && (
        <div className="flex items-start overflow-x-auto pb-1">
          {steps.map(([name, s], i) => {
            const meta = STEP_STATUS_META[s.status] || STEP_STATUS_META.pending
            return (
              <div key={name} className="flex min-w-0 flex-1 items-start last:flex-none">
                <div className="flex min-w-[72px] flex-col items-center gap-1">
                  <span
                    title={s.message || undefined}
                    className={clsx(
                      'flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-medium',
                      meta.dotCls,
                    )}
                  >
                    {s.status === 'done' ? (
                      <CheckCircle2 size={12} />
                    ) : s.status === 'running' ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : s.status === 'error' ? (
                      <XCircle size={12} />
                    ) : s.status === 'skip' ? (
                      <span className="text-[9px]">跳过</span>
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className={clsx('max-w-[96px] truncate text-center text-[10px]', meta.textCls)}>
                    {stepTitles[name] || name}
                  </span>
                </div>
                {i < steps.length - 1 && (
                  <span
                    className={clsx(
                      'mt-3 h-px flex-1',
                      s.status === 'done' ? 'bg-emerald-500/40' : 'bg-slate-800',
                    )}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
      {runningMessage && (
        <p className="mt-3 truncate rounded-md bg-slate-950/60 px-2.5 py-1.5 text-xs text-slate-400">
          {runningMessage}
        </p>
      )}
    </div>
  )
}
