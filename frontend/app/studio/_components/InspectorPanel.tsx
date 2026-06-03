'use client'

import { useCallback, useEffect, useState } from 'react'
import { Info, Lock, Music2, Sliders, Subtitles } from 'lucide-react'
import Link from 'next/link'
import { patchAgentWorkspace } from '@/lib/agent-api'
import { bgmApi, type BgmTrack } from '@/lib/api'
import { BgmTrackPicker } from '@/components/ui/bgm-track-picker'
import { SubtitlePanel } from '@/app/match/_components/SubtitlePanel'
import { useStudioStore } from '@/lib/studio-store'
import { useStudioMediaConfig } from './useStudioMediaConfig'
import type { InspectorTabId, ProductionPresetId, ProductionProfileApi } from '@/lib/agent-types'
import { readProductionProfile } from '@/lib/studio-media-config'

const PRESETS: { id: ProductionPresetId; label: string; hint: string }[] = [
  { id: 'auto', label: '自动', hint: '按内容推断' },
  { id: 'ecommerce', label: '电商爆款', hint: '快切·强 duck·弹出字幕' },
  { id: 'knowledge', label: '知识讲解', hint: '柔转场·稳字幕' },
  { id: 'cinematic', label: '纪录片', hint: '长 dissolve·精响度' },
  { id: 'fast_cut', label: '快剪卡点', hint: '硬切·节拍对齐' },
]

const TABS: { id: InspectorTabId; label: string; icon: typeof Sliders }[] = [
  { id: 'production', label: '制作', icon: Sliders },
  { id: 'subtitle', label: '字幕', icon: Subtitles },
  { id: 'bgm', label: 'BGM', icon: Music2 },
]

