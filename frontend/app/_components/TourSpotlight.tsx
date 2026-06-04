'use client'

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import Link from 'next/link'
import clsx from 'clsx'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import type { OnboardingTourStep, TourPlacement } from '@/lib/onboarding-tour'
import { resolveTourTarget } from '@/lib/onboarding-tour'

const PAD = 8
const POPOVER_GAP = 14
const VIEWPORT_MARGIN = 12
const ESTIMATED_POPOVER_H = 260

export type SpotlightRect = {
  top: number
  left: number
  width: number
  height: number
}

type ResolvedPlacement = 'top' | 'bottom' | 'left' | 'right'

export type PopoverLayout = {
  top: number
  left: number
  placement: ResolvedPlacement
}

function measureTarget(el: HTMLElement): SpotlightRect {
  const r = el.getBoundingClientRect()
  return {
    top: Math.max(0, r.top - PAD),
    left: Math.max(0, r.left - PAD),
    width: r.width + PAD * 2,
    height: r.height + PAD * 2,
  }
}

function positionForPlacement(
  placement: ResolvedPlacement,
  rect: SpotlightRect,
  popW: number,
  popH: number,
): { top: number; left: number } {
  const centerX = rect.left + rect.width / 2
  if (placement === 'bottom') {
    return {
      top: rect.top + rect.height + POPOVER_GAP,
      left: centerX - popW / 2,
    }
  }
  if (placement === 'top') {
    return {
      top: rect.top - POPOVER_GAP - popH,
      left: centerX - popW / 2,
    }
  }
  if (placement === 'right') {
    return {
      top: rect.top,
      left: rect.left + rect.width + POPOVER_GAP,
    }
  }
  return {
    top: rect.top,
    left: rect.left - POPOVER_GAP - popW,
  }
}

function fitsViewport(top: number, left: number, popW: number, popH: number): boolean {
  return (
    top >= VIEWPORT_MARGIN &&
    left >= VIEWPORT_MARGIN &&
    top + popH <= window.innerHeight - VIEWPORT_MARGIN &&
    left + popW <= window.innerWidth - VIEWPORT_MARGIN
  )
}

function clampToViewport(top: number, left: number, popW: number, popH: number): { top: number; left: number } {
  const maxLeft = window.innerWidth - popW - VIEWPORT_MARGIN
  const maxTop = window.innerHeight - popH - VIEWPORT_MARGIN
  return {
    top: Math.min(Math.max(VIEWPORT_MARGIN, top), maxTop),
    left: Math.min(Math.max(VIEWPORT_MARGIN, left), maxLeft),
  }
}

/** 按可用空间选择方位，保证弹层在视口内 */
export function computePopoverLayout(
  rect: SpotlightRect,
  popW: number,
  popH: number,
  preferred: TourPlacement = 'auto',
): PopoverLayout {
  const order: ResolvedPlacement[] =
    preferred === 'auto'
      ? ['bottom', 'top', 'right', 'left']
      : ([preferred as ResolvedPlacement, 'bottom', 'top', 'right', 'left'].filter(
          (p, i, arr) => arr.indexOf(p) === i,
        ) as ResolvedPlacement[])

  for (const placement of order) {
    const raw = positionForPlacement(placement, rect, popW, popH)
    if (fitsViewport(raw.top, raw.left, popW, popH)) {
      return { ...clampToViewport(raw.top, raw.left, popW, popH), placement }
    }
  }

  const fallback = positionForPlacement('bottom', rect, popW, popH)
  const clamped = clampToViewport(fallback.top, fallback.left, popW, popH)
  return { ...clamped, placement: 'bottom' }
}

interface TourSpotlightProps {
  open: boolean
  step: OnboardingTourStep
  stepIndex: number
  totalSteps: number
  targetMissing?: boolean
  /** 路径变化后触发重新测量锚点 */
  layoutKey?: string | number
  onPrev: () => void
  onNext: () => void
  onSkip: () => void
  onComplete: () => void
}

