'use client'

import { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import Link from 'next/link'
import clsx from 'clsx'
import { Send, Loader2, Sparkles, RotateCcw, Square, ShieldAlert, Zap, Unlock } from 'lucide-react'
import { rollbackAgentSessionToMessage, streamAgentChat, getAgentSession, patchAgentWorkspace } from '@/lib/agent-api'
import { genId, useStudioStore } from '@/lib/studio-store'
import type { ArtifactRef, PlanStepState, StudioMessage, AgentPermissionMode } from '@/lib/agent-types'
import { ExportResultPanel } from './ExportResultPanel'
import { StudioExportGuide } from './StudioExportGuide'
import {
  ReasoningBlock,
  StudioExecutionTrace,
  ToolCallBlock,
  parseMcpTool,
} from './StudioExecutionTrace'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'
import { applyRollbackResult, refreshStudioMessagesInStore } from '@/lib/studio-load-session'
import { idleReasonMessage, isExportLikeMessage } from '@/lib/studio-action-intent'
import { mergeSuggestionChips } from '@/lib/studio-phase-suggestions'
import { StudioPanelHeaderAction } from './StudioPanelHeaderAction'

function mergeWorkspacePatch(
  ws: ReturnType<typeof useStudioStore.getState>['workspace'],
  patch: Record<string, unknown>
) {
  if (!ws) return ws
  const jobs = { ...(ws.jobs || {}), ...((patch.jobs as object) || {}) }
  const prefs = { ...(ws.user_preferences || {}), ...((patch.user_preferences as object) || {}) }
  const permissions = {
    mode: 'ask' as AgentPermissionMode,
    ...(ws.permissions || {}),
    ...((patch.permissions as object) || {}),
  }
  return {
    ...ws,
    ...patch,
    jobs,
    user_preferences: prefs,
    permissions,
    selected_video_ids: (patch.selected_video_ids as string[]) ?? ws.selected_video_ids,
    plans: (patch.plans as typeof ws.plans) ?? ws.plans,
    pipeline_phase: (patch.pipeline_phase as typeof ws.pipeline_phase) ?? ws.pipeline_phase,
    active_plan_id:
      patch.active_plan_id !== undefined
        ? (patch.active_plan_id as string | null)
        : ws.active_plan_id,
  }
}

// ── 执行权限三档（对齐 AI IDE 的 approval mode）────────────────────────────

const PERMISSION_MODES: {
  id: AgentPermissionMode
  label: string
  icon: typeof Zap
  hint: string
}[] = [
  { id: 'ask', label: '每次询问', icon: ShieldAlert, hint: '长任务 / 成片 / 导出每次确认后再执行（默认）' },
  { id: 'auto', label: '自动审核', icon: Zap, hint: '长任务与成片自动执行；外部 MCP 工具仍需确认' },
  { id: 'full', label: '完全访问', icon: Unlock, hint: '全部自动执行不再询问（不可逆操作除外）' },
]

function PermissionModeSwitch({
  mode,
  grantedCount,
  disabled,
  onSelect,
}: {
  mode: AgentPermissionMode
  grantedCount: number
  disabled?: boolean
  onSelect: (mode: AgentPermissionMode) => void
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900/80 p-0.5">
        {PERMISSION_MODES.map((m) => {
          const Icon = m.icon
          const active = mode === m.id
          return (
            <button
              key={m.id}
              type="button"
              disabled={disabled}
              title={m.hint}
              onClick={() => onSelect(m.id)}
              className={clsx(
                'flex items-center gap-1 rounded-md px-2 py-1 text-[11px] transition-colors disabled:opacity-40',
                active
                  ? m.id === 'ask'
                    ? 'bg-amber-500/20 text-amber-200'
                    : m.id === 'auto'
                      ? 'bg-cyan-500/20 text-cyan-200'
                      : 'bg-rose-500/20 text-rose-200'
                  : 'text-slate-500 hover:text-slate-200',
              )}
            >
              <Icon size={11} />
              {m.label}
            </button>
          )
        })}
      </div>
      {grantedCount > 0 && mode === 'ask' && (
        <span className="text-[10px] text-slate-500">本会话已免确认 {grantedCount} 个工具</span>
      )}
    </div>
  )
}

export function StudioThread() {
  const confirm = useConfirm()
  const toast = useToast()
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const pendingUserMsgIdRef = useRef<string | null>(null)
  const [input, setInput] = useState('')
  const error = useStudioStore((s) => s.error)

  const {
    sessionId,
    workspace,
    messages,
    streaming,
    pendingConfirm,
    setStreaming,
    setError,
    addMessage,
    updateMessage,
    setWorkspace,
    setPendingConfirm,
    setSelectedArtifact,
    lastSuggestions,
    setLastSuggestions,
  } = useStudioStore()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setError(null)
  }, [setStreaming, setError])

  const suggestionItems = useMemo(
    () => mergeSuggestionChips(lastSuggestions, workspace),
    [lastSuggestions, workspace]
  )

  const handleStream = useCallback(
    async (body: {
      message: string
      resume_call_id?: string
      confirm_approved?: boolean
      grant_session?: boolean
    }) => {
      if (!sessionId) return
      setStreaming(true)
      setError(null)
      const asstId = genId()
      const traceId = genId()
      const reasoningId = genId()
      let asstText = ''
      let reasoningText = ''
      let hadToolStart = false
      let hadConfirm = false
      let traceAdded = false
      let reasoningAdded = false
      const userIntentExport = isExportLikeMessage(body.message)
      addMessage({ id: asstId, type: 'assistant', content: '' })

      const ensureTrace = () => {
        if (!traceAdded) {
          addMessage({ id: traceId, type: 'execution_trace', steps: [] })
          traceAdded = true
        }
      }

      const ctrl = new AbortController()
      abortRef.current = ctrl

      await streamAgentChat(sessionId, body, {
        signal: ctrl.signal,
        onError: (err) => {
          const msg = err.message || '请求失败'
          setError(msg)
          toast.error(msg)
        },
        onEvent: (event, data) => {
          const d = data as Record<string, unknown>
          if (event === 'error') {
            const msg = String(d.detail || d.message || '服务端错误')
            setError(msg)
            toast.error(msg)
          }
          if (event === 'user_message' && typeof d.id === 'string') {
            const localId = pendingUserMsgIdRef.current
            if (localId) {
              updateMessage(localId, { id: d.id } as Partial<StudioMessage>)
              pendingUserMsgIdRef.current = null
            }
          }
          if (event === 'route') {
            ensureTrace()
            updateMessage(traceId, {
              type: 'execution_trace',
              route: String(d.route || ''),
              routeReason: String(d.reason || ''),
            } as Partial<StudioMessage>)
          }
          if (event === 'plan_steps') {
            ensureTrace()
            const rawSteps = (d.steps as Array<Record<string, unknown>>) || []
            const steps: PlanStepState[] = rawSteps.map((s) => ({
              id: String(s.id || genId()),
              title: String(s.title || s.tool || '步骤'),
              tool: String(s.tool || ''),
              status: 'pending',
            }))
            updateMessage(traceId, { type: 'execution_trace', steps } as Partial<StudioMessage>)
          }
          if (event === 'plan_step_update') {
            ensureTrace()
            const stepId = String(d.step_id || '')
            const cur = useStudioStore.getState().messages.find((m) => m.id === traceId)
            if (cur?.type === 'execution_trace') {
              const steps = cur.steps.map((s) =>
                s.id === stepId
                  ? {
                      ...s,
                      status: (d.status as PlanStepState['status']) || s.status,
                      message: String(d.message || s.message || ''),
                      title: String(d.title || s.title),
                      tool: String(d.tool || s.tool),
                    }
                  : s
              )
              updateMessage(traceId, { type: 'execution_trace', steps } as Partial<StudioMessage>)
            }
          }
          if (event === 'progress') {
            ensureTrace()
            updateMessage(traceId, {
              type: 'execution_trace',
              progress: {
                jobId: String(d.job_id || ''),
                message: String(d.message || ''),
                percent: typeof d.percent === 'number' ? d.percent : undefined,
                status: String(d.status || ''),
              },
            } as Partial<StudioMessage>)
          }
          if (event === 'workspace_patch' && d.patch && typeof d.patch === 'object') {
            const ws = useStudioStore.getState().workspace
            if (ws) {
              const merged = mergeWorkspacePatch(ws, d.patch as Record<string, unknown>)
              if (merged) setWorkspace(merged)
            }
          }
          if (event === 'artifact') {
            const art = d as unknown as ArtifactRef
            setSelectedArtifact(art)
            if (art.type !== 'video' || art.id !== 'list') {
              addMessage({ id: genId(), type: 'artifact', artifact: art })
            }
          }
          if (event === 'suggestions') {
            const items = (d.items as string[]) || []
            if (items.length) setLastSuggestions(items)
          }
          if (event === 'tool_start') {
            hadToolStart = true
            addMessage({
              id: String(d.call_id || genId()),
              type: 'tool',
              name: String(d.name || ''),
              status: 'running',
              input: (d.input as Record<string, unknown>) || {},
              round: typeof d.round === 'number' ? d.round : undefined,
            })
          }
          if (event === 'tool_end') {
            const cid = String(d.call_id || '')
            updateMessage(cid, {
              type: 'tool',
              status: (d.ok as boolean) ? 'done' : 'failed',
              summary: String(d.summary || d.error || ''),
            } as Partial<StudioMessage>)
            const art = (d as { artifact?: ArtifactRef }).artifact
            if (art?.type === 'export') {
              setSelectedArtifact(art)
            }
          }
          if (event === 'message_delta' && typeof d.content === 'string') {
            asstText += d.content
            updateMessage(asstId, { type: 'assistant', content: asstText })
          }
          if (event === 'reasoning_delta' && typeof d.content === 'string') {
            reasoningText += d.content
            if (!reasoningAdded) {
              addMessage({ id: reasoningId, type: 'reasoning', content: reasoningText })
              reasoningAdded = true
            } else {
              updateMessage(reasoningId, { type: 'reasoning', content: reasoningText })
            }
          }
          if (event === 'confirm_required') {
            hadConfirm = true
            setPendingConfirm({
              callId: String(d.call_id),
              tool: String(d.tool),
              risk: String(d.risk),
              preview: String(d.preview || ''),
            })
            addMessage({
              id: genId(),
              type: 'confirm',
              callId: String(d.call_id),
              tool: String(d.tool),
              risk: String(d.risk),
              preview: String(d.preview || ''),
            })
          }
          if (event === 'done') {
            if (d.pending_confirm) return
            if (!asstText.trim() && traceAdded) {
              updateMessage(asstId, { type: 'assistant', content: '' })
            }
            const idleMsg = idleReasonMessage(d)
            if (idleMsg) {
              setError(idleMsg)
              toast.error(idleMsg)
            } else if (userIntentExport && !hadToolStart && !hadConfirm) {
              const hint =
                '导出指令未触发成片任务。请确认已有方案，或点击中间方案区的「一键成片」；也可再说「导出成片」。'
              setError(hint)
              toast.error(hint)
            }
          }
        },
      })

      setStreaming(false)
      abortRef.current = null
      try {
        const sess = await getAgentSession(sessionId)
        setWorkspace(sess.workspace)
        const after = useStudioStore.getState()
        if (!after.pendingConfirm && !hadConfirm) {
          await refreshStudioMessagesInStore(sessionId, after)
        }
      } catch {
        /* ignore */
      }
    },
    [
      sessionId,
      setStreaming,
      setError,
      addMessage,
      updateMessage,
      setWorkspace,
      setPendingConfirm,
      setSelectedArtifact,
      setLastSuggestions,
      toast,
    ]
  )

  const quickSend = useCallback(
    async (text: string) => {
      if (!sessionId || streaming) return
      setInput('')
      const userId = genId()
      pendingUserMsgIdRef.current = userId
      addMessage({ id: userId, type: 'user', content: text })
      await handleStream({ message: text })
    },
    [sessionId, streaming, setInput, addMessage, handleStream]
  )

  const send = async () => {
    const text = input.trim()
    if (!text || streaming || !sessionId) return
    setInput('')
    const userId = genId()
    pendingUserMsgIdRef.current = userId
    addMessage({ id: userId, type: 'user', content: text })
    await handleStream({ message: text })
  }

  const approveConfirm = async (grantSession: boolean) => {
    if (!pendingConfirm || !sessionId) return
    const callId = pendingConfirm.callId
    const toolName = pendingConfirm.tool
    setPendingConfirm(null)
    if (grantSession) {
      toast.success(`本会话内「${toolName}」不再逐次确认`)
    }
    await handleStream({
      message: '继续执行已确认的操作',
      resume_call_id: callId,
      confirm_approved: true,
      grant_session: grantSession,
    })
  }

  const rejectConfirm = async () => {
    if (!pendingConfirm || !sessionId) return
    const callId = pendingConfirm.callId
    setPendingConfirm(null)
    await handleStream({
      message: '用户取消了操作',
      resume_call_id: callId,
      confirm_approved: false,
    })
  }

  const permissionMode: AgentPermissionMode = workspace?.permissions?.mode ?? 'ask'
  const grantedToolCount = workspace?.permissions?.session_granted?.length ?? 0
  const [switchingPerm, setSwitchingPerm] = useState(false)

  const handlePermissionSelect = async (next: AgentPermissionMode) => {
    if (!sessionId || switchingPerm || next === permissionMode) return
    if (next === 'full') {
      const ok = await confirm({
        title: '切换到「完全访问」？',
        description:
          'Agent 执行长任务、渲染成片、导出与外部工具时将不再逐次询问，直接自动执行（仅不可逆操作仍会确认）。',
        confirmLabel: '开启完全访问',
        variant: 'danger',
      })
      if (!ok) return
    }
    setSwitchingPerm(true)
    try {
      const res = await patchAgentWorkspace(sessionId, {
        permissions: {
          mode: next,
          session_granted: workspace?.permissions?.session_granted ?? [],
        },
      })
      setWorkspace(res.workspace)
      toast.success(`执行权限：${PERMISSION_MODES.find((m) => m.id === next)?.label ?? next}`)
    } catch {
      toast.error('权限档位切换失败，请重试')
    } finally {
      setSwitchingPerm(false)
    }
  }

  const rollbackToMessage = async (messageId: string, preview: string) => {
    if (!sessionId || streaming) return
    const ok = await confirm({
      title: '回退到此',
      description: `将删除此消息及之后的全部对话，并恢复对应的工作区状态。\n\n「${preview.slice(0, 60)}${preview.length > 60 ? '…' : ''}」`,
      confirmLabel: '回退',
    })
    if (!ok) return
    try {
      const res = await rollbackAgentSessionToMessage(sessionId, messageId)
      const label = await applyRollbackResult(sessionId, res, useStudioStore.getState())
      toast.success(`已回退：${label}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-[#0d0f14]">
      <div className="shrink-0 px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-violet-400" />
        <span className="text-sm font-medium text-slate-200">对话</span>
        {streaming ? (
          <span className="flex items-center gap-1.5 text-[10px] text-violet-300">
            <Loader2 className="w-3 h-3 animate-spin" />
            Agent 执行中…
          </span>
        ) : null}
        {permissionMode === 'full' ? (
          <span
            title="Agent 执行不再逐次询问，仅不可逆操作除外"
            className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[10px] text-rose-300"
          >
            完全访问
          </span>
        ) : permissionMode === 'auto' ? (
          <span
            title="长任务与成片自动执行，外部工具仍需确认"
            className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] text-cyan-300"
          >
            自动审核
          </span>
        ) : null}
        <StudioPanelHeaderAction panelId="thread" />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto styled-scrollbar overscroll-contain px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="space-y-3 mr-2">
            <p className="text-xs text-slate-400 leading-relaxed">
              先说明素材与诉求（口播 / 原声 / 时长），生成方案后再选导出方式。不同方案听感差别很大，生成前建议想清楚。
            </p>
            <p className="text-[11px] text-slate-500">
              对话依赖设置中的 LLM 配置；若报错可点下方提示或前往
              <Link href="/settings" className="mx-1 text-violet-300 hover:text-violet-200 underline underline-offset-2">设置</Link>
              查看「配置就绪状态」。
            </p>
            <StudioExportGuide variant="overview" compact />
            <p className="text-[11px] text-slate-500">
              示例：「用选中素材做 60 秒电商口播方案」→ 方案生成后 →「导出成片（配音版）」
            </p>
            {!streaming && suggestionItems.length > 0 ? (
              <SuggestionChips items={suggestionItems} disabled={false} onPick={(t) => void quickSend(t)} />
            ) : null}
          </div>
        )}
        {messages.map((m, idx) => (
          <MessageRow
            key={m.id}
            msg={m}
            streaming={streaming}
            pendingConfirm={pendingConfirm}
            isLastAssistant={
              streaming && m.type === 'assistant' && idx === messages.length - 1
            }
            onApproveConfirm={approveConfirm}
            onRejectConfirm={rejectConfirm}
            onRollbackToMessage={rollbackToMessage}
          />
        ))}
        {suggestionItems.length > 0 && !streaming && (
          <SuggestionChips items={suggestionItems} disabled={streaming} onPick={(t) => void quickSend(t)} />
        )}
        <div ref={bottomRef} />
      </div>
      {error ? (
        <div className="shrink-0 px-4 pb-2 text-xs text-red-400/95 bg-red-500/10 border border-red-500/20 rounded-lg mx-3 py-2 flex items-start justify-between gap-2">
          <span className="min-w-0 break-words">{error}</span>
          <Link
            href="/settings"
            className="shrink-0 text-red-300 hover:text-red-200 underline underline-offset-2"
            title="对话依赖 LLM 等配置，到设置页检查配置就绪状态"
          >
            去设置检查 →
          </Link>
        </div>
      ) : null}
      <div className="shrink-0 p-3 border-t border-slate-800" data-tour="page-studio-input">
        <div className="mb-2 flex items-center justify-between gap-2">
          <PermissionModeSwitch
            mode={permissionMode}
            grantedCount={grantedToolCount}
            disabled={streaming || switchingPerm}
            onSelect={(m) => void handlePermissionSelect(m)}
          />
        </div>
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (!streaming) send()
              }
            }}
            rows={2}
            disabled={streaming}
            placeholder={streaming ? 'Agent 正在执行，可点停止…' : '输入指令…'}
            className="flex-1 resize-none rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-violet-500/50 disabled:opacity-60"
          />
          {streaming ? (
            <button
              type="button"
              onClick={stopStreaming}
              title="停止"
              className="p-2 rounded-lg bg-red-600/90 hover:bg-red-500 text-white"
            >
              <Square className="w-4 h-4 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              disabled={!input.trim()}
              className="p-2 rounded-lg bg-violet-600 text-white disabled:opacity-40"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageRow({
  msg,
  streaming,
  pendingConfirm,
  isLastAssistant,
  onApproveConfirm,
  onRejectConfirm,
  onRollbackToMessage,
}: {
  msg: StudioMessage
  streaming: boolean
  pendingConfirm: ReturnType<typeof useStudioStore.getState>['pendingConfirm']
  isLastAssistant?: boolean
  onApproveConfirm: (grantSession: boolean) => void
  onRejectConfirm: () => void
  onRollbackToMessage: (messageId: string, preview: string) => void
}) {
  if (msg.type === 'user') {
    return (
      <div className="group relative ml-4">
        <div className="text-sm text-slate-100 bg-blue-600/20 border border-blue-500/30 rounded-lg px-3 py-2 pr-10">
          {msg.content}
        </div>
        <button
          type="button"
          title="回退到此"
          disabled={streaming}
          onClick={() => void onRollbackToMessage(msg.id, msg.content)}
          className="absolute top-1.5 right-1.5 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] text-slate-400 border border-transparent opacity-0 group-hover:opacity-100 hover:text-slate-100 hover:border-slate-600 hover:bg-slate-800/80 disabled:opacity-30 transition-opacity"
        >
          <RotateCcw className="w-3 h-3" />
          回退
        </button>
      </div>
    )
  }
  if (msg.type === 'execution_trace') {
    return <StudioExecutionTrace msg={msg} />
  }
  if (msg.type === 'assistant') {
    if (!msg.content?.trim() && !isLastAssistant) return null
    return (
      <div className="text-sm text-slate-300 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 mr-4 whitespace-pre-wrap">
        {msg.content}
        {isLastAssistant && streaming ? (
          <span className="inline-block w-1.5 h-4 ml-0.5 bg-violet-400 animate-pulse align-middle" />
        ) : null}
      </div>
    )
  }
  if (msg.type === 'reasoning') {
    return <ReasoningBlock content={msg.content} streaming={streaming} />
  }
  if (msg.type === 'tool') {
    return <ToolCallBlock msg={msg} />
  }
  if (msg.type === 'confirm') {
    const isActive = pendingConfirm?.callId === msg.callId && !streaming
    const mcp = parseMcpTool(msg.tool)
    const toolLabel = mcp ? mcp.tool : msg.tool
    return (
      <div className="text-sm border border-amber-500/50 bg-amber-500/15 rounded-lg p-3 mr-4 space-y-2">
        <p className="text-amber-100 font-medium">
          需要你的确认
          {mcp && (
            <span
              title={`外部 MCP 服务：${mcp.serverId}`}
              className="ml-2 rounded border border-cyan-500/50 bg-cyan-500/15 px-1 py-px align-middle font-mono text-[10px] font-normal text-cyan-200"
            >
              MCP·{mcp.serverId}
            </span>
          )}
        </p>
        <p className="text-amber-200/90 text-xs leading-relaxed">{msg.preview}</p>
        {isActive ? (
          <div className="flex flex-wrap items-center gap-2 pt-0.5">
            <button
              type="button"
              onClick={onRejectConfirm}
              className="px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:text-slate-100 text-xs transition-colors"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => onApproveConfirm(false)}
              className="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-900 text-xs font-semibold"
            >
              执行 · {toolLabel}
            </button>
            <button
              type="button"
              onClick={() => onApproveConfirm(true)}
              title="授权后本会话内该工具不再逐次确认"
              className="px-3 py-1.5 rounded-lg border border-amber-500/60 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20 text-xs transition-colors"
            >
              本会话不再询问
            </button>
          </div>
        ) : (
          <p className="text-[10px] text-slate-500">已处理或已过期</p>
        )}
      </div>
    )
  }
  if (msg.type === 'artifact') {
    if (msg.artifact.type === 'export') {
      return (
        <div className="mr-2">
          <ExportResultPanel artifact={msg.artifact} compact />
        </div>
      )
    }
    return (
      <div className="text-xs text-violet-300 px-2">
        产物 · {msg.artifact.type} / {msg.artifact.id}
      </div>
    )
  }
  return null
}

function SuggestionChips({
  items,
  disabled,
  onPick,
}: {
  items: string[]
  disabled: boolean
  onPick: (text: string) => void
}) {
  const unique = [...new Set(items.map((s) => s.trim()).filter(Boolean))]
  if (!unique.length) return null
  return (
    <div className="flex flex-col gap-1.5 mr-4">
      <p className="text-[10px] text-slate-500 px-1">快捷操作</p>
      {unique.map((label) => (
        <button
          key={label}
          type="button"
          disabled={disabled}
          onClick={() => onPick(label)}
          className="text-left text-sm text-slate-200 bg-slate-800/80 border border-slate-600 hover:border-violet-500/50 rounded-lg px-3 py-2 disabled:opacity-40 transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  )
}
