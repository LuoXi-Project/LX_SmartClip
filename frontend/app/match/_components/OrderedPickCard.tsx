'use client'

import type { MouseEvent, ReactNode } from 'react'

/**
 * 手动匹配 ClipCard 与文案成片素材条目的共性外壳：缩略条 + 标题 + 有序号角标。
 * ClipCard 仍保留评分条等差异内容；新需求优先用本组件保持交互与样式一致。
 */
export function OrderedPickCard({
  imageUrl,
  imageAlt = '',
  title,
  subtitle,
  orderPositions,
  selected,
  onClick,
  disabled = false,
  className = '',
  children,
  footer,
}: {
  imageUrl: string
  imageAlt?: string
  title: string
  subtitle?: string
  /** 在成组顺序中的 1-based 位次，多条表示同 key 在组内复用 */
  orderPositions: number[]
  selected: boolean
  onClick: (e: MouseEvent) => void
  disabled?: boolean
  className?: string
  children?: ReactNode
  footer?: ReactNode
}) {
  const posLabel =
    orderPositions.length === 0 ? null : orderPositions.join('·')

  return (
    <div
      className={`relative flex-shrink-0 w-52 rounded-xl border overflow-hidden transition-all ${
        selected
          ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/40'
          : 'border-slate-700 bg-slate-900/50 hover:border-slate-500'
      } ${className}`}
    >
      {posLabel !== null && (
        <div
          className="absolute top-2 right-2 z-10 max-w-[4.5rem] min-h-5 px-1 rounded-full bg-indigo-500 flex items-center justify-center"
          title={
            orderPositions.length > 1
              ? `本组内顺序位次：第 ${orderPositions.join('、')} 段`
              : `本组内第 ${orderPositions[0]} 段`
          }
        >
          <span className="text-[10px] text-white font-semibold tabular-nums leading-tight text-center px-0.5">
            {posLabel}
          </span>
        </div>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className={`block w-full text-left ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
      >
        <div className="w-full h-24 bg-slate-800 overflow-hidden flex items-center justify-center">
          <img src={imageUrl} alt={imageAlt} className="w-full h-full object-cover" loading="lazy" />
        </div>
        <div className="px-3 py-2 space-y-0.5">
          <p className="text-xs text-slate-200 font-medium truncate">{title}</p>
          {subtitle ? <p className="text-[10px] text-slate-500 truncate">{subtitle}</p> : null}
          {children}
        </div>
      </button>
      {footer}
    </div>
  )
}
