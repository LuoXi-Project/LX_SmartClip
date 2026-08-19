'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  CheckCircle2,
  ChevronRight,
  Clock3,
  Copy,
  History,
  Loader2,
  Pencil,
  Play,
  Plus,
  Search,
  Sparkles,
  Square,
  Store,
  Trash2,
  Workflow as WorkflowIcon,
  X,
  XCircle,
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
import { useWorkflowPrefStore } from '@/lib/workflow-store'
import { ParamForm } from './_components/ParamForm'
import { DefinitionEditor } from './_components/DefinitionEditor'
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

export default function WorkflowsPageClient() {
  const toast = useToast()
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

  // 市场：搜索 / 分类 / 选中详情 / 管理编辑器
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [selected, setSelected] = useState<WorkflowDefinition | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [editingDef, setEditingDef] = useState<WorkflowDefinition | null>(null)
  const [showHistory, setShowHistory] = useState(true)

  const abortRef = useRef<AbortController | null>(null)
  const toastHandleRef = useRef<ReturnType<typeof toast.task> | null>(null)

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
              toastHandleRef.current?.done('工作流已完成' + (renderUrl ? '，可在历史中下载成片' : ''))
              refresh()
            } else if (event === 'failed') {
              const cancelled = !!(m as Record<string, unknown>)?.cancelled
              const message = String((m as Record<string, unknown>)?.message || '运行失败')
              setActiveRun((prev) =>
                prev ? { ...prev, status: cancelled ? 'cancelled' : 'error' } : prev,
              )
              patchTask(run.jobId, { status: cancelled ? 'cancelled' : 'error', error: message })
              if (cancelled) toastHandleRef.current?.done('工作流已取消')
              else toastHandleRef.current?.fail(message)
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
          (values[p.name] == null || (typeof values[p.name] === 'string' && !(values[p.name] as string).trim())),
      )
      if (missing.length) {
        toast.error(`请填写：${missing.map((p) => p.label).join('、')}`)
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
        toastHandleRef.current = toast.task(`工作流：${def.name}`)
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
        toastHandleRef.current = toast.task(`工作流：${def.name}`)
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
        toastHandleRef.current = toast.task(`工作流：${name}`)
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

  const handleDuplicate = useCallback(
    async (id: string) => {
      try {
        await workflowApi.duplicateDefinition(id)
        toast.success('已复制为自定义工作流')
        refresh(false)
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      }
    },
    [toast, refresh],
  )

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await workflowApi.deleteDefinition(id)
        toast.success('已删除自定义工作流')
        if (selected?.id === id) setSelected(null)
        refresh(false)
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      }
    },
    [toast, refresh, selected],
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

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {/* 页头 + 搜索 */}
      <div className="mb-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-100">
              <WorkflowIcon size={20} className="text-violet-400" />
              工作流
              <span className="rounded-md border border-violet-500/40 bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-normal text-violet-300">
                后台自动执行
              </span>
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              从市场选择工作流一键运行；全程后台执行，可在任务中心查看子任务进度。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setEditingDef(null)
                setShowEditor((v) => !v)
              }}
              className="flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 transition-colors hover:border-cyan-500/50 hover:text-cyan-200"
            >
              <Plus size={12} /> 自定义工作流
            </button>
            <button
              type="button"
              onClick={() => setShowHistory((v) => !v)}
              className="flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-slate-100"
            >
              <History size={12} /> 运行历史
            </button>
          </div>
        </div>

        {/* 搜索 + 分类筛选 */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
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
        <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* 运行中面板 */}
      {activeRun && <ActiveRunPanel run={activeRun} elapsed={elapsed} onCancel={handleCancel} />}

      {/* 最近使用 */}
      {recentDefs.length > 0 && (
        <section className="mb-7">
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-200">
            <Clock3 size={14} className="text-amber-400" />
            最近使用
          </h2>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {recentDefs.map((def) => (
              <RecentCard
                key={def.id}
                def={def}
                busy={starting === def.id || activeRun?.status === 'running'}
                onOpen={() => setSelected(def)}
                onQuickRerun={() => handleQuickRerun(def)}
              />
            ))}
          </div>
        </section>
      )}

      {/* 工作流市场 */}
      <section className="mb-7">
        <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-slate-200">
          <Store size={14} className="text-cyan-400" />
          工作流市场
          <span className="text-xs font-normal text-slate-500">
            {marketDefs.length}/{definitions.length}
          </span>
        </h2>
        {showEditor && (
          <div className="mb-3">
            <DefinitionEditor
              editing={editingDef}
              onSaved={() => {
                setShowEditor(false)
                setEditingDef(null)
                refresh(false)
              }}
            />
          </div>
        )}
        {marketDefs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-800 p-6 text-center text-sm text-slate-500">
            没有匹配的工作流{search ? `（搜索「${search}」无结果）` : ''}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {marketDefs.map((def) => (
              <MarketCard
                key={def.id}
                def={def}
                onOpen={() => setSelected(def)}
                onEdit={() => {
                  setEditingDef(def)
                  setShowEditor(true)
                  window.scrollTo({ top: 0, behavior: 'smooth' })
                }}
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
          onParam={(name, value) => setPrefParam(selected.id, name, value)}
          onStart={() => handleStart(selected)}
          starting={starting === selected.id}
          onClose={() => setSelected(null)}
          onDuplicate={selected.is_builtin ? () => handleDuplicate(selected.id) : undefined}
          onEdit={
            !selected.is_builtin
              ? () => {
                  setEditingDef(selected)
                  setShowEditor(true)
                  setSelected(null)
                  window.scrollTo({ top: 0, behavior: 'smooth' })
                }
              : undefined
          }
          onDelete={!selected.is_builtin ? () => handleDelete(selected.id) : undefined}
        />
      )}
    </main>
  )
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
  return (
    <div className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 transition-colors hover:border-amber-500/40">
      <div className="flex items-start justify-between gap-2">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-slate-100">{def.name}</span>
            <span className="shrink-0 rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
              {def.category}
            </span>
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
          className="flex shrink-0 items-center gap-1 rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-1 text-xs text-amber-200 transition-colors hover:bg-amber-500/20 disabled:opacity-40"
        >
          {busy ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
          再跑
        </button>
      </div>
    </div>
  )
}

// ── 市场卡片 ──────────────────────────────────────────────────────────────

function MarketCard({
  def,
  onOpen,
  onEdit,
}: {
  def: WorkflowDefinition
  onOpen: () => void
  onEdit: () => void
}) {
  return (
    <div className="group relative rounded-lg border border-slate-800 bg-slate-900/50 p-4 transition-colors hover:border-cyan-500/40">
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-sm font-medium text-slate-100">{def.name}</span>
          {def.is_builtin ? (
            <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
              内置
            </span>
          ) : (
            <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[10px] text-cyan-300">
              自定义 v{def.version}
            </span>
          )}
          <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
            {def.category}
          </span>
        </div>
        {def.description && (
          <p className="line-clamp-2 text-xs leading-5 text-slate-400">{def.description}</p>
        )}
        {/* 步骤链 */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1">
          {def.steps.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1">
              {i > 0 && <ChevronRight size={11} className="text-slate-600" />}
              <span className="rounded-md border border-slate-700 bg-slate-900/60 px-1.5 py-0.5 text-[11px] text-slate-300">
                {s.title}
              </span>
            </span>
          ))}
        </div>
        <div className="mt-2.5 flex items-center gap-3 text-[11px] text-slate-500">
          {def.last_run_at ? (
            <span>
              最近使用 {fmtRelative(def.last_run_at)} · 累计 {def.run_count} 次
            </span>
          ) : (
            <span>尚未使用</span>
          )}
        </div>
      </button>
      {!def.is_builtin && (
        <button
          type="button"
          onClick={onEdit}
          title="编辑 JSON"
          className="absolute right-3 top-3 rounded-md border border-slate-700/70 p-1 text-slate-500 opacity-0 transition-all hover:border-slate-500 hover:text-slate-200 group-hover:opacity-100"
        >
          <Pencil size={12} />
        </button>
      )}
    </div>
  )
}

