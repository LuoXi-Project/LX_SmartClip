'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  History,
  MessageSquarePlus,
  RotateCcw,
  Trash2,
  Eraser,
  X,
  Loader2,
} from 'lucide-react'
import {
  clearAgentMessages,
  deleteAgentSession,
  listAgentSessions,
  rollbackAgentSession,
  resetAgentSession,
  type SessionListItem,
} from '@/lib/agent-api'
import { applyRollbackResult } from '@/lib/studio-load-session'
import { useStudioStore } from '@/lib/studio-store'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'

type StudioSessionDrawerProps = {
  open: boolean
  onClose: () => void
  onNewSession: () => void
  onSwitchSession: (sessionId: string) => void
}

export function StudioSessionDrawer({
  open,
  onClose,
  onNewSession,
  onSwitchSession,
}: StudioSessionDrawerProps) {
  const toast = useToast()
  const confirm = useConfirm()
  const { sessionId, sessionList, setSessionList } = useStudioStore()
  const [loading, setLoading] = useState(false)

  const refreshList = useCallback(async () => {
    setLoading(true)
    try {
      const list = await listAgentSessions(50)
      setSessionList(list)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [setSessionList, toast])

  useEffect(() => {
    if (open) void refreshList()
  }, [open, refreshList])

  const handleDelete = async (item: SessionListItem) => {
    const ok = await confirm({
      title: '删除会话',
      description: `确定删除「${item.title}」？此操作不可恢复。`,
      confirmLabel: '删除',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await deleteAgentSession(item.session_id)
      toast.success('已删除')
      if (item.session_id === sessionId) onNewSession()
      await refreshList()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex">
      <button type="button" className="flex-1 bg-black/50" onClick={onClose} aria-label="关闭" />
      <aside className="w-full max-w-sm bg-[#0d0f14] border-l border-slate-800 flex flex-col shadow-2xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <div className="flex items-center gap-2 text-sm font-medium">
            <History className="w-4 h-4 text-violet-400" />
            会话历史
          </div>
          <button type="button" onClick={onClose} className="p-1 text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-3 border-b border-slate-800">
          <button
            type="button"
            onClick={() => {
              onClose()
              onNewSession()
            }}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm"
          >
            <MessageSquarePlus className="w-4 h-4" />
            新建会话
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loading ? (
            <div className="flex justify-center py-8 text-slate-500">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : sessionList.length === 0 ? (
            <p className="text-xs text-slate-500 px-2 py-4">暂无历史会话</p>
          ) : (
            sessionList.map((item) => {
              const active = item.session_id === sessionId
              return (
                <div
                  key={item.session_id}
                  className={`group rounded-lg border px-3 py-2 ${
                    active
                      ? 'border-violet-500/50 bg-violet-500/10'
                      : 'border-slate-800 hover:border-slate-600 bg-slate-900/40'
                  }`}
                >
                  <button
                    type="button"
                    className="w-full text-left"
                    onClick={() => {
                      onSwitchSession(item.session_id)
                      onClose()
                    }}
                  >
                    <div className="text-sm text-slate-200 truncate">{item.title}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5 flex gap-2">
                      <span>{item.pipeline_phase}</span>
                      <span>{item.message_count} 条消息</span>
                    </div>
                    {item.preview ? (
                      <div className="text-xs text-slate-400 mt-1 line-clamp-2">{item.preview}</div>
                    ) : null}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(item)}
                    className="mt-2 opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
                  >
                    <Trash2 className="w-3 h-3" />
                    删除
                  </button>
                </div>
              )
            })
          )}
        </div>
      </aside>
    </div>
  )
}

type StudioToolbarProps = {
  onOpenHistory: () => void
  onNewSession: () => void
}

export function StudioToolbar({ onOpenHistory, onNewSession }: StudioToolbarProps) {
  const toast = useToast()
  const confirm = useConfirm()
  const {
    sessionId,
    streaming,
    workspace,
    canRollback,
    clearMessagesLocal,
    setWorkspace,
    setMessages,
    setSelectedArtifact,
  } = useStudioStore()

  const handleClearMessages = async () => {
    if (!sessionId) return
    const ok = await confirm({
      title: '清空对话',
      description: '仅清除对话记录，保留当前方案与工作区状态。Agent 将不再看到此前聊天内容。',
      confirmLabel: '清空',
    })
    if (!ok) return
    try {
      await clearAgentMessages(sessionId)
      clearMessagesLocal()
      toast.success('对话已清空')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const handleReset = async () => {
    if (!sessionId) return
    const ok = await confirm({
      title: '重置工作区',
      description: '清空对话并重置方案/选中素材等，会话 ID 不变。适合打错了想重来。',
      confirmLabel: '重置',
      variant: 'danger',
    })
    if (!ok) return
    try {
      const res = await resetAgentSession(sessionId)
      setWorkspace(res.workspace)
      setMessages([])
      setSelectedArtifact(null)
      toast.success('工作区已重置')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const handleRollback = async () => {
    if (!sessionId) return
    if (!canRollback()) {
      toast.info('暂无可回退的内容')
      return
    }
    const ok = await confirm({
      title: '回退一步',
      description: '将撤销最近一轮对话或操作检查点，并删除之后的对话记录。',
      confirmLabel: '回退',
    })
    if (!ok) return
    try {
      const res = await rollbackAgentSession(sessionId)
      const label = await applyRollbackResult(sessionId, res, useStudioStore.getState())
      toast.success(`已回退：${label}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const btn =
    'inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-300 border border-slate-700 hover:border-slate-500 hover:text-slate-100 disabled:opacity-40'

  return (
    <div className="flex items-center gap-1 flex-wrap">
      <button type="button" className={btn} onClick={onNewSession} disabled={streaming}>
        <MessageSquarePlus className="w-3.5 h-3.5" />
        新建
      </button>
      <button type="button" className={btn} onClick={onOpenHistory}>
        <History className="w-3.5 h-3.5" />
        历史
      </button>
      <button type="button" className={btn} onClick={() => void handleClearMessages()} disabled={streaming || !sessionId}>
        <Eraser className="w-3.5 h-3.5" />
        清对话
      </button>
      <button type="button" className={btn} onClick={() => void handleRollback()} disabled={streaming || !sessionId || !canRollback()}>
        <RotateCcw className="w-3.5 h-3.5" />
        回退
      </button>
      <button type="button" className={btn} onClick={() => void handleReset()} disabled={streaming || !sessionId}>
        <Trash2 className="w-3.5 h-3.5" />
        重置
      </button>
      {workspace?.pipeline_phase ? (
        <span className="text-[10px] text-slate-600 ml-1 hidden sm:inline">
          · {workspace.pipeline_phase}
        </span>
      ) : null}
    </div>
  )
}
