'use client'

import { EMBEDDING_PROVIDERS, EMB_KEYS } from './constants'
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
  embProvider: string
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
  onApplyProvider: (p: ProviderPreset) => void
}

export function EmbeddingSection({ config, edits, saving, saved, embProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = EMB_KEYS.some((k) => isDirty(k) && config[k])

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">向量检索 / Embedding</h2>
          <p className="text-xs text-slate-500 mt-0.5">嵌入模型与检索参数</p>
        </div>
        <div className="flex items-center gap-3">
          <ProviderSelector providers={EMBEDDING_PROVIDERS} selectedId={embProvider} onSelect={onApplyProvider} />
          {groupDirty && (
            <button onClick={() => onSaveGroup(EMB_KEYS)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
              <Save className="w-3.5 h-3.5" />保存全部
            </button>
          )}
        </div>
      </div>
      <div className="px-6 py-5 space-y-5">
        {config.embedding_base_url && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 地址</label>
            <div className="flex gap-2">
              <input type="text" value={v('embedding_base_url')} onChange={(e) => onSet('embedding_base_url', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="https://api.openai.com/v1" />
              <SaveBtn dirty={isDirty('embedding_base_url')} saving={!!saving['embedding_base_url']} saved={!!saved['embedding_base_url']} onSave={() => onSave('embedding_base_url')} />
            </div>
          </div>
        )}
        {config.embedding_api_key && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 密钥</label>
            <div className="flex gap-2">
              <input type="password" value={v('embedding_api_key')} onChange={(e) => onSet('embedding_api_key', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="••••••••" />
              <SaveBtn dirty={isDirty('embedding_api_key')} saving={!!saving['embedding_api_key']} saved={!!saved['embedding_api_key']} onSave={() => onSave('embedding_api_key')} />
            </div>
          </div>
        )}
        {config.embedding_model && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">Embedding 模型</label>
            <div className="flex gap-2 items-start">
              <div className="flex-1">
                <ModelPicker value={v('embedding_model')} onChange={(val) => onSet('embedding_model', val)}
                  baseUrl={v('embedding_base_url')} apiKey={v('embedding_api_key')} placeholder="text-embedding-3-small" />
              </div>
              <SaveBtn dirty={isDirty('embedding_model')} saving={!!saving['embedding_model']} saved={!!saved['embedding_model']} onSave={() => onSave('embedding_model')} />
            </div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-4 pt-2 border-t border-slate-800">
          {(['vector_dimension', 'top_k', 'match_top_k', 'match_top_n'] as const).filter((k) => config[k]).map((key) => (
            <div key={key} className="space-y-1.5">
              <label className="text-xs text-slate-400">{config[key].label || key}</label>
              <div className="flex gap-2">
                <input type="number" value={v(key)} onChange={(e) => onSet(key, e.target.value)}
                  className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors" />
                <SaveBtn dirty={isDirty(key)} saving={!!saving[key]} saved={!!saved[key]} onSave={() => onSave(key)} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
