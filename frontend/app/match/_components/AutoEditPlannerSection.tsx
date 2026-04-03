'use client'

import { Loader2, Sparkles } from 'lucide-react'
import type { BgmTrack, AutoEditMode } from '@/lib/api'
import type { AutoPlanStage } from './autoEditTypes'
import { AutoEditBgmMixPanel } from './AutoEditBgmMixPanel'

export type AutoEditPlannerSectionProps = {
  hideLlmPlannerUi?: boolean

  bgmTracks: BgmTrack[]
  bgmListError: string

  autoError: string
  autoLoading: boolean
  autoPlansCount: number

  autoPrompt: string
  onAutoPromptChange: (value: string) => void

  autoMode: AutoEditMode
  onAutoModeChange: (value: AutoEditMode) => void

  autoTargetDuration: number | ''
  onAutoTargetDurationChange: (value: number | '') => void

  autoNumPlans: number
  onAutoNumPlansChange: (value: number) => void

  autoBgmMixEnabled: boolean
  onAutoBgmMixEnabledChange: (value: boolean) => void

  autoBgmPlanPolicy: 'auto' | 'none' | 'user' | 'ai'
  onAutoBgmPlanPolicyChange: (value: 'auto' | 'none' | 'user' | 'ai') => void

  autoBgmTrackFilename: string
  onAutoBgmTrackFilenameChange: (value: string) => void

  autoUseTimelineEngine: boolean
  onAutoUseTimelineEngineChange: (value: boolean) => void

  autoExplain: boolean
  onAutoExplainChange: (value: boolean) => void

  onGeneratePlans: () => void

  autoPlanLogs: string[]
  autoPlanElapsedSec: number
  autoPlanStage: AutoPlanStage
  autoPlanStagePercent: Record<AutoPlanStage, number>
}

