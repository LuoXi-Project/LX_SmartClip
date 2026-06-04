import type { AutoEditMode, AutoEditPlanApi } from '@/lib/api'

export type PlanModeGuide = {
  mode: AutoEditMode
  label: string
  short: string
  pipeline: string[]
  bestFor: string[]
  avoidWhen: string[]
}

export type ExportPathId = 'mp4' | 'jianying' | 'tts_override'

export type ExportPathGuide = {
  id: ExportPathId
  title: string
  subtitle: string
  steps: string[]
  output: string
  recommended: boolean
  caution?: string
}

const MODE_GUIDES: Record<AutoEditMode, PlanModeGuide> = {
  voiceover: {
    mode: 'voiceover',
    label: '配音剪辑方案',
    short: 'AI 配音驱动节奏，字幕对齐 TTS',
    pipeline: [
      '按方案选段并合成 TTS 配音',
      '按配音时长生成/对齐字幕时间轴',
      '拼接画面 + 替换音轨 + 可选 BGM 混音',
      '烧录字幕后输出 MP4',
    ],
    bestFor: ['口播解说', '电商带货', '知识讲解', '需要统一人声'],
    avoidWhen: ['必须保留现场同期声', '已有专业配音只需剪辑'],
  },
  original: {
    mode: 'original',
    label: '原声剪辑方案',
    short: '保留素材原声，按画面时长拼接',
    pipeline: [
      '按方案选段拼接视频',
      '保留片段原声/同期声（不强制 TTS）',
      '音频归一化/限幅，可选 BGM',
      '可选烧录字幕（文案来自方案/句读）',
    ],
    bestFor: ['采访/Vlog', '现场录制', '音乐/氛围为主的片子'],
    avoidWhen: ['需要全新 AI 旁白覆盖原声'],
  },
  auto: {
    mode: 'auto',
    label: '自动混合方案',
    short: '系统按段落文案自动选择配音或原声',
    pipeline: [
      '有旁白文案的段落 → 走 TTS 配音管线',
      '无文案/强调现场感的段落 → 保留原声',
      '统一时间轴后混音、字幕与导出',
    ],
    bestFor: ['素材类型混杂', '快速出初版'],
    avoidWhen: ['要求全片统一为单一听感（建议生成时指定口播或原声）'],
  },
}

export function getPlanModeGuide(mode: AutoEditMode | undefined): PlanModeGuide {
  return MODE_GUIDES[mode || 'auto']
}

export function getExportPathsForPlan(plan: AutoEditPlanApi): ExportPathGuide[] {
  const mode = plan.mode || 'auto'
  const subtitleOn = true // 实际以检查器为准；文案中说明

  const mp4Voiceover: ExportPathGuide = {
    id: 'mp4',
    title: '导出成片 MP4',
    subtitle: '一键渲染最终视频，可直接发布',
    steps: [
      '合成 TTS（有文案段落）',
      '生成字幕时间轴并烧录',
      'FFmpeg 拼接 + BGM 混音',
      '输出完整 MP4',
    ],
    output: '带配音/字幕的成品视频',
    recommended: mode === 'voiceover' || mode === 'auto',
    caution:
      mode === 'original'
        ? '当前为原声方案：默认保留素材原声。若需全片 AI 配音，请用下方「重新配音导出」或在对话中说「不保留原声，进行 tts 配音」。'
        : undefined,
  }

  const mp4Original: ExportPathGuide = {
    id: 'mp4',
    title: '导出成片 MP4',
    subtitle: '保留原声拼接，可选烧录字幕',
    steps: [
      '按段落 clip 拼接画面',
      '保留原声轨并做响度处理',
      subtitleOn ? '按方案文案生成字幕并烧录' : '不烧录字幕（可在检查器关闭）',
      '输出完整 MP4',
    ],
    output: '听感接近素材现场的成品视频',
    recommended: mode === 'original',
  }

  const jianying: ExportPathGuide = {
    id: 'jianying',
    title: '导出剪映草稿',
    subtitle: '不在此步渲染 MP4，供剪映内二次精剪',
    steps: [
      '打包时间轴、素材引用与 TTS/字幕轨',
      '下载 ZIP 或写入本机剪映目录',
      '在剪映内调色、改字、换音乐后再导出',
    ],
    output: '剪映工程（效果取决于你在剪映中的操作）',
    recommended: false,
    caution: '与「成片 MP4」不是同一条流水线：草稿不会在洛曦内直接生成最终片。',
  }

  const ttsOverride: ExportPathGuide = {
    id: 'tts_override',
    title: '重新配音导出',
    subtitle: '在对话中触发：强制 TTS，不保留原声',
    steps: [
      '对话发送：「不保留原声，进行 tts 配音」',
      '或生成方案时明确「口播/配音」诉求',
      '确认后按配音管线渲染 MP4',
    ],
    output: '全片 AI 配音风格的 MP4',
    recommended: mode === 'original',
    caution: '会改变听感，与「原声方案」设计目标相反，请确认后再用。',
  }

  if (mode === 'original') {
    return [mp4Original, jianying, ttsOverride]
  }
  if (mode === 'voiceover') {
    return [{ ...mp4Voiceover, recommended: true }, jianying]
  }
  return [mp4Voiceover, jianying, ttsOverride]
}

/** 方案生成后给对话区的快捷指令（与 export_intent 对齐） */
export function planNextSuggestions(plan: AutoEditPlanApi): string[] {
  const mode = plan.mode || 'auto'
  if (mode === 'original') {
    return ['导出成片（保留原声）', '导出剪映草稿', '不保留原声，进行tts配音']
  }
  if (mode === 'voiceover') {
    return ['导出成片（配音版）', '导出剪映草稿']
  }
  return ['导出成片', '导出剪映草稿', '不保留原声，进行tts配音']
}

export const STUDIO_WORKFLOW_HINT = [
  '1. 对话选素材并说明诉求（口播 / 原声 / 时长）',
  '2. 生成方案后在画布查看模式与时间轴',
  '3. 按方案类型选择「成片 MP4」或「剪映草稿」',
  '4. 右侧检查器调整字幕、BGM、制作风格后再导出',
].join('\n')
