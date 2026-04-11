/** 与后端 `note_*` 及提示词「目录 / 原片跳转 / 截图 / AI 总结」一致 */
export const NOTE_LAYOUT_ROWS = [
  { k: 'toc' as const, label: '目录', desc: '文首 TOC，链到各级标题' },
  { k: 'timeJump' as const, label: '原片跳转', desc: '可点击时间，跳转下方预览' },
  { k: 'screenshot' as const, label: '原片截图位', desc: '节末 *Screenshot-[mm:ss] / *Screenshot-mm:ss 占位，服务端落盘' },
  { k: 'aiSummary' as const, label: 'AI 总结', desc: '总览末尾整片小结' },
] as const
