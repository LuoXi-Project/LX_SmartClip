'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from 'react'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ConfirmOptions {
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'default'
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>

// ─── Context ──────────────────────────────────────────────────────────────────

const ConfirmContext = createContext<ConfirmFn | null>(null)

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirm must be used inside <ConfirmProvider>')
  return ctx
}

// ─── Provider ─────────────────────────────────────────────────────────────────

interface DialogState extends ConfirmOptions {
  open: boolean
}

const CLOSED: DialogState = { open: false, title: '' }

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState>(CLOSED)
  // Store the resolve callback between render cycles
  const resolveRef = useRef<((value: boolean) => void) | null>(null)

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve
      setState({ open: true, ...options })
    })
  }, [])

  const handleConfirm = () => {
    setState(CLOSED)
    resolveRef.current?.(true)
    resolveRef.current = null
  }

  const handleCancel = () => {
    setState(CLOSED)
    resolveRef.current?.(false)
    resolveRef.current = null
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <ConfirmDialog
        open={state.open}
        title={state.title}
        description={state.description}
        confirmLabel={state.confirmLabel}
        cancelLabel={state.cancelLabel}
        variant={state.variant}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </ConfirmContext.Provider>
  )
}
