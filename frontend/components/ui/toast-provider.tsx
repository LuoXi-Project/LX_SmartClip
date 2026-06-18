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
import { CheckCircle2, XCircle, Info, X, Loader2 } from 'lucide-react'
import { useTaskStore } from '@/lib/task-store'

// ─── Types ────────────────────────────────────────────────────────────────────

type ToastVariant = 'success' | 'error' | 'info' | 'task'

interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastItem {
  id: string
  message: string
  variant: ToastVariant
  /** auto-dismiss delay in ms, 0 = no auto-dismiss */
  duration: number
  /** task 变体专属：进度百分比（0-100），undefined 表示不确定进度 */
  percent?: number
  /** task 变体专属：当前阶段文案 */
  stage?: string
  /** task 变体专属：取消回调 */
  onCancel?: () => void
  /** error 变体专属：动作按钮（如「重试」）*/
  action?: ToastAction
}

/** task() 返回的句柄：支持原地更新进度、完成、失败。 */
export interface TaskHandle {
  /** id，便于外部定位（如点击跳转）*/
  id: string
  update: (patch: {
    message?: string
    percent?: number | null
    stage?: string
  }) => void
  done: (message?: string) => void
  fail: (message: string, opts?: { action?: ToastAction }) => void
}

interface ToastAPI {
  success: (message: string, duration?: number) => void
  error: (message: string, duration?: number) => void
  info: (message: string, duration?: number) => void
  /** 启动一个持久驻留的「任务态」toast，返回可原地更新的句柄。 */
  task: (title: string, opts?: { percent?: number; onCancel?: () => void; stage?: string }) => TaskHandle
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
  task: 0, // 持久驻留，仅由 done/fail/手动关闭
}

const VARIANT_STYLES: Record<ToastVariant, { container: string; icon: typeof CheckCircle2 }> = {
  success: {
    container: 'border-emerald-500/30 bg-emerald-950/80 text-emerald-200',
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
  task: {
    container: 'border-cyan-500/30 bg-cyan-950/80 text-cyan-200',
    icon: Loader2,
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

  // Auto-dismiss（task 变体 duration=0 不自动消失；duration 变更时重置定时器）
  useEffect(() => {
    if (!item.duration) return
    timerRef.current = setTimeout(() => dismiss(), item.duration)
    return () => clearTimeout(timerRef.current)
  }, [item.duration])

  const dismiss = () => {
    setVisible(false)
    setTimeout(() => onRemove(item.id), 300)
  }

  const { container, icon: Icon } = VARIANT_STYLES[item.variant]
  const isTask = item.variant === 'task'

  return (
    <div
      className={`flex items-start gap-3 min-w-[280px] max-w-xs px-4 py-3 rounded-xl border backdrop-blur-md shadow-xl transition-all duration-300 ${
        container
      } ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      }`}
    >
      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${isTask ? 'animate-spin' : ''}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm leading-snug whitespace-pre-line">{item.message}</p>
        {isTask && (
          <div className="mt-2 space-y-1.5">
            {item.stage && <p className="text-[11px] opacity-80">{item.stage}</p>}
            <div className="h-1 rounded-full bg-black/30 overflow-hidden relative">
              {item.percent === undefined ? (
                <div className="absolute top-0 h-full w-2/5 rounded-full bg-cyan-400/80 animate-hf-indeterminate" />
              ) : (
                <div
                  className="h-full rounded-full bg-cyan-400 transition-all duration-500"
                  style={{ width: `${Math.max(0, Math.min(100, item.percent))}%` }}
                />
              )}
            </div>
            {item.percent !== undefined && (
              <p className="text-[11px] opacity-70 text-right">{item.percent}%</p>
            )}
          </div>
        )}
        {item.action && (
          <button
            onClick={item.action.onClick}
            className="mt-2 inline-flex items-center rounded-md border border-current/30 px-2 py-0.5 text-xs hover:bg-white/10 transition-colors"
          >
            {item.action.label}
          </button>
        )}
      </div>
      <div className="flex flex-col items-center gap-1 shrink-0">
        {isTask && item.onCancel && (
          <button
            onClick={() => {
              item.onCancel?.()
              dismiss()
            }}
            className="opacity-60 hover:opacity-100 hover:text-red-300 transition-opacity text-[11px]"
            title="取消"
          >
            取消
          </button>
        )}
        <button
          onClick={dismiss}
          className="opacity-50 hover:opacity-100 transition-opacity"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  // 当 TaskHub 有任务时，把 toast 栈上移避开，避免右下角重叠
  const hasActiveTasks = useTaskStore((s) => Object.keys(s.tasks).length > 0)

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const add = useCallback((item: Partial<Omit<ToastItem, 'id'>> & { id?: string; message: string; variant: ToastVariant }) => {
    const id = item.id ?? `toast-${Date.now()}-${Math.random()}`
    const dur = item.duration ?? DEFAULT_DURATION_MS[item.variant]
    setToasts((prev) => [...prev, { ...item, id, duration: dur } as ToastItem])
    return id
  }, [])

  /** 原地更新某个 toast 的字段（按 id 替换，未变更的保留）。 */
  const patch = useCallback((id: string, p: Partial<ToastItem>) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, ...p } : t)))
  }, [])

  /** 终止一个 task toast：切到终态变体并安排自动消失。 */
  const finishTask = useCallback(
    (id: string, variant: 'success' | 'error', message: string, duration: number, action?: ToastAction) => {
      setToasts((prev) =>
        prev.map((t) =>
          t.id === id
            ? { ...t, variant, message, duration, action, percent: undefined, stage: undefined, onCancel: undefined }
            : t,
        ),
      )
    },
    [],
  )

  const startTask = useCallback<ToastAPI['task']>(
    (title, opts) => {
      const id = `task-${Date.now()}-${Math.random()}`
      add({
        id,
        message: title,
        variant: 'task',
        percent: opts?.percent,
        stage: opts?.stage,
        onCancel: opts?.onCancel,
      })
      const handle: TaskHandle = {
        id,
        update: (p) =>
          patch(id, {
            message: p.message,
            stage: p.stage,
            percent: p.percent === null ? undefined : p.percent,
          }),
        done: (msg) => finishTask(id, 'success', msg ?? '已完成', 3500),
        fail: (msg, o) => finishTask(id, 'error', msg, 10000, o?.action),
      }
      return handle
    },
    [add, patch, finishTask],
  )

  const api: ToastAPI = {
    success: (msg, dur) => add({ message: msg, variant: 'success', duration: dur }),
    error: (msg, dur) => add({ message: msg, variant: 'error', duration: dur }),
    info: (msg, dur) => add({ message: msg, variant: 'info', duration: dur }),
    task: startTask,
  }

  return (
    <ToastContext.Provider value={api}>
      {children}

      {/* Toast stack — bottom-right；有后台任务时上移避开 TaskHub */}
      <div
        className="fixed right-6 z-[1000] flex flex-col gap-2 items-end pointer-events-none transition-[bottom] duration-300"
        style={{ bottom: hasActiveTasks ? '8.5rem' : '1.5rem' }}
      >
        {toasts.map((t) => (
          <div key={t.id} className="pointer-events-auto">
            <ToastCard item={t} onRemove={remove} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
