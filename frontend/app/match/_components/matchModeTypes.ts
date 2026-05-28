/** 智能剪辑页工作区模式：v3/v4 为新产品线入口，与后端阶段对应 */
export type MatchWorkspaceMode =
  | 'manual'
  | 'audio_match'
  | 'voiceover'
  | 'auto'
  | 'template'
  | 'replica'
  | 'script_stock'
  | 'mix_edit'
  | 'video_dub'
  | 'film_commentary'

/** 段落文案 + 检索 clip + 侧栏 ZIP/成片导出（手动匹配、音频匹配） */
export function isManualLikeMode(m: MatchWorkspaceMode): boolean {
  return m === 'manual' || m === 'audio_match'
}

/** 方案驱动成片：自动实验 / 模板 / 口播快剪（侧栏提示在主区方案卡片一键成片） */
export function isAutoLikeMode(m: MatchWorkspaceMode): boolean {
  return (
    m === 'auto' ||
    m === 'template' ||
    m === 'voiceover' ||
    m === 'replica' ||
    m === 'script_stock' ||
    m === 'mix_edit' ||
    m === 'video_dub' ||
    m === 'film_commentary'
  )
}

export function normalizeMatchWorkspaceMode(raw: unknown): MatchWorkspaceMode {
  if (
    raw === 'manual' ||
    raw === 'audio_match' ||
    raw === 'voiceover' ||
    raw === 'auto' ||
    raw === 'template' ||
    raw === 'replica' ||
    raw === 'script_stock' ||
    raw === 'mix_edit' ||
    raw === 'video_dub' ||
    raw === 'film_commentary'
  )
    return raw
  return 'manual'
}
