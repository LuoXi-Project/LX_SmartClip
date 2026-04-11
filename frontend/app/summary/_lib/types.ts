/** 与后端 `note_*` 及提示词版式开关一致 */
export type NoteLayoutKey = 'toc' | 'timeJump' | 'screenshot' | 'aiSummary'

export type NoteLayoutOptions = Record<NoteLayoutKey, boolean>
