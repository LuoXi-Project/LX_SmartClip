'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  Copy,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Pencil,
  Play,
  Plus,
  Sparkles,
  Square,
  Trash2,
  Workflow as WorkflowIcon,
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
  /** 步骤名 -> 状态/消息（含引擎广播的 done 终态步骤） */
  stepStates: Record<string, { status: string; message: string }>
  status: 'running' | 'done' | 'error' | 'cancelled'
  renderUrl: string
  startedAt: number
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
  const [starting, setStarting] = useState(false)
  const [retrying, setRetrying] = useState<string | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [editingDef, setEditingDef] = useState<WorkflowDefinition | null>(null)
  const [elapsed, setElapsed] = useState(0)

  const abortRef = useRef<AbortController | null>(null)
  const toastHandleRef = useRef<ReturnType<typeof toast.task> | null>(null)

  const builtinDefs = useMemo(() => definitions.filter((d) => d.is_builtin), [definitions])
  const customDefs = useMemo(() => definitions.filter((d) => !d.is_builtin), [definitions])

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
                  ? {
                      ...prev,
                      stepStates: { ...prev.stepStates, [step]: { status, message } },
                    }
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

  /** 一键运行：收集表单 → POST → 订阅 SSE */
  const handleStart = useCallback(
    async (def: WorkflowDefinition) => {
      const values = prefValues[def.id] || {}
      // 前端先做一次必填粗检（后端仍会强校验）
      const missing = def.params.filter(
        (p) =>
          p.required &&
          (values[p.name] == null || (typeof values[p.name] === 'string' && !(values[p.name] as string).trim())),
      )
      if (missing.length) {
        toast.error(`请填写：${missing.map((p) => p.label).join('、')}`)
        return
      }
      setStarting(true)
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
        void subscribeRun(run)
        refresh()
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      } finally {
        setStarting(false)
      }
    },
    [prefValues, toast, subscribeRun, refresh],
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
        const defName =
          definitions.find((d) => d.id === original?.workflow_id)?.name || original?.workflow_name || '重跑'
        toastHandleRef.current = toast.task(`工作流：${defName}`)
        const run: ActiveRun = {
          runId: created.run_id,
          jobId: created.job_id,
          workflowId: original?.workflow_id || '',
          workflowName: defName,
          stepStates: {},
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
        refresh(false)
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      }
    },
    [toast, refresh],
  )

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="animate-spin text-cyan-400" size={28} />
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      {/* 页头 */}
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-xl font-semibold text-slate-100">
          <WorkflowIcon size={20} className="text-violet-400" />
          工作流
          <span className="rounded-md border border-violet-500/40 bg-violet-500/10 px-1.5 py-0.5 text-[11px] font-normal text-violet-300">
            后台自动执行
          </span>
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          一键调度「采集 → 预处理 → 剪辑 → 成片」等能力链，全程后台运行，可在任务中心查看子任务进度。
        </p>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}

      {/* 运行中面板 */}
      {activeRun && <ActiveRunPanel run={activeRun} elapsed={elapsed} onCancel={handleCancel} />}

      {/* 内置工作流 */}
      <Section title="内置工作流" icon={<Sparkles size={14} className="text-violet-400" />}>
        {builtinDefs.map((def) => (
          <WorkflowCard
            key={def.id}
            def={def}
            values={prefValues[def.id] || {}}
            onParam={(name, value) => setPrefParam(def.id, name, value)}
            onStart={() => handleStart(def)}
            starting={starting}
            disabled={activeRun?.status === 'running'}
            onDuplicate={() => handleDuplicate(def.id)}
          />
        ))}
      </Section>

      {/* 自定义工作流 */}
      <Section
        title={`自定义工作流${customDefs.length ? `（${customDefs.length}）` : ''}`}
        icon={<WorkflowIcon size={14} className="text-cyan-400" />}
        action={
          <button
            type="button"
            onClick={() => {
              setEditingDef(null)
              setShowEditor((v) => !v)
            }}
            className="flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 transition-colors hover:border-cyan-500/50 hover:text-cyan-200"
          >
            <Plus size={12} /> JSON 新建
          </button>
        }
      >
        {showEditor && (
          <DefinitionEditor
            editing={editingDef}
            onSaved={() => {
              setShowEditor(false)
              setEditingDef(null)
              refresh(false)
            }}
          />
        )}
        {customDefs.map((def) => (
          <WorkflowCard
            key={def.id}
            def={def}
            values={prefValues[def.id] || {}}
            onParam={(name, value) => setPrefParam(def.id, name, value)}
            onStart={() => handleStart(def)}
            starting={starting}
            disabled={activeRun?.status === 'running'}
            onEdit={() => {
              setEditingDef(def)
              setShowEditor(true)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
            onDelete={() => handleDelete(def.id)}
          />
        ))}
      </Section>

      {/* 运行历史 */}
      <Section title="运行历史" icon={<CheckCircle2 size={14} className="text-emerald-400" />}>
        <RunHistory runs={runs} onRetry={handleRetry} onCancel={handleCancel} retrying={retrying} />
      </Section>
    </main>
  )
}

