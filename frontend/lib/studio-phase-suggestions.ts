import type { PipelinePhase, WorkspaceState } from '@/lib/agent-types'

/** 按工作区阶段给出默认快捷指令（Codex 式「下一步」提示） */
export function getPhaseSuggestions(workspace: WorkspaceState | null): string[] {
  if (!workspace) {
    return ['列出素材库里的视频', '帮我选 3 个视频做 60 秒口播方案']
  }

  const phase = workspace.pipeline_phase as PipelinePhase
  const videoCount = workspace.selected_video_ids?.length ?? 0
  const planCount = workspace.plans?.length ?? 0
  const hasProcessJob = (workspace.jobs?.process_task_ids?.length ?? 0) > 0

  switch (phase) {
    case 'idle':
    case 'ingest':
      if (videoCount === 0) {
        return ['列出所有视频', '帮我找适合口播的素材', '选 3 个视频做方案']
      }
      if (hasProcessJob) {
        return ['查询素材处理进度', '处理完成后生成 60 秒口播方案']
      }
      return ['开始处理选中素材', '用选中素材做 60 秒电商口播方案']

    case 'process':
      return ['查询处理进度', '处理完成后生成口播方案']

    case 'match':
      return ['生成自动剪辑方案', '做 60 秒口播方案']

    case 'plan':
    case 'realize':
      if (planCount > 0) {
        return ['导出成片', '导出剪映草稿', '把方案改成 45 秒']
      }
      return ['生成剪辑方案', '做 60 秒口播方案']

    case 'export':
      return ['再做一个新方案', '导出剪映草稿', '字幕改成大字黄色']

    default:
      if (planCount > 0) return ['导出成片', '调整方案']
      if (videoCount > 0) return ['生成剪辑方案']
      return ['列出所有视频']
  }
}

/** Agent suggestions 优先，再补阶段默认，去重并限制条数 */
export function mergeSuggestionChips(
  agentItems: string[],
  workspace: WorkspaceState | null,
  max = 4
): string[] {
  const phaseItems = getPhaseSuggestions(workspace)
  const seen = new Set<string>()
  const out: string[] = []

  for (const raw of [...agentItems, ...phaseItems]) {
    const label = raw.trim()
    if (!label || seen.has(label)) continue
    seen.add(label)
    out.push(label)
    if (out.length >= max) break
  }
  return out
}
