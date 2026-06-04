/** StageA 分段 JSON 摘要 → 生成中可读的 Markdown 预览 */

export type StageASegment = {
  title?: string
  overview?: string
  chapters?: Array<{
    title?: string
    summary?: string
    key_points?: string[]
    evidence?: string[]
  }>
  key_points?: string[]
  highlights?: string[]
  quotes?: string[]
  action_items?: string[]
  tags?: string[]
}

function bulletList(items: string[] | undefined, empty = '（无）'): string {
  if (!items?.length) return empty
  return items.map((x) => `- ${x}`).join('\n')
}

function formatOneSegment(seg: StageASegment, index: number, total: number): string {
  const parts: string[] = []
  const title = seg.title?.trim() || `分段 ${index}`
  parts.push(`### 第 ${index}/${total} 段 · ${title}`)
  if (seg.overview?.trim()) {
    parts.push('', '**概述**', '', seg.overview.trim())
  }
  if (seg.chapters?.length) {
    parts.push('', '**章节**', '')
    for (const ch of seg.chapters) {
      const chTitle = ch.title?.trim() || '章节'
      parts.push(`- **${chTitle}**`)
      if (ch.summary?.trim()) parts.push(`  - ${ch.summary.trim()}`)
      if (ch.key_points?.length) {
        parts.push('  - 要点：' + ch.key_points.join('；'))
      }
    }
  }
  if (seg.key_points?.length) {
    parts.push('', '**要点**', '', bulletList(seg.key_points))
  }
  if (seg.highlights?.length) {
    parts.push('', '**亮点**', '', bulletList(seg.highlights))
  }
  if (seg.quotes?.length) {
    parts.push('', '**金句**', '', seg.quotes.map((q) => `> ${q}`).join('\n\n'))
  }
  return parts.join('\n')
}

export function formatStageAProgressMarkdown(
  segments: StageASegment[],
  opts: { idx: number; total: number; phase?: 'stage_a' | 'stage_b' },
): string {
  const { idx, total, phase = 'stage_a' } = opts
  const header =
    phase === 'stage_b'
      ? `# 正在生成完整笔记\n\n分段分析已完成（${total}/${total}），正在流式写入 Markdown…\n`
      : `# 分段分析进行中\n\n已完成 **${idx}/${total}** 段，下方为已产出摘要（最终笔记将在全部段完成后合并生成）。\n`
  const body = segments.map((s, i) => formatOneSegment(s, i + 1, total)).join('\n\n---\n\n')
  return `${header}\n---\n\n${body}\n`
}
