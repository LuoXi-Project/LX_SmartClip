import { API_BASE_URL } from '@/lib/runtime-config'
import type { WorkspaceState } from '@/lib/agent-types'

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
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    handlers.onError(new Error(err.detail || `HTTP ${res.status}`))
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = 'message'

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const block of parts) {
        const lines = block.split('\n')
        let eventName = currentEvent
        let dataStr = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) eventName = line.slice(7).trim()
          if (line.startsWith('data: ')) dataStr += line.slice(6)
        }
        if (!dataStr) continue
        currentEvent = eventName
        try {
          handlers.onEvent(eventName, JSON.parse(dataStr))
        } catch {
          handlers.onEvent(eventName, { raw: dataStr })
        }
      }
    }
  } catch (e) {
    if ((e as Error).name !== 'AbortError') handlers.onError(e as Error)
  }
}
