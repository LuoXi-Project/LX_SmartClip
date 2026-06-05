'use client'

import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useStudioLayoutContext } from './StudioLayoutContext'
import type { StudioPanelId } from '@/lib/studio-layout-persist'

export function StudioPanelHeaderAction({ panelId }: { panelId: StudioPanelId }) {
  const ctx = useStudioLayoutContext()
  if (!ctx) return null

  const collapsed = ctx.isCollapsed(panelId)
  const visible = ctx.isVisible(panelId)

  if (!visible) return null

  return (
    <button
      type="button"
      onClick={() => (collapsed ? ctx.expandPanel(panelId) : ctx.collapsePanel(panelId))}
      title={collapsed ? '展开面板' : '折叠面板'}
      className="ml-auto p-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800/80 transition-colors"
    >
      {collapsed ? (
        <PanelLeftOpen className="w-3.5 h-3.5" />
      ) : (
        <PanelLeftClose className="w-3.5 h-3.5" />
      )}
    </button>
  )
}
