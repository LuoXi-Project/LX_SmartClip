'use client'

import { ASR_PROVIDERS, ASR_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { SaveBtn } from './SaveBtn'
import { Save, Info } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'
import { ApiSecretField } from './ApiSecretField'
import { ApiTextField } from './ApiTextField'
import { ConfigField } from './ConfigField'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  asrProvider: string
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
  onApplyProvider: (p: ProviderPreset) => void
}

export function AsrSection({ config, edits, saving, saved, asrProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = ASR_KEYS.some((k) => isDirty(k) && config[k])
  const concurrency = Math.max(1, parseInt(v('asr_concurrency') || '1', 10) || 1)

  const SelectRow = ({ cfgKey, label }: { cfgKey: string; label: string }) => {
    if (!config[cfgKey]) return null
    return (
      <div className="space-y-1.5">
        <label className="text-xs text-slate-400">{label}</label>
        <div className="flex gap-2">
          <div className="flex-1">
            <ConfigField cfgKey={cfgKey} item={config[cfgKey]} value={v(cfgKey)} onChange={(val) => onSet(cfgKey, val)} />
          </div>
          <SaveBtn dirty={isDirty(cfgKey)} saving={!!saving[cfgKey]} saved={!!saved[cfgKey]} onSave={() => onSave(cfgKey)} />
        </div>
      </div>
    )
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">语音识别 (ASR)</h2>
          <p className="text-xs text-slate-500 mt-0.5">自动语音转文字引擎与参数配置</p>
        </div>
        <div className="flex items-center gap-3">
          <ProviderSelector providers={ASR_PROVIDERS} selectedId={asrProvider} onSelect={onApplyProvider} />
          {groupDirty && (
            <button
              onClick={() => onSaveGroup(ASR_KEYS)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
            >
              <Save className="w-3.5 h-3.5" />保存全部
            </button>
          )}
        </div>
      </div>

      <div className="px-6 py-5 space-y-4">

        {/* 本地 Whisper */}
        {asrProvider === 'whisper' && (
          <>
            <div className="rounded-lg bg-slate-700/30 border border-slate-600/40 px-4 py-2.5 text-xs text-slate-400">
              本地 Whisper — 在机器上直接运行，无需网络，需安装 <code className="text-indigo-300 bg-slate-800 px-1 rounded">openai-whisper</code>
            </div>
            <SelectRow cfgKey="asr_model" label="模型规格（越大精度越高，速度越慢）" />
          </>
        )}

        {/* OpenAI 兼容 */}
        {asrProvider === 'openai' && (
          <>
            <div className="rounded-lg bg-green-500/5 border border-green-500/20 px-4 py-2.5 text-xs text-green-300">
              OpenAI Whisper API — 支持 OpenAI 官方及任何兼容 <code className="text-green-200 bg-slate-800 px-1 rounded">/audio/transcriptions</code> 接口的服务
            </div>
            <ApiTextField
              label="API 地址"
              value={v('asr_base_url')}
              onChange={(val) => onSet('asr_base_url', val)}
              placeholder="https://api.openai.com/v1"
              dirty={isDirty('asr_base_url')}
              saving={!!saving['asr_base_url']}
              saved={!!saved['asr_base_url']}
              onSave={() => onSave('asr_base_url')}
            />
            <ApiSecretField
              label="API 密钥"
              value={v('asr_api_key')}
              onChange={(val) => onSet('asr_api_key', val)}
              placeholder="••••••••"
              dirty={isDirty('asr_api_key')}
              saving={!!saving['asr_api_key']}
              saved={!!saved['asr_api_key']}
              onSave={() => onSave('asr_api_key')}
            />
            <ApiTextField
              label="模型名称"
              value={v('asr_openai_model')}
              onChange={(val) => onSet('asr_openai_model', val)}
              placeholder="whisper-1"
              dirty={isDirty('asr_openai_model')}
              saving={!!saving['asr_openai_model']}
              saved={!!saved['asr_openai_model']}
              onSave={() => onSave('asr_openai_model')}
            />
          </>
        )}

        <div className="border-t border-slate-800/70 pt-2" />
        <p className="text-xs font-medium text-slate-500 -mt-1">并发控制</p>
        {config.asr_concurrency && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              并发数量
              <span title="同时并行处理 ASR 的片段数量" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={1} max={16} step={1} value={concurrency}
                  onChange={(e) => onSet('asr_concurrency', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={1} max={16} step={1} value={v('asr_concurrency')}
                  onChange={(e) => onSet('asr_concurrency', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('asr_concurrency')} saving={!!saving['asr_concurrency']} saved={!!saved['asr_concurrency']} onSave={() => onSave('asr_concurrency')} />
            </div>
            <p className="text-xs text-slate-500">
              当前并发 <span className="text-indigo-400 font-medium">{concurrency}</span> 个片段同时转写
              {concurrency >= 8 && <span className="text-amber-400 ml-1.5">· 注意 CPU/显存与 API 速率限制</span>}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
