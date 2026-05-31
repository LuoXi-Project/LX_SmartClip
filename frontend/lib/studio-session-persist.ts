export const STUDIO_LAST_SESSION_KEY = 'lx-studio-last-session-id'

export function readLastStudioSessionId(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return localStorage.getItem(STUDIO_LAST_SESSION_KEY)
  } catch {
    return null
  }
}

export function writeLastStudioSessionId(sessionId: string) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STUDIO_LAST_SESSION_KEY, sessionId)
  } catch {
    /* ignore */
  }
}

export function clearLastStudioSessionId() {
  if (typeof window === 'undefined') return
  try {
    localStorage.removeItem(STUDIO_LAST_SESSION_KEY)
  } catch {
    /* ignore */
  }
}
