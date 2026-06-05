'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  DEFAULT_LAYOUT,
  ensureAtLeastOneVisible,
  movePanelInOrder,
  readStudioLayout,
  reorderPanels,
  type StudioLayoutState,
  type StudioPanelId,
  writeStudioLayout,
} from '@/lib/studio-layout-persist'

const LG_BREAKPOINT = 1024

export function useIsDesktopLayout() {
  const [isDesktop, setIsDesktop] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${LG_BREAKPOINT}px)`)
    const update = () => setIsDesktop(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])

  return isDesktop
}

export function useStudioLayout() {
  const [layout, setLayout] = useState<StudioLayoutState>(DEFAULT_LAYOUT)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    setLayout(readStudioLayout())
    setHydrated(true)
  }, [])

  const commit = useCallback((updater: (prev: StudioLayoutState) => StudioLayoutState) => {
    setLayout((prev) => {
      const next = updater(prev)
      writeStudioLayout(next)
      return next
    })
  }, [])

  const setPanelSizes = useCallback(
    (sizes: Partial<Record<StudioPanelId, number>>) => {
      commit((prev) => ({ ...prev, sizes: { ...prev.sizes, ...sizes } }))
    },
    [commit]
  )

  const setPanelCollapsed = useCallback(
    (id: StudioPanelId, collapsed: boolean) => {
      commit((prev) => ({
        ...prev,
        collapsed: { ...prev.collapsed, [id]: collapsed },
      }))
    },
    [commit]
  )

  const togglePanelVisible = useCallback(
    (id: StudioPanelId) => {
      commit((prev) => ({
        ...prev,
        visible: ensureAtLeastOneVisible(prev.visible, id),
      }))
    },
    [commit]
  )

  const setPanelOrder = useCallback(
    (panelOrder: StudioPanelId[]) => {
      commit((prev) => ({ ...prev, panelOrder }))
    },
    [commit]
  )

  const movePanel = useCallback(
    (id: StudioPanelId, direction: -1 | 1) => {
      commit((prev) => ({
        ...prev,
        panelOrder: movePanelInOrder(prev.panelOrder, id, direction),
      }))
    },
    [commit]
  )

  const dragReorder = useCallback(
    (from: number, to: number) => {
      commit((prev) => ({
        ...prev,
        panelOrder: reorderPanels(prev.panelOrder, from, to),
      }))
    },
    [commit]
  )

  const setMobileActivePanel = useCallback(
    (mobileActivePanel: StudioPanelId) => {
      commit((prev) => ({ ...prev, mobileActivePanel }))
    },
    [commit]
  )

  const resetLayout = useCallback(() => {
    const next = {
      ...DEFAULT_LAYOUT,
      panelOrder: [...DEFAULT_LAYOUT.panelOrder],
    }
    setLayout(next)
    writeStudioLayout(next)
  }, [])

  return {
    layout,
    hydrated,
    setPanelSizes,
    setPanelCollapsed,
    togglePanelVisible,
    setPanelOrder,
    movePanel,
    dragReorder,
    setMobileActivePanel,
    resetLayout,
  }
}
