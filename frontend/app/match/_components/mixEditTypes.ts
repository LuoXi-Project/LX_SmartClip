/** 混剪顶层音轨模式 */
export type MixAudioMode = 'keep_original' | 'mute_all_original'

/** 模式二：成片音轨 */
export type MuteAudioTrack = 'ai_tts_asr' | 'ai_tts_llm' | 'bgm_only'

/** 混剪素材 clip 时长筛选与头尾裁剪 */
export type MixClipFilterConfig = {
  minDurationSec?: number
  maxDurationSec?: number
  trimHeadSec?: number
  trimTailSec?: number
}

export function buildMixClipFilterPayload(
  config: MixClipFilterConfig
): MixClipFilterConfig | undefined {
  const min =
    config.minDurationSec != null && Number.isFinite(config.minDurationSec) && config.minDurationSec > 0
      ? config.minDurationSec
      : undefined
  const max =
    config.maxDurationSec != null && Number.isFinite(config.maxDurationSec) && config.maxDurationSec > 0
      ? config.maxDurationSec
      : undefined
  const head =
    config.trimHeadSec != null && Number.isFinite(config.trimHeadSec) && config.trimHeadSec > 0
      ? config.trimHeadSec
      : undefined
  const tail =
    config.trimTailSec != null && Number.isFinite(config.trimTailSec) && config.trimTailSec > 0
      ? config.trimTailSec
      : undefined
  if (min == null && max == null && head == null && tail == null) return undefined
  return {
    ...(min != null ? { minDurationSec: min } : {}),
    ...(max != null ? { maxDurationSec: max } : {}),
    ...(head != null ? { trimHeadSec: head } : {}),
    ...(tail != null ? { trimTailSec: tail } : {}),
  }
}

/** 转为后端 API 字段（snake_case） */
export function toMixClipFilterApi(
  config: MixClipFilterConfig | undefined
):
  | {
      min_duration_sec?: number
      max_duration_sec?: number
      trim_head_sec?: number
      trim_tail_sec?: number
    }
  | undefined {
  const normalized = config ? buildMixClipFilterPayload(config) : undefined
  if (!normalized) return undefined
  return {
    ...(normalized.minDurationSec != null ? { min_duration_sec: normalized.minDurationSec } : {}),
    ...(normalized.maxDurationSec != null ? { max_duration_sec: normalized.maxDurationSec } : {}),
    ...(normalized.trimHeadSec != null ? { trim_head_sec: normalized.trimHeadSec } : {}),
    ...(normalized.trimTailSec != null ? { trim_tail_sec: normalized.trimTailSec } : {}),
  }
}
