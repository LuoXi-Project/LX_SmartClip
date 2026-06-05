'use client'

import { createContext, useContext } from 'react'
import type { StudioPanelId } from '@/lib/studio-layout-persist'

export type StudioLayoutContextValue = {
  collapsePanel: (id: StudioPanelId) => void
  expandPanel: (id: StudioPanelId) => void
  isCollapsed: (id: StudioPanelId) => boolean
  isVisible: (id: StudioPanelId) => boolean
}

const StudioLayoutContext = createContext<StudioLayoutContextValue | null>(null)

export function StudioLayoutProvider({
  value,
  children,
}: {
  value: StudioLayoutContextValue
  children: React.ReactNode
}) {
  return <StudioLayoutContext.Provider value={value}>{children}</StudioLayoutContext.Provider>
}

export function useStudioLayoutContext() {
  return useContext(StudioLayoutContext)
}
