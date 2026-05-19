'use client'

import { useRef, useState } from 'react'
import { Film, Sparkles } from 'lucide-react'
import { useToast } from '@/components/ui/toast-provider'
import { autoEditApi } from '@/lib/api'
import type {
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

export function MixEditPostprocessSection({ value, onChange, disabled }: MixEditPostprocessSectionProps) {
  const vr = value.visual_random!
  const ov = value.overlay_video!

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
    </section>
  )
}