export function AutoEditPlannerSection({
  hideLlmPlannerUi = false,

  bgmTracks,
  bgmListError,

  autoError,
  autoLoading,
  autoPlansCount,

  autoPrompt,
  onAutoPromptChange,

  autoMode,
  onAutoModeChange,

  autoTargetDuration,
  onAutoTargetDurationChange,

  autoNumPlans,
  onAutoNumPlansChange,

  autoBgmMixEnabled,
  onAutoBgmMixEnabledChange,

  autoBgmPlanPolicy,
  onAutoBgmPlanPolicyChange,

  autoBgmTrackFilename,
  onAutoBgmTrackFilenameChange,

  autoUseTimelineEngine,
  onAutoUseTimelineEngineChange,

  autoExplain,
  onAutoExplainChange,

  onGeneratePlans,

  autoPlanLogs,
  autoPlanElapsedSec,
  autoPlanStage,
  autoPlanStagePercent,
}: AutoEditPlannerSectionProps) {
  return (
    <section className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 space-y-4">
      <p className="text-xs font-semibold text-emerald-300 uppercase tracking-widest flex items-center gap-2">
        <Sparkles className="w-4 h-4" />
        {hideLlmPlannerUi ? '口播快剪 · 成片导出' : '自动一键成片 · 方案规划'}
      </p>

      {hideLlmPlannerUi && (
        <>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            剪辑方案由上方「生成快剪方案」得到；此处配置背景音乐混音，并在下方微调片段时间轴后一键成片。
          </p>
          {autoError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {autoError}
            </div>
          )}

          <AutoEditBgmMixPanel
            wrapperClassName="space-y-2"
            bgmTracks={bgmTracks}
            bgmListError={bgmListError}
            autoBgmMixEnabled={autoBgmMixEnabled}
            onAutoBgmMixEnabledChange={onAutoBgmMixEnabledChange}
            autoBgmPlanPolicy={autoBgmPlanPolicy}
            onAutoBgmPlanPolicyChange={onAutoBgmPlanPolicyChange}
            autoBgmTrackFilename={autoBgmTrackFilename}
            onAutoBgmTrackFilenameChange={onAutoBgmTrackFilenameChange}
            helperText="开关与曲目作用于「一键成片」请求，会覆盖方案中的 BGM 占位字段。"
            strategyLabel="规划阶段 BGM 策略（占位）"
            emptyBgmHintPrefix="曲库暂无曲目时可到"
          />
        </>
      )}

      {!hideLlmPlannerUi && (
        <>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-xs text-slate-300 flex items-center justify-between">
                目标时长（秒）
                <span className="text-[11px] text-slate-500">10 - 600</span>
              </label>
              <input
                type="number"
                min={10}
                max={600}
                value={autoTargetDuration}
                onChange={(e) => onAutoTargetDurationChange(e.target.value ? Number(e.target.value) : '')}
                className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs text-slate-300">候选方案数量</label>
              <select
                value={autoNumPlans}
                onChange={(e) => onAutoNumPlansChange(Number(e.target.value))}
                className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
              >
                {[1, 2, 3, 5].map((n) => (
                  <option key={n} value={n}>
                    {n} 个方案
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-xs text-slate-300">成片模式</label>
              <select
                value={autoMode}
                onChange={(e) => onAutoModeChange(e.target.value as AutoEditMode)}
                className="w-full rounded-lg bg-slate-900/70 border border-slate-700 px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-emerald-400"
              >
                <option value="auto">自动（智能选择原声/配音）</option>
                <option value="voiceover">配音剪辑</option>
                <option value="original">原声剪辑</option>
              </select>
            </div>

            <AutoEditBgmMixPanel
              wrapperClassName="space-y-2 sm:col-span-2"
              bgmTracks={bgmTracks}
              bgmListError={bgmListError}
              autoBgmMixEnabled={autoBgmMixEnabled}
              onAutoBgmMixEnabledChange={onAutoBgmMixEnabledChange}
              autoBgmPlanPolicy={autoBgmPlanPolicy}
              onAutoBgmPlanPolicyChange={onAutoBgmPlanPolicyChange}
              autoBgmTrackFilename={autoBgmTrackFilename}
              onAutoBgmTrackFilenameChange={onAutoBgmTrackFilenameChange}
              policySelectDisabled={autoLoading}
              helperText="开关与下方曲目仅作用于「一键成片」请求，会覆盖方案 JSON 中的 BGM 占位字段的实际混音行为。"
              emptyBgmHintPrefix="曲库暂无曲目时仍可勾选「自动」尝试扫描服务端目录；也可到"
            />

            <div className="space-y-2 sm:col-span-2">
              <label className="text-xs text-slate-300 flex items-center gap-2">
                <Sparkles className="w-3.5 h-3.5 text-cyan-400/90" />
                新引擎（事件级时间轴）
              </label>
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-3 space-y-2">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoUseTimelineEngine}
                    onChange={(e) => onAutoUseTimelineEngineChange(e.target.checked)}
                    disabled={autoLoading}
                    className="rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500/40 disabled:opacity-50"
                  />
                  <span className="text-sm text-slate-200">
                    启用 Timeline Engine（DSL→事件池→Tier→编排→编译回 Plan）
                  </span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoExplain}
                    onChange={(e) => onAutoExplainChange(e.target.checked)}
                    disabled={autoLoading || !autoUseTimelineEngine}
                    className="rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500/40 disabled:opacity-50"
                  />
                  <span className="text-[12px] text-slate-300">Explain 调试（生成可解释中间产物）</span>
                </label>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  默认关闭不影响现有方案生成；开启后后端会优先走新引擎，失败会自动回退旧逻辑。
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs text-slate-300">创作提示词 / 文案 / 提纲</label>
            <textarea
              value={autoPrompt}
              onChange={(e) => onAutoPromptChange(e.target.value)}
              placeholder="例如：做一个 60 秒的搞笑职场翻车集锦，节奏轻快，适合短视频平台..."
              rows={4}
              className="w-full rounded-xl bg-slate-950/80 border border-slate-700 px-4 py-3 text-sm outline-none focus:border-emerald-400 placeholder-slate-600 resize-none"
            />
          </div>
          {autoError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {autoError}
            </div>
          )}
          <div className="flex items-center gap-3">
            <button
              onClick={onGeneratePlans}
              disabled={autoLoading || !autoPrompt.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-sm font-medium text-slate-950 transition-colors"
            >
              {autoLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {autoLoading ? '方案生成中...' : '生成自动成片方案'}
            </button>
            {autoPlansCount > 0 && (
              <span className="text-xs text-emerald-300/80">已生成 {autoPlansCount} 个方案，可进一步与成片管线打通。</span>
            )}
          </div>

          {(autoLoading || autoPlanLogs.length > 0) && (
            <div className="rounded-xl border border-emerald-500/30 bg-slate-950/60 px-4 py-3 space-y-2">
              <div className="space-y-1 text-[11px]">
                <div className="flex items-center justify-between">
                  <span className="text-slate-300">
                    当前阶段：
                    {autoPlanStage === 'idle'
                      ? '待开始'
                      : autoPlanStage === 'preparing'
                        ? '准备中'
                        : autoPlanStage === 'connecting'
                          ? '连接中'
                          : autoPlanStage === 'planning'
                            ? '规划中'
                            : autoPlanStage === 'done'
                              ? '已完成'
                              : '失败'}
                  </span>
                  <span className={autoPlanStage === 'failed' ? 'text-red-400' : 'text-slate-400'}>
                    {autoPlanStage === 'failed' ? '失败' : `${autoPlanStagePercent[autoPlanStage]}%`}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-500 ${autoPlanStage === 'failed' ? 'bg-red-500' : 'bg-emerald-500'}`}
                    style={{ width: `${autoPlanStagePercent[autoPlanStage]}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-emerald-300 flex items-center gap-1.5">
                  {autoLoading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {autoLoading ? '实时生成进度' : '最近一次生成记录'}
                </span>
                <span className="text-slate-500">
                  {autoLoading ? `已等待 ${autoPlanElapsedSec}s` : `总耗时约 ${autoPlanElapsedSec}s`}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  { key: 'init', label: '初始化' },
                  { key: 'context', label: '素材分析' },
                  { key: 'llm', label: '方案生成' },
                  { key: 'post', label: '结果整理' },
                ].map((step, idx) => {
                  const stepRankMap: Record<string, number> = { init: 1, context: 2, llm: 3, post: 4 }
                  const stageRankMap: Record<AutoPlanStage, number> = {
                    idle: 0,
                    preparing: 1,
                    connecting: 2,
                    planning: 3,
                    done: 4,
                    failed: 0,
                  }
                  const currentRank = stageRankMap[autoPlanStage] ?? 0
                  const stepRank = stepRankMap[step.key]
                  const active = currentRank === stepRank && autoLoading
                  const passed = currentRank > stepRank || autoPlanStage === 'done'
                  return (
                    <span
                      key={step.key}
                      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                        active
                          ? 'border-emerald-400 bg-emerald-500/20 text-emerald-200'
                          : passed
                            ? 'border-cyan-400/60 bg-cyan-500/10 text-cyan-200'
                            : 'border-slate-700 bg-slate-900/70 text-slate-500'
                      }`}
                    >
                      {idx + 1}. {step.label}
                    </span>
                  )
                })}
                {autoPlanStage === 'failed' && (
                  <span className="inline-flex items-center rounded-full border border-red-400/60 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300">
                    失败
                  </span>
                )}
              </div>
              {autoLoading && (
                <p className="text-[11px] text-slate-400">
                  {autoPlanElapsedSec < 3
                    ? '正在初始化模型与策略...'
                    : autoPlanElapsedSec < 10
                      ? '正在分析提示词并筛选素材...'
                      : '正在生成候选方案，请稍候...'}
                </p>
              )}
              <div className="max-h-28 overflow-y-auto rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2">
                {autoPlanLogs.length === 0 ? (
                  <p className="text-[11px] text-slate-500">等待日志...</p>
                ) : (
                  autoPlanLogs.map((line, idx) => (
                    <p key={`${line}-${idx}`} className="text-[11px] text-slate-400 leading-5">
                      {line}
                    </p>
                  ))
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}

