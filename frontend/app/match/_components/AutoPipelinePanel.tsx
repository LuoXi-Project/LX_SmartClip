'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Bot, Check, ChevronDown, Loader2, Music, RefreshCw, Rocket, Search, Square, Subtitles,
} from 'lucide-react'
import apiClient, { ttsApi, type VoiceInfo } from '@/lib/api'
import type { ExportMode } from './types'

/** 全自动流水线阶段（切分 → 匹配 → 配音 → 字幕 → 渲染） */
export type AutoPipelineStageKey = 'splitting' | 'matching' | 'tts' | 'srt' | 'rendering'

/** 流水线整体状态：idle 未运行 / running 运行中 / done 完成 / error 失败 / cancelled 已取消 */
export type AutoPipelineStatus = 'idle' | 'running' | 'done' | 'error' | 'cancelled'

export interface AutoPipelineState {
  status: AutoPipelineStatus
  /** 当前（或中止时所在的）阶段；idle 时为空 */
  stage: AutoPipelineStageKey | ''
  matchDone: number
  matchTotal: number
  ttsDone: number
  ttsTotal: number
  error: string
}

export const INITIAL_AUTO_PIPELINE_STATE: AutoPipelineState = {
  status: 'idle',
  stage: '',
  matchDone: 0,
  matchTotal: 0,
  ttsDone: 0,
  ttsTotal: 0,
  error: '',
}

// 与 TTS 试听页保持一致的引擎分组：
// - edge-tts：音色下拉 + 语速/音量；openai/bailian/volcengine：音色名称文本输入；
// - gpt-sovits/index-tts/custom-http：参数由服务端决定，直接用设置页配置
const NO_PARAM_PROVIDERS = ['gpt-sovits', 'index-tts', 'custom-http']
const PROVIDER_LABELS: Record<string, string> = {
  'edge-tts': 'Edge TTS',
  openai: 'OpenAI TTS',
  bailian: '百炼 (阿里云)',
  volcengine: '火山引擎',
  'gpt-sovits': 'GPT-SoVITS',
  'index-tts': 'IndexTTS',
  'custom-http': '自定义 HTTP',
}

const RATE_PRESETS = [
  { label: '很慢', value: '-50%' },
  { label: '慢', value: '-20%' },
  { label: '正常', value: '+0%' },
  { label: '快', value: '+20%' },
  { label: '很快', value: '+50%' },
]
const VOLUME_PRESETS = [
  { label: '小', value: '-30%' },
  { label: '正常', value: '+0%' },
  { label: '大', value: '+20%' },
  { label: '最大', value: '+50%' },
]

const EXPORT_MODE_OPTIONS: Array<{ value: ExportMode; icon: string; title: string; desc: string }> = [
  { value: 'subtitle', icon: '💬', title: '一键成片', desc: '配音 + 字幕烧录 MP4' },
  { value: 'original', icon: '🔇', title: '原声成片', desc: '保留原声拼接 MP4' },
  { value: 'jianying_tts', icon: '✂️', title: '剪映草稿', desc: '配音轨时间轴' },
  { value: 'jianying_original', icon: '✂️', title: '剪映草稿(原声)', desc: '原声时间轴' },
  { value: 'zip', icon: '📦', title: '素材压缩包', desc: '切片 + 音频 ZIP' },
]

/** 该成片方式是否需要先合成配音 */
export function exportModeNeedsTts(mode: ExportMode): boolean {
  return mode === 'subtitle' || mode === 'jianying_tts'
}

type StageStepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'failed'

export type AutoPipelinePanelProps = {
  /** 共享文案（取自上方工作区级文案输入框，只读展示与就绪判断） */
  globalQuery: string
  selectedVideoCount: number
  ttsVoice: string
  onTtsVoiceChange: (v: string) => void
  ttsRate: string
  onTtsRateChange: (v: string) => void
  ttsVolume: string
  onTtsVolumeChange: (v: string) => void
  subtitleEnabled: boolean
  onSubtitleEnabledChange: (v: boolean) => void
  exportMode: ExportMode
  onExportModeChange: (m: ExportMode) => void
  manualBgmEnabled: boolean
  onManualBgmEnabledChange: (v: boolean) => void
  manualBgmTrackCount: number
  topK: number
  onTopKChange: (v: number) => void
  topN: number
  onTopNChange: (v: number) => void
  pipeline: AutoPipelineState
  onRun: () => void
  onCancel: () => void
}

