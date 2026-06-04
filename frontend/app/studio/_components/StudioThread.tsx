'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import { Send, Loader2, Sparkles, RotateCcw } from 'lucide-react'
import { rollbackAgentSessionToMessage, streamAgentChat, getAgentSession } from '@/lib/agent-api'
import { genId, useStudioStore } from '@/lib/studio-store'
import type { ArtifactRef, StudioMessage } from '@/lib/agent-types'
import { ExportResultPanel } from './ExportResultPanel'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'
import { applyRollbackResult, refreshStudioMessagesInStore } from '@/lib/studio-load-session'

export function StudioThread() {
  const confirm = useConfirm()
  const toast = useToast()
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [input, setInput] = useState('')

  const {
    sessionId,
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
  } = useStudioStore()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleStream = useCallback(
    async (body: { message: string; resume_call_id?: string; confirm_approved?: boolean }) => {
      if (!sessionId) return
      setStreaming(true)
      setError(null)
      const asstId = genId()
      let asstText = ''
      addMessage({ id: asstId, type: 'assistant', content: '' })

      const ctrl = new AbortController()
      abortRef.current = ctrl

      await streamAgentChat(sessionId, body, {
        signal: ctrl.signal,
        onError: (err) => setError(err.message),
        onEvent: (event, data) => {
          const d = data as Record<string, unknown>
          if (event === 'user_message' && typeof d.id === 'string') {
            const localId = [...useStudioStore.getState().messages]
              .reverse()
              .find((m) => m.type === 'user')?.id
            if (localId) {
              updateMessage(localId, { id: d.id } as Partial<StudioMessage>)
            }
          }
          if (event === 'artifact') {
            const art = d as unknown as ArtifactRef
            setSelectedArtifact(art)
            if (art.type !== 'video' || art.id !== 'list') {
              addMessage({ id: genId(), type: 'artifact', artifact: art })
            }
          }
          if (event === 'tool_start') {
            addMessage({
              id: String(d.call_id || genId()),
              type: 'tool',
              name: String(d.name || ''),
              status: 'running',
              input: (d.input as Record<string, unknown>) || {},
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
            addMessage({
              id: genId(),
              type: 'reasoning',
              content: String(d.content),
            })
          }
          if (event === 'confirm_required') {
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
          }
        },
      })

      setStreaming(false)
      abortRef.current = null
      try {
        const [sess] = await Promise.all([
          getAgentSession(sessionId),
          refreshStudioMessagesInStore(sessionId, useStudioStore.getState()),
        ])
        setWorkspace(sess.workspace)
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
    ]
  )

  const send = async () => {
    const text = input.trim()
    if (!text || streaming || !sessionId) return
    setInput('')
    addMessage({ id: genId(), type: 'user', content: text })
    await handleStream({ message: text })
  }

  const approveConfirm = async () => {
    if (!pendingConfirm || !sessionId) return
    const ok = await confirm({
      title: '确认执行',
      description: pendingConfirm.preview || `将执行 ${pendingConfirm.tool}`,
      confirmLabel: '执行',
      cancelLabel: '取消',
    })
    if (!ok) {
      setPendingConfirm(null)
      await handleStream({
        message: '用户取消了操作',
        resume_call_id: pendingConfirm.callId,
        confirm_approved: false,
      })
      return
    }
    const callId = pendingConfirm.callId
    setPendingConfirm(null)
    await handleStream({
      message: '继续执行已确认的操作',
      resume_call_id: callId,
      confirm_approved: true,
    })
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
    <div className="flex flex-col h-full border-r border-slate-800 bg-[#0d0f14]">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-violet-400" />
        <span className="text-sm font-medium text-slate-200">对话</span>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 min-h-0">
        {messages.length === 0 && (
          <p className="text-xs text-slate-500 leading-relaxed">
            描述你的剪辑目标，例如：「用素材库最新视频做 60 秒电商口播并导出成片」
          </p>
        )}
        {messages.map((m) => (
          <MessageRow
            key={m.id}
            msg={m}
            streaming={streaming}
            onApproveConfirm={approveConfirm}
            onRollbackToMessage={rollbackToMessage}
          />
        ))}
        <div ref={bottomRef} />
      </div>
      {useStudioStore.getState().error && (
        <div className="px-4 text-xs text-red-400">{useStudioStore.getState().error}</div>
      )}
      <div className="p-3 border-t border-slate-800" data-tour="page-studio-input">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            rows={2}
            disabled={streaming}
            placeholder="输入指令…"
            className="flex-1 resize-none rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-violet-500/50"
          />
          <button
            type="button"
            onClick={send}
            disabled={streaming || !input.trim()}
            className="p-2 rounded-lg bg-violet-600 text-white disabled:opacity-40"
          >
            {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}

function MessageRow({
  msg,
  streaming,
  onApproveConfirm,
  onRollbackToMessage,
}: {
  msg: StudioMessage
  streaming: boolean
  onApproveConfirm: () => void
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
  if (msg.type === 'assistant') {
    return (
      <div className="text-sm text-slate-300 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 mr-4 whitespace-pre-wrap">
        {msg.content || '…'}
      </div>
    )
  }
  if (msg.type === 'reasoning') {
    return (
      <div className="text-xs text-slate-500 italic border-l-2 border-slate-700 pl-2 mr-6">
        {msg.content}
      </div>
    )
  }
  if (msg.type === 'tool') {
    return (
      <div className="text-xs text-slate-400 font-mono px-2">
        [{msg.status}] {msg.name}
        {msg.summary ? ` — ${msg.summary}` : ''}
      </div>
    )
  }
  if (msg.type === 'confirm') {
    return (
      <div className="text-xs border border-amber-500/40 bg-amber-500/10 rounded-lg p-3 mr-4">
        <p className="text-amber-200 mb-2">{msg.preview}</p>
        <button
          type="button"
          onClick={onApproveConfirm}
          className="px-2 py-1 rounded bg-amber-600 text-slate-900 text-xs font-medium"
        >
          确认执行 ({msg.tool})
        </button>
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
