/**
 * 与手动匹配 `toggleClipSelected` 一致：在有序列表中切换某个 id（存在则全部去掉，否则追加）。
 * 用于「同一条只出现一次」的多选。
 */
export function toggleIdInOrderedList(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]
}

/** 在末尾再追加一条，用于同组内复用同一段素材（需配合 Shift+点击等入口） */
export function appendIdToOrderedList(ids: string[], id: string): string[] {
  return [...ids, id]
}

/**
 * 返回该 key 在成组顺序中所有 1-based 位次，用于多选组内同 key 复用时显示序号（如 1、3 或 ×2）。
 */
export function orderPositionsForKey(orderedKeys: string[], key: string): number[] {
  const out: number[] = []
  orderedKeys.forEach((k, i) => {
    if (k === key) out.push(i + 1)
  })
  return out
}
