'use client'

import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  ChevronDown,
  ChevronUp,
  GripVertical,
  LayoutGrid,
  Layers,
  MessageSquare,
  RotateCcw,
  SlidersHorizontal,
} from 'lucide-react'
import {
  PANEL_META,
  type StudioLayoutState,
  type StudioPanelId,
} from '@/lib/studio-layout-persist'

const PANEL_ICONS: Record<StudioPanelId, typeof MessageSquare> = {
  thread: MessageSquare,
  canvas: Layers,
  inspector: SlidersHorizontal,
}

type StudioLayoutControlsProps = {
  layout: StudioLayoutState
  isDesktop: boolean
  onToggleVisible: (id: StudioPanelId) => void
  onMovePanel: (id: StudioPanelId, direction: -1 | 1) => void
  onDragReorder: (from: number, to: number) => void
  onMobileSelect: (id: StudioPanelId) => void
  onReset: () => void
}

export function StudioLayoutControls({
  layout,
  isDesktop,
  onToggleVisible,
  onMovePanel,
  onDragReorder,
  onMobileSelect,
  onReset,
}: StudioLayoutControlsProps) {
  const [open, setOpen] = useState(false)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const btn =
    'inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs border transition-colors disabled:opacity-40'

  return (
    <div className="flex items-center gap-1 shrink-0" ref={popoverRef}>
      {!isDesktop ? (
        <div className="flex items-center gap-0.5 rounded-lg border border-slate-800 bg-slate-900/50 p-0.5">
          {layout.panelOrder.map((id) => {
            const Icon = PANEL_ICONS[id]
            const active = layout.mobileActivePanel === id
            return (
              <button
                key={id}
                type="button"
                onClick={() => onMobileSelect(id)}
                className={clsx(
                  'inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-colors',
                  active
                    ? 'bg-violet-600/20 text-violet-200'
                    : 'text-slate-500 hover:text-slate-300'
                )}
              >
                <Icon className="w-3 h-3" />
                {PANEL_META[id].shortLabel}
              </button>
            )
          })}
        </div>
      ) : (
        <>
          {layout.panelOrder.map((id) => {
            const Icon = PANEL_ICONS[id]
            const on = layout.visible[id]
            return (
              <button
                key={id}
                type="button"
                title={`${on ? '隐藏' : '显示'}${PANEL_META[id].label}`}
                onClick={() => onToggleVisible(id)}
                className={clsx(
                  btn,
                  on
                    ? 'border-violet-500/40 bg-violet-500/10 text-violet-200'
                    : 'border-slate-700 text-slate-500 hover:border-slate-600 hover:text-slate-300'
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                <span className="hidden xl:inline">{PANEL_META[id].shortLabel}</span>
              </button>
            )
          })}
        </>
      )}

      <div className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={clsx(
            btn,
            'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200',
            open && 'border-violet-500/40 bg-violet-500/10 text-violet-200'
          )}
          title="布局设置"
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">布局</span>
        </button>

        {open ? (
          <div className="absolute right-0 top-full mt-1 z-50 w-64 rounded-lg border border-slate-700 bg-[#12151c] shadow-xl p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300">面板顺序</span>
              <button
                type="button"
                onClick={() => {
                  onReset()
                  setOpen(false)
                }}
                className="inline-flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300"
              >
                <RotateCcw className="w-3 h-3" />
                恢复默认
              </button>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              拖拽或使用箭头调整左→右顺序；桌面端可拖拽分隔条调节宽度。
            </p>
            <ul className="space-y-1">
              {layout.panelOrder.map((id, index) => {
                const Icon = PANEL_ICONS[id]
                return (
                  <li
                    key={id}
                    draggable
                    onDragStart={() => setDragFrom(index)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (dragFrom !== null && dragFrom !== index) {
                        onDragReorder(dragFrom, index)
                      }
                      setDragFrom(null)
                    }}
                    onDragEnd={() => setDragFrom(null)}
                    className={clsx(
                      'flex items-center gap-2 rounded-md border px-2 py-1.5',
                      dragFrom === index
                        ? 'border-violet-500/50 bg-violet-500/10'
                        : 'border-slate-800 bg-slate-900/40'
                    )}
                  >
                    <GripVertical className="w-3.5 h-3.5 text-slate-600 shrink-0 cursor-grab" />
                    <Icon className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span className="flex-1 text-xs text-slate-300">{PANEL_META[id].label}</span>
                    <div className="flex flex-col shrink-0">
                      <button
                        type="button"
                        disabled={index === 0}
                        onClick={() => onMovePanel(id, -1)}
                        className="p-0.5 text-slate-500 hover:text-slate-300 disabled:opacity-30"
                      >
                        <ChevronUp className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        disabled={index === layout.panelOrder.length - 1}
                        onClick={() => onMovePanel(id, 1)}
                        className="p-0.5 text-slate-500 hover:text-slate-300 disabled:opacity-30"
                      >
                        <ChevronDown className="w-3 h-3" />
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
            {isDesktop ? (
              <div className="pt-1 border-t border-slate-800">
                <span className="text-[10px] text-slate-500">可见性由顶栏图标切换</span>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
