'use client'

import { VLM_PROVIDERS, VLM_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { ModelPicker } from './ModelPicker'
import { SaveBtn } from './SaveBtn'
import { Save } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  vlmProvider: string
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
  onApplyProvider: (p: ProviderPreset) => void
}

export function VlmSection({ config, edits, saving, saved, vlmProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = VLM_KEYS.some((k) => isDirty(k) && config[k])

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">API / 大模型</h2>
          <p className="text-xs text-slate-500 mt-0.5">视觉描述 (VLM) 与文本模型配置</p>
        </div>
        <div className="flex items-center gap-3">
          <ProviderSelector providers={VLM_PROVIDERS} selectedId={vlmProvider} onSelect={onApplyProvider} />
          {groupDirty && (
            <button onClick={() => onSaveGroup(VLM_KEYS)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
              <Save className="w-3.5 h-3.5" />保存全部
            </button>
          )}
        </div>
      </div>
      <div className="px-6 py-5 space-y-5">
        {config.vlm_base_url && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 地址</label>
            <div className="flex gap-2">
              <input type="text" value={v('vlm_base_url')} onChange={(e) => onSet('vlm_base_url', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="https://api.openai.com/v1" />
              <SaveBtn dirty={isDirty('vlm_base_url')} saving={!!saving['vlm_base_url']} saved={!!saved['vlm_base_url']} onSave={() => onSave('vlm_base_url')} />
            </div>
          </div>
        )}
        {config.vlm_api_key && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 密钥</label>
            <div className="flex gap-2">
              <input type="password" value={v('vlm_api_key')} onChange={(e) => onSet('vlm_api_key', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="••••••••" />
              <SaveBtn dirty={isDirty('vlm_api_key')} saving={!!saving['vlm_api_key']} saved={!!saved['vlm_api_key']} onSave={() => onSave('vlm_api_key')} />
            </div>
          </div>
        )}
        {config.vlm_model && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">VLM 模型</label>
            <div className="flex gap-2 items-start">
              <div className="flex-1">
                <ModelPicker value={v('vlm_model')} onChange={(val) => onSet('vlm_model', val)}
                  baseUrl={v('vlm_base_url')} apiKey={v('vlm_api_key')} placeholder="gpt-4o" />
              </div>
              <SaveBtn dirty={isDirty('vlm_model')} saving={!!saving['vlm_model']} saved={!!saved['vlm_model']} onSave={() => onSave('vlm_model')} />
            </div>
          </div>
        )}
        {config.llm_model && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">LLM 模型 (文本)</label>
            <div className="flex gap-2 items-start">
              <div className="flex-1">
                <ModelPicker value={v('llm_model')} onChange={(val) => onSet('llm_model', val)}
                  baseUrl={v('vlm_base_url')} apiKey={v('vlm_api_key')} placeholder="gpt-4o-mini" />
              </div>
              <SaveBtn dirty={isDirty('llm_model')} saving={!!saving['llm_model']} saved={!!saved['llm_model']} onSave={() => onSave('llm_model')} />
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
