'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import {
  dispatchOnboardingPrepare,
  ONBOARDING_TOUR_STEPS,
  waitForTourTarget,
  type OnboardingTourStep,
} from '@/lib/onboarding-tour'
import {
  clearActiveTourSession,
  loadOnboardingState,
  readActiveTourSession,
  saveActiveTourSession,
  saveOnboardingStatus,
  shouldAutoShowOnboarding,
  type OnboardingStatus,
} from '@/lib/onboarding'
import { TourSpotlight } from './TourSpotlight'

export const ONBOARDING_REOPEN_EVENT = 'lx-smartclip-onboarding-open'

const STEPS = ONBOARDING_TOUR_STEPS

function persistStatus(status: OnboardingStatus) {
  void saveOnboardingStatus(status)
}

function isOnRoute(pathname: string | null, step: OnboardingTourStep): boolean {
  if (!step.routePrefix) return true
  return !!pathname?.startsWith(step.routePrefix)
}

async function prepareStep(step: OnboardingTourStep, pathname: string | null) {
  if (step.prepare === 'mobile-nav') {
    dispatchOnboardingPrepare({ openMobileNav: true, anchor: step.anchor })
    await new Promise((r) => window.setTimeout(r, 280))
  }
  if (step.scrollToId && step.routePrefix && pathname?.startsWith(step.routePrefix)) {
    await new Promise((r) => window.setTimeout(r, 120))
    document.getElementById(step.scrollToId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    await new Promise((r) => window.setTimeout(r, 350))
  }
}

export function OnboardingGuide() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [stepIndex, setStepIndex] = useState(0)
  const [hydrated, setHydrated] = useState(false)
  const [targetMissing, setTargetMissing] = useState(false)
  const [layoutKey, setLayoutKey] = useState(0)
  const setupGenRef = useRef(0)

  const step = STEPS[stepIndex]
  const onRoute = step ? isOnRoute(pathname, step) : true

  const openWizard = useCallback((fromStep = 0) => {
    setStepIndex(fromStep)
    setOpen(true)
    saveActiveTourSession(fromStep)
  }, [])

  const resolveAnchor = useCallback(async (s: OnboardingTourStep, timeoutMs: number) => {
    if (!s.anchor) {
      setTargetMissing(false)
      return
    }
    const el = await waitForTourTarget(s.anchor, { timeoutMs })
    setTargetMissing(!el)
    if (el) setLayoutKey((k) => k + 1)
  }, [])

  const runStepSetup = useCallback(
    async (index: number, path: string | null) => {
      const gen = ++setupGenRef.current
      const s = STEPS[index]
      if (!s) return

      await prepareStep(s, path)
      if (gen !== setupGenRef.current) return

      if (!s.anchor) {
        setTargetMissing(false)
        return
      }

      if (s.routePrefix && !path?.startsWith(s.routePrefix)) {
        setTargetMissing(true)
        return
      }

      await resolveAnchor(s, s.routePrefix ? 8000 : 5000)
    },
    [resolveAnchor],
  )

  useEffect(() => {
    if (!open) return
    saveActiveTourSession(stepIndex)
    void runStepSetup(stepIndex, pathname)
  }, [open, stepIndex, pathname, runStepSetup])

  /** 进入目标页后继续等待页面锚点（含设置页异步加载） */
  useEffect(() => {
    if (!open || !step?.anchor || !step.routePrefix) return
    if (!pathname?.startsWith(step.routePrefix)) return

    let cancelled = false
    const tick = async () => {
      for (let i = 0; i < 60 && !cancelled; i++) {
        const el = await waitForTourTarget(step.anchor!, { timeoutMs: 200, intervalMs: 200 })
        if (cancelled) return
        if (el) {
          setTargetMissing(false)
          setLayoutKey((k) => k + 1)
          if (step.scrollToId) {
            document.getElementById(step.scrollToId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
          return
        }
        await new Promise((r) => window.setTimeout(r, 200))
      }
    }
    void tick()
    return () => {
      cancelled = true
    }
  }, [open, pathname, step?.id, step?.anchor, step?.routePrefix, step?.scrollToId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const state = await loadOnboardingState()
      if (cancelled) return
      setHydrated(true)

      const resumed = readActiveTourSession()
      if (resumed && shouldAutoShowOnboarding(state)) {
        openWizard(resumed.stepIndex)
        return
      }
      if (resumed) clearActiveTourSession()

      if (shouldAutoShowOnboarding(state)) {
        openWizard(0)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [openWizard])

  useEffect(() => {
    const handler = () => openWizard(readActiveTourSession()?.stepIndex ?? 0)
    window.addEventListener(ONBOARDING_REOPEN_EVENT, handler)
    return () => window.removeEventListener(ONBOARDING_REOPEN_EVENT, handler)
  }, [openWizard])

  if (!hydrated && !open) return null
  if (!open || !step) return null

  const close = (status: OnboardingStatus) => {
    setOpen(false)
    clearActiveTourSession()
    persistStatus(status)
  }

  const goTo = (next: number) => {
    if (next < 0 || next >= STEPS.length) return
    setStepIndex(next)
  }

  const goNext = () => {
    if (stepIndex >= STEPS.length - 1) {
      close('completed')
      return
    }
    goTo(stepIndex + 1)
  }

  const goPrev = () => goTo(Math.max(0, stepIndex - 1))

  const showRouteHint = !!step.routePrefix && !onRoute && !!step.anchor

  return (
    <TourSpotlight
      open={open}
      step={step}
      stepIndex={stepIndex}
      totalSteps={STEPS.length}
      targetMissing={showRouteHint ? true : targetMissing}
      layoutKey={layoutKey}
      onPrev={goPrev}
      onNext={goNext}
      onSkip={() => close('skipped')}
      onComplete={() => close('completed')}
    />
  )
}

export function openOnboardingGuide() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(ONBOARDING_REOPEN_EVENT))
}
