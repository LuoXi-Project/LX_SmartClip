'use client'

import { create } from 'zustand'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ArtifactRef, InspectorTabId, PendingConfirm, StudioMessage, WorkspaceState } from '@/lib/agent-types'
import type { SessionListItem } from '@/lib/agent-api'

function genId() {
  return Math.random().toString(36).slice(2)
}

interface StudioStore {
  sessionId: string | null
  workspace: WorkspaceState | null
  messages: StudioMessage[]
  sessionList: SessionListItem[]
  streaming: boolean
  pendingConfirm: PendingConfirm | null
  selectedArtifact: ArtifactRef | null
  error: string | null
  lastSuggestions: string[]
  inspectorTab: InspectorTabId

  setSession: (sessionId: string, workspace: WorkspaceState) => void
  setWorkspace: (ws: WorkspaceState) => void
  setMessages: (messages: StudioMessage[]) => void
  setSessionList: (list: SessionListItem[]) => void
  addMessage: (msg: StudioMessage) => void
  updateMessage: (id: string, patch: Partial<StudioMessage>) => void
  clearMessagesLocal: () => void
  resetUiState: () => void
  setStreaming: (v: boolean) => void
  setPendingConfirm: (c: PendingConfirm | null) => void
  setSelectedArtifact: (a: ArtifactRef | null) => void
  setError: (e: string | null) => void
  setLastSuggestions: (items: string[]) => void
  setInspectorTab: (tab: InspectorTabId) => void
  getActivePlan: () => AutoEditPlanApi | null
  checkpointCount: () => number
  canRollback: () => boolean
}

export const useStudioStore = create<StudioStore>((set, get) => ({
  sessionId: null,
  workspace: null,
  messages: [],
  sessionList: [],
  streaming: false,
  pendingConfirm: null,
  selectedArtifact: null,
  error: null,
  lastSuggestions: [],
  inspectorTab: 'production',

  setSession: (sessionId, workspace) =>
    set({ sessionId, workspace, error: null, pendingConfirm: null }),
  setWorkspace: (ws) => set({ workspace: ws }),
  setMessages: (messages) => set({ messages }),
  setSessionList: (sessionList) => set({ sessionList }),
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateMessage: (id, patch) =>
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } as StudioMessage : m)),
    })),
  clearMessagesLocal: () => set({ messages: [], pendingConfirm: null }),
  resetUiState: () =>
    set({
      messages: [],
      pendingConfirm: null,
      selectedArtifact: null,
      streaming: false,
      lastSuggestions: [],
    }),
  setStreaming: (streaming) => set({ streaming }),
  setPendingConfirm: (pendingConfirm) => set({ pendingConfirm }),
  setSelectedArtifact: (selectedArtifact) => set({ selectedArtifact }),
  setError: (error) => set({ error }),
  setLastSuggestions: (lastSuggestions) => set({ lastSuggestions }),
  setInspectorTab: (inspectorTab) => set({ inspectorTab }),
  checkpointCount: () => get().workspace?.checkpoints?.length ?? 0,
  canRollback: () => {
    const { workspace, messages } = get()
    if ((workspace?.checkpoints?.length ?? 0) > 0) return true
    return messages.some((m) => m.type === 'user')
  },
  getActivePlan: () => {
    const { workspace, selectedArtifact } = get()
    if (!workspace?.plans?.length) return null
    if (selectedArtifact?.type === 'plan') {
      return (selectedArtifact.payload as unknown as AutoEditPlanApi) || null
    }
    const pid = workspace.active_plan_id
    if (pid) {
      return workspace.plans.find((p) => p.plan_id === pid) ?? workspace.plans[0]
    }
    return workspace.plans[0] ?? null
  },
}))

export { genId }
