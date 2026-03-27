'use client'

import { useEffect, useRef } from 'react'
import { AlertTriangle, X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'default'
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null)

  // Focus confirm button when dialog opens
  useEffect(() => {
    if (open) {
      setTimeout(() => confirmRef.current?.focus(), 50)
    }
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onCancel])

  if (!open) return null

  const isDanger = variant === 'danger'

  return (
    <div
      className="fixed inset-0 z-[999] flex items-center justify-center p-4"
      aria-modal="true"
      role="dialog"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150"
        onClick={onCancel}
      />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-sm bg-[#161922] border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 animate-in fade-in zoom-in-95 duration-150">
        {/* Close button */}
        <button
          onClick={onCancel}
          className="absolute top-3.5 right-3.5 p-1 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="p-6">
          {/* Icon + Title */}
          <div className="flex items-start gap-3.5 mb-3">
            <div
              className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center ${
                isDanger
                  ? 'bg-red-500/15 text-red-400'
                  : 'bg-amber-500/15 text-amber-400'
              }`}
            >
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div className="pt-1.5">
              <h3 className="text-slate-100 font-semibold text-base leading-snug">{title}</h3>
              {description && (
                <p className="text-slate-400 text-sm mt-1 leading-relaxed">{description}</p>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-2.5 mt-5 justify-end">
            <button
              onClick={onCancel}
              className="px-4 py-2 text-sm font-medium text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors"
            >
              {cancelLabel}
            </button>
            <button
              ref={confirmRef}
              onClick={onConfirm}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                isDanger
                  ? 'bg-red-600 hover:bg-red-500 text-white'
                  : 'bg-cyan-600 hover:bg-cyan-500 text-white'
              }`}
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
