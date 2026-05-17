import type { AutoEditPlanApi, TtsVideoAlignConfigApi } from '@/lib/api'

export const DEFAULT_VOICEOVER_TTS_ALIGN: TtsVideoAlignConfigApi = {
  policy: 'loop_video_to_cover',
  max_audio_atempo: 2,
  min_audio_atempo: 0.5,
  max_video_pts_factor: 2,
  min_video_pts_factor: 0.5,
}

const PLACEHOLDER_ASR_TEXT = /^（/

/** 方案中每一段均有可用 ASR 文案时，才允许「重新配音」成片 */
export function voiceoverPlanSupportsRedub(plan: AutoEditPlanApi): boolean {
  const segments = plan.segments?.filter((s) => !s.exclude_from_output) ?? []
  if (!segments.length) return false
  return segments.every((s) => {
    const sub = s.subtitle
    const text = sub?.text?.trim()
    if (!text) return false
    if (sub?.strategy !== 'asr' || sub?.source !== 'asr') return false
    if (PLACEHOLDER_ASR_TEXT.test(text)) return false
    return true
  })
}

/** 将方案改为 TTS 导出（文案仍为各段 subtitle.text，通常为 ASR） */
export function buildVoiceoverRedubPlan(plan: AutoEditPlanApi): AutoEditPlanApi {
  return {
    ...plan,
    segments: plan.segments.map((s) =>
      s.exclude_from_output ? s : { ...s, audio_mode: 'tts' as const }
    ),
  }
}
