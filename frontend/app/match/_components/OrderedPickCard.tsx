'use client'

import { createPortal } from 'react-dom'
import { Play, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'

/**
 * 手动匹配 ClipCard 与文案成片素材条目的共性外壳：缩略条 + 标题 + 有序号角标。
 * 可选 previewVideoUrl：左下角按钮预览播放（stopPropagation）；缩略图其余区域与下方文案区均可勾选。
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
  previewVideoUrl,
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
  /** 已缓存等可直链播放的素材；有值时缩略图左下角播放，其余图区 + 下方文案区勾选 */
  previewVideoUrl?: string | null
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)
  const posLabel =
    orderPositions.length === 0 ? null : orderPositions.join('·')

  const closePreview = useCallback(() => {
    setPreviewOpen(false)
    const v = videoRef.current
    if (v) {
      v.pause()
      v.currentTime = 0
    }
  }, [])

  useEffect(() => {
    if (!previewOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePreview()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [previewOpen, closePreview])

  const textPick = (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`block w-full text-left px-3 py-2 space-y-0.5 ${
        disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-slate-800/60'
      }`}
    >
      <p className="text-xs text-slate-200 font-medium truncate">{title}</p>
      {subtitle ? <p className="text-[10px] text-slate-500 truncate">{subtitle}</p> : null}
      {children}
    </button>
  )

  const previewLayer =
    previewVideoUrl && !disabled ? (
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setPreviewOpen(true)
        }}
        className="absolute bottom-1.5 left-1.5 z-[5] flex items-center justify-center rounded-full bg-black/75 text-white p-1.5 ring-1 ring-white/30 shadow-md hover:bg-black/90 hover:ring-white/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
        aria-label="预览播放"
      >
        <Play className="w-4 h-4 fill-current shrink-0" />
      </button>
    ) : null

  const imageSelectLayer =
    !disabled ? (
      <button
        type="button"
        onClick={onClick}
        className="absolute inset-0 z-[1]"
        aria-label={`${title} · 点击勾选`}
      />
    ) : null

  const portal =
    previewOpen &&
    previewVideoUrl &&
    typeof document !== 'undefined' &&
    createPortal(
      <div
        className="fixed inset-0 z-[3000] flex items-center justify-center bg-black/80 p-4"
        role="presentation"
        onClick={closePreview}
      >
        <div
          className="relative w-full max-w-3xl rounded-xl border border-slate-600 bg-black overflow-hidden shadow-2xl"
          role="dialog"
          aria-modal="true"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={closePreview}
            className="absolute top-2 right-2 z-10 p-2 rounded-lg bg-slate-900/90 text-slate-200 hover:bg-slate-800 border border-slate-600"
            aria-label="关闭预览"
          >
            <X className="w-5 h-5" />
          </button>
          <video
            ref={videoRef}
            src={previewVideoUrl}
            className="w-full max-h-[min(80vh,560px)] object-contain bg-black"
            controls
            playsInline
            autoPlay
          />
        </div>
      </div>,
      document.body,
    )

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
          className="absolute top-2 right-2 z-10 max-w-[4.5rem] min-h-5 px-1 rounded-full bg-indigo-500 flex items-center justify-center pointer-events-none"
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
      <div className="w-full h-24 bg-slate-800 overflow-hidden relative flex items-center justify-center">
        <img src={imageUrl} alt={imageAlt} className="w-full h-full object-cover pointer-events-none" loading="lazy" />
        {imageSelectLayer}
        {previewLayer}
      </div>
      {textPick}
      {footer}
      {portal}
    </div>
  )
}
