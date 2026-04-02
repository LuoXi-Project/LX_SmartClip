'use client'

import { useState } from 'react'
import { LLM_KEYS, LLM_PROVIDERS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { ModelPicker } from './ModelPicker'
import { SaveBtn } from './SaveBtn'
import { Save, Info, Eye, EyeOff } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  llmProvider: string
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
  onApplyProvider: (p: ProviderPreset) => void
}

export function LlmSection({ config, edits, saving, saved, llmProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = LLM_KEYS.some((k) => isDirty(k) && config[k])

  const concurrency = Math.max(1, parseInt(v('llm_concurrency') || '1', 10) || 1)
  const [showLlmApiKey, setShowLlmApiKey] = useState(false)

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">LLM 文本模型</h2>
          <p className="text-xs text-slate-500 mt-0.5">文案生成、字幕时间轴、片段精排等文本处理</p>
        </div>
        <div className="flex items-center gap-3">
          <ProviderSelector providers={LLM_PROVIDERS} selectedId={llmProvider} onSelect={onApplyProvider} />
          {groupDirty && (
            <button onClick={() => onSaveGroup(LLM_KEYS)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
              <Save className="w-3.5 h-3.5" />保存全部
            </button>
          )}
        </div>
      </div>

      <div className="px-6 py-5 space-y-5">
        {config.llm_base_url && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 地址</label>
            <div className="flex gap-2">
              <input type="text" value={v('llm_base_url')} onChange={(e) => onSet('llm_base_url', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="https://api.openai.com/v1" />
              <SaveBtn dirty={isDirty('llm_base_url')} saving={!!saving['llm_base_url']} saved={!!saved['llm_base_url']} onSave={() => onSave('llm_base_url')} />
            </div>
            <p className="text-xs text-slate-500">LLM 服务的 API 基础地址，支持 OpenAI 兼容 API</p>
          </div>
        )}

        {config.llm_api_key && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">API 密钥</label>
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <input
                  type={showLlmApiKey ? 'text' : 'password'}
                  value={v('llm_api_key')}
                  onChange={(e) => onSet('llm_api_key', e.target.value)}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 pr-10 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                  placeholder="********"
                />
                <button
                  type="button"
                  onClick={() => setShowLlmApiKey((s) => !s)}
                  className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
                  aria-label={showLlmApiKey ? '隐藏明文密钥' : '显示明文密钥'}
                >
                  {showLlmApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <SaveBtn dirty={isDirty('llm_api_key')} saving={!!saving['llm_api_key']} saved={!!saved['llm_api_key']} onSave={() => onSave('llm_api_key')} />
            </div>
            <p className="text-xs text-slate-500">用于认证 LLM API 请求的密钥</p>
          </div>
        )}

        {config.llm_model && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">LLM 模型</label>
            <div className="flex gap-2 items-start">
              <div className="flex-1">
                <ModelPicker value={v('llm_model')} onChange={(val) => onSet('llm_model', val)}
                  baseUrl={v('llm_base_url')} apiKey={v('llm_api_key')} placeholder="gpt-4o-mini" />
              </div>
              <SaveBtn dirty={isDirty('llm_model')} saving={!!saving['llm_model']} saved={!!saved['llm_model']} onSave={() => onSave('llm_model')} />
            </div>
            <p className="text-xs text-slate-500">用于文本生成的模型名称，如 gpt-4o-mini、claude-3-haiku 等</p>
          </div>
        )}

        <div className="border-t border-slate-800/70" />
        <p className="text-xs font-medium text-slate-500 -mt-1">生成参数</p>

        {config.llm_temperature && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              温度 (Temperature)
              <span title="控制输出的随机性，0 = 确定性，2 = 最随机" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={0} max={2} step={0.1} value={v('llm_temperature')}
                  onChange={(e) => onSet('llm_temperature', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={0} max={2} step={0.1} value={v('llm_temperature')}
                  onChange={(e) => onSet('llm_temperature', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('llm_temperature')} saving={!!saving['llm_temperature']} saved={!!saved['llm_temperature']} onSave={() => onSave('llm_temperature')} />
            </div>
            <p className="text-xs text-slate-500">
              <span className="text-slate-400">当前温度 <span className="text-indigo-400 font-medium">{parseFloat(v('llm_temperature')).toFixed(1)}</span></span>
              {parseFloat(v('llm_temperature')) < 0.5 && <span className="text-blue-400 ml-1.5">· 精确模式（适合精排、分类）</span>}
              {parseFloat(v('llm_temperature')) >= 0.5 && parseFloat(v('llm_temperature')) <= 1.5 && <span className="text-slate-400 ml-1.5">· 平衡模式</span>}
              {parseFloat(v('llm_temperature')) > 1.5 && <span className="text-amber-400 ml-1.5">· 创意模式（适合文案生成）</span>}
            </p>
          </div>
        )}

        {config.llm_max_tokens && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              最大输出 Tokens
              <span title="单次请求的最大输出 token 数，超过此值会被截断" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2">
              <input type="number" min={100} step={500} value={v('llm_max_tokens')}
                onChange={(e) => onSet('llm_max_tokens', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="20480" />
              <SaveBtn dirty={isDirty('llm_max_tokens')} saving={!!saving['llm_max_tokens']} saved={!!saved['llm_max_tokens']} onSave={() => onSave('llm_max_tokens')} />
            </div>
            <p className="text-xs text-slate-500">
              当前限制 <span className="text-indigo-400 font-medium">{parseInt(v('llm_max_tokens')).toLocaleString()}</span> tokens · 影响文案生成、字幕时间轴等任务的输出长度
            </p>
          </div>
        )}

        {config.llm_max_context_tokens && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              最大输入上下文 Tokens
              <span title="模型支持的最大输入 token 数，用于文案生成等长上下文任务" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2">
              <input type="number" min={1000} step={1000} value={v('llm_max_context_tokens')}
                onChange={(e) => onSet('llm_max_context_tokens', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="128000" />
              <SaveBtn dirty={isDirty('llm_max_context_tokens')} saving={!!saving['llm_max_context_tokens']} saved={!!saved['llm_max_context_tokens']} onSave={() => onSave('llm_max_context_tokens')} />
            </div>
            <p className="text-xs text-slate-500">
              当前限制 <span className="text-indigo-400 font-medium">{parseInt(v('llm_max_context_tokens')).toLocaleString()}</span> tokens · 文案生成时会根据此值自动截断视频内容
            </p>
          </div>
        )}

        <div className="border-t border-slate-800/70" />
        <p className="text-xs font-medium text-slate-500 -mt-1">并发控制</p>

        {config.llm_concurrency && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              并发数量
              <span title="同时并行调用 LLM API 的任务数量" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={1} max={16} step={1} value={concurrency}
                  onChange={(e) => onSet('llm_concurrency', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={1} max={16} step={1} value={v('llm_concurrency')}
                  onChange={(e) => onSet('llm_concurrency', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('llm_concurrency')} saving={!!saving['llm_concurrency']} saved={!!saved['llm_concurrency']} onSave={() => onSave('llm_concurrency')} />
            </div>
            <p className="text-xs text-slate-500">
              当前并发 <span className="text-indigo-400 font-medium">{concurrency}</span> 个任务同时处理
              {concurrency >= 8 && <span className="text-amber-400 ml-1.5">· 注意 API 速率限制</span>}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}