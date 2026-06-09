import type { AutoEditMode, AutoEditPlanApi } from '@/lib/api'

export interface PlanAudioSummaryApi {
  mode: AutoEditMode
  tts_count: number
  original_count: number
  mute_count: number
  active_segment_count: number
  will_export_tts: boolean
  will_keep_original: boolean
  label: string
  short: string
  warnings: string[]
}

function computeFromSegments(plan: AutoEditPlanApi): PlanAudioSummaryApi {
  const segs = (plan.segments || []).filter((s) => !s.exclude_from_output)
  let tts = 0
  let original = 0
  let mute = 0
  for (const s of segs) {
    if (s.audio_mode === 'tts') tts++
    else if (s.audio_mode === 'mute') mute++
    else original++
  }
  const mode = plan.mode || 'auto'
  const will_export_tts = tts > 0 && (mode === 'voiceover' || mode === 'auto')
  const will_keep_original = original > 0 && mode === 'original'
  const mixed = tts > 0 && original > 0

  let label: string
  let short: string
  if (mode === 'voiceover') {
    if (tts === segs.length && segs.length > 0) {
      label = '全片 AI 配音'
      short = `${tts} 段将合成 TTS 并替换音轨`
    } else if (tts > 0) {
      label = '以 AI 配音为主'
      short = `${tts} 段 TTS · ${mute} 段静音 · ${original} 段原声`
    } else {
      label = '配音方案（无 TTS 段）'
      short = '当前无段落标记为 TTS，成片可能不会配音'
    }
  } else if (mode === 'original') {
    label = original === segs.length && segs.length > 0 ? '保留素材原声' : '原声剪辑'
    short = `${original} 段原声` + (mute ? ` · ${mute} 段静音` : '') + '，不强制 TTS'
  } else if (mixed) {
    label = '配音 + 原声混合'
    short = `${tts} 段 TTS · ${original} 段原声 · ${mute} 段静音`
  } else if (tts === segs.length && segs.length > 0) {
    label = '全片 AI 配音'
    short = `${tts} 段 TTS`
  } else if (original === segs.length && segs.length > 0) {
    label = '全片保留原声'
    short = `${original} 段原声`
  } else {
    label = '自动混合'
    short = `${tts} 段 TTS · ${original} 段原声 · ${mute} 段静音`
  }

  const warnings: string[] = []
  if (mode === 'voiceover' && tts === 0 && segs.length > 0) {
    warnings.push('方案为配音模式，但没有段落标记 TTS，成片可能无 AI 配音')
  }
  if (mode === 'voiceover' && mute > 0 && tts < segs.length) {
    warnings.push(`${mute} 段为静音，成片时这些段落无旁白（仅画面/BGM）`)
  }

  return {
    mode,
    tts_count: tts,
    original_count: original,
    mute_count: mute,
    active_segment_count: segs.length,
    will_export_tts,
    will_keep_original,
    label,
    short,
    warnings,
  }
}

export function getPlanAudioSummary(plan: AutoEditPlanApi): PlanAudioSummaryApi {
  const raw = plan.audio_summary
  if (raw && typeof raw.label === 'string' && raw.label.length > 0) {
    return {
      mode: (raw.mode || plan.mode || 'auto') as AutoEditMode,
      tts_count: Number(raw.tts_count ?? 0),
      original_count: Number(raw.original_count ?? 0),
      mute_count: Number(raw.mute_count ?? 0),
      active_segment_count: Number(raw.active_segment_count ?? 0),
      will_export_tts: Boolean(raw.will_export_tts),
      will_keep_original: Boolean(raw.will_keep_original),
      label: raw.label,
      short: raw.short || '',
      warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
    }
  }
  return computeFromSegments(plan)
}
