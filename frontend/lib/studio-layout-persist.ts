export type StudioPanelId = 'thread' | 'canvas' | 'inspector'

export const STUDIO_LAYOUT_STORAGE_KEY = 'lx-studio-layout-v1'

export const PANEL_META: Record<
  StudioPanelId,
  { label: string; shortLabel: string; defaultSize: number; minSize: number }
> = {
  thread: { label: '对话', shortLabel: '对话', defaultSize: 25, minSize: 12 },
  canvas: { label: '产物画布', shortLabel: '画布', defaultSize: 42, minSize: 20 },
  inspector: { label: '检查器', shortLabel: '检查器', defaultSize: 33, minSize: 15 },
}

export const DEFAULT_PANEL_ORDER: StudioPanelId[] = ['thread', 'canvas', 'inspector']

export type StudioLayoutState = {
  panelOrder: StudioPanelId[]
  sizes: Partial<Record<StudioPanelId, number>>
  collapsed: Partial<Record<StudioPanelId, boolean>>
  visible: Record<StudioPanelId, boolean>
  mobileActivePanel: StudioPanelId
}

export const DEFAULT_LAYOUT: StudioLayoutState = {
  panelOrder: [...DEFAULT_PANEL_ORDER],
  sizes: {},
  collapsed: {},
  visible: { thread: true, canvas: true, inspector: true },
  mobileActivePanel: 'thread',
}

function isPanelId(v: unknown): v is StudioPanelId {
  return v === 'thread' || v === 'canvas' || v === 'inspector'
}

function normalizeOrder(order: unknown): StudioPanelId[] {
  if (!Array.isArray(order)) return [...DEFAULT_PANEL_ORDER]
  const seen = new Set<StudioPanelId>()
  const next: StudioPanelId[] = []
  for (const item of order) {
    if (isPanelId(item) && !seen.has(item)) {
      seen.add(item)
      next.push(item)
    }
  }
  for (const id of DEFAULT_PANEL_ORDER) {
    if (!seen.has(id)) next.push(id)
  }
  return next
}

export function readStudioLayout(): StudioLayoutState {
  if (typeof window === 'undefined') return { ...DEFAULT_LAYOUT, panelOrder: [...DEFAULT_PANEL_ORDER] }
  try {
    const raw = localStorage.getItem(STUDIO_LAYOUT_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_LAYOUT, panelOrder: [...DEFAULT_PANEL_ORDER] }
    const parsed = JSON.parse(raw) as Partial<StudioLayoutState>
    return {
      panelOrder: normalizeOrder(parsed.panelOrder),
      sizes: parsed.sizes ?? {},
      collapsed: parsed.collapsed ?? {},
      visible: {
        thread: parsed.visible?.thread !== false,
        canvas: parsed.visible?.canvas !== false,
        inspector: parsed.visible?.inspector !== false,
      },
      mobileActivePanel: isPanelId(parsed.mobileActivePanel)
        ? parsed.mobileActivePanel
        : DEFAULT_LAYOUT.mobileActivePanel,
    }
  } catch {
    return { ...DEFAULT_LAYOUT, panelOrder: [...DEFAULT_PANEL_ORDER] }
  }
}

export function writeStudioLayout(state: StudioLayoutState) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(STUDIO_LAYOUT_STORAGE_KEY, JSON.stringify(state))
  } catch {
    /* ignore */
  }
}

export function movePanelInOrder(
  order: StudioPanelId[],
  id: StudioPanelId,
  direction: -1 | 1
): StudioPanelId[] {
  const idx = order.indexOf(id)
  if (idx < 0) return order
  const target = idx + direction
  if (target < 0 || target >= order.length) return order
  const next = [...order]
  ;[next[idx], next[target]] = [next[target], next[idx]]
  return next
}

export function reorderPanels(order: StudioPanelId[], from: number, to: number): StudioPanelId[] {
  if (from === to || from < 0 || to < 0 || from >= order.length || to >= order.length) return order
  const next = [...order]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

export function visiblePanelCount(visible: Record<StudioPanelId, boolean>): number {
  return (['thread', 'canvas', 'inspector'] as StudioPanelId[]).filter((id) => visible[id]).length
}

export function ensureAtLeastOneVisible(
  visible: Record<StudioPanelId, boolean>,
  toggledId: StudioPanelId
): Record<StudioPanelId, boolean> {
  const next = { ...visible, [toggledId]: !visible[toggledId] }
  if (visiblePanelCount(next) === 0) return visible
  return next
}
