import type { AutoEditBgmPlanApi, AutoEditPlanApi } from '@/lib/api'
import type { ProductionProfileApi } from '@/lib/agent-types'
import { DEFAULT_SUBTITLE_STYLE, type SubtitleStyle } from '@/lib/subtitle-types'

export type StudioBgmMode = 'auto' | 'manual' | 'none'

export interface StudioMediaConfig {
  subtitle: {
    enabled: boolean
    style: SubtitleStyle
    strict_use_client_srt: boolean
    locked: boolean
  }
  bgm: {
    enabled: boolean
    mode: StudioBgmMode
    track_ids: string[]
    volume_db: number
    locked: boolean
  }
}

export const DEFAULT_STUDIO_MEDIA_CONFIG: StudioMediaConfig = {
  subtitle: {
    enabled: true,
    style: { ...DEFAULT_SUBTITLE_STYLE },
    strict_use_client_srt: false,
    locked: false,
  },
  bgm: {
    enabled: false,
    mode: 'auto',
    track_ids: [],
    volume_db: -12,
    locked: false,
  },
}

export function readStudioMediaConfig(
  prefs: Record<string, unknown> | undefined | null
): StudioMediaConfig {
  const raw = prefs?.media_config
  if (!raw || typeof raw !== 'object') {
    return {
      ...DEFAULT_STUDIO_MEDIA_CONFIG,
      subtitle: {
        ...DEFAULT_STUDIO_MEDIA_CONFIG.subtitle,
        style: { ...DEFAULT_SUBTITLE_STYLE },
      },
    }
  }
  const m = raw as Partial<StudioMediaConfig>
  return {
    subtitle: {
      ...DEFAULT_STUDIO_MEDIA_CONFIG.subtitle,
      ...(m.subtitle || {}),
      style: {
        ...DEFAULT_SUBTITLE_STYLE,
        ...(m.subtitle?.style || {}),
      },
    },
    bgm: {
      ...DEFAULT_STUDIO_MEDIA_CONFIG.bgm,
      ...(m.bgm || {}),
    },
  }
}

export function mergeBgmIntoPlan(
  plan: AutoEditPlanApi,
  media: StudioMediaConfig
): AutoEditPlanApi {
  const pb = plan.bgm
  const base = (): AutoEditBgmPlanApi => ({
    enabled: false,
    source: pb?.source ?? 'library',
    track_id: pb?.track_id ?? null,
    volume_db: pb?.volume_db ?? -12,
    loop: pb?.loop ?? true,
    fade_in_sec: pb?.fade_in_sec ?? 0.8,
    fade_out_sec: pb?.fade_out_sec ?? 1.0,
  })

  if (!media.bgm.enabled || media.bgm.mode === 'none') {
    return { ...plan, bgm: { ...base(), enabled: false } }
  }

  const vol = media.bgm.volume_db ?? pb?.volume_db ?? -12

  if (media.bgm.mode === 'manual' && media.bgm.track_ids.length > 0) {
    const primary = media.bgm.track_ids[0]
    return {
      ...plan,
      bgm: {
        ...base(),
        enabled: true,
        source: 'user',
        track_id: primary,
        track_ids: media.bgm.track_ids,
        volume_db: vol,
      },
    }
  }

  // auto：启用混音，曲目由后端 manifest / plan 决定
  return {
    ...plan,
    bgm: {
      ...base(),
      enabled: true,
      source: pb?.source ?? 'library',
      track_id: pb?.track_id ?? null,
      track_ids: pb?.track_ids,
      volume_db: vol,
    },
  }
}

export function readProductionProfile(
  prefs: Record<string, unknown> | undefined | null
): ProductionProfileApi {
  const raw = prefs?.production_profile
  if (raw && typeof raw === 'object') {
    return raw as ProductionProfileApi
  }
  return {
    preset_id: (prefs?.default_production_preset as ProductionProfileApi['preset_id']) || 'auto',
  }
}

export function bgmTrackLabel(
  trackIds: string[],
  tracks: Array<{ id: string; title?: string; filename?: string }>
): string {
  if (!trackIds.length) return '自动选曲'
  const id = trackIds[0]
  const hit = tracks.find((t) => t.id === id || t.filename === id)
  return hit?.title || hit?.filename || id.slice(0, 12)
}