function LockToggle({
  locked,
  onToggle,
  title,
}: {
  locked: boolean
  onToggle: () => void
  title: string
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      title={title}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${
        locked
          ? 'border-amber-500/50 bg-amber-500/10 text-amber-300'
          : 'border-slate-700 text-slate-500 hover:border-slate-600'
      }`}
    >
      <Lock className="w-3 h-3" />
      {locked ? '已锁定' : '可改'}
    </button>
  )
}

export function InspectorPanel() {
  const { workspace, selectedArtifact, sessionId, inspectorTab, setInspectorTab } =
    useStudioStore()
  const { media, patchMedia } = useStudioMediaConfig()
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([])
  const [bgmListError, setBgmListError] = useState('')

  const profile = readProductionProfile(workspace?.user_preferences)
  const preset = profile.preset_id || 'auto'

  useEffect(() => {
    let cancelled = false
    bgmApi
      .list()
      .then((list) => {
        if (!cancelled) setBgmTracks(list)
      })
      .catch((e) => {
        if (!cancelled) setBgmListError((e as Error).message || '加载 BGM 失败')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const applyPreset = useCallback(
    async (presetId: ProductionPresetId) => {
      if (!sessionId || !workspace) return
      const next: ProductionProfileApi = { ...profile, preset_id: presetId }
      await patchAgentWorkspace(sessionId, {
        user_preferences: {
          ...workspace.user_preferences,
          default_production_preset: presetId,
          production_profile: next,
        },
      })
      useStudioStore.setState((s) =>
        s.workspace
          ? {
              workspace: {
                ...s.workspace,
                user_preferences: {
                  ...s.workspace.user_preferences,
                  default_production_preset: presetId,
                  production_profile: next,
                },
              },
            }
          : {}
      )
    },
    [sessionId, workspace, profile]
  )

  const bgmPickValue = media.bgm.track_ids[0] || ''

  return (
    <div className="flex flex-col h-full border-l border-slate-800 bg-[#0d0f14]">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Info className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-medium text-slate-200">检查器</span>
      </div>

      <div className="flex border-b border-slate-800 px-2 pt-2 gap-1">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = inspectorTab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setInspectorTab(t.id)}
              className={`flex-1 flex items-center justify-center gap-1 py-2 text-[11px] rounded-t-lg border-b-2 transition-colors ${
                active
                  ? 'border-indigo-500 text-indigo-200 bg-slate-900/60'
                  : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          )
        })}
      </div>

      <div className="flex-1 overflow-auto p-4 text-xs text-slate-400 space-y-4">
        {inspectorTab === 'production' && (
          <>
            <section>
              <h3 className="text-slate-500 uppercase tracking-wider mb-2">制作风格</h3>
              <p className="text-[11px] text-slate-500 mb-2">
                转场、响度、ducking、字幕动效模板。对话里也可说「电商风、转场柔一点」。
              </p>
              <div className="flex flex-col gap-1.5">
                {PRESETS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => void applyPreset(p.id)}
                    className={`text-left rounded-lg px-3 py-2 border transition-colors ${
                      preset === p.id
                        ? 'border-indigo-500/60 bg-indigo-500/10 text-indigo-200'
                        : 'border-slate-800 bg-slate-900/40 hover:border-slate-700 text-slate-300'
                    }`}
                  >
                    <div className="font-medium text-sm">{p.label}</div>
                    <div className="text-[10px] text-slate-500 mt-0.5">{p.hint}</div>
                  </button>
                ))}
              </div>
            </section>
            {workspace && (
              <section>
                <h3 className="text-slate-500 uppercase tracking-wider mb-2">工作区</h3>
                <ul className="space-y-1 text-[11px]">
                  <li>阶段：{workspace.pipeline_phase}</li>
                  <li>视频：{workspace.selected_video_ids?.length ?? 0} 个</li>
                  <li>方案：{workspace.plans?.length ?? 0} 个</li>
                </ul>
              </section>
            )}
          </>
        )}

        {inspectorTab === 'subtitle' && (
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-slate-300 text-sm">
                <input
                  type="checkbox"
                  checked={media.subtitle.enabled}
                  onChange={(e) =>
                    void patchMedia({
                      subtitle: { ...media.subtitle, enabled: e.target.checked },
                    })
                  }
                  className="rounded border-slate-600"
                />
                成片烧录字幕
              </label>
              <LockToggle
                locked={media.subtitle.locked}
                onToggle={() =>
                  void patchMedia({
                    subtitle: { ...media.subtitle, locked: !media.subtitle.locked },
                  })
                }
                title="锁定后 Agent 只改文案，不改样式"
              />
            </div>
            <p className="text-[10px] text-slate-500">
              手调参数会同步到预览区；Agent 可在对话中改文案或描述风格（未锁定时）。
            </p>
            <SubtitlePanel
              style={media.subtitle.style}
              onChange={(style) => void patchMedia({ subtitle: { ...media.subtitle, style } })}
              enabled={media.subtitle.enabled}
              onToggle={(v) => void patchMedia({ subtitle: { ...media.subtitle, enabled: v } })}
              strictUseClientSrt={media.subtitle.strict_use_client_srt}
              onStrictUseClientSrtChange={(v) =>
                void patchMedia({ subtitle: { ...media.subtitle, strict_use_client_srt: v } })
              }
              timingSource="tts"
            />
          </section>
        )}

        {inspectorTab === 'bgm' && (
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-slate-300 text-sm">
                <input
                  type="checkbox"
                  checked={media.bgm.enabled}
                  onChange={(e) =>
                    void patchMedia({
                      bgm: {
                        ...media.bgm,
                        enabled: e.target.checked,
                        mode: e.target.checked ? media.bgm.mode : 'none',
                      },
                    })
                  }
                  className="rounded border-slate-600"
                />
                启用 BGM
              </label>
              <LockToggle
                locked={media.bgm.locked}
                onToggle={() =>
                  void patchMedia({ bgm: { ...media.bgm, locked: !media.bgm.locked } })
                }
                title="锁定后 Agent 不会更换曲目"
              />
            </div>

            <div className="flex gap-2">
              {(['auto', 'manual'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  disabled={!media.bgm.enabled}
                  onClick={() =>
                    void patchMedia({ bgm: { ...media.bgm, mode: m } })
                  }
                  className={`flex-1 py-1.5 rounded-lg border text-[11px] ${
                    media.bgm.mode === m
                      ? 'border-violet-500/60 bg-violet-500/10 text-violet-200'
                      : 'border-slate-800 text-slate-500'
                  } disabled:opacity-40`}
                >
                  {m === 'auto' ? '自动选曲' : '手动指定'}
                </button>
              ))}
            </div>

            {media.bgm.enabled && media.bgm.mode === 'manual' && (
              <BgmTrackPicker
                tracks={bgmTracks}
                value={bgmPickValue}
                onChange={(id) =>
                  void patchMedia({
                    bgm: {
                      ...media.bgm,
                      track_ids: id ? [id] : [],
                      mode: 'manual',
                    },
                  })
                }
                trackValueField="id"
                allowAuto={false}
                listError={bgmListError}
                emptyHint={
                  <p className="text-[11px] text-slate-500">
                    暂无曲目，请至{' '}
                    <Link href="/bgm" className="text-cyan-400 underline">
                      BGM 页
                    </Link>{' '}
                    上传
                  </p>
                }
              />
            )}

            {media.bgm.enabled && (
              <label className="block text-[11px] text-slate-400">
                音量 {media.bgm.volume_db} dB
                <input
                  type="range"
                  min={-24}
                  max={-6}
                  step={1}
                  value={media.bgm.volume_db}
                  onChange={(e) =>
                    void patchMedia({
                      bgm: { ...media.bgm, volume_db: Number(e.target.value) },
                    })
                  }
                  className="w-full mt-1 accent-violet-500"
                />
              </label>
            )}

            <p className="text-[10px] text-slate-500">
              时间轴 BGM 轨与成片混音一致；自动模式下由方案/曲库匹配选曲。
            </p>
          </section>
        )}

        {selectedArtifact?.type === 'plan' && inspectorTab === 'production' && (
          <section>
            <h3 className="text-slate-500 uppercase tracking-wider mb-2">方案摘要</h3>
            <p className="text-[11px] text-slate-300">
              {(selectedArtifact.payload?.title as string) || selectedArtifact.id}
            </p>
          </section>
        )}
      </div>
    </div>
  )
}
