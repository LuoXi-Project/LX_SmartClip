'use client'

import { useEffect, useMemo, useState } from 'react'
import { X, Check, RotateCcw, Loader2, Wand2, CheckCheck } from 'lucide-react'
import type { AsrCorrectBatchResult, AsrSegmentJson } from '@/lib/api'

/** 单句审核状态：accepted=用校准后文本（可编辑），false=还原为原文 */
type SegReview = {
  /** 是否采纳校准后文本（false=保留原文） */
  accepted: boolean
  /** 当前编辑中的文本（accepted 时生效） */
  text: string
}

/** 按 clip 聚合的审核状态 */
type ClipReview = {
  clip_id: string
  /** 原文段（不变） */
  original_segments: AsrSegmentJson[]
  /** 校准后段（不变，作参考） */
  corrected_segments: AsrSegmentJson[]
  /** 每句审核状态，下标与 segments 对齐 */
  segs: SegReview[]
  error?: string
}

export interface BatchCorrectReviewModalProps {
  open: boolean
  /** 批量校准预览结果（apply=false 的返回） */
  data: AsrCorrectBatchResult | null
  submitting: boolean
  onClose: () => void
  /**
   * 提交审核结果。
   * 返回每个 clip 的最终 segments（保留原 start/end，text 为用户审核后的），
   * 按 clip_id 索引。
   */
  onSubmit: (finalized: Record<string, AsrSegmentJson[]>) => void
}

