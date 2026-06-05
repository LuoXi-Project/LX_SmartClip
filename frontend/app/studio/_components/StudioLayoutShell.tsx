'use client'

import { useCallback, useEffect, useMemo, useRef, type ReactNode } from 'react'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
  type PanelImperativeHandle,
} from '@/components/ui/resizable'
import { PANEL_META, type StudioLayoutState, type StudioPanelId } from '@/lib/studio-layout-persist'
import { StudioLayoutProvider } from './StudioLayoutContext'

type StudioLayoutShellProps = {
  loading?: boolean
  layout: StudioLayoutState
  hydrated: boolean
  isDesktop: boolean
  setPanelSizes: (sizes: Partial<Record<StudioPanelId, number>>) => void
  setPanelCollapsed: (id: StudioPanelId, collapsed: boolean) => void
  thread: ReactNode
  canvas: ReactNode
  inspector: ReactNode
}

export function StudioLayoutShell({
  loading,
  layout,
  hydrated,
  isDesktop,
  setPanelSizes,
  setPanelCollapsed,
  thread,
  canvas,
  inspector,
}: StudioLayoutShellProps) {
  const panelRefs = useRef<Partial<Record<StudioPanelId, PanelImperativeHandle>>>({})

  const nodes: Record<StudioPanelId, ReactNode> = { thread, canvas, inspector }

  const visibleOrder = useMemo(
    () => layout.panelOrder.filter((id) => layout.visible[id]),
    [layout.panelOrder, layout.visible]
  )

  const defaultLayout = useMemo(() => {
    const result: Record<string, number> = {}
    for (const id of visibleOrder) {
      result[id] = layout.sizes[id] ?? PANEL_META[id].defaultSize
    }
    return result
  }, [visibleOrder, layout.sizes])

  const handleLayoutChanged = useCallback(
    (layoutMap: Record<string, number>) => {
      const next: Partial<Record<StudioPanelId, number>> = {}
      for (const id of visibleOrder) {
        if (typeof layoutMap[id] === 'number') next[id] = layoutMap[id]
      }
      setPanelSizes(next)
    },
    [visibleOrder, setPanelSizes]
  )

  const collapsePanel = useCallback((id: StudioPanelId) => {
    panelRefs.current[id]?.collapse()
  }, [])

  const expandPanel = useCallback((id: StudioPanelId) => {
    panelRefs.current[id]?.expand()
  }, [])

  const layoutContext = useMemo(
    () => ({
      collapsePanel,
      expandPanel,
      isCollapsed: (id: StudioPanelId) => !!layout.collapsed[id],
      isVisible: (id: StudioPanelId) => layout.visible[id],
    }),
    [collapsePanel, expandPanel, layout.collapsed, layout.visible]
  )

  useEffect(() => {
    if (!hydrated || !isDesktop) return
    for (const id of visibleOrder) {
      const handle = panelRefs.current[id]
      if (!handle) continue
      if (layout.collapsed[id]) handle.collapse()
      else handle.expand()
    }
  }, [hydrated, isDesktop, visibleOrder, layout.collapsed])

  if (!hydrated) {
    return (
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 lg:grid lg:grid-cols-12 overflow-hidden">
          <div className="h-[min(42vh,360px)] lg:h-full lg:col-span-3 overflow-hidden border-b lg:border-b-0 border-slate-800">
            {thread}
          </div>
          <div className="flex-1 min-h-0 lg:col-span-5 border-x border-slate-800 overflow-hidden">{canvas}</div>
          <div className="hidden lg:block lg:col-span-4 overflow-hidden">{inspector}</div>
        </div>
      </div>
    )
  }

  return (
    <StudioLayoutProvider value={layoutContext}>
      <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {isDesktop ? (
          <ResizablePanelGroup
            key={visibleOrder.join('-')}
            id="studio-workspace"
            orientation="horizontal"
            className="flex-1 min-h-0"
            defaultLayout={defaultLayout}
            onLayoutChanged={handleLayoutChanged}
          >
            {visibleOrder.map((id, index) => {
              const meta = PANEL_META[id]
              return (
                <DesktopPanel
                  key={id}
                  id={id}
                  defaultSize={layout.sizes[id] ?? meta.defaultSize}
                  minSize={meta.minSize}
                  showHandle={index < visibleOrder.length - 1}
                  loading={id === 'thread' ? loading : false}
                  panelRef={(handle) => {
                    if (handle) panelRefs.current[id] = handle
                    else delete panelRefs.current[id]
                  }}
                  onResize={(collapsed) => setPanelCollapsed(id, collapsed)}
                >
                  {nodes[id]}
                </DesktopPanel>
              )
            })}
          </ResizablePanelGroup>
        ) : (
          <div className="flex-1 min-h-0 overflow-hidden relative">
            {loading && layout.mobileActivePanel === 'thread' ? (
              <div className="absolute inset-0 z-10 bg-[#0d0f14]/80 flex items-center justify-center">
                <span className="text-sm text-slate-400">加载中…</span>
              </div>
            ) : null}
            {nodes[layout.mobileActivePanel]}
          </div>
        )}
      </div>
    </StudioLayoutProvider>
  )
}

function DesktopPanel({
  id,
  defaultSize,
  minSize,
  showHandle,
  loading,
  panelRef,
  onResize,
  children,
}: {
  id: StudioPanelId
  defaultSize: number
  minSize: number
  showHandle: boolean
  loading?: boolean
  panelRef: (handle: PanelImperativeHandle | null) => void
  onResize: (collapsed: boolean) => void
  children: ReactNode
}) {
  return (
    <>
      <ResizablePanel
        id={id}
        defaultSize={defaultSize}
        minSize={minSize}
        collapsible
        collapsedSize={0}
        onResize={(size) => onResize(size.asPercentage < 1)}
        className="min-w-0"
        panelRef={panelRef}
      >
        <div className="relative h-full min-h-0 overflow-hidden">
          {loading ? (
            <div className="absolute inset-0 z-10 bg-[#0d0f14]/80 flex items-center justify-center">
              <span className="text-sm text-slate-400">加载中…</span>
            </div>
          ) : null}
          {children}
        </div>
      </ResizablePanel>
      {showHandle ? <ResizableHandle withHandle /> : null}
    </>
  )
}