export function AutoPipelinePanel({
  globalQuery,
  selectedVideoCount,
  ttsVoice,
  onTtsVoiceChange,
  ttsRate,
  onTtsRateChange,
  ttsVolume,
  onTtsVolumeChange,
  subtitleEnabled,
  onSubtitleEnabledChange,
  exportMode,
  onExportModeChange,
  manualBgmEnabled,
  onManualBgmEnabledChange,
  manualBgmTrackCount,
  topK,
  onTopKChange,
  topN,
  onTopNChange,
  pipeline,
  onRun,
  onCancel,
}: AutoPipelinePanelProps) {
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false)
  const [voiceSearch, setVoiceSearch] = useState('')
  const [voices, setVoices] = useState<VoiceInfo[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [ttsProvider, setTtsProvider] = useState('')
  const [globalTtsVoice, setGlobalTtsVoice] = useState('')
  const [advOpen, setAdvOpen] = useState(false)
  const configLoadedRef = useRef(false)

  const running = pipeline.status === 'running'

  useEffect(() => {
    if (configLoadedRef.current) return
    configLoadedRef.current = true
    apiClient
      .get<unknown, Record<string, { value?: string }>>('/api/config')
      .then((cfg) => {
        const provider = String(cfg?.tts_provider?.value ?? 'edge-tts').trim() || 'edge-tts'
        setTtsProvider(provider)
        setGlobalTtsVoice(String(cfg?.tts_voice?.value ?? '').trim())
        if (provider === 'edge-tts') void loadVoices()
      })
      .catch(() => {
        setTtsProvider('edge-tts')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadVoices = async () => {
    setVoicesLoading(true)
    try {
      const list = await ttsApi.listVoices()
      setVoices(Array.isArray(list) ? list : [])
    } catch {
      setVoices([])
    } finally {
      setVoicesLoading(false)
    }
  }

  const providerLabel = PROVIDER_LABELS[ttsProvider] || ttsProvider || 'Edge TTS'
  const isEdgeProvider = ttsProvider === 'edge-tts' || ttsProvider === ''
  const noParamProvider = NO_PARAM_PROVIDERS.includes(ttsProvider)

  const filteredVoices = useMemo(
    () =>
      voices.filter(
        (v) =>
          v.friendly_name.toLowerCase().includes(voiceSearch.toLowerCase()) ||
          v.name.toLowerCase().includes(voiceSearch.toLowerCase()),
      ),
    [voices, voiceSearch],
  )
  const selectedVoiceInfo = voices.find((v) => v.name === ttsVoice)
  const voiceSummary = ttsVoice
    ? selectedVoiceInfo?.friendly_name || ttsVoice
    : globalTtsVoice
      ? `全局·${globalTtsVoice}`
      : '全局设置'
  const exportModeInfo = EXPORT_MODE_OPTIONS.find((m) => m.value === exportMode)

  // ── 步骤条状态推导 ──
  const needsTts = exportModeNeedsTts(exportMode)
  const needsSrt = subtitleEnabled && (exportMode === 'subtitle' || exportMode === 'jianying_tts')
  const stageIdx: Record<AutoPipelineStageKey, number> = { splitting: 0, matching: 1, tts: 2, srt: 3, rendering: 4 }
  const currentIdx = pipeline.stage ? stageIdx[pipeline.stage] : -1
  const steps: Array<{ key: AutoPipelineStageKey; label: string; counter?: string; status: StageStepStatus }> = []

  for (const key of Object.keys(stageIdx) as AutoPipelineStageKey[]) {
    let status: StageStepStatus = 'pending'
    let counter: string | undefined
    if (key === 'tts' && !needsTts) {
      status = 'skipped'
    } else if (key === 'srt' && !needsSrt) {
      status = 'skipped'
    } else {
      const idx = stageIdx[key]
      if (idx < currentIdx) status = 'done'
      else if (idx === currentIdx) {
        status =
          pipeline.status === 'error' ? 'failed'
          : pipeline.status === 'running' ? 'running'
          : pipeline.status === 'cancelled' ? 'pending'
          : 'done'
      } else if (pipeline.status === 'done') {
        status = 'done'
      }
      if (key === 'matching') counter = `${pipeline.matchDone}/${pipeline.matchTotal}`
      if (key === 'tts') counter = `${pipeline.ttsDone}/${pipeline.ttsTotal}`
    }
    steps.push({
      key,
      label:
        key === 'splitting' ? '切分'
        : key === 'matching' ? '匹配'
        : key === 'tts' ? '配音'
        : key === 'srt' ? '字幕'
        : '渲染',
      counter,
      status,
    })
  }

  const canRun = !running && globalQuery.trim().length > 0
  const renderStage = pipeline.status === 'running' && pipeline.stage === 'rendering'
  const chipBase =
    'flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors select-none'

  return (
    <section className="rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-500/10 via-slate-900/50 to-slate-900/40 p-5 space-y-4">
      {/* 标题 */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Rocket className="w-4 h-4 text-indigo-400" />
          <p className="text-sm font-semibold text-slate-100">全自动成片</p>
          <span className="text-[11px] text-slate-500">文案取上方输入框，点好参数即可一键出片</span>
        </div>
        <span className="flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] text-emerald-300">
          ✦ 参数自动记忆，下次直接用
        </span>
      </div>

      {/* 文案就绪状态：引用上方工作区级输入框 */}
      <div
        className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
          globalQuery.trim()
            ? 'border-emerald-500/25 bg-emerald-500/5 text-emerald-300'
            : 'border-slate-700 bg-slate-900/50 text-slate-500'
        }`}
      >
        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500/20 text-[10px] text-indigo-300">1</span>
        {globalQuery.trim() ? (
          <span>
            文案已就绪（约 {globalQuery.trim().length} 字，{globalQuery.trim().split(/\n\s*\n/).filter(Boolean).length || 1} 段）
          </span>
        ) : (
          <span>请先在上方「① 文案」输入框粘贴或生成文案</span>
        )}
      </div>

      {/* ② 成片参数：一行可交互 chips，点击即改 */}
      <div className="space-y-1.5">
        <p className="text-[11px] font-semibold text-slate-400">
          <span className="mr-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500/20 text-[10px] text-indigo-300">2</span>
          成片参数（点击修改）
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {/* 成片方式：紧凑下拉 */}
          <label
            className={`${chipBase} border-slate-700 bg-slate-900/60 text-slate-300 ${running ? 'opacity-50 pointer-events-none' : 'cursor-pointer hover:border-indigo-500/60'}`}
            title={exportModeInfo?.desc}
          >
            <span>{exportModeInfo?.icon ?? '💬'}</span>
            <select
              value={exportMode}
              onChange={(e) => onExportModeChange(e.target.value as ExportMode)}
              className="bg-transparent text-xs text-slate-200 outline-none cursor-pointer"
            >
              {EXPORT_MODE_OPTIONS.map((m) => (
                <option key={m.value} value={m.value} className="bg-slate-900">
                  {m.icon} {m.title}
                </option>
              ))}
            </select>
          </label>

          {/* 配音音色：下拉（内含语速/音量） */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setVoiceMenuOpen((v) => !v)}
              disabled={running}
              className={`${chipBase} border-slate-700 bg-slate-900/60 text-slate-300 hover:border-indigo-500/60 disabled:opacity-50`}
            >
              <Bot className="w-3.5 h-3.5 text-slate-500" />
              <span className="max-w-36 truncate">{voiceSummary}</span>
              <ChevronDown className={`w-3.5 h-3.5 text-slate-500 transition-transform ${voiceMenuOpen ? 'rotate-180' : ''}`} />
            </button>
            {voiceMenuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setVoiceMenuOpen(false)} />
                <div className="absolute z-20 mt-1.5 w-72 rounded-xl border border-slate-700 bg-[#0f131b] shadow-2xl overflow-hidden">
                  {noParamProvider ? (
                    <p className="p-3 text-[11px] text-slate-500 leading-relaxed">
                      当前引擎（{providerLabel}）由服务端决定音色，全自动直接使用「设置页」中该引擎的参数。
                    </p>
                  ) : isEdgeProvider ? (
                    <>
                      <div className="p-2 border-b border-slate-800">
                        <button
                          type="button"
                          onClick={() => onTtsVoiceChange('')}
                          className={`w-full text-left px-3 py-2 text-xs rounded-lg transition-colors ${!ttsVoice ? 'text-indigo-400 bg-indigo-500/10' : 'text-slate-300 hover:bg-slate-800'}`}
                        >
                          使用全局设置{globalTtsVoice ? `（${globalTtsVoice}）` : ''}
                        </button>
                      </div>
                      <div className="p-2 border-b border-slate-800 flex items-center gap-2">
                        <Search className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                        <input
                          value={voiceSearch}
                          onChange={(e) => setVoiceSearch(e.target.value)}
                          placeholder="搜索音色..."
                          className="w-full bg-transparent text-xs outline-none placeholder-slate-600 text-slate-200"
                        />
                        {voicesLoading && <RefreshCw className="w-3 h-3 text-slate-600 animate-spin shrink-0" />}
                      </div>
                      <div className="max-h-44 overflow-y-auto p-1">
                        {filteredVoices.map((voice) => (
                          <button
                            key={voice.name}
                            type="button"
                            onClick={() => onTtsVoiceChange(voice.name)}
                            className={`w-full text-left px-3 py-2 text-xs rounded-lg flex items-center justify-between gap-2 transition-colors ${voice.name === ttsVoice ? 'text-indigo-400 bg-indigo-500/10' : 'text-slate-300 hover:bg-slate-800'}`}
                          >
                            <span className="truncate">
                              <span className="font-medium">{voice.friendly_name}</span>
                              <span className="text-slate-600 ml-1.5">{voice.locale} · {voice.gender}</span>
                            </span>
                            {voice.name === ttsVoice && <Check className="w-3.5 h-3.5 shrink-0" />}
                          </button>
                        ))}
                        {!voicesLoading && filteredVoices.length === 0 && (
                          <p className="px-3 py-4 text-xs text-slate-600 text-center">未找到匹配音色</p>
                        )}
                      </div>
                      <div className="flex gap-3 p-2.5 border-t border-slate-800">
                        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
                          语速
                          <select
                            value={ttsRate}
                            onChange={(e) => onTtsRateChange(e.target.value)}
                            className="rounded-md bg-slate-900 border border-slate-700 px-1.5 py-1 text-[11px] text-slate-200 outline-none"
                          >
                            {RATE_PRESETS.map((p) => (
                              <option key={p.value} value={p.value}>{p.label}</option>
                            ))}
                          </select>
                        </label>
                        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
                          音量
                          <select
                            value={ttsVolume}
                            onChange={(e) => onTtsVolumeChange(e.target.value)}
                            className="rounded-md bg-slate-900 border border-slate-700 px-1.5 py-1 text-[11px] text-slate-200 outline-none"
                          >
                            {VOLUME_PRESETS.map((p) => (
                              <option key={p.value} value={p.value}>{p.label}</option>
                            ))}
                          </select>
                        </label>
                      </div>
                    </>
                  ) : (
                    <div className="p-3 space-y-2">
                      <p className="text-[11px] text-slate-500">引擎：{providerLabel}，填写该引擎的音色名称</p>
                      <input
                        value={ttsVoice}
                        onChange={(e) => onTtsVoiceChange(e.target.value)}
                        placeholder={`留空使用全局设置${globalTtsVoice ? `（${globalTtsVoice}）` : ''}`}
                        className="w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs text-slate-200 outline-none focus:border-indigo-500/60 placeholder-slate-600"
                      />
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* 字幕开关 */}
          <button
            type="button"
            onClick={() => onSubtitleEnabledChange(!subtitleEnabled)}
            disabled={running}
            title="样式在右侧「字幕设置」调整"
            className={`${chipBase} disabled:opacity-50 ${
              subtitleEnabled
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500'
            }`}
          >
            <Subtitles className="w-3.5 h-3.5" />
            字幕{subtitleEnabled ? '开' : '关'}
          </button>

          {/* BGM 开关 */}
          <button
            type="button"
            onClick={() => onManualBgmEnabledChange(!manualBgmEnabled)}
            disabled={running}
            title="曲目在下方「手动 BGM」多选配置"
            className={`${chipBase} disabled:opacity-50 ${
              manualBgmEnabled
                ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500'
            }`}
          >
            <Music className="w-3.5 h-3.5" />
            BGM{manualBgmEnabled ? `·${manualBgmTrackCount}首` : '关'}
          </button>

          {/* 素材范围（只读，指向页首选择器） */}
          <span
            className={`${chipBase} border-slate-700 bg-slate-900/60 text-slate-400`}
            title="在页面顶部「限定视频范围」中勾选"
          >
            🎬 素材{selectedVideoCount > 0 ? `·已选${selectedVideoCount}` : '·全库'}
          </span>

          {/* 高级参数（初筛/推荐） */}
          <button
            type="button"
            onClick={() => setAdvOpen((v) => !v)}
            className={`${chipBase} border-slate-700 bg-slate-900/40 text-slate-500 hover:border-slate-500`}
          >
            高级
            <ChevronDown className={`w-3 h-3 transition-transform ${advOpen ? 'rotate-180' : ''}`} />
          </button>
        </div>
        {advOpen && (
          <div className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
            <label className="flex items-center gap-2 text-[11px] text-slate-400">
              初筛（向量召回）
              <input
                type="number"
                min={1}
                max={50}
                value={topK}
                onChange={(e) => onTopKChange(Number(e.target.value))}
                className="w-14 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-center text-xs text-slate-200 outline-none focus:border-indigo-500/60"
              />
            </label>
            <label className="flex items-center gap-2 text-[11px] text-slate-400">
              推荐（精选段数）
              <input
                type="number"
                min={1}
                max={20}
                value={topN}
                onChange={(e) => onTopNChange(Number(e.target.value))}
                className="w-14 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-center text-xs text-slate-200 outline-none focus:border-indigo-500/60"
              />
            </label>
            <span className="text-[10px] text-slate-600">初筛=向量检索召回数；推荐=送入精选的候选数，自动与手动匹配共用</span>
          </div>
        )}
      </div>

      {/* ③ 一键运行 */}
      <div className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={onRun}
            disabled={!canRun}
            className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-medium flex items-center gap-2 transition-colors shadow-lg shadow-indigo-950/40"
          >
            <span className="mr-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-white/15 text-[10px]">3</span>
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
            {running ? '全自动运行中...' : '一键全自动成片'}
          </button>
          {running && (
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2.5 rounded-xl border border-slate-700 bg-slate-800/40 hover:border-red-500/60 hover:text-red-300 text-sm flex items-center gap-2 transition-colors"
              title={renderStage ? '终止后台成片任务（ffmpeg 渲染会立即中止）' : '中止全自动流程'}
            >
              <Square className="w-3.5 h-3.5" />
              {renderStage ? '取消渲染' : '取消'}
            </button>
          )}
          {!globalQuery.trim() && !running && (
            <span className="text-xs text-slate-600">先在上方粘贴文案，即可一键出片</span>
          )}
        </div>

        {/* 步骤条（运行后显示） */}
        {pipeline.status !== 'idle' && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2.5 space-y-2">
            <div className="flex items-center gap-1 overflow-x-auto">
              {steps.map((step, i) => (
                <div key={step.key} className="flex items-center gap-1 shrink-0">
                  {i > 0 && <div className={`w-4 h-px ${steps[i - 1].status === 'done' ? 'bg-emerald-500/40' : 'bg-slate-700'}`} />}
                  <div
                    className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] ${
                      step.status === 'running' ? 'bg-indigo-500/15 text-indigo-300'
                      : step.status === 'done' ? 'text-emerald-300'
                      : step.status === 'failed' ? 'bg-red-500/15 text-red-300'
                      : step.status === 'skipped' ? 'text-slate-600 line-through'
                      : 'text-slate-500'
                    }`}
                  >
                    {step.status === 'running' && <Loader2 className="w-3 h-3 animate-spin shrink-0" />}
                    {step.status === 'done' && <Check className="w-3 h-3 shrink-0" />}
                    {step.status === 'failed' && <span className="shrink-0">✕</span>}
                    {step.status === 'pending' && <span className="shrink-0 text-slate-600">○</span>}
                    {step.status === 'skipped' && <span className="shrink-0">—</span>}
                    <span className="whitespace-nowrap">{step.label}</span>
                    {step.counter && <span className="text-slate-500">{step.counter}</span>}
                  </div>
                </div>
              ))}
            </div>
            {pipeline.error && (
              <p className="text-[11px] text-red-400 flex items-start gap-1.5">
                <span className="shrink-0">✕</span>
                {pipeline.error}
              </p>
            )}
            {pipeline.status === 'cancelled' && <p className="text-[11px] text-amber-400">已取消：可调整文案/参数后重新一键运行</p>}
            {pipeline.status === 'done' && <p className="text-[11px] text-emerald-400">全自动成片完成，文件已自动下载；可在下方段落区继续微调后重新导出</p>}
            {renderStage && (
              <p className="text-[11px] text-slate-500">正在后台渲染成片（进度见右下角提示与右上角任务中心），完成后自动下载；点「取消渲染」可立即中止</p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
