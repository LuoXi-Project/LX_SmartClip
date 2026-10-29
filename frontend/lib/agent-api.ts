import { API_BASE_URL } from '@/lib/runtime-config'
import type { WorkspaceState } from '@/lib/agent-types'
import { readSSE } from '@/lib/stream'

const base = () => (API_BASE_URL || '').replace(/\/$/, '')

export type SessionListItem = {
  session_id: string
  title: string
  pipeline_phase: string
  created_at: string
  updated_at: string
  message_count: number
  preview: string
}

export async function listAgentSessions(limit = 50): Promise<SessionListItem[]> {
  const res = await fetch(`${base()}/api/agent/sessions?limit=${limit}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return data.sessions || []
}

export async function createAgentSession(body: {
  title?: string
  video_ids?: string[]
}): Promise<{ session_id: string; workspace: WorkspaceState }> {
  const res = await fetch(`${base()}/api/agent/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function getAgentSession(
  sessionId: string
): Promise<{ session_id: string; workspace: WorkspaceState }> {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function deleteAgentSession(sessionId: string): Promise<void> {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
}

export async function patchAgentWorkspace(
  sessionId: string,
  patch: Record<string, unknown>
): Promise<{ session_id: string; workspace: WorkspaceState }> {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/workspace`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function listAgentMessages(sessionId: string, limit = 200) {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/messages?limit=${limit}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<{ messages: Array<{ id: string; role: string; content: Record<string, unknown>; created_at: string }> }>
}

export async function clearAgentMessages(sessionId: string) {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/clear-messages`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<{ ok: boolean; deleted: number }>
}

export async function resetAgentSession(sessionId: string) {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/reset`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<{ session_id: string; workspace: WorkspaceState }>
}

export async function rollbackAgentSession(sessionId: string) {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/rollback`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<{ ok: boolean; label: string; workspace: WorkspaceState }>
}

export async function rollbackAgentSessionToMessage(sessionId: string, messageId: string) {
  const res = await fetch(
    `${base()}/api/agent/sessions/${sessionId}/rollback-to/${messageId}`,
    { method: 'POST' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<{ ok: boolean; label: string; workspace: WorkspaceState }>
}

export type ChatStreamBody = {
  message: string
  resume_call_id?: string
  confirm_approved?: boolean
  /** 确认执行且勾选「本会话不再询问」时为 true：后端把工具写入 permissions.session_granted */
  grant_session?: boolean
}

export async function streamAgentChat(
  sessionId: string,
  body: ChatStreamBody,
  handlers: {
    onEvent: (event: string, data: unknown) => void
    onError: (err: Error) => void
    signal?: AbortSignal
  }
): Promise<void> {
  const res = await fetch(`${base()}/api/agent/sessions/${sessionId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: handlers.signal,
  })
  await readSSE(res, handlers, handlers.signal)
}

// ── Agent 技能包 ──────────────────────────────────────────────────────────

export interface AgentSkillItem {
  slug: string
  name: string
  description: string
  source: 'builtin' | 'user'
  body_chars: number
  has_references: boolean
  enabled: boolean
}

export const agentSkillsApi = {
  list: async (): Promise<AgentSkillItem[]> => {
    const res = await fetch(`${base()}/api/agent/skills`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.items || []
  },
  content: async (slug: string): Promise<string> => {
    const res = await fetch(`${base()}/api/agent/skills/${slug}/content`)
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    const data = await res.json()
    return data.content || ''
  },
  create: async (body: { name: string; description?: string; body: string; slug?: string }) => {
    const res = await fetch(`${base()}/api/agent/skills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json() as Promise<{ ok: boolean; slug: string; name: string }>
  },
  setEnabled: async (slug: string, enabled: boolean) => {
    const res = await fetch(`${base()}/api/agent/skills/${slug}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
  },
  remove: async (slug: string) => {
    const res = await fetch(`${base()}/api/agent/skills/${slug}`, { method: 'DELETE' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
  },
}