export function BatchCorrectReviewModal({
  open,
  data,
  submitting,
  onClose,
  onSubmit,
}: BatchCorrectReviewModalProps) {
  // 审核状态：clip_id -> ClipReview
  const [reviews, setReviews] = useState<Record<string, ClipReview>>({})

  // 每当 data 变化（新一次批量校准），重建审核状态
  useEffect(() => {
    if (!open || !data) {
      setReviews({})
      return
    }
    const next: Record<string, ClipReview> = {}
    for (const item of data.results) {
      if (item.status !== 'success') {
        next[item.clip_id] = {
          clip_id: item.clip_id,
          original_segments: [],
          corrected_segments: [],
          segs: [],
          error: item.error,
        }
        continue
      }
      const orig = item.original_segments ?? []
      const corr = item.corrected_segments ?? []
      // 默认：有改动的句接受校准，无改动的不动
      const segs: SegReview[] = corr.map((c, i) => {
        const o = orig[i]?.text ?? ''
        const changed = (c.text ?? '') !== o
        return { accepted: changed, text: c.text ?? '' }
      })
      next[item.clip_id] = {
        clip_id: item.clip_id,
        original_segments: orig,
        corrected_segments: corr,
        segs,
      }
    }
    setReviews(next)
  }, [open, data])

  // 统计
  const stats = useMemo(() => {
    let totalClips = 0
    let changedClips = 0
    let failedClips = 0
    let totalSegs = 0
    let acceptedSegs = 0
    for (const cr of Object.values(reviews)) {
      if (cr.error) {
        failedClips += 1
        continue
      }
      const hasChange = cr.segs.some((s) => s.accepted)
      if (cr.corrected_segments.length > 0) totalClips += 1
      if (hasChange) changedClips += 1
      for (const s of cr.segs) {
        totalSegs += 1
        if (s.accepted) acceptedSegs += 1
      }
    }
    return { totalClips, changedClips, failedClips, totalSegs, acceptedSegs }
  }, [reviews])

  /** 切换某 clip 某句的采纳状态 */
  const toggleSeg = (clipId: string, idx: number) => {
    setReviews((prev) => {
      const cr = prev[clipId]
      if (!cr) return prev
      const segs = [...cr.segs]
      segs[idx] = { ...segs[idx], accepted: !segs[idx].accepted }
      return { ...prev, [clipId]: { ...cr, segs } }
    })
  }

  /** 编辑某 clip 某句的文本 */
  const editSegText = (clipId: string, idx: number, text: string) => {
    setReviews((prev) => {
      const cr = prev[clipId]
      if (!cr) return prev
      const segs = [...cr.segs]
      segs[idx] = { ...segs[idx], text, accepted: true }
      return { ...prev, [clipId]: { ...cr, segs } }
    })
  }

  /** 某 clip 全部接受 */
  const acceptAllInClip = (clipId: string) => {
    setReviews((prev) => {
      const cr = prev[clipId]
      if (!cr) return prev
      const segs = cr.segs.map((s) => ({ ...s, accepted: true }))
      return { ...prev, [clipId]: { ...cr, segs } }
    })
  }

  /** 某 clip 全部还原 */
  const revertAllInClip = (clipId: string) => {
    setReviews((prev) => {
      const cr = prev[clipId]
      if (!cr) return prev
      const segs = cr.segs.map((s) => ({ ...s, accepted: false }))
      return { ...prev, [clipId]: { ...cr, segs } }
    })
  }

  /** 全局全部接受 */
  const acceptAll = () => {
    setReviews((prev) => {
      const next: Record<string, ClipReview> = {}
      for (const [k, cr] of Object.entries(prev)) {
        next[k] = { ...cr, segs: cr.segs.map((s) => ({ ...s, accepted: true })) }
      }
      return next
    })
  }

  /** 提交：组装最终 segments */
  const handleSubmit = () => {
    const finalized: Record<string, AsrSegmentJson[]> = {}
    for (const cr of Object.values(reviews)) {
      if (cr.error || cr.original_segments.length === 0) continue
      // 接受的句用编辑后 text，未接受的用原文 text；start/end 始终保留原值
      const segs: AsrSegmentJson[] = cr.original_segments.map((o, i) => {
        const review = cr.segs[i]
        const text = review?.accepted ? review.text : o.text
        return { start: o.start, end: o.end, text }
      })
      finalized[cr.clip_id] = segs
    }
    onSubmit(finalized)
  }

  if (!open || !data) return null

  const clipEntries = Object.values(reviews).filter(
    (cr) => cr.original_segments.length > 0 || cr.error,
  )

  return (
    <div
      className="fixed inset-0 z-[998] flex items-center justify-center p-4"
      aria-modal="true"
      role="dialog"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150"
        onClick={submitting ? undefined : onClose}
      />
      <div className="relative z-10 w-full max-w-3xl max-h-[88vh] flex flex-col bg-[#161922] border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-indigo-500/15 text-indigo-400 flex items-center justify-center">
              <Wand2 className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-slate-100 font-semibold text-sm">批量校准审核</h3>
              <p className="text-[11px] text-slate-500 leading-tight">
                {stats.changedClips}/{stats.totalClips} 片段有改动 · 已采纳 {stats.acceptedSegs}/{stats.totalSegs} 句
                {stats.failedClips > 0 && (
                  <span className="text-red-400"> · {stats.failedClips} 个失败</span>
                )}
              </p>
            </div>
          </div>
          <button
            onClick={submitting ? undefined : onClose}
            disabled={submitting}
            className="p-1 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-40"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2 px-5 py-2 border-b border-slate-800 bg-slate-950/20 shrink-0">
          <button
            type="button"
            onClick={acceptAll}
            disabled={submitting}
            className="inline-flex items-center gap-1 rounded-md border border-emerald-700/50 bg-emerald-900/30 px-2.5 py-1 text-[11px] text-emerald-200 hover:border-emerald-500 disabled:opacity-40 transition-colors"
          >
            <CheckCheck className="w-3.5 h-3.5" />
            全部接受
          </button>
          <p className="text-[11px] text-slate-500 ml-1">
            绿色=已采纳校准；灰色=保留原文。可点句子切换，或直接编辑文字。
          </p>
        </div>

        {/* Body: 片段列表 */}
        <div className="flex-1 min-h-0 overflow-y-auto styled-scrollbar p-4 space-y-3">
          {/* 诊断：后端报告有成功但审核层未收到句级数据 */}
          {stats.totalClips === 0 && (data?.success ?? 0) > 0 && (
            <div className="rounded-lg border border-amber-800/50 bg-amber-950/20 p-3 text-[11px] text-amber-300 space-y-1">
              <div className="font-medium">⚠ 数据异常</div>
              <div>
                后端报告 {data?.success} 个片段校准成功（{data?.changed} 个有改动），但审核层未收到可显示的句级数据。
              </div>
              <div className="text-amber-400/70">
                返回结果条目 {(data?.results ?? []).length}。请刷新页面后重试；若持续出现，请检查浏览器控制台网络响应。
              </div>
            </div>
          )}
          {clipEntries.length === 0 && (
            <div className="text-center text-sm text-slate-500 py-10 space-y-2">
              <div>无可审核的片段</div>
              <div className="text-[11px] text-slate-600">
                后端返回：共 {data?.total ?? 0}，成功 {data?.success ?? 0}，有改动 {data?.changed ?? 0}，结果条目 {(data?.results ?? []).length}
              </div>
            </div>
          )}
          {clipEntries.map((cr) => {
            const clipIdx = clipEntries.indexOf(cr) + 1
            return (
              <div
                key={cr.clip_id}
                className="rounded-lg border border-slate-800 bg-slate-900/40 overflow-hidden"
              >
                {/* clip 头 */}
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-slate-950/30">
                  <div className="text-[11px] text-slate-400 font-medium">
                    片段 #{clipIdx}
                    <span className="text-slate-600 ml-1.5">{cr.clip_id.slice(0, 8)}…</span>
                    {cr.error ? (
                      <span className="text-red-400 ml-2">· 失败：{cr.error}</span>
                    ) : (
                      <span className="text-amber-400 ml-2">· {cr.segs.length} 句</span>
                    )}
                  </div>
                  {!cr.error && cr.segs.length > 0 && (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => acceptAllInClip(cr.clip_id)}
                        disabled={submitting}
                        className="inline-flex items-center gap-0.5 rounded border border-emerald-800/50 bg-emerald-900/20 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:border-emerald-600 disabled:opacity-40 transition-colors"
                      >
                        <Check className="w-2.5 h-2.5" />全接受
                      </button>
                      <button
                        type="button"
                        onClick={() => revertAllInClip(cr.clip_id)}
                        disabled={submitting}
                        className="inline-flex items-center gap-0.5 rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400 hover:text-slate-200 disabled:opacity-40 transition-colors"
                      >
                        <RotateCcw className="w-2.5 h-2.5" />全还原
                      </button>
                    </div>
                  )}
                </div>

                {/* 句级列表 */}
                {!cr.error && cr.segs.length > 0 && (
                  <div className="p-2 space-y-1.5">
                    {cr.segs.map((s, i) => {
                      const origText = cr.original_segments[i]?.text ?? ''
                      const corrText = cr.corrected_segments[i]?.text ?? ''
                      const isChanged = corrText !== origText
                      const editing = s.text !== corrText && s.accepted
                      return (
                        <div
                          key={i}
                          className={`rounded-md border p-2 text-xs transition-colors ${
                            s.accepted
                              ? 'border-emerald-800/50 bg-emerald-950/15'
                              : 'border-slate-800 bg-slate-950/30'
                          } ${!isChanged ? 'opacity-60' : ''}`}
                        >
                          <div className="flex items-start gap-2">
                            <button
                              type="button"
                              onClick={() => toggleSeg(cr.clip_id, i)}
                              disabled={submitting || !isChanged}
                              title={s.accepted ? '已采纳校准（点击还原原文）' : '保留原文（点击采纳校准）'}
                              className={`mt-0.5 shrink-0 w-4 h-4 rounded flex items-center justify-center transition-colors ${
                                s.accepted
                                  ? 'bg-emerald-600 text-white'
                                  : isChanged
                                    ? 'border border-slate-600 text-transparent hover:border-emerald-500'
                                    : 'border border-slate-700 text-transparent cursor-not-allowed'
                              }`}
                            >
                              <Check className="w-2.5 h-2.5" />
                            </button>
                            <div className="flex-1 min-w-0">
                              <div className="text-[10px] text-slate-600 mb-0.5">
                                #{i + 1} · {cr.original_segments[i]?.start.toFixed(2)}s—{cr.original_segments[i]?.end.toFixed(2)}s
                              </div>
                              {!isChanged ? (
                                <div className="text-slate-400 break-all">{origText || '（空）'}</div>
                              ) : (
                                <>
                                  {/* 原文 */}
                                  <div className="text-slate-500 line-through decoration-slate-600 break-all">
                                    {origText || '（空）'}
                                  </div>
                                  {/* 校准后（可编辑） */}
                                  <textarea
                                    value={s.text}
                                    onChange={(e) => editSegText(cr.clip_id, i, e.target.value)}
                                    disabled={submitting}
                                    rows={1}
                                    className={`mt-0.5 w-full px-1.5 py-1 rounded text-slate-200 break-all resize-y outline-none transition-colors ${
                                      editing
                                        ? 'bg-amber-950/25 border border-amber-800/50 focus:border-amber-600'
                                        : 'bg-transparent border border-transparent focus:border-indigo-600'
                                    } disabled:opacity-60`}
                                  />
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-slate-800 shrink-0">
          <div className="text-[11px] text-slate-500">
            提交后将写库覆盖 ASR，时间轴保留不变。
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={submitting ? undefined : onClose}
              disabled={submitting}
              className="px-3.5 py-1.5 text-sm font-medium text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-40"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting || stats.changedClips === 0}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              提交审核结果
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
