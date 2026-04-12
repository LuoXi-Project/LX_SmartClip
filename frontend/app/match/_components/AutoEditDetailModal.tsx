'use client'

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import type { AutoEditPlanApi } from '@/lib/api'
import type { ClipMetaByClip, SelectedPreviewState } from './autoEditTypes'
import { fmt } from './types'

export type AutoEditDetailModalProps = {
  detailPlan: { plan: AutoEditPlanApi; index: number } | null
  onClose: () => void

  detailEditMode: boolean
  setDetailEditMode: Dispatch<SetStateAction<boolean>>

  detailDraft: AutoEditPlanApi | null
  setDetailDraft: Dispatch<SetStateAction<AutoEditPlanApi | null>>

  setCustomPlanById: Dispatch<SetStateAction<Record<string, AutoEditPlanApi>>>

  clipMetaByClip: ClipMetaByClip
  setSelectedPreview: Dispatch<SetStateAction<SelectedPreviewState | null>>
}

export function AutoEditDetailModal({
  detailPlan,
  onClose,
  detailEditMode,
  setDetailEditMode,
  detailDraft,
  setDetailDraft,
  setCustomPlanById,
  clipMetaByClip,
  setSelectedPreview,
}: AutoEditDetailModalProps) {
  if (!detailPlan) return null
  const [viewMode, setViewMode] = useState<'detail' | 'copy'>('detail')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'ok' | 'fail'>('idle')
  const segments = (detailDraft?.segments ?? detailPlan.plan.segments) ?? []
  const activeSegments = useMemo(() => segments.filter((s) => !s.exclude_from_output), [segments])
  const mergedCopyText = useMemo(() => {
    return activeSegments
      .map((s) => s.subtitle?.text?.trim())
      .filter((txt): txt is string => Boolean(txt))
      .join('\n')
  }, [activeSegments])

  useEffect(() => {
    setViewMode('detail')
    setCopyStatus('idle')
  }, [detailPlan.plan.plan_id])

  useEffect(() => {
    if (copyStatus === 'idle') return
    const timer = window.setTimeout(() => setCopyStatus('idle'), 1500)
    return () => window.clearTimeout(timer)
  }, [copyStatus])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="方案详情"
    >
      <button type="button" className="absolute inset-0 bg-black/60" onClick={onClose} aria-label="关闭" />
      <div className="relative w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl overflow-hidden">
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-100 truncate">
              {detailPlan.plan.title || `方案 ${detailPlan.index + 1}`} · 字幕详情 / 更多信息
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              plan_id: {detailPlan.plan.plan_id} · 段落：{activeSegments.length} 段参与成片 / 共 {segments.length} 段 · 模式：
              {detailPlan.plan.mode === 'auto'
                ? '自动'
                : detailPlan.plan.mode === 'voiceover'
                  ? '配音剪辑'
                  : '原声剪辑'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 flex-shrink-0"
          >
            关闭（Esc）
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto px-4 py-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] text-slate-500">
              在这里的修改会覆盖当前方案，并在点击“一键成片”时生效（只影响本次候选方案，不影响重新生成）。
              标记「弃用」的段落不会进入拼接与字幕轴；其余段落按顺序连续对齐，无需手改时间消除空洞。
            </div>
            <div className="flex items-center gap-2">
              <div className="inline-flex items-center rounded-lg border border-slate-700 bg-slate-950/40 p-0.5">
                <button
                  type="button"
                  onClick={() => setViewMode('detail')}
                  className={`text-[11px] rounded-md px-2 py-1 transition-colors ${
                    viewMode === 'detail'
                      ? 'bg-cyan-500/20 text-cyan-200'
                      : 'text-slate-300 hover:bg-slate-900/70'
                  }`}
                >
                  段落明细
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode('copy')}
                  className={`text-[11px] rounded-md px-2 py-1 transition-colors ${
                    viewMode === 'copy' ? 'bg-cyan-500/20 text-cyan-200' : 'text-slate-300 hover:bg-slate-900/70'
                  }`}
                >
                  文案速览
                </button>
              </div>
              {viewMode === 'detail' && (
                <button
                  type="button"
                  onClick={() => setDetailEditMode((v) => !v)}
                  className={`text-[11px] rounded-lg border px-2 py-1 transition-colors ${
                    detailEditMode
                      ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                      : 'border-slate-700 bg-slate-950/40 text-slate-300 hover:bg-slate-950/70'
                  }`}
                >
                  {detailEditMode ? '退出编辑' : '进入编辑'}
                </button>
              )}
              <button
                type="button"
                disabled={!detailDraft}
                onClick={() => {
                  if (!detailDraft) return
                  setCustomPlanById((prev) => ({ ...prev, [detailDraft.plan_id]: detailDraft }))
                  setDetailEditMode(false)
                }}
                className="text-[11px] rounded-lg border border-emerald-500/60 bg-emerald-500/15 px-2 py-1 text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
                title="保存后将用于一键成片提交"
              >
                保存修改
              </button>
              <button
                type="button"
                disabled={!detailDraft}
                onClick={() => {
                  if (!detailDraft) return
                  setCustomPlanById((prev) => {
                    const next = { ...prev }
                    delete next[detailDraft.plan_id]
                    return next
                  })
                  setDetailDraft(detailPlan.plan)
                  setDetailEditMode(false)
                }}
                className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-300 hover:bg-slate-950/70 disabled:opacity-50"
                title="清除该方案的自定义覆盖"
              >
                恢复默认
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
            <p className="text-[11px] text-slate-400">方案摘要</p>
            <p className="text-xs text-slate-200 mt-1 whitespace-pre-wrap">
              {(detailDraft?.summary ?? detailPlan.plan.summary)?.trim()
                ? (detailDraft?.summary ?? detailPlan.plan.summary)
                : '（无）'}
            </p>
          </div>

          {viewMode === 'copy' ? (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-[11px] text-slate-400">文案速览（仅字幕文本）</p>
                <button
                  type="button"
                  onClick={async () => {
                    if (!mergedCopyText.trim()) return
                    try {
                      await navigator.clipboard.writeText(mergedCopyText)
                      setCopyStatus('ok')
                    } catch {
                      setCopyStatus('fail')
                    }
                  }}
                  disabled={!mergedCopyText.trim()}
                  className="text-[11px] rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-2 py-1 text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50"
                >
                  {copyStatus === 'ok' ? '复制成功' : copyStatus === 'fail' ? '复制失败' : '复制全文案'}
                </button>
              </div>
              <textarea
                value={mergedCopyText}
                readOnly
                rows={16}
                className="mt-2 w-full rounded-lg bg-slate-950/60 border border-slate-700 px-3 py-2 text-xs leading-5 text-slate-100 outline-none"
                placeholder="当前方案没有可用字幕文案。"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                参与成片 {activeSegments.length} 段，含文案{' '}
                {activeSegments.filter((s) => s.subtitle?.text?.trim()).length} 段（已排除弃用段）。
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
              <p className="text-[11px] text-slate-400">
                段落明细（字幕/音频/片段选择）· {activeSegments.length}/{segments.length} 段参与成片
              </p>
              <div className="mt-2 space-y-2">
                {segments.map((s, segIdx) => {
                const excluded = !!s.exclude_from_output
                const clipId = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id || ''
                const cm = clipId ? clipMetaByClip[clipId] : undefined
                // 字幕详情需要显示“方案标注”的句子级绝对时间；
                // 否则 quick-cut（同一 clip 多句）会把每句都显示成整段 clip 的时间轴。
                const abs0 = s.start_time_sec
                const abs1 = s.end_time_sec
                const subtitleText = s.subtitle?.text?.trim() || ''

                return (
                  <div
                    key={s.id}
                    className={`rounded-xl border px-3 py-2 ${
                      excluded
                        ? 'border-amber-900/60 bg-amber-950/20 opacity-90'
                        : 'border-slate-800 bg-slate-950/30'
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className={`text-xs font-semibold ${excluded ? 'text-amber-200/90' : 'text-slate-200'}`}>
                        #{s.order} · {fmt(abs0)}–{fmt(abs1)}
                        {excluded && (
                          <span className="ml-2 text-[10px] font-normal text-amber-400/90">已弃用</span>
                        )}
                      </p>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                        <span>音频模式: {s.audio_mode}</span>
                        <span>片段ID: {clipId || '-'}</span>
                        {cm?.video_id && <span>视频ID: {cm.video_id}</span>}
                        {s.subtitle?.strategy && <span>字幕: {s.subtitle.strategy}</span>}
                        {s.subtitle?.source && <span>来源: {s.subtitle.source}</span>}
                        {typeof s.override_duration_sec === 'number' && s.override_duration_sec > 0 && (
                          <span className="text-cyan-300/90">覆盖时长: {s.override_duration_sec.toFixed(3)}s</span>
                        )}
                      </div>
                    </div>

                    {detailEditMode && (
                      <label className="mt-2 flex cursor-pointer items-center gap-2 text-[11px] text-slate-300">
                        <input
                          type="checkbox"
                          className="rounded border-slate-600 bg-slate-900 text-amber-500 focus:ring-amber-500/40"
                          checked={excluded}
                          onChange={() => {
                            setDetailDraft((prev) => {
                              if (!prev) return prev
                              const segs = [...(prev.segments ?? [])]
                              const cur = { ...segs[segIdx], exclude_from_output: !excluded }
                              segs[segIdx] = cur
                              return { ...prev, segments: segs }
                            })
                          }}
                        />
                        <span>
                          弃用本段（成片不拼接、字幕不计入；其余段顺序连续对齐）
                        </span>
                      </label>
                    )}

                    <div className="mt-2 grid gap-2 md:grid-cols-2">
                      <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-2 py-2">
                        <p className="text-[11px] text-slate-400">字幕文本</p>
                        {detailEditMode ? (
                          <textarea
                            value={subtitleText}
                            onChange={(e) => {
                              const v = e.target.value
                              setDetailDraft((prev) => {
                                if (!prev) return prev
                                const segs = [...(prev.segments ?? [])]
                                const cur = { ...segs[segIdx] }
                                cur.subtitle = {
                                  strategy: cur.subtitle?.strategy ?? 'auto',
                                  text: v,
                                  source: 'user',
                                }
                                segs[segIdx] = cur
                                return { ...prev, segments: segs }
                              })
                            }}
                            rows={3}
                            className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-400 resize-y"
                            placeholder="输入该段字幕（将覆盖原字幕；TTS 段也会用于配音文本）"
                          />
                        ) : (
                          <p className={`text-xs text-slate-200 mt-1 whitespace-pre-wrap ${subtitleText ? '' : 'text-slate-500'}`}>
                            {subtitleText || '（无字幕/策略为 none）'}
                          </p>
                        )}
                      </div>

                      <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-2 py-2">
                        <p className="text-[11px] text-slate-400">片段 / 时间轴 / 可控时长（start/end 可能是时间轴坐标，不一定是片段内时间）</p>
                        <div className="mt-1 text-[11px] text-slate-300 space-y-1">
                          <p className="text-slate-400">
                            selected_clip_ids：
                            {(s.selected_clip_ids ?? []).length ? (s.selected_clip_ids ?? []).join(', ') : '（无）'}
                          </p>

                          {detailEditMode && !excluded && (
                            <div className="grid grid-cols-3 gap-2 pt-1">
                              <label className="col-span-1 text-[10px] text-slate-500">
                                start_sec
                                <input
                                  type="number"
                                  step={0.001}
                                  value={Number.isFinite(s.start_time_sec) ? s.start_time_sec : 0}
                                  onChange={(e) => {
                                    const nv = Number(e.target.value)
                                    setDetailDraft((prev) => {
                                      if (!prev) return prev
                                      const segs = [...(prev.segments ?? [])]
                                      const cur = {
                                        ...segs[segIdx],
                                        start_time_sec: Number.isFinite(nv) ? nv : segs[segIdx].start_time_sec,
                                      }
                                      segs[segIdx] = cur
                                      return { ...prev, segments: segs }
                                    })
                                  }}
                                  className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-cyan-400"
                                />
                              </label>

                              <label className="col-span-1 text-[10px] text-slate-500">
                                end_sec
                                <input
                                  type="number"
                                  step={0.001}
                                  value={Number.isFinite(s.end_time_sec) ? s.end_time_sec : 0}
                                  onChange={(e) => {
                                    const nv = Number(e.target.value)
                                    setDetailDraft((prev) => {
                                      if (!prev) return prev
                                      const segs = [...(prev.segments ?? [])]
                                      const cur = {
                                        ...segs[segIdx],
                                        end_time_sec: Number.isFinite(nv) ? nv : segs[segIdx].end_time_sec,
                                      }
                                      segs[segIdx] = cur
                                      return { ...prev, segments: segs }
                                    })
                                  }}
                                  className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-cyan-400"
                                />
                              </label>

                              <label className="col-span-1 text-[10px] text-slate-500">
                                段落时长(s)
                                <input
                                  type="number"
                                  step={0.001}
                                  value={typeof s.override_duration_sec === 'number' ? s.override_duration_sec : ''}
                                  onChange={(e) => {
                                    const raw = e.target.value
                                    const nv = raw === '' ? null : Number(raw)
                                    setDetailDraft((prev) => {
                                      if (!prev) return prev
                                      const segs = [...(prev.segments ?? [])]
                                      const cur = {
                                        ...segs[segIdx],
                                        override_duration_sec: raw === '' ? null : (Number.isFinite(nv as number) ? (nv as number) : null),
                                      }
                                      segs[segIdx] = cur
                                      return { ...prev, segments: segs }
                                    })
                                  }}
                                  className="mt-1 w-full rounded-md bg-slate-950/60 border border-slate-700 px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-cyan-400"
                                  placeholder="留空=自动"
                                  title="原声段会裁剪该段画面以对齐字幕；TTS 段若缩短会截断音频"
                                />
                              </label>
                            </div>
                          )}

                          <p className="text-slate-400">clip_group：{(s.clip_group ?? []).length ? '' : '（无）'}</p>

                          {(s.clip_group ?? []).slice(0, 6).map((c) => (
                            <p key={c.clip_id} className="truncate">
                              - {c.clip_id} · video_id: {c.video_id}
                              {typeof c.weight === 'number' ? ` · weight: ${c.weight}` : ''}
                            </p>
                          ))}
                          {(s.clip_group ?? []).length > 6 && (
                            <p className="text-slate-500">… 其余 {(s.clip_group ?? []).length - 6} 条已省略</p>
                          )}

                          {detailEditMode && !excluded && (
                            <div className="pt-1 flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => {
                                  setDetailDraft((prev) => {
                                    if (!prev) return prev
                                    const segs = [...(prev.segments ?? [])]
                                    const cur = { ...segs[segIdx], selected_clip_ids: [], clip_group: segs[segIdx].clip_group ?? [] }
                                    segs[segIdx] = cur
                                    return { ...prev, segments: segs }
                                  })
                                }}
                                className="text-[11px] rounded-lg border border-slate-700 bg-slate-950/40 px-2 py-1 text-slate-200 hover:bg-slate-950/70"
                                title="清空 selected_clip_ids，让后端按时间窗/候选池自动回退选片（更贴合你改的 start/end）"
                              >
                                按时间窗回退选片
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  if (!clipId) return
                                  setSelectedPreview({
                                    planId: detailPlan.plan.plan_id,
                                    planTitle: detailPlan.plan.title || `方案 ${detailPlan.index + 1}`,
                                    segmentId: s.id,
                                    order: s.order,
                                    clipId,
                                    videoId: cm?.video_id ?? null,
                                    source: (cm?.video_id ?? null) ? 'video' : 'clip',
                                    startSec: s.start_time_sec,
                                    endSec: s.end_time_sec,
                                  })
                                }}
                                className="text-[11px] rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-2 py-1 text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-60"
                                disabled={!clipId}
                                title="把该段送到上方预览播放器，方便边改边对齐"
                              >
                                片段预览
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

