'use client'

import { useState } from 'react'
import { FileText, Keyboard, Sparkles } from 'lucide-react'
import { VoiceInputControl } from '@/components/ui/voice-input'
import { CopyGeneratorPanel } from './CopyGeneratorPanel'

export type CopySourcePanelProps = {
  globalQuery: string
  onGlobalQueryChange: (value: string) => void
  /** AI 生成读取的素材范围（与页面顶部「限定视频范围」一致） */
  selectedVideoIds: string[]
  onAiApply: (parts: string[]) => void
  replicaTemplateGuide?: string
}

/**
 * 工作区级「文案」输入源（置顶卡片）：
 * 同一份文案两种产出方式 —— 手动输入 / AI 智能生成（Tab 切换）。
 * 全自动成片与手动逐段模式共用此文案。
 */
export function CopySourcePanel({
  globalQuery,
  onGlobalQueryChange,
  selectedVideoIds,
  onAiApply,
  replicaTemplateGuide,
}: CopySourcePanelProps) {
  const [tab, setTab] = useState<'manual' | 'ai'>('manual')

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
      {/* 卡片头：步骤号 + 标题 + Tab 切换 */}
      <div className="flex items-center justify-between gap-3 flex-wrap px-4 pt-3 pb-0">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500/20 text-[10px] text-indigo-300">1</span>
          <FileText className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">文案</p>
          <span className="text-[11px] text-slate-600 normal-case font-normal">
            按空行自动拆段；下方「全自动成片」与「手动逐段模式」共用
          </span>
        </div>
        <div className="flex items-center gap-1 rounded-xl border border-slate-700 bg-slate-900/70 p-1">
          <button
            type="button"
            onClick={() => setTab('manual')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors ${
              tab === 'manual' ? 'bg-indigo-500/15 text-indigo-300' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Keyboard className="w-3.5 h-3.5" />
            手动输入
          </button>
          <button
            type="button"
            onClick={() => setTab('ai')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors ${
              tab === 'ai' ? 'bg-indigo-500/15 text-indigo-300' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            AI 生成
          </button>
        </div>
      </div>

      {/* Tab 内容 */}
      <div className="p-4">
        {tab === 'manual' ? (
          <div className="relative">
            <textarea
              value={globalQuery}
              onChange={(e) => onGlobalQueryChange(e.target.value)}
              placeholder="粘贴完整口播/脚本文案；也可点右上「AI 生成」让 AI 基于素材代写，或用右侧语音按钮口述..."
              rows={4}
              className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 pr-12 text-sm outline-none focus:border-indigo-500 placeholder-slate-600 resize-none"
            />
            <div className="absolute right-2 top-2 z-10">
              <VoiceInputControl
                intent="这是剪辑工作台的文案输入：用户口述或朗读完整口播/脚本。整理成适合按空行拆分的正文，保留段落感；不要添加元说明。"
                value={globalQuery}
                onTextChange={onGlobalQueryChange}
                merge="append"
              />
            </div>
          </div>
        ) : (
          <CopyGeneratorPanel
            variant="embedded"
            selectedVideoIds={selectedVideoIds}
            onApply={onAiApply}
            replicaTemplateGuide={replicaTemplateGuide}
            onApplied={() => setTab('manual')}
          />
        )}
      </div>
    </section>
  )
}