// ── 详情弹层（选中后使用） ────────────────────────────────────────────────

function WorkflowDetailModal({
  def,
  values,
  onParam,
  onStart,
  starting,
  onClose,
  onDuplicate,
  onEdit,
  onDelete,
}: {
  def: WorkflowDefinition
  values: Record<string, unknown>
  onParam: (name: string, value: unknown) => void
  onStart: () => void
  starting: boolean
  onClose: () => void
  onDuplicate?: () => void
  onEdit?: () => void
  onDelete?: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center sm:p-6">
      <div className="max-h-[88vh] w-full max-w-xl overflow-y-auto rounded-t-xl border border-slate-700 bg-slate-900 p-5 shadow-2xl sm:rounded-xl">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <h3 className="text-base font-semibold text-slate-100">{def.name}</h3>
              {def.is_builtin ? (
                <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
                  <Sparkles size={9} className="mr-0.5 inline" />
                  内置
                </span>
              ) : (
                <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[10px] text-cyan-300">
                  自定义 v{def.version}
                </span>
              )}
              <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
                {def.category}
              </span>
            </div>
            {def.description && (
              <p className="mt-1.5 text-xs leading-5 text-slate-400">{def.description}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {onDuplicate && (
              <IconBtn title="复制为自定义" onClick={onDuplicate}>
                <Copy size={13} />
              </IconBtn>
            )}
            {onEdit && (
              <IconBtn title="编辑 JSON" onClick={onEdit}>
                <Pencil size={13} />
              </IconBtn>
            )}
            {onDelete && (
              <IconBtn title="删除" onClick={onDelete} danger>
                <Trash2 size={13} />
              </IconBtn>
            )}
            <IconBtn title="关闭" onClick={onClose}>
              <X size={14} />
            </IconBtn>
          </div>
        </div>

        {/* 步骤链 */}
        <div className="mb-4 flex flex-wrap items-center gap-1 rounded-lg border border-slate-800 bg-slate-950/50 p-2.5">
          {def.steps.map((s, i) => (
            <span key={s.name} className="flex items-center gap-1">
              {i > 0 && <ChevronRight size={11} className="text-slate-600" />}
              <span className="rounded-md border border-slate-700 bg-slate-900/60 px-1.5 py-0.5 text-[11px] text-slate-300">
                {s.title}
              </span>
            </span>
          ))}
        </div>

        <div className="border-t border-slate-800 pt-4">
          <ParamForm params={def.params} values={values} onChange={onParam} />
        </div>

        <div className="mt-5 flex items-center justify-between gap-2">
          <span className="text-[11px] text-slate-500">
            {def.last_run_at ? `最近使用 ${fmtRelative(def.last_run_at)} · 累计 ${def.run_count} 次` : '尚未使用过'}
          </span>
          <button
            type="button"
            onClick={onStart}
            disabled={starting}
            className="flex items-center gap-1.5 rounded-md border border-cyan-500/50 bg-cyan-500/15 px-4 py-2 text-sm font-medium text-cyan-100 transition-colors hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {starting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            一键运行
          </button>
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

function ActiveRunPanel({
  run,
  elapsed,
  onCancel,
}: {
  run: ActiveRun
  elapsed: number
  onCancel: (runId: string) => void
}) {
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0')
  const ss = String(elapsed % 60).padStart(2, '0')
  const runningMessage = Object.values(run.stepStates).find((s) => s.status === 'running')?.message

  return (
    <div className="mb-6 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-cyan-100">
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
          {run.status === 'running' && (
            <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-px text-[11px] text-cyan-300">
              后台运行中，可离开本页
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

      {/* 步骤状态 */}
      <div className="flex flex-wrap items-center gap-1.5">
        {Object.entries(run.stepStates).map(([name, s]) => (
          <span
            key={name}
            title={s.message}
            className={clsx(
              'flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px]',
              s.status === 'done'
                ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                : s.status === 'running'
                  ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
                  : s.status === 'error'
                    ? 'border-rose-500/50 bg-rose-500/10 text-rose-300'
                    : s.status === 'skip'
                      ? 'border-slate-700 text-slate-500'
                      : 'border-slate-700 text-slate-500',
            )}
          >
            {s.status === 'done' ? (
              <CheckCircle2 size={10} />
            ) : s.status === 'running' ? (
              <Loader2 size={10} className="animate-spin" />
            ) : s.status === 'error' ? (
              <XCircle size={10} />
            ) : null}
            {name}
          </span>
        ))}
      </div>
      {runningMessage && <p className="mt-2 truncate text-xs text-slate-400">{runningMessage}</p>}
    </div>
  )
}
