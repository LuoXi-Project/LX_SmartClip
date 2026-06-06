import type { ArtifactRef, PendingConfirm, PlanStepState, StudioMessage } from '@/lib/agent-types'
import { genId } from '@/lib/studio-store'

type ApiMessageRow = {
  id: string
  role: string
  content: Record<string, unknown>
  created_at: string
}

export function hydrateStudioMessages(rows: ApiMessageRow[]): StudioMessage[] {
  const out: StudioMessage[] = []
  const toolIndex = new Map<string, number>()

  for (const row of rows) {
    const c = row.content || {}
    const studioType = String(c.studio_type || '')
    const id = row.id || genId()

    if (studioType === 'user' || (!studioType && row.role === 'user')) {
      out.push({ id, type: 'user', content: String(c.text || '') })
      continue
    }
    if (studioType === 'assistant' || (!studioType && row.role === 'assistant' && c.text)) {
      out.push({ id, type: 'assistant', content: String(c.text || '') })
      continue
    }
    if (studioType === 'tool') {
      const callId = String(c.call_id || id)
      const msg: StudioMessage = {
        id: callId,
        type: 'tool',
        name: String(c.name || ''),
        status: (c.status as 'running' | 'done' | 'failed') || 'done',
        summary: String(c.summary || ''),
        input: (c.input as Record<string, unknown>) || {},
      }
      const existing = toolIndex.get(callId)
      if (existing !== undefined) {
        out[existing] = msg
      } else {
        toolIndex.set(callId, out.length)
        out.push(msg)
      }
      continue
    }
    if (studioType === 'artifact' && c.artifact) {
      out.push({
        id,
        type: 'artifact',
        artifact: c.artifact as ArtifactRef,
      })
      continue
    }
    if (studioType === 'confirm') {
      out.push({
        id,
        type: 'confirm',
        callId: String(c.call_id || id),
        tool: String(c.tool || ''),
        risk: String(c.risk || 'L2'),
        preview: String(c.preview || ''),
      })
      continue
    }
    if (studioType === 'execution_trace') {
      const rawSteps = (c.steps as Array<Record<string, unknown>>) || []
      const steps: PlanStepState[] = rawSteps.map((s) => ({
        id: String(s.id || ''),
        title: String(s.title || s.tool || '步骤'),
        tool: String(s.tool || ''),
        status: (s.status as PlanStepState['status']) || 'pending',
        message: s.message ? String(s.message) : undefined,
      }))
      out.push({
        id,
        type: 'execution_trace',
        route: c.route ? String(c.route) : undefined,
        routeReason: c.route_reason ? String(c.route_reason) : undefined,
        steps,
      })
    }
  }
  return out
}

export function pickPendingConfirmFromMessages(messages: StudioMessage[]): PendingConfirm | null {
  const last = messages[messages.length - 1]
  if (last?.type !== 'confirm') return null
  return {
    callId: last.callId,
    tool: last.tool,
    risk: last.risk,
    preview: last.preview,
  }
}

export function pickLatestExportArtifact(messages: StudioMessage[]): ArtifactRef | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i]
    if (m.type === 'artifact' && m.artifact.type === 'export') return m.artifact
  }
  return null
}

export function pickLatestPlanArtifact(messages: StudioMessage[]): ArtifactRef | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i]
    if (m.type === 'artifact' && m.artifact.type === 'plan') return m.artifact
  }
  return null
}
