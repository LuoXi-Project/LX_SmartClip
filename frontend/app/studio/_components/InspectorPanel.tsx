'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Info, Loader2, Lock, Mic, Music2, Sliders, Sparkles, Subtitles } from 'lucide-react'
import Link from 'next/link'
import { patchAgentWorkspace } from '@/lib/agent-api'
import { bgmApi, motionApi, type BgmTrack, type CaptionStyleItem } from '@/lib/api'
import { BgmTrackPicker } from '@/components/ui/bgm-track-picker'
import { SubtitlePanel } from '@/app/match/_components/SubtitlePanel'
import { useStudioStore } from '@/lib/studio-store'
import { useStudioMediaConfig } from './useStudioMediaConfig'
import type { AutoEditPlanApi } from '@/lib/api'
import type { InspectorTabId, ProductionPresetId, ProductionProfileApi } from '@/lib/agent-types'
import { getPlanAudioSummary } from '@/lib/plan-audio-summary'
import { readProductionProfile } from '@/lib/studio-media-config'
import { StudioPanelHeaderAction } from './StudioPanelHeaderAction'

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
  const [captionStyles, setCaptionStyles] = useState<CaptionStyleItem[]>([])
  const [captionPreviewUrl, setCaptionPreviewUrl] = useState('')
  const [captionPreviewLoading, setCaptionPreviewLoading] = useState(false)

  const profile = readProductionProfile(workspace?.user_preferences)
  const activePlan = useMemo(() => {
    if (!workspace?.plans?.length) return null
    const pid = workspace.active_plan_id
    const raw = pid
      ? workspace.plans.find((p) => (p as AutoEditPlanApi).plan_id === pid) ?? workspace.plans[0]
      : workspace.plans[0]
    return raw as AutoEditPlanApi
  }, [workspace])

  const audioSummary = activePlan ? getPlanAudioSummary(activePlan) : null

  const preset = profile.preset_id || 'auto'
  const captions = profile.captions || { engine: 'ass' as const, style: 'karaoke-hormozi' }

  useEffect(() => {
    let cancelled = false
    motionApi
      .captionStyles()
      .then((items) => {
        if (!cancelled) setCaptionStyles(items)
      })
      .catch(() => {
        /* 动效运行时未就绪时静默：选择器留空 */
      })
    return () => {
      cancelled = true
    }
  }, [])

  const patchCaptions = useCallback(
    async (next: NonNullable<ProductionProfileApi['captions']>) => {
      if (!sessionId || !workspace) return
      const merged: ProductionProfileApi = { ...profile, captions: { ...captions, ...next } }
      await patchAgentWorkspace(sessionId, {
        user_preferences: {
          ...workspace.user_preferences,
          production_profile: merged,
        },
      })
      useStudioStore.setState((s) =>
        s.workspace
          ? {
              workspace: {
                ...s.workspace,
                user_preferences: {
                  ...s.workspace.user_preferences,
                  production_profile: merged,
                },
              },
            }
          : {},
      )
    },
    [sessionId, workspace, profile, captions],
  )

  const loadCaptionPreview = useCallback(async (style: string) => {
    setCaptionPreviewLoading(true)
    try {
      const res = await motionApi.captionPreview({ style })
      setCaptionPreviewUrl(res.preview_url)
    } catch {
      setCaptionPreviewUrl('')
    } finally {
      setCaptionPreviewLoading(false)
    }
  }, [])

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
    <div className="flex flex-col h-full bg-[#0d0f14]">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Info className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-medium text-slate-200">检查器</span>
        <StudioPanelHeaderAction panelId="inspector" />
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

      <div className="flex-1 overflow-auto styled-scrollbar p-4 text-xs text-slate-400 space-y-4">
        {inspectorTab === 'production' && (
          <>
            {audioSummary ? (
              <section className="rounded-lg border border-slate-700 bg-slate-900/50 p-3 space-y-2">
                <h3 className="text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                  <Mic className="w-3.5 h-3.5" /> 听感 / 配音
                </h3>
                <p className="text-sm text-slate-200 font-medium">{audioSummary.label}</p>
                <p className="text-[11px] text-slate-400">{audioSummary.short}</p>
                <div className="flex flex-wrap gap-1.5 text-[10px]">
                  <span className="px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-200 border border-violet-500/30">
                    TTS {audioSummary.tts_count}
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                    原声 {audioSummary.original_count}
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                    静音 {audioSummary.mute_count}
                  </span>
                </div>
                {audioSummary.will_export_tts ? (
                  <p className="text-[10px] text-emerald-400">导出成片时将合成 AI 配音</p>
                ) : audioSummary.will_keep_original ? (
                  <p className="text-[10px] text-amber-300">导出成片时保留素材原声，不强制 TTS</p>
                ) : null}
                {audioSummary.warnings.map((w) => (
                  <p key={w} className="text-[10px] text-amber-400/90">
                    {w}
                  </p>
                ))}
                <p className="text-[10px] text-slate-500">
                  制作风格（如电商）只管转场/响度，不管是否配音；以本栏为准。
                </p>
              </section>
            ) : null}

            <section>
              <h3 className="text-slate-500 uppercase tracking-wider mb-2">制作风格</h3>
              <p className="text-[11px] text-slate-500 mb-2">
                转场、响度、ducking、字幕动效模板。对话里也可说「电商风、转场柔一点」。
                成片听感由<strong className="text-slate-400">方案模式</strong>（配音/原声）决定，导出前请在画布展开「成片怎么选？」。
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

            {/* 字幕引擎：ASS 硬字幕 / HyperFrames 动效字幕（逐词卡拉OK等） */}
            <div className="pt-2 border-t border-slate-800 space-y-2">
              <h3 className="text-slate-500 uppercase tracking-wider text-[10px]">字幕引擎</h3>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => void patchCaptions({ engine: 'ass' })}
                  className={`flex-1 rounded-lg border px-2 py-1.5 text-xs transition-colors ${
                    captions.engine !== 'hyperframes'
                      ? 'border-indigo-500/60 bg-indigo-500/10 text-indigo-200'
                      : 'border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  传统硬字幕
                </button>
                <button
                  type="button"
                  onClick={() => {
                    void patchCaptions({ engine: 'hyperframes' })
                    if (!captionPreviewUrl) void loadCaptionPreview(captions.style || 'karaoke-hormozi')
                  }}
                  className={`flex-1 flex items-center justify-center gap-1 rounded-lg border px-2 py-1.5 text-xs transition-colors ${
                    captions.engine === 'hyperframes'
                      ? 'border-fuchsia-500/60 bg-fuchsia-500/10 text-fuchsia-200'
                      : 'border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Sparkles className="w-3 h-3" />
                  动效字幕
                </button>
              </div>
              {captions.engine === 'hyperframes' && (
                <div className="space-y-2">
                  <p className="text-[10px] text-slate-500">
                    逐词卡拉OK/打字机等动效字幕（HyperFrames 渲染，比 ASS 慢约 1~3 分钟）
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {captionStyles.map((s) => (
                      <button
                        key={s.slug}
                        type="button"
                        onClick={() => {
                          void patchCaptions({ style: s.slug })
                          void loadCaptionPreview(s.slug)
                        }}
                        className={`text-left rounded-lg px-3 py-2 border transition-colors ${
                          (captions.style || 'karaoke-hormozi') === s.slug
                            ? 'border-fuchsia-500/60 bg-fuchsia-500/10 text-fuchsia-200'
                            : 'border-slate-800 bg-slate-900/40 hover:border-slate-700 text-slate-300'
                        }`}
                      >
                        <div className="font-medium text-sm">{s.title}</div>
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          {s.description || s.preview || s.slug}
                        </div>
                      </button>
                    ))}
                    {captionStyles.length === 0 && (
                      <p className="text-[10px] text-slate-600">
                        模板列表不可用（动效运行时未就绪，请检查 Node 环境）
                      </p>
                    )}
                  </div>
                  {captionPreviewLoading ? (
                    <div className="flex items-center gap-1.5 text-[11px] text-slate-500 py-2">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> 生成预览…
                    </div>
                  ) : captionPreviewUrl ? (
                    <div className="rounded-xl overflow-hidden border border-slate-800 bg-slate-950">
                      <iframe
                        src={captionPreviewUrl}
                        title="字幕动效预览"
                        className="w-full aspect-[9/16] max-h-80 bg-black"
                        sandbox="allow-scripts allow-same-origin"
                      />
                    </div>
                  ) : null}
                </div>
              )}
            </div>
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
