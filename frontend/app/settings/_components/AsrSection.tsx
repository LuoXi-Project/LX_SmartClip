'use client'

import { ASR_PROVIDERS, ASR_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { SaveBtn } from './SaveBtn'
import { Save } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'

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

  const Row = ({ cfgKey, label, type = 'text', placeholder = '' }: { cfgKey: string; label: string; type?: string; placeholder?: string }) => (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2">
        <input
          type={type}
          value={v(cfgKey)}
          onChange={(e) => onSet(cfgKey, e.target.value)}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
          placeholder={placeholder}
        />
        <SaveBtn dirty={isDirty(cfgKey)} saving={!!saving[cfgKey]} saved={!!saved[cfgKey]} onSave={() => onSave(cfgKey)} />
      </div>
    </div>
  )

  const SelectRow = ({ cfgKey, label }: { cfgKey: string; label: string }) => {
    if (!config[cfgKey]) return null
    const opts: string[] = JSON.parse(config[cfgKey].options ?? '[]')
    return (
      <div className="space-y-1.5">
        <label className="text-xs text-slate-400">{label}</label>
        <div className="flex gap-2">
          <select
            value={v(cfgKey)}
            onChange={(e) => onSet(cfgKey, e.target.value)}
            className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors text-slate-200 cursor-pointer"
          >
            {opts.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
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
            <Row cfgKey="asr_base_url" label="API 地址" placeholder="https://api.openai.com/v1" />
            <Row cfgKey="asr_api_key" label="API 密钥" type="password" placeholder="••••••••" />
            <Row cfgKey="asr_openai_model" label="模型名称" placeholder="whisper-1" />
          </>
        )}

      </div>
    </section>
  )
}
