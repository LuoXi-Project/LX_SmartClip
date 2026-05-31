import { getAgentSession, listAgentMessages } from '@/lib/agent-api'
import {
  hydrateStudioMessages,
  pickLatestExportArtifact,
  pickLatestPlanArtifact,
} from '@/lib/studio-message-hydrate'
import { writeLastStudioSessionId } from '@/lib/studio-session-persist'
import { useStudioStore } from '@/lib/studio-store'

export async function refreshStudioMessagesInStore(
  sessionId: string,
  store: ReturnType<typeof useStudioStore.getState>
) {
  const msgRes = await listAgentMessages(sessionId)
  const messages = hydrateStudioMessages(msgRes.messages || [])
  store.setMessages(messages)
  const exportArt = pickLatestExportArtifact(messages)
  const planArt = pickLatestPlanArtifact(messages)
  store.setSelectedArtifact(exportArt || planArt)
  return messages
}

export async function applyRollbackResult(
  sessionId: string,
  res: { workspace: import('@/lib/agent-types').WorkspaceState; label: string },
  store: ReturnType<typeof useStudioStore.getState>
) {
  store.setWorkspace(res.workspace)
  await refreshStudioMessagesInStore(sessionId, store)
  return res.label
}

export async function loadStudioSessionIntoStore(
  sessionId: string,
  store: ReturnType<typeof useStudioStore.getState>
) {
  const [sess, msgRes] = await Promise.all([
    getAgentSession(sessionId),
    listAgentMessages(sessionId),
  ])
  const messages = hydrateStudioMessages(msgRes.messages || [])
  store.setSession(sess.session_id, sess.workspace)
  store.setMessages(messages)
  const exportArt = pickLatestExportArtifact(messages)
  const planArt = pickLatestPlanArtifact(messages)
  store.setSelectedArtifact(exportArt || planArt)
  writeLastStudioSessionId(sessionId)
  return sess
}
