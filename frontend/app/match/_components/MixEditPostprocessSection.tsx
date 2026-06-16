'use client'

import { useRef, useState } from 'react'
import { Film, Shield, Sparkles } from 'lucide-react'
import { useToast } from '@/components/ui/toast-provider'
import { autoEditApi } from '@/lib/api'
import type {
  MixAntiDetectConfigApi,
  MixPostprocessConfigApi,
  MixVisualRandomConfigApi,
} from './mixEditPostprocessTypes'

type MixEditPostprocessSectionProps = {
  value: MixPostprocessConfigApi
  onChange: (next: MixPostprocessConfigApi) => void
  disabled?: boolean
}

function NumInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  disabled,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  disabled?: boolean
}) {
  return (
    <label className="block space-y-0.5">
      <span className="text-[10px] text-slate-500">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 0.01}
        disabled={disabled}
        onChange={(e) => {
          const n = Number(e.target.value)
          if (Number.isFinite(n)) onChange(n)
        }}
        className="w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 disabled:opacity-50"
      />
    </label>
  )
}

function OverlayPathRow({
  label,
  placeholder,
  path,
  disabled,
  onPathChange,
}: {
  label: string
  placeholder: string
  path: string
  disabled?: boolean
  onPathChange: (path: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const toast = useToast()

  const handleFile = async (file: File | null) => {
    if (!file) return
    setUploading(true)
    try {
      const res = await autoEditApi.mixUploadAsset(file, 'overlay')
      onPathChange(res.path || res.stored_path || '')
      toast.success('文件已上传')
    } catch (e: unknown) {
      toast.error((e as Error)?.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-1">
      <span className="text-[10px] text-slate-500">{label}</span>
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text"
          value={path}
          disabled={disabled}
          onChange={(e) => onPathChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 min-w-[12rem] rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 disabled:opacity-50"
        />
        <button
          type="button"
          disabled={disabled || uploading}
          onClick={() => inputRef.current?.click()}
          className="px-2.5 py-1.5 rounded-md border border-slate-600 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          {uploading ? '上传中…' : '选择文件…'}
        </button>
        <button
          type="button"
          disabled={disabled || !path}
          onClick={() => onPathChange('')}
          className="px-2.5 py-1.5 rounded-md border border-slate-700 text-[11px] text-slate-500 hover:text-slate-300 disabled:opacity-50"
        >
          清空
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="video/*,.mp4,.mov,.mkv,.webm"
          className="hidden"
          onChange={(e) => {
            void handleFile(e.target.files?.[0] ?? null)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}

function VisualBlock({
  vr,
  disabled,
  onChange,
}: {
  vr: MixVisualRandomConfigApi
  disabled?: boolean
  onChange: (patch: Partial<MixVisualRandomConfigApi>) => void
}) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3">
      <p className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
        <Sparkles className="w-3.5 h-3.5 text-violet-400" />
        视觉随机变换
      </p>

      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input
          type="checkbox"
          checked={vr.enable_zoom}
          disabled={disabled}
          onChange={(e) => onChange({ enable_zoom: e.target.checked })}
          className="rounded border-slate-600"
        />
        启用随机放大
      </label>
      {vr.enable_zoom ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pl-5">
          <NumInput label="放大概率" value={vr.zoom_probability} min={0} max={1} step={0.01} disabled={disabled} onChange={(v) => onChange({ zoom_probability: v })} />
          <NumInput label="放大倍率下限" value={vr.zoom_ratio_min} min={1} max={3} step={0.01} disabled={disabled} onChange={(v) => onChange({ zoom_ratio_min: v })} />
          <NumInput label="放大倍率上限" value={vr.zoom_ratio_max} min={1} max={3} step={0.01} disabled={disabled} onChange={(v) => onChange({ zoom_ratio_max: v })} />
          <NumInput label="最小间隔片段" value={vr.zoom_min_interval_segments} min={0} max={100} step={1} disabled={disabled} onChange={(v) => onChange({ zoom_min_interval_segments: Math.round(v) })} />
        </div>
      ) : null}

      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={vr.enable_mirror} disabled={disabled} onChange={(e) => onChange({ enable_mirror: e.target.checked })} className="rounded border-slate-600" />
        启用水平镜像
      </label>
      {vr.enable_mirror ? (
        <div className="pl-5 max-w-[10rem]">
          <NumInput label="镜像概率" value={vr.mirror_probability} min={0} max={1} disabled={disabled} onChange={(v) => onChange({ mirror_probability: v })} />
        </div>
      ) : null}

      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={vr.enable_rotation} disabled={disabled} onChange={(e) => onChange({ enable_rotation: e.target.checked })} className="rounded border-slate-600" />
        启用随机旋转
      </label>
      {vr.enable_rotation ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pl-5">
          <NumInput label="旋转概率" value={vr.rotation_probability} min={0} max={1} disabled={disabled} onChange={(v) => onChange({ rotation_probability: v })} />
          <NumInput label="旋转角度下限 (度)" value={vr.rotation_deg_min} min={-45} max={45} disabled={disabled} onChange={(v) => onChange({ rotation_deg_min: v })} />
          <NumInput label="旋转角度上限 (度)" value={vr.rotation_deg_max} min={-45} max={45} disabled={disabled} onChange={(v) => onChange({ rotation_deg_max: v })} />
        </div>
      ) : null}

      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" checked={vr.enable_color} disabled={disabled} onChange={(e) => onChange({ enable_color: e.target.checked })} className="rounded border-slate-600" />
        启用随机调色（饱和度/色温/色调）
      </label>
      {vr.enable_color ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pl-5">
          <NumInput label="调色概率" value={vr.color_probability} min={0} max={1} disabled={disabled} onChange={(v) => onChange({ color_probability: v })} />
          <NumInput label="调色强度下限" value={vr.color_intensity_min} min={-1} max={1} step={0.001} disabled={disabled} onChange={(v) => onChange({ color_intensity_min: v })} />
          <NumInput label="调色强度上限" value={vr.color_intensity_max} min={-1} max={1} step={0.001} disabled={disabled} onChange={(v) => onChange({ color_intensity_max: v })} />
        </div>
      ) : null}
    </div>
  )
}

function AntiDetectBlock({
  ad,
  disabled,
  onChange,
}: {
  ad: MixAntiDetectConfigApi
  disabled?: boolean
  onChange: (patch: Partial<MixAntiDetectConfigApi>) => void
}) {
  const video = ad.video!
  const audio = ad.audio!
  const scheduler = ad.scheduler!

  return (
    <div className="space-y-3 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-3">
      <p className="text-xs font-semibold text-emerald-200 flex items-center gap-1.5">
        <Shield className="w-3.5 h-3.5" />
        防检测管线（成片导出后处理）
      </p>
      <p className="text-[10px] text-slate-500">
        FFmpeg 解码分离 → OpenCV 画面扰动 + Librosa/FFmpeg 音频混淆 → 调度循环 → MP4 归档
      </p>
      <label className="flex items-center gap-2 text-xs text-slate-300">
        <input
          type="checkbox"
          checked={ad.enabled}
          disabled={disabled}
          onChange={(e) => onChange({ enabled: e.target.checked })}
          className="rounded border-slate-600"
        />
        启用防检测后处理
      </label>

      {ad.enabled ? (
        <div className="space-y-3 pl-1 border-l border-emerald-500/20 ml-1">
          <div className="space-y-2">
            <p className="text-[11px] font-medium text-slate-400">画面管线</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={video.enable_inpaint} disabled={disabled}
                  onChange={(e) => onChange({ video: { ...video, enable_inpaint: e.target.checked } })}
                  className="rounded border-slate-600" />
                痕迹擦除
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={video.enable_displacement} disabled={disabled}
                  onChange={(e) => onChange({ video: { ...video, enable_displacement: e.target.checked } })}
                  className="rounded border-slate-600" />
                位移扰动
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={video.enable_crawl} disabled={disabled}
                  onChange={(e) => onChange({ video: { ...video, enable_crawl: e.target.checked } })}
                  className="rounded border-slate-600" />
                爬行轨迹
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={video.enable_pixel_noise} disabled={disabled}
                  onChange={(e) => onChange({ video: { ...video, enable_pixel_noise: e.target.checked } })}
                  className="rounded border-slate-600" />
                像素增强
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={video.enable_frame_ops} disabled={disabled}
                  onChange={(e) => onChange({ video: { ...video, enable_frame_ops: e.target.checked } })}
                  className="rounded border-slate-600" />
                抽补帧
              </label>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <NumInput label="爬行幅度(px)" value={video.crawl_amplitude_px} min={0} max={48} disabled={disabled}
                onChange={(v) => onChange({ video: { ...video, crawl_amplitude_px: v } })} />
              <NumInput label="位移上限(px)" value={video.displacement_px_max} min={0} max={20} disabled={disabled}
                onChange={(v) => onChange({ video: { ...video, displacement_px_max: v } })} />
              <NumInput label="像素噪声σ" value={video.pixel_noise_sigma} min={0} max={12} disabled={disabled}
                onChange={(v) => onChange({ video: { ...video, pixel_noise_sigma: v } })} />
              <NumInput label="擦除强度" value={video.inpaint_strength} min={0} max={1} disabled={disabled}
                onChange={(v) => onChange({ video: { ...video, inpaint_strength: v } })} />
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-[11px] font-medium text-slate-400">音频管线</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={audio.enable_fingerprint_obfusc} disabled={disabled}
                  onChange={(e) => onChange({ audio: { ...audio, enable_fingerprint_obfusc: e.target.checked } })}
                  className="rounded border-slate-600" />
                频谱混淆
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={audio.enable_segment_speed} disabled={disabled}
                  onChange={(e) => onChange({ audio: { ...audio, enable_segment_speed: e.target.checked } })}
                  className="rounded border-slate-600" />
                分段变速
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={audio.enable_reverb_pitch} disabled={disabled}
                  onChange={(e) => onChange({ audio: { ...audio, enable_reverb_pitch: e.target.checked } })}
                  className="rounded border-slate-600" />
                混响变调
              </label>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <NumInput label="变速幅度" value={audio.speed_variation} min={0} max={0.15} disabled={disabled}
                onChange={(v) => onChange({ audio: { ...audio, speed_variation: v } })} />
              <NumInput label="变调(半音)" value={audio.pitch_semitones} min={-2} max={2} disabled={disabled}
                onChange={(v) => onChange({ audio: { ...audio, pitch_semitones: v } })} />
              <NumInput label="混响混合" value={audio.reverb_mix} min={0} max={0.45} disabled={disabled}
                onChange={(v) => onChange({ audio: { ...audio, reverb_mix: v } })} />
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-[11px] font-medium text-slate-400">调度引擎</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <label className="block space-y-0.5 sm:col-span-2">
                <span className="text-[10px] text-slate-500">随机种子（留空自动生成）</span>
                <input
                  type="text"
                  value={scheduler.random_seed || ''}
                  disabled={disabled}
                  onChange={(e) => onChange({ scheduler: { ...scheduler, random_seed: e.target.value } })}
                  className="w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 disabled:opacity-50"
                />
              </label>
              <NumInput label="循环次数" value={scheduler.loop_iterations} min={1} max={5} step={1} disabled={disabled}
                onChange={(v) => onChange({ scheduler: { ...scheduler, loop_iterations: Math.round(v) } })} />
              <NumInput label="循环增益" value={scheduler.loop_gain} min={1} max={2.5} disabled={disabled}
                onChange={(v) => onChange({ scheduler: { ...scheduler, loop_gain: v } })} />
            </div>
            <label className="block space-y-0.5 max-w-[10rem]">
              <span className="text-[10px] text-slate-500">输出格式</span>
              <select
                value={scheduler.output_format}
                disabled={disabled}
                onChange={(e) => onChange({ scheduler: { ...scheduler, output_format: e.target.value as 'mp4' | 'mkv' } })}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
              >
                <option value="mp4">MP4</option>
                <option value="mkv">MKV</option>
              </select>
            </label>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function MixEditPostprocessSection({ value, onChange, disabled }: MixEditPostprocessSectionProps) {
  const vr = value.visual_random!
  const ov = value.overlay_video!
  const ad = value.anti_detect!

  return (
    <section className="space-y-3">
      <VisualBlock
        vr={vr}
        disabled={disabled}
        onChange={(patch) =>
          onChange({
            ...value,
            visual_random: { ...vr, ...patch },
          })
        }
      />

      <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/50 p-3">
        <p className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
          <Film className="w-3.5 h-3.5 text-cyan-400" />
          覆盖视频
        </p>
        <p className="text-[10px] text-slate-500">低不透明度叠加在成片画面上，可带微弱环境音</p>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={ov.enabled}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                ...value,
                overlay_video: { ...ov, enabled: e.target.checked },
              })
            }
            className="rounded border-slate-600"
          />
          启用覆盖视频
        </label>
        {ov.enabled ? (
          <>
            <OverlayPathRow
              label="覆盖视频路径"
              placeholder="mp4/mov/… 或选择文件上传"
              path={ov.path || ''}
              disabled={disabled}
              onPathChange={(path) =>
                onChange({ ...value, overlay_video: { ...ov, path, enabled: true } })
              }
            />
            <div className="grid grid-cols-2 gap-2">
              <NumInput
                label="覆盖视频不透明度"
                value={ov.opacity}
                min={0}
                max={1}
                step={0.01}
                disabled={disabled}
                onChange={(v) => onChange({ ...value, overlay_video: { ...ov, opacity: v } })}
              />
              <NumInput
                label="覆盖视频音量"
                value={ov.volume}
                min={0}
                max={1}
                step={0.01}
                disabled={disabled}
                onChange={(v) => onChange({ ...value, overlay_video: { ...ov, volume: v } })}
              />
            </div>
          </>
        ) : null}
      </div>

      <AntiDetectBlock
        ad={ad}
        disabled={disabled}
        onChange={(patch) =>
          onChange({
            ...value,
            anti_detect: { ...ad, ...patch },
          })
        }
      />
    </section>
  )
}
