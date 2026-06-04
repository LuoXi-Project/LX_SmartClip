'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Loader2, ArrowLeft } from 'lucide-react'
import { createAgentSession } from '@/lib/agent-api'
import { loadStudioSessionIntoStore } from '@/lib/studio-load-session'
import { readLastStudioSessionId } from '@/lib/studio-session-persist'
import { useStudioStore } from '@/lib/studio-store'
import { StudioThread } from './_components/StudioThread'
import { ArtifactCanvas } from './_components/ArtifactCanvas'
import { InspectorPanel } from './_components/InspectorPanel'
import { StudioSessionDrawer, StudioToolbar } from './_components/StudioSessionDrawer'

export default function StudioPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const sessionParam = searchParams.get('session')
  const { sessionId, workspace, setError, resetUiState } = useStudioStore()
  const [loading, setLoading] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(false)

  const navigateSession = useCallback(
    (id: string) => {
      router.replace(`/studio?session=${id}`)
    },
    [router]
  )

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      resetUiState()
      const targetId = sessionParam || readLastStudioSessionId()
      try {
        if (targetId) {
          await loadStudioSessionIntoStore(targetId, useStudioStore.getState())
          if (!cancelled && !sessionParam) navigateSession(targetId)
        } else {
          const res = await createAgentSession({ title: '智剪项目' })
          if (!cancelled) {
            useStudioStore.getState().setSession(res.session_id, res.workspace)
            useStudioStore.getState().setMessages([])
            navigateSession(res.session_id)
          }
        }
      } catch {
        if (cancelled) return
        try {
          const res = await createAgentSession({ title: '智剪项目' })
          useStudioStore.getState().setSession(res.session_id, res.workspace)
          useStudioStore.getState().setMessages([])
          navigateSession(res.session_id)
        } catch (e2) {
          setError((e2 as Error).message)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionParam, navigateSession, resetUiState, setError])

  const handleNewSession = async () => {
    setLoading(true)
    try {
      const res = await createAgentSession({ title: '智剪项目' })
      resetUiState()
      useStudioStore.getState().setSession(res.session_id, res.workspace)
      navigateSession(res.session_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  if (loading && !sessionId) {
    return (
      <div className="min-h-screen bg-[#0d0f14] flex items-center justify-center text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin mr-2" />
        加载工作台…
      </div>
    )
  }

  return (
    <main className="h-[calc(100dvh-3rem)] max-h-[calc(100dvh-3rem)] bg-[#0d0f14] text-slate-200 flex flex-col overflow-hidden">
      <header className="h-auto min-h-12 border-b border-slate-800 flex flex-wrap items-center px-4 py-2 gap-3 shrink-0">
        <Link href="/" className="text-slate-400 hover:text-slate-200 flex items-center gap-1 text-sm shrink-0">
          <ArrowLeft className="w-4 h-4" />
          首页
        </Link>
        <span className="text-sm font-semibold text-slate-100 truncate max-w-[200px] sm:max-w-xs">
          {workspace?.title || '智剪工作台'}
        </span>
        <StudioToolbar
          onOpenHistory={() => setHistoryOpen(true)}
          onNewSession={() => void handleNewSession()}
        />
        <Link href="/match" className="text-xs text-slate-500 hover:text-slate-300 ml-auto shrink-0">
          经典模式 →
        </Link>
      </header>
      <div className="flex-1 min-h-0 flex flex-col lg:grid lg:grid-cols-12 overflow-hidden">
        <div className="h-[min(42vh,360px)] shrink-0 min-h-0 overflow-hidden lg:h-full lg:max-h-none lg:col-span-3 relative border-b border-slate-800 lg:border-b-0">
          {loading ? (
            <div className="absolute inset-0 z-10 bg-[#0d0f14]/80 flex items-center justify-center">
              <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
            </div>
          ) : null}
          <StudioThread />
        </div>
        <div className="flex-1 min-h-0 lg:col-span-5 border-x border-slate-800 overflow-hidden">
          <ArtifactCanvas />
        </div>
        <div className="min-h-0 hidden lg:block lg:col-span-4 overflow-hidden">
          <InspectorPanel />
        </div>
      </div>
      <StudioSessionDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onNewSession={() => void handleNewSession()}
        onSwitchSession={navigateSession}
      />
    </main>
  )
}
