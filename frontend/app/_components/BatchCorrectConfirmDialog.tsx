'use client'

import { useEffect, useState } from 'react'
import { Wand2, X, Loader2 } from 'lucide-react'

interface BatchCorrectConfirmDialogProps {
  open: boolean
  /** 待校准片段数 */
  totalClips: number
  /** 全局提示词（作输入框预填/placeholder 参考） */
  globalHint: string | null
  /** 校准进行中（按钮转圈，禁用关闭） */
  running: boolean
  /** 用户点「开始校准」，携带输入的提示词（空串=用全局） */
  onConfirm: (hint: string) => void
  /** 关闭/取消 */
  onCancel: () => void
}

/**
 * 批量校准的确认弹窗：带「辅助提示词」输入框。
 * 与 ConfirmDialog 风格一致，但额外支持文本输入。
 * 流程：点批量校准 → 此弹窗填提示词 → 开始校准 → 自动进入审核弹层。
 */
export function BatchCorrectConfirmDialog({
  open,
  totalClips,
  globalHint,
  running,
  onConfirm,
  onCancel,
}: BatchCorrectConfirmDialogProps) {
  const [hint, setHint] = useState('')

  // 弹窗打开时预填全局提示词（若已懒加载到），关闭时不清空以便复看
  useEffect(() => {
    if (open && globalHint !== null) {
      setHint(globalHint)
    }
  }, [open, globalHint])

  // 关闭弹窗时重置输入（下次打开重新预填）
  useEffect(() => {
    if (!open) setHint('')
  }, [open])

  // Esc 关闭（校准中禁用）
  useEffect(() => {
    if (!open || running) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, running, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[999] flex items-center justify-center p-4"
      aria-modal="true"
      role="dialog"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-150"
        onClick={running ? undefined : onCancel}
      />
      <div className="relative z-10 w-full max-w-md bg-[#161922] border border-slate-700/60 rounded-2xl shadow-2xl shadow-black/60 animate-in fade-in zoom-in-95 duration-150">
        <button
          onClick={running ? undefined : onCancel}
          disabled={running}
          className="absolute top-3.5 right-3.5 p-1 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors disabled:opacity-40"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="p-6">
          <div className="flex items-start gap-3.5 mb-3">
            <div className="shrink-0 w-10 h-10 rounded-full bg-indigo-500/15 text-indigo-400 flex items-center justify-center">
              <Wand2 className="w-5 h-5" />
            </div>
            <div className="pt-1.5">
              <h3 className="text-slate-100 font-semibold text-base leading-snug">批量 LLM 校准</h3>
              <p className="text-slate-400 text-sm mt-1 leading-relaxed">
                将对当前视频全部 <span className="text-slate-200 font-medium">{totalClips}</span> 个片段调用 LLM 校准。校准后会弹出审核界面，可逐句确认后再写库，不会直接覆盖。
              </p>
            </div>
          </div>

          {/* 辅助提示词输入框 */}
          <div className="mt-4 space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              辅助提示词（可选）
              <span
                title="填入领域词汇/专有名词/口音特点，提升领域词修正率。留空则用「设置-语音识别」里的全局值"
                className="text-slate-600 cursor-help"
              >
                ⓘ
              </span>
            </label>
            <textarea
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              disabled={running}
              rows={3}
              placeholder={
                globalHint
                  ? `已预填全局值（可修改）。留空则用全局：${globalHint}`
                  : '留空用全局设置。例：这是面巾纸视频，「面积纸」应为「面巾纸」'
              }
              className="w-full px-3 py-2 rounded-lg bg-slate-900/60 border border-slate-700 text-sm text-slate-200 placeholder-slate-600 outline-none focus:border-indigo-500 transition-colors resize-y disabled:opacity-60"
            />
          </div>

          <div className="flex gap-2.5 mt-5 justify-end">
            <button
              onClick={onCancel}
              disabled={running}
              className="px-4 py-2 text-sm font-medium text-slate-300 bg-slate-700/60 hover:bg-slate-700 rounded-lg transition-colors disabled:opacity-40"
            >
              取消
            </button>
            <button
              onClick={() => onConfirm(hint)}
              disabled={running}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition-colors disabled:opacity-60"
            >
              {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {running ? '校准中…' : '开始校准'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
