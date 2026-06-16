/** 混剪后处理配置（与后端 MixPostprocessConfig 对齐） */

export type MixVisualRandomConfigApi = {
  enable_zoom: boolean
  zoom_probability: number
  zoom_ratio_min: number
  zoom_ratio_max: number
  zoom_min_interval_segments: number
  enable_mirror: boolean
  mirror_probability: number
  enable_rotation: boolean
  rotation_probability: number
  rotation_deg_min: number
  rotation_deg_max: number
  enable_color: boolean
  color_probability: number
  color_intensity_min: number
  color_intensity_max: number
}

export type MixOverlayVideoConfigApi = {
  enabled: boolean
  path?: string | null
  opacity: number
  volume: number
}

export type MixUserBgmConfigApi = {
  enabled: boolean
  path?: string | null
  volume: number
}

export type MixAntiDetectVideoConfigApi = {
  enabled: boolean
  enable_inpaint: boolean
  inpaint_strength: number
  enable_displacement: boolean
  displacement_px_max: number
  enable_color_shift: boolean
  color_shift_max: number
  enable_frame_ops: boolean
  frame_drop_probability: number
  frame_dup_probability: number
  enable_scale_jitter: boolean
  scale_jitter_max: number
  enable_pixel_noise: boolean
  pixel_noise_sigma: number
  enable_crawl: boolean
  crawl_amplitude_px: number
}

export type MixAntiDetectAudioConfigApi = {
  enabled: boolean
  enable_fingerprint_obfusc: boolean
  noise_floor_db: number
  enable_phase_eq: boolean
  enable_segment_speed: boolean
  speed_variation: number
  enable_reverb_pitch: boolean
  pitch_semitones: number
  reverb_mix: number
}

export type MixAntiDetectSchedulerConfigApi = {
  random_seed?: string | null
  loop_iterations: number
  loop_gain: number
  output_format: 'mp4' | 'mkv'
}

export type MixAntiDetectConfigApi = {
  enabled: boolean
  video?: MixAntiDetectVideoConfigApi
  audio?: MixAntiDetectAudioConfigApi
  scheduler?: MixAntiDetectSchedulerConfigApi
}

export type MixPostprocessConfigApi = {
  visual_random?: MixVisualRandomConfigApi | null
  overlay_video?: MixOverlayVideoConfigApi | null
  user_bgm?: MixUserBgmConfigApi | null
  anti_detect?: MixAntiDetectConfigApi | null
}

export const DEFAULT_MIX_VISUAL_RANDOM: MixVisualRandomConfigApi = {
  enable_zoom: true,
  zoom_probability: 0.4,
  zoom_ratio_min: 1.1,
  zoom_ratio_max: 1.2,
  zoom_min_interval_segments: 1,
  enable_mirror: true,
  mirror_probability: 0.3,
  enable_rotation: true,
  rotation_probability: 0.3,
  rotation_deg_min: -1.5,
  rotation_deg_max: 1.5,
  enable_color: true,
  color_probability: 0.5,
  color_intensity_min: -0.15,
  color_intensity_max: 0.15,
}

export const DEFAULT_MIX_POSTPROCESS: MixPostprocessConfigApi = {
  visual_random: { ...DEFAULT_MIX_VISUAL_RANDOM },
  overlay_video: {
    enabled: false,
    path: '',
    opacity: 0.15,
    volume: 0.1,
  },
  anti_detect: {
    enabled: false,
    video: {
      enabled: true,
      enable_inpaint: true,
      inpaint_strength: 0.55,
      enable_displacement: true,
      displacement_px_max: 3,
      enable_color_shift: true,
      color_shift_max: 0.06,
      enable_frame_ops: true,
      frame_drop_probability: 0.012,
      frame_dup_probability: 0.015,
      enable_scale_jitter: true,
      scale_jitter_max: 0.025,
      enable_pixel_noise: true,
      pixel_noise_sigma: 2.2,
      enable_crawl: true,
      crawl_amplitude_px: 8,
    },
    audio: {
      enabled: true,
      enable_fingerprint_obfusc: true,
      noise_floor_db: -46,
      enable_phase_eq: true,
      enable_segment_speed: true,
      speed_variation: 0.035,
      enable_reverb_pitch: true,
      pitch_semitones: 0.35,
      reverb_mix: 0.09,
    },
    scheduler: {
      random_seed: '',
      loop_iterations: 1,
      loop_gain: 1.18,
      output_format: 'mp4',
    },
  },
}

export function buildMixPostprocessPayload(
  cfg: MixPostprocessConfigApi,
): MixPostprocessConfigApi | undefined {
  const vr = cfg.visual_random
  const hasVisual =
    vr &&
    (vr.enable_zoom || vr.enable_mirror || vr.enable_rotation || vr.enable_color)
  const ov = cfg.overlay_video
  const hasOverlay = Boolean(ov?.enabled && (ov.path || '').trim())
  const ad = cfg.anti_detect
  const hasAntiDetect = Boolean(ad?.enabled)
  if (!hasVisual && !hasOverlay && !hasAntiDetect) return undefined
  return {
    visual_random: hasVisual ? vr : undefined,
    overlay_video: hasOverlay
      ? {
          enabled: true,
          path: (ov!.path || '').trim(),
          opacity: ov!.opacity,
          volume: ov!.volume,
        }
      : undefined,
    anti_detect: hasAntiDetect
      ? {
          enabled: true,
          video: ad!.video,
          audio: ad!.audio,
          scheduler: ad!.scheduler
            ? {
                ...ad!.scheduler,
                random_seed: (ad!.scheduler.random_seed || '').trim() || undefined,
              }
            : undefined,
        }
      : undefined,
  }
}
