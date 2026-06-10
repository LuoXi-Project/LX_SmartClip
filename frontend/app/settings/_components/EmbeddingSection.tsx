'use client'

import { EMBEDDING_PROVIDERS, EMB_KEYS, MATCH_MODE_OPTIONS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { SaveBtn } from './SaveBtn'
import { Save, Info, Sparkles, Type, Brain, Zap } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'
import { ApiSecretField } from './ApiSecretField'
import { ApiTextField } from './ApiTextField'
import { ModelField } from './ModelField'

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
  const currentMatchMode = v('match_mode') || 'auto'
  const matchModeIcons: Record<string, typeof Sparkles> = {
    auto: Sparkles,
    vector: Zap,
    text: Type,
    llm_only: Brain,
  }

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
          <ApiTextField
            label="API 地址"
            value={v('embedding_base_url')}
            onChange={(val) => onSet('embedding_base_url', val)}
            placeholder={
              embProvider === 'volcengine'
                ? 'https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal'
                : 'https://api.openai.com/v1'
            }
            description={
              embProvider === 'volcengine' ? (
                <span>
                  火山方舟多模态向量接口，需与控制台地域一致；详见{' '}
                  <a
                    href="https://www.volcengine.com/docs/82379/1399008?lang=zh"
                    target="_blank"
                    rel="noreferrer"
                    className="text-indigo-400 hover:text-indigo-300 underline"
                  >
                    快速入门
                  </a>
                  。密钥为方舟 API Key（Bearer）。请求体中的 dimensions 与本页「向量维度」一致，仅支持 1024 或 2048。
                </span>
              ) : undefined
            }
            dirty={isDirty('embedding_base_url')}
            saving={!!saving['embedding_base_url']}
            saved={!!saved['embedding_base_url']}
            onSave={() => onSave('embedding_base_url')}
          />
        )}
        {config.embedding_api_key && (
          <ApiSecretField
            label="API 密钥"
            value={v('embedding_api_key')}
            onChange={(val) => onSet('embedding_api_key', val)}
            placeholder="••••••••"
            dirty={isDirty('embedding_api_key')}
            saving={!!saving['embedding_api_key']}
            saved={!!saved['embedding_api_key']}
            onSave={() => onSave('embedding_api_key')}
          />
        )}
        {config.embedding_model && (
          <ModelField
            label="Embedding 模型"
            value={v('embedding_model')}
            onChange={(val) => onSet('embedding_model', val)}
            baseUrl={v('embedding_base_url')}
            apiKey={v('embedding_api_key')}
            placeholder={embProvider === 'volcengine' ? 'doubao-embedding-vision-251215' : 'text-embedding-3-small'}
            description={
              embProvider === 'volcengine' ? (
                <span>方舟控制台开通的 Embedding 模型 ID；纯文本片段仅需 input 中的 text 字段即可。</span>
              ) : undefined
            }
            dirty={isDirty('embedding_model')}
            saving={!!saving['embedding_model']}
            saved={!!saved['embedding_model']}
            onSave={() => onSave('embedding_model')}
          />
        )}
        {config.match_mode && (
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-xs text-slate-400">素材匹配 / 检索模式</label>
                <p className="text-[11px] text-slate-600 mt-0.5">
                  手动匹配与素材检索共用；即使已配置 Embed 也可切换为文本或纯 LLM 模式
                </p>
              </div>
              <SaveBtn
                dirty={isDirty('match_mode')}
                saving={!!saving['match_mode']}
                saved={!!saved['match_mode']}
                onSave={() => onSave('match_mode')}
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {MATCH_MODE_OPTIONS.map((mode) => {
                const Icon = matchModeIcons[mode.value] ?? Sparkles
                const active = currentMatchMode === mode.value
                return (
                  <button
                    key={mode.value}
                    type="button"
                    onClick={() => onSet('match_mode', mode.value)}
                    className={`text-left rounded-xl border px-4 py-3.5 transition-all duration-200 ${
                      active
                        ? 'border-indigo-500 bg-indigo-500/10 ring-1 ring-indigo-500/30'
                        : 'border-slate-700 bg-slate-800/40 hover:border-slate-500 hover:bg-slate-800/70'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Icon className={`w-4 h-4 shrink-0 ${active ? 'text-indigo-400' : 'text-slate-400'}`} />
                      <span className={`text-sm font-medium ${active ? 'text-indigo-300' : 'text-slate-200'}`}>
                        {mode.label}
                      </span>
                      {active && (
                        <span className="ml-auto text-[10px] font-semibold text-indigo-400 bg-indigo-500/15 px-1.5 py-0.5 rounded-full">
                          当前
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-slate-500 leading-relaxed">{mode.desc}</p>
                  </button>
                )
              })}
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
