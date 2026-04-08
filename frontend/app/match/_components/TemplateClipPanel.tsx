'use client'

import { useEffect, useRef, useState } from 'react'
import { useMatchStore } from '@/lib/store'
import { autoEditApi } from '@/lib/api'
import { LayoutTemplate } from 'lucide-react'
import { AutoEditPanel, type AutoEditPanelProps } from './AutoEditPanel'

/**
 * v4 模板剪辑：槽位结构（hook/problem/solution…）将对接后端；此处先选行业模板预设，
 * 并复用「自动一键成片」方案卡片与时间轴手调（方案详情内编辑），保证与实验模式一致的体验。
 */
type TemplateClipPanelProps = AutoEditPanelProps & {
  templatePresetSource: 'library' | 'replica'
  onReleaseReplicaTemplateLock: () => void
}

export function TemplateClipPanel(props: TemplateClipPanelProps) {
  const preset = useMatchStore((s) => s.templatePreset)
  const setPreset = useMatchStore((s) => s.setTemplatePreset)
  const autoTemplateEnabled = useMatchStore((s) => s.autoTemplateEnabled)
  const setAutoTemplateEnabled = useMatchStore((s) => s.setAutoTemplateEnabled)
  const templateLockedByReplica = props.templatePresetSource === 'replica'
  // 避免模板列表异步加载时“回退到第一个模板”覆盖用户刚选的模板
  const userSelectedRef = useRef(false)

  const [templates, setTemplates] = useState<Array<{ id: string; label: string }>>([])
  const [templatesLoading, setTemplatesLoading] = useState(true)
  const [templatesError, setTemplatesError] = useState('')

  useEffect(() => {
    let mounted = true
    setTemplatesLoading(true)
    setTemplatesError('')

    autoEditApi
      .templates()
      .then((res) => {
        if (!mounted) return
        const next = res || []
        setTemplates(next)
        if (!userSelectedRef.current && next.length > 0) {
          const curPreset = useMatchStore.getState().templatePreset
          if (!next.some((t) => t.id === curPreset)) setPreset(next[0].id)
        }
      })
      .catch((e: unknown) => {
        if (!mounted) return
        const msg = (e as { message?: string })?.message || '加载模板失败'
        setTemplatesError(msg)
      })
      .finally(() => {
        if (!mounted) return
        setTemplatesLoading(false)
      })

    return () => {
      mounted = false
    }
  }, [])

  // 模板剪辑依赖事件级编排，默认帮用户打开 Timeline Engine
  useEffect(() => {
    if (autoTemplateEnabled && !props.autoUseTimelineEngine) props.onAutoUseTimelineEngineChange(true)
  }, [autoTemplateEnabled, props.autoUseTimelineEngine, props.onAutoUseTimelineEngineChange])

  return (
    <>
      <section className="rounded-2xl border border-amber-500/25 bg-amber-500/5 p-5 space-y-4">
        <p className="text-xs font-semibold text-amber-300 uppercase tracking-widest flex items-center gap-2">
          <LayoutTemplate className="w-4 h-4" />
          模板剪辑
        </p>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          结构驱动 + 内容填充（slot 标签匹配与兜底将走后端）。生成方案后可在候选卡片中打开详情，手动调整片段时间轴与字幕，再一键成片。
        </p>
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoTemplateEnabled}
              onChange={(e) => setAutoTemplateEnabled(e.target.checked)}
              className="rounded border-slate-600 bg-slate-900 text-amber-500 focus:ring-amber-500/40"
            />
            <span className="text-sm text-slate-200">启用模板剪辑（slot 编排）</span>
          </label>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            关闭后将回到原「一键智能剪辑（实验）」的 tier 预算编排逻辑。
          </p>
        </div>
        {templatesLoading ? (
          <p className="text-[11px] text-slate-500 leading-relaxed">加载模板中…</p>
        ) : templatesError ? (
          <p className="text-[11px] text-red-300 leading-relaxed">{templatesError}</p>
        ) : templates.length === 0 ? (
          <p className="text-[11px] text-slate-500 leading-relaxed">暂无模板</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {templateLockedByReplica ? (
              <div className="w-full flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-500/35 bg-emerald-500/10 px-3 py-2">
                <p className="text-[11px] text-emerald-200">当前由链接复刻约束驱动，模板已锁定为：复刻模板</p>
                <button
                  type="button"
                  onClick={props.onReleaseReplicaTemplateLock}
                  className="text-[11px] text-slate-200 border border-slate-600 rounded-lg px-2.5 py-1 hover:border-slate-500"
                >
                  解除锁定
                </button>
              </div>
            ) : null}
            {templates.map((t) => (
              <button
                key={t.id}
                type="button"
                disabled={templateLockedByReplica}
                onClick={() => {
                  userSelectedRef.current = true
                  setPreset(t.id)
                }}
                className={`px-3 py-1.5 rounded-xl border text-xs transition-colors ${
                  preset === t.id
                    ? 'border-amber-500/70 bg-amber-500/15 text-amber-200'
                    : 'border-slate-700 bg-slate-900/50 text-slate-400 hover:border-slate-600'
                } ${
                  templateLockedByReplica ? 'cursor-not-allowed opacity-45 hover:border-slate-700' : ''
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
      </section>
      <AutoEditPanel {...props} />
    </>
  )
}
