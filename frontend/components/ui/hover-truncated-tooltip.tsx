'use client'

import { createPortal } from 'react-dom'
import { useEffect, useRef, useState } from 'react'

type ClampLines = 1 | 2 | 3 | 4

function getClampClass(clamp: ClampLines) {
  switch (clamp) {
    case 1:
      // 单行场景用 truncate，既保证省略号外观一致，也让 scrollWidth 判断更可靠
      return 'truncate'
    case 2:
      return 'line-clamp-2'
    case 3:
      return 'line-clamp-3'
    case 4:
      return 'line-clamp-4'
    default:
      return 'line-clamp-2'
  }
}

export function HoverTruncatedTooltip({
  text,
  tooltipTitle,
  tooltipContent,
  clamp = 2,
  as = 'p',
  anchorClassName,
  tooltipClassName,
  openDelayMs = 0,
  hideDelayMs = 140,
}: {
  text: string
  tooltipTitle?: string
  tooltipContent?: React.ReactNode
  clamp?: ClampLines
  as?: 'p' | 'span'
  anchorClassName?: string
  tooltipClassName?: string
  /** 进入时延迟（避免抖动），默认 0ms */
  openDelayMs?: number
  /** 离开时延迟（给用户一点“接触 tooltip”的容错）默认 140ms */
  hideDelayMs?: number
}) {
  const anchorRef = useRef<HTMLElement | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelHide = () => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }

  const cancelOpen = () => {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
  }

  const scheduleHide = () => {
    cancelOpen()
    cancelHide()
    hideTimerRef.current = setTimeout(() => setPos(null), hideDelayMs)
  }

  const tryOpen = () => {
    cancelHide()
    const el = anchorRef.current
    if (!el) return
    // 判断是否“视觉省略”：
    // - 单行 truncate：用 scrollWidth > clientWidth
    // - 多行 line-clamp：有时 scrollHeight 可能不反映真实省略，因此两者都兜底判断
    if (!(el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1)) return
    const r = el.getBoundingClientRect()
    setPos({
      left: r.left + r.width / 2,
      top: r.bottom + 8,
    })
  }

  const onPointerEnter = () => {
    cancelHide()
    cancelOpen()
    if (openDelayMs > 0) {
      openTimerRef.current = setTimeout(() => tryOpen(), openDelayMs)
      return
    }
    tryOpen()
  }

  useEffect(() => {
    if (!pos) return
    const onDismiss = () => setPos(null)
    window.addEventListener('scroll', onDismiss, true)
    window.addEventListener('resize', onDismiss)
    return () => {
      window.removeEventListener('scroll', onDismiss, true)
      window.removeEventListener('resize', onDismiss)
    }
  }, [pos])

  useEffect(() => {
    return () => {
      cancelHide()
      cancelOpen()
    }
  }, [])

  const clampClass = getClampClass(clamp)
  const Tag = as

  return (
    <>
      <Tag
        ref={anchorRef as any}
        onPointerEnter={onPointerEnter}
        onPointerLeave={scheduleHide}
        className={[
          clampClass,
          'leading-snug cursor-help',
          anchorClassName,
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {text}
      </Tag>
      {pos &&
        typeof document !== 'undefined' &&
        createPortal(
          <div
            role="tooltip"
            className={[
              'fixed z-[200] w-[min(18rem,calc(100vw-1.5rem))] max-h-[min(16rem,42vh)] overflow-y-auto rounded-xl',
              'border border-slate-600/80 bg-[#141721]/98 px-3 py-2.5 text-[11px] leading-relaxed',
              'text-slate-200 shadow-2xl shadow-black/40 backdrop-blur-md whitespace-pre-wrap',
              'break-words outline-none ring-1 ring-indigo-500/15',
              tooltipClassName,
            ]
              .filter(Boolean)
              .join(' ')}
            style={{
              left: pos.left,
              top: pos.top,
              transform: 'translateX(-50%)',
            }}
            onPointerEnter={() => cancelHide()}
            onPointerLeave={scheduleHide}
          >
            {tooltipTitle && (
              <p className="text-[9px] font-semibold uppercase tracking-wider text-indigo-400/90 mb-1.5">
                {tooltipTitle}
              </p>
            )}
            <div className="text-slate-200/95 not-italic">{tooltipContent ?? text}</div>
          </div>,
          document.body,
        )}
    </>
  )
}

