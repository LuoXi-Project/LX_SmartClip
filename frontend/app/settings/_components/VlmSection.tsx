'use client'

import { useMemo, useState } from 'react'
import { VLM_PROVIDERS, VLM_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { ModelPicker } from './ModelPicker'
import { SaveBtn } from './SaveBtn'
import { Save, Info, AlertTriangle, Eye, EyeOff } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'

const TOKENS_PROMPT_OVERHEAD = 300

function calcOpenAITokens(width: number, height: number, detail = 'auto'): number {
  if (detail === 'low') return 85
  const origShort = Math.min(width, height)
  const origLong = Math.max(width, height)
  if (detail === 'auto' && origShort <= 768 && origLong <= 2048) return 85
  let w = width, h = height
  if (w > 2048 || h > 2048) { const s = 2048 / Math.max(w, h); w = Math.floor(w * s); h = Math.floor(h * s) }
  const ss = Math.min(w, h)
  if (ss > 768) { const s = 768 / ss; w = Math.floor(w * s); h = Math.floor(h * s) }
  return Math.ceil(w / 512) * Math.ceil(h / 512) * 170 + 85
}

function calcQwenTokens(width: number, height: number, patchSize = 28): number {
  const maxT = 1225, minT = 4
  const maxP = maxT * patchSize * patchSize
  const minP = minT * patchSize * patchSize
  let w = width, h = height, t = w * h
  if (t > maxP) { const s = Math.sqrt(maxP / t); w = Math.floor(w * s); h = Math.floor(h * s) }
  else if (t < minP) { const s = Math.sqrt(minP / t); w = Math.floor(w * s); h = Math.floor(h * s) }
  return Math.max(minT, Math.min(maxT, Math.ceil(h / patchSize) * Math.ceil(w / patchSize)))
}

function calcGlmTokens(width: number, height: number): number {
  const maxSize = 1120, patchSize = 336, patchTokens = 256, baseTokens = 256
  let w = width, h = height
  if (w > maxSize || h > maxSize) {
    const scale = maxSize / Math.max(w, h)
    w = Math.floor(w * scale); h = Math.floor(h * scale)
  }
  return Math.ceil(w / patchSize) * Math.ceil(h / patchSize) * patchTokens + baseTokens
}

const RESOLUTION_PRESETS = [
  { label: '720p  (1280x720)',   w: 1280, h: 720  },
  { label: '1080p (1920x1080)', w: 1920, h: 1080 },
  { label: '540p  (960x540)',   w: 960,  h: 540  },
  { label: '480p  (854x480)',   w: 854,  h: 480  },
  { label: '2K    (2560x1440)', w: 2560, h: 1440 },
]

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

  const contextLength = Math.max(1, parseInt(v('vlm_context_length') || '8192', 10) || 8192)
  const maxImages = Math.max(1, parseInt(v('vlm_max_images_per_batch') || '10', 10) || 10)
  const concurrency = Math.max(1, parseInt(v('vlm_concurrency') || '3', 10) || 3)

  const [resPresetIdx, setResPresetIdx] = useState(0)
  const preset = RESOLUTION_PRESETS[resPresetIdx]
  const isQwenStyle = ['siliconflow', 'zhipuai'].includes(vlmProvider)
  const isGlmStyle = vlmProvider === 'zhipuai' || v('vlm_model').toLowerCase().includes('glm')
  const [showVlmApiKey, setShowVlmApiKey] = useState(false)

  const tokensPerImage = useMemo(
    () => isGlmStyle ? calcGlmTokens(preset.w, preset.h) : isQwenStyle ? calcQwenTokens(preset.w, preset.h) : calcOpenAITokens(preset.w, preset.h),
    [preset, isQwenStyle, isGlmStyle]
  )
  const openaiTokens = useMemo(() => calcOpenAITokens(preset.w, preset.h), [preset])
  const qwenTokens   = useMemo(() => calcQwenTokens(preset.w, preset.h),   [preset])
  const glmTokens    = useMemo(() => calcGlmTokens(preset.w, preset.h),    [preset])

  const imageTokensUsed = useMemo(
    () => maxImages * tokensPerImage + TOKENS_PROMPT_OVERHEAD,
    [maxImages, tokensPerImage]
  )
  // GLM real-world usage is ~2x the formula estimate (empirical from logs)
  const glmSafetyFactor = isGlmStyle ? 2.0 : 1.0
  const tokenBudgetOk = imageTokensUsed * glmSafetyFactor <= contextLength
  const suggestedMax = useMemo(
    () => Math.max(1, Math.floor((contextLength - TOKENS_PROMPT_OVERHEAD) / (tokensPerImage * glmSafetyFactor))),
    [contextLength, tokensPerImage, glmSafetyFactor]
  )
  const usagePercent = Math.min(100, Math.round((imageTokensUsed / contextLength) * 100))

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">VLM 视觉模型</h2>
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
              <div className="flex-1 relative">
                <input
                  type={showVlmApiKey ? 'text' : 'password'}
                  value={v('vlm_api_key')}
                  onChange={(e) => onSet('vlm_api_key', e.target.value)}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 pr-10 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowVlmApiKey((s) => !s)}
                  className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-200 transition-colors"
                  aria-label={showVlmApiKey ? '隐藏明文密钥' : '显示明文密钥'}
                >
                  {showVlmApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
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
        <div className="border-t border-slate-800/70" />
        <p className="text-xs font-medium text-slate-500 -mt-1">图像分析参数</p>

        {config.vlm_context_length && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              上下文长度 (tokens)
              <span title="模型支持的最大 token 数" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2">
              <input type="number" min={1} step={1024} value={v('vlm_context_length')}
                onChange={(e) => onSet('vlm_context_length', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="8192" />
              <SaveBtn dirty={isDirty('vlm_context_length')} saving={!!saving['vlm_context_length']} saved={!!saved['vlm_context_length']} onSave={() => onSave('vlm_context_length')} />
            </div>
            <p className="text-xs text-slate-500">
              当前上下文 {contextLength.toLocaleString()} tokens → 最多可传入约 <span className="text-indigo-400 font-medium">{suggestedMax}</span> 张图片
            </p>
          </div>
        )}

        {config.vlm_max_images_per_batch && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              单次最大图片数
              <span title="每次调用 VLM API 传入的最大图片数量，超出时均匀采样" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2">
              <input
                type="number" min={1} max={200} step={1}
                value={v('vlm_max_images_per_batch')}
                onChange={(e) => onSet('vlm_max_images_per_batch', e.target.value)}
                className={`flex-1 rounded-lg bg-slate-800 border px-3 py-2 text-sm outline-none transition-colors font-mono ${
                  tokenBudgetOk ? 'border-slate-700 focus:border-indigo-500' : 'border-amber-500/60 focus:border-amber-400'
                }`}
                placeholder="10"
              />
              <SaveBtn dirty={isDirty('vlm_max_images_per_batch')} saving={!!saving['vlm_max_images_per_batch']} saved={!!saved['vlm_max_images_per_batch']} onSave={() => onSave('vlm_max_images_per_batch')} />
            </div>

            <div className="space-y-2 rounded-lg bg-slate-800/50 border border-slate-700/50 px-3 py-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">按帧分辨率估算</span>
                <select
                  value={resPresetIdx}
                  onChange={(e) => setResPresetIdx(Number(e.target.value))}
                  className="text-xs bg-slate-700 border border-slate-600 rounded px-1.5 py-0.5 text-slate-300 outline-none cursor-pointer"
                >
                  {RESOLUTION_PRESETS.map((p, i) => (
                    <option key={i} value={i}>{p.label}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>单张: <span className="text-slate-300 font-mono">{tokensPerImage}</span> tokens
                  {isGlmStyle && <span className="text-amber-400/70"> ×2 实测</span>}
                </span>
                <span className="text-slate-700">|</span>
                <span>OpenAI: <span className="font-mono text-slate-400">{openaiTokens}</span></span>
                <span className="text-slate-700">|</span>
                <span>Qwen: <span className="font-mono text-slate-400">{qwenTokens}</span></span>
                <span className="text-slate-700">|</span>
                <span>GLM: <span className="font-mono text-slate-400">{glmTokens}</span></span>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-500">预估总消耗</span>
                  <span className={tokenBudgetOk ? 'text-slate-400' : 'text-amber-400 font-medium'}>
                    {imageTokensUsed.toLocaleString()} / {contextLength.toLocaleString()}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-700 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      usagePercent >= 100 ? 'bg-amber-500' : usagePercent >= 80 ? 'bg-yellow-500' : 'bg-indigo-500'
                    }`}
                    style={{ width: `${Math.min(100, usagePercent)}%` }}
                  />
                </div>
                {!tokenBudgetOk && (
                  <p className="flex items-center gap-1 text-xs text-amber-400">
                    <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                    超出上下文限制，建议最多 <span className="font-medium">{suggestedMax}</span> 张
                    {isGlmStyle && <span className="text-xs opacity-75">（GLM 实测消耗约为公式 2 倍，已保守估算）</span>}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {config.vlm_concurrency && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              并发数量
              <span title="同时并行调用 VLM API 的片段数量" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={1} max={16} step={1} value={concurrency}
                  onChange={(e) => onSet('vlm_concurrency', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={1} max={16} step={1} value={v('vlm_concurrency')}
                  onChange={(e) => onSet('vlm_concurrency', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('vlm_concurrency')} saving={!!saving['vlm_concurrency']} saved={!!saved['vlm_concurrency']} onSave={() => onSave('vlm_concurrency')} />
            </div>
            <p className="text-xs text-slate-500">
              当前并发 <span className="text-indigo-400 font-medium">{concurrency}</span> 个片段同时分析
              {concurrency >= 8 && <span className="text-amber-400 ml-1.5">· 注意 API 速率限制</span>}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
