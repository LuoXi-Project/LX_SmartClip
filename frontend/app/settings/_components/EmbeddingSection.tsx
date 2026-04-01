'use client'

import { EMBEDDING_PROVIDERS, EMB_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { ModelPicker } from './ModelPicker'
import { SaveBtn } from './SaveBtn'
import { Save, Info } from 'lucide-react'
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
  const concurrency = Math.max(1, parseInt(v('embedding_concurrency') || '3', 10) || 3)

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

        <div className="border-t border-slate-800/70 pt-4" />
        <p className="text-xs font-medium text-slate-500 -mt-2">并发控制</p>
        {config.embedding_concurrency && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              并发数量
              <span title="同时并行生成 Embedding 的片段数量" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={1} max={16} step={1} value={concurrency}
                  onChange={(e) => onSet('embedding_concurrency', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={1} max={16} step={1} value={v('embedding_concurrency')}
                  onChange={(e) => onSet('embedding_concurrency', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('embedding_concurrency')} saving={!!saving['embedding_concurrency']} saved={!!saved['embedding_concurrency']} onSave={() => onSave('embedding_concurrency')} />
            </div>
            <p className="text-xs text-slate-500">
              当前并发 <span className="text-indigo-400 font-medium">{concurrency}</span> 个片段同时生成向量
              {concurrency >= 8 && <span className="text-amber-400 ml-1.5">· 注意 API 速率限制</span>}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
