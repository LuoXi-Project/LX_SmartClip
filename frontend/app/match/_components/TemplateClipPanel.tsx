'use client'

import { useState } from 'react'
import { LayoutTemplate } from 'lucide-react'
import { AutoEditPanel, type AutoEditPanelProps } from './AutoEditPanel'

const TEMPLATE_PRESETS = [
  { id: 'ecommerce', label: '电商转化' },
  { id: 'marketing', label: '营销号' },
  { id: 'tech_review', label: '科技测评' },
] as const

export type TemplatePresetId = (typeof TEMPLATE_PRESETS)[number]['id']

/**
 * v4 模板剪辑：槽位结构（hook/problem/solution…）将对接后端；此处先选行业模板预设，
 * 并复用「自动一键成片」方案卡片与时间轴手调（方案详情内编辑），保证与实验模式一致的体验。
 */
export function TemplateClipPanel(props: AutoEditPanelProps) {
  const [preset, setPreset] = useState<TemplatePresetId>('ecommerce')

  return (
    <>
      <section className="rounded-2xl border border-amber-500/25 bg-amber-500/5 p-5 space-y-4">
        <p className="text-xs font-semibold text-amber-300 uppercase tracking-widest flex items-center gap-2">
          <LayoutTemplate className="w-4 h-4" />
          模板剪辑（v4）
        </p>
        <p className="text-[11px] text-slate-500 leading-relaxed">
          结构驱动 + 内容填充（slot 标签匹配与兜底将走后端）。生成方案后可在候选卡片中打开详情，手动调整片段时间轴与字幕，再一键成片。
        </p>
        <div className="flex flex-wrap gap-2">
          {TEMPLATE_PRESETS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setPreset(t.id)}
              className={`px-3 py-1.5 rounded-xl border text-xs transition-colors ${
                preset === t.id
                  ? 'border-amber-500/70 bg-amber-500/15 text-amber-200'
                  : 'border-slate-700 bg-slate-900/50 text-slate-400 hover:border-slate-600'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </section>
      <AutoEditPanel {...props} />
    </>
  )
}