export function TourSpotlight({
  open,
  step,
  stepIndex,
  totalSteps,
  targetMissing = false,
  layoutKey = 0,
  onPrev,
  onNext,
  onSkip,
  onComplete,
}: TourSpotlightProps) {
  const maskId = useId().replace(/:/g, '')
  const popoverRef = useRef<HTMLDivElement>(null)
  const [rect, setRect] = useState<SpotlightRect | null>(null)
  const [popoverLayout, setPopoverLayout] = useState<PopoverLayout | null>(null)

  const remeasure = useCallback(() => {
    if (!step.anchor) {
      setRect(null)
      setPopoverLayout(null)
      return
    }
    const el = resolveTourTarget(step.anchor)
    if (!el) {
      setRect(null)
      setPopoverLayout(null)
      return
    }
    const next = measureTarget(el)
    setRect(next)
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })

    const popW = Math.min(360, window.innerWidth - VIEWPORT_MARGIN * 2)
    const popH = popoverRef.current?.offsetHeight || ESTIMATED_POPOVER_H
    setPopoverLayout(computePopoverLayout(next, popW, popH, step.placement ?? 'auto'))
  }, [step.anchor, step.placement])

  useLayoutEffect(() => {
    if (!open) return
    remeasure()
  }, [open, remeasure, step.id, targetMissing, layoutKey])

  useLayoutEffect(() => {
    if (!open || !rect || targetMissing) return
    const pop = popoverRef.current
    if (!pop) return
    const popW = pop.offsetWidth
    const popH = pop.offsetHeight
    setPopoverLayout(computePopoverLayout(rect, popW, popH, step.placement ?? 'auto'))
  }, [open, rect, targetMissing, step.placement])

  useEffect(() => {
    if (!open || !step.anchor) return
    const onResize = () => remeasure()
    window.addEventListener('resize', onResize)
    window.addEventListener('scroll', onResize, true)
    return () => {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onResize, true)
    }
  }, [open, remeasure, step.anchor])

  if (!open) return null

  const isCenter = !step.anchor || targetMissing || !rect
  const isLast = stepIndex === totalSteps - 1
  const showSpotlight = !isCenter && rect

  const popoverStyle: React.CSSProperties | undefined =
    !isCenter && rect && popoverLayout
      ? {
          position: 'fixed',
          zIndex: 202,
          top: popoverLayout.top,
          left: popoverLayout.left,
          maxWidth: Math.min(360, window.innerWidth - VIEWPORT_MARGIN * 2),
          width: Math.min(360, window.innerWidth - VIEWPORT_MARGIN * 2),
        }
      : undefined

  return (
    <div className="fixed inset-0 z-[200] pointer-events-none" aria-modal role="dialog">
      {showSpotlight && rect ? (
        <>
          <svg className="absolute inset-0 w-full h-full" aria-hidden>
            <defs>
              <mask id={maskId}>
                <rect width="100%" height="100%" fill="white" />
                <rect
                  x={rect.left}
                  y={rect.top}
                  width={rect.width}
                  height={rect.height}
                  rx={10}
                  fill="black"
                />
              </mask>
            </defs>
            <rect
              width="100%"
              height="100%"
              fill="rgba(0,0,0,0.72)"
              mask={`url(#${maskId})`}
            />
          </svg>
          <div
            className="absolute rounded-[10px] border-2 border-violet-400 shadow-[0_0_0_4px_rgba(139,92,246,0.25)] animate-pulse pointer-events-none"
            style={{
              top: rect.top,
              left: rect.left,
              width: rect.width,
              height: rect.height,
            }}
          />
        </>
      ) : (
        <div className="absolute inset-0 bg-black/72 pointer-events-none" aria-hidden />
      )}

      <div
        ref={popoverRef}
        className={clsx(
          'pointer-events-auto bg-[#161922] border border-slate-700/70 rounded-2xl shadow-2xl shadow-black/60 overflow-hidden',
          isCenter && 'fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(100%,24rem)] mx-4',
        )}
        style={popoverStyle}
      >
        <div className="px-4 pt-4 pb-2 flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-wider text-violet-400/90 font-medium">
              新手指引 · {stepIndex + 1} / {totalSteps}
            </p>
            <h3 className="text-base font-semibold text-slate-100 mt-0.5">{step.title}</h3>
          </div>
          <button
            type="button"
            onClick={onSkip}
            className="shrink-0 p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/80 transition-colors"
            aria-label="跳过引导"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 pb-3">
          <p className="text-sm text-slate-400 leading-relaxed">{step.description}</p>
          {targetMissing && step.anchor ? (
            <p className="mt-2 text-xs text-amber-200/90 bg-amber-500/10 border border-amber-500/25 rounded-lg px-2.5 py-2">
              {step.href
                ? '请先点击高亮的导航项，或下方链接进入对应页面，指引会继续保持。'
                : '未找到高亮区域，请稍候或点下一步继续。'}
            </p>
          ) : null}
          {step.bullets?.length ? (
            <ul className="mt-2 space-y-1 text-xs text-slate-500 list-disc pl-4 marker:text-slate-600">
              {step.bullets.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          ) : null}
          {step.href ? (
            <Link
              href={step.href}
              className="mt-3 inline-flex text-xs font-medium text-violet-300 hover:text-violet-200"
            >
              前往该页面 →
            </Link>
          ) : null}
        </div>

        <div className="px-4 pb-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800/60 pt-3">
          <button
            type="button"
            disabled={stepIndex === 0}
            onClick={onPrev}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-sm text-slate-400 hover:text-slate-200 disabled:opacity-30 rounded-lg hover:bg-slate-800/50 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            上一步
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onSkip}
              className="text-sm text-slate-500 hover:text-slate-300 px-2 py-1.5"
            >
              跳过
            </button>
            {isLast ? (
              <button
                type="button"
                onClick={onComplete}
                className="inline-flex items-center gap-1 px-3.5 py-1.5 text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 rounded-lg"
              >
                完成
              </button>
            ) : (
              <button
                type="button"
                onClick={onNext}
                className="inline-flex items-center gap-1 px-3.5 py-1.5 text-sm font-medium text-white bg-slate-700 hover:bg-slate-600 rounded-lg"
              >
                下一步
                <ChevronRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
