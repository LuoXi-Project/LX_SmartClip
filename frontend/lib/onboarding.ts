import apiClient from '@/lib/api'

export const ONBOARDING_VERSION = 1

/** 浏览器 localStorage 回退键（不含 host/port，但 origin 仍随端口变化；主存储在后端 SQLite） */
export const ONBOARDING_LS_KEY = 'lx_smartclip_onboarding_v1'

/** 进行中的指引会话（路由切换/组件重挂载时恢复，避免从头再来） */
export const ONBOARDING_ACTIVE_SESSION_KEY = 'lx_smartclip_tour_active_v1'

export interface OnboardingActiveSession {
  stepIndex: number
  startedAt: string
}

export function saveActiveTourSession(stepIndex: number): void {
  if (typeof window === 'undefined') return
  try {
    const payload: OnboardingActiveSession = {
      stepIndex,
      startedAt: new Date().toISOString(),
    }
    window.sessionStorage.setItem(ONBOARDING_ACTIVE_SESSION_KEY, JSON.stringify(payload))
  } catch {
    // ignore
  }
}

export function readActiveTourSession(): OnboardingActiveSession | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(ONBOARDING_ACTIVE_SESSION_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as OnboardingActiveSession
    if (typeof data.stepIndex !== 'number' || data.stepIndex < 0) return null
    return data
  } catch {
    return null
  }
}

export function clearActiveTourSession(): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.removeItem(ONBOARDING_ACTIVE_SESSION_KEY)
  } catch {
    // ignore
  }
}

export type OnboardingStatus = 'pending' | 'completed' | 'skipped'

export interface OnboardingState {
  version: number
  status: OnboardingStatus
  updated_at?: string | null
}

export function shouldAutoShowOnboarding(state: OnboardingState | null): boolean {
  if (!state) return true
  return state.status === 'pending'
}

function readLocalFallback(): OnboardingState | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(ONBOARDING_LS_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as OnboardingState
    if (!data || typeof data.status !== 'string') return null
    return data
  } catch {
    return null
  }
}

function writeLocalFallback(state: OnboardingState): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(ONBOARDING_LS_KEY, JSON.stringify(state))
  } catch {
    // ignore quota / private mode
  }
}

export async function loadOnboardingState(): Promise<OnboardingState> {
  try {
    const data = await apiClient.get<unknown, OnboardingState>('/api/ui/onboarding')
    if (data?.status) {
      writeLocalFallback(data)
      return data
    }
  } catch {
    // 后端未就绪时用本地回退
  }
  return (
    readLocalFallback() ?? {
      version: ONBOARDING_VERSION,
      status: 'pending',
      updated_at: null,
    }
  )
}

export async function saveOnboardingStatus(status: OnboardingStatus): Promise<OnboardingState> {
  const next: OnboardingState = {
    version: ONBOARDING_VERSION,
    status,
    updated_at: new Date().toISOString(),
  }
  writeLocalFallback(next)
  try {
    const saved = await apiClient.put<unknown, OnboardingState>('/api/ui/onboarding', {
      status,
      version: ONBOARDING_VERSION,
    })
    writeLocalFallback(saved)
    return saved
  } catch {
    return next
  }
}

export async function resetOnboardingForReplay(): Promise<void> {
  await saveOnboardingStatus('pending')
}