function Section({
  title,
  icon,
  action,
  children,
}: {
  title: string
  icon: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="mb-7">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-medium text-slate-200">
          {icon}
          {title}
        </h2>
        {action}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  )
}

function WorkflowCard({
  def,
  values,
  onParam,
  onStart,
  starting,
  disabled,
  onDuplicate,
  onEdit,
  onDelete,
}: {
  def: WorkflowDefinition
  values: Record<string, unknown>
  onParam: (name: string, value: unknown) => void
  onStart: () => void
  starting: boolean
  disabled: boolean
  onDuplicate?: () => void
  onEdit?: () => void
  onDelete?: () => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4 transition-colors hover:border-slate-700">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium text-slate-100">{def.name}</span>
            <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400">
              {def.category}
            </span>
            {def.is_builtin ? (
              <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
                内置
              </span>
            ) : (
              <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[10px] text-cyan-300">
                自定义 v{def.version}
              </span>
            )}
          </div>
          {def.description && (
            <p className="mt-1 text-xs leading-5 text-slate-400">{def.description}</p>
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
        </div>
      </div>

      {/* 步骤链 */}
      <div className="mb-3 flex flex-wrap items-center gap-1">
        {def.steps.map((s, i) => (
          <span key={s.name} className="flex items-center gap-1">
            {i > 0 && <ChevronRight size={11} className="text-slate-600" />}
            <span className="rounded-md border border-slate-700 bg-slate-900/60 px-1.5 py-0.5 text-[11px] text-slate-300">
              {s.title}
            </span>
          </span>
        ))}
      </div>

      {open && (
        <>
          <div className="mb-3 border-t border-slate-800/70 pt-3">
            <ParamForm params={def.params} values={values} onChange={onParam} />
          </div>
          <button
            type="button"
            onClick={onStart}
            disabled={starting || disabled}
            className={clsx(
              'flex items-center gap-1.5 rounded-md border px-3.5 py-1.5 text-sm font-medium transition-colors',
              disabled
                ? 'cursor-not-allowed border-slate-800 text-slate-600'
                : 'border-cyan-500/50 bg-cyan-500/15 text-cyan-100 hover:bg-cyan-500/25',
            )}
          >
            {starting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {disabled ? '有工作流运行中…' : '一键运行'}
          </button>
        </>
      )}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-2 text-[11px] text-slate-500 transition-colors hover:text-slate-300"
      >
        {open ? '收起参数' : '展开参数'}
      </button>
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
      {runningMessage && (
        <p className="mt-2 truncate text-xs text-slate-400">{runningMessage}</p>
      )}
    </div>
  )
}
