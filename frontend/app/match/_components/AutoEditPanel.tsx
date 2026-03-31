'use client'

import { Loader2, Sparkles } from 'lucide-react'
import { type AutoEditMode, type AutoEditPlanApi } from '@/lib/api'
import { type AutoPlanStage } from './autoEditTypes'

type AutoEditPanelProps = {
  autoPrompt: string
  onAutoPromptChange: (value: string) => void
  autoMode: AutoEditMode
  onAutoModeChange: (value: AutoEditMode) => void
  autoTargetDuration: number | ''
  onAutoTargetDurationChange: (value: number | '') => void
  autoNumPlans: number
  onAutoNumPlansChange: (value: number) => void
  autoLoading: boolean
  autoError: string
  autoPlans: AutoEditPlanApi[]
  autoExpandedPlanIds: string[]
  onTogglePlanExpand: (planId: string) => void
  autoRealizingId: string | null
  autoRealizeMsg: string
  autoRealizeDownloads: Record<string, { filename: string; url: string }>
  autoPlanLogs: string[]
  autoPlanElapsedSec: number
  autoPlanStage: AutoPlanStage
  autoPlanStagePercent: Record<AutoPlanStage, number>
  subtitleEnabled: boolean
  onGeneratePlans: () => void
  onRealizePlan: (plan: AutoEditPlanApi, index: number) => void
}

export function AutoEditPanel({
  autoPrompt,
  onAutoPromptChange,
  autoMode,
  onAutoModeChange,
  autoTargetDuration,
  onAutoTargetDurationChange,
  autoNumPlans,
  onAutoNumPlansChange,
  autoLoading,
  autoError,
  autoPlans,
  autoExpandedPlanIds,
  onTogglePlanExpand,
  autoRealizingId,
  autoRealizeMsg,
  autoRealizeDownloads,
  autoPlanLogs,
  autoPlanElapsedSec,
  autoPlanStage,
  autoPlanStagePercent,
  subtitleEnabled,
  onGeneratePlans,
  onRealizePlan,
}: AutoEditPanelProps) {
  return (
    <>
      <section className="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5 space-y-4">
        <p className="text-xs font-semibold text-emerald-300 uppercase tracking-widest flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          自动一键成片 · 方案规划
        </p>
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
              <option value="voiceover">配音为主</option>
              <option value="original">原声为主</option>
            </select>
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
          {autoPlans.length > 0 && (
            <span className="text-xs text-emerald-300/80">已生成 {autoPlans.length} 个方案，可进一步与成片管线打通。</span>
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
              <span className="text-slate-500">{autoLoading ? `已等待 ${autoPlanElapsedSec}s` : `总耗时约 ${autoPlanElapsedSec}s`}</span>
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
      </section>

      {autoPlans.length > 0 && (
        <section className="space-y-3">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">候选方案 · {autoPlans.length} 个</p>
          <div className="grid md:grid-cols-2 gap-3">
            {autoPlans.map((p, idx) => (
              <div key={p.plan_id || idx} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-100 truncate">{p.title || `方案 ${idx + 1}`}</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      模式：{p.mode === 'auto' ? '自动' : p.mode === 'voiceover' ? '配音为主' : '原声为主'}
                    </p>
                  </div>
                  <div className="text-right text-[11px] text-slate-500 space-y-0.5">
                    {p.target_duration_sec && <p>目标：{Math.round(p.target_duration_sec)}s</p>}
                    {p.estimated_duration_sec && <p>预估：{Math.round(p.estimated_duration_sec)}s</p>}
                    <p>段落：{p.segments?.length ?? 0}</p>
                  </div>
                </div>
                {p.summary && (
                  <div className="space-y-1">
                    <p className={`text-xs text-slate-300 ${autoExpandedPlanIds.includes(p.plan_id) ? '' : 'line-clamp-3'}`}>{p.summary}</p>
                    {p.summary.length > 80 && (
                      <button
                        type="button"
                        onClick={() => onTogglePlanExpand(p.plan_id)}
                        className="text-[11px] text-cyan-300 hover:text-cyan-200"
                      >
                        {autoExpandedPlanIds.includes(p.plan_id) ? '收起详情' : '展开详情'}
                      </button>
                    )}
                  </div>
                )}
                <div className="text-[11px] text-slate-500 space-y-0.5">
                  <p>
                    输出：
                    {p.mode === 'original'
                      ? subtitleEnabled
                        ? '原声 + 字幕'
                        : '原声（无字幕）'
                      : subtitleEnabled
                        ? '配音 + 字幕'
                        : '配音（无字幕）'}
                  </p>
                  <p>
                    片段预览：
                    {p.segments?.slice(0, 3).map((s) => (
                      <span key={s.id} className="inline-block mr-2">
                        #{s.order}（{Math.round(s.start_time_sec)}-{Math.round(s.end_time_sec)}s）
                      </span>
                    ))}
                    {p.segments?.length > 3 && <span>…</span>}
                  </p>
                </div>
                <div className="pt-1 space-y-1">
                  <button
                    onClick={() => onRealizePlan(p, idx)}
                    disabled={autoRealizingId !== null}
                    className="w-full inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/50 bg-emerald-500/10 text-[11px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-60 transition-colors"
                  >
                    {autoRealizingId === p.plan_id ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        成片生成中...
                      </>
                    ) : (
                      <>一键成片</>
                    )}
                  </button>
                  {autoRealizeMsg && <p className="text-[11px] text-emerald-300/80">{autoRealizeMsg}</p>}
                  {autoRealizeDownloads[p.plan_id] && (
                    <a
                      href={autoRealizeDownloads[p.plan_id].url}
                      download={autoRealizeDownloads[p.plan_id].filename}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-[11px] text-cyan-300 hover:text-cyan-200 underline underline-offset-2"
                    >
                      下载成片：{autoRealizeDownloads[p.plan_id].filename}
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  )
}
