'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

type ToastVariant = 'success' | 'error' | 'info'

interface ToastItem {
  id: string
  message: string
  variant: ToastVariant
  /** auto-dismiss delay in ms, 0 = no auto-dismiss */
  duration: number
}

interface ToastAPI {
  success: (message: string, duration?: number) => void
  error: (message: string, duration?: number) => void
  info: (message: string, duration?: number) => void
}

// ─── Context ──────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastAPI | null>(null)

export function useToast(): ToastAPI {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}

// ─── Single Toast Item ────────────────────────────────────────────────────────

const DEFAULT_DURATION_MS: Record<ToastVariant, number> = {
  success: 3500,
  error: 10000,
  info: 3500,
}

const VARIANT_STYLES: Record<ToastVariant, { container: string; icon: typeof CheckCircle2 }> = {
  success: {
    container:
      'border-emerald-500/30 bg-emerald-950/80 text-emerald-200',
    icon: CheckCircle2,
  },
  error: {
    container: 'border-red-500/30 bg-red-950/80 text-red-200',
    icon: XCircle,
  },
  info: {
    container: 'border-cyan-500/30 bg-cyan-950/80 text-cyan-200',
    icon: Info,
  },
}

function ToastCard({
  item,
  onRemove,
}: {
  item: ToastItem
  onRemove: (id: string) => void
}) {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()

  // Slide-in
  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(raf)
  }, [])

  // Auto-dismiss
  useEffect(() => {
    if (!item.duration) return
    timerRef.current = setTimeout(() => dismiss(), item.duration)
    return () => clearTimeout(timerRef.current)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const dismiss = () => {
    setVisible(false)
    setTimeout(() => onRemove(item.id), 300)
  }

  const { container, icon: Icon } = VARIANT_STYLES[item.variant]

  return (
    <div
      className={`flex items-start gap-3 min-w-[260px] max-w-xs px-4 py-3 rounded-xl border backdrop-blur-md shadow-xl transition-all duration-300 ${
        container
      } ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      }`}
    >
      <Icon className="w-4 h-4 mt-0.5 shrink-0" />
      <p className="flex-1 text-sm leading-snug whitespace-pre-line">{item.message}</p>
      <button
        onClick={dismiss}
        className="shrink-0 opacity-50 hover:opacity-100 transition-opacity"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const add = useCallback((message: string, variant: ToastVariant, duration?: number) => {
    const id = `toast-${Date.now()}-${Math.random()}`
    const dur = duration ?? DEFAULT_DURATION_MS[variant]
    setToasts((prev) => [...prev, { id, message, variant, duration: dur }])
  }, [])

  const api: ToastAPI = {
    success: (msg, dur) => add(msg, 'success', dur),
    error: (msg, dur) => add(msg, 'error', dur),
    info: (msg, dur) => add(msg, 'info', dur),
  }

  return (
    <ToastContext.Provider value={api}>
      {children}

      {/* Toast stack — bottom-right */}
      <div className="fixed bottom-6 right-6 z-[1000] flex flex-col gap-2 items-end pointer-events-none">
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <ToastCard item={t} onRemove={remove} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
