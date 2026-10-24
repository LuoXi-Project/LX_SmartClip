'use client'

import { ASR_PROVIDERS, ASR_KEYS, ASR_LANGUAGE_PRESETS, PROVIDER_KEY_LINKS } from './constants'
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

const ASR_LANG_CUSTOM = '__custom__'

export function AsrSection({ config, edits, saving, saved, asrProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = ASR_KEYS.some((k) => isDirty(k) && config[k])
  const concurrency = Math.max(1, parseInt(v('asr_concurrency') || '1', 10) || 1)
  const presetLangValues = new Set(ASR_LANGUAGE_PRESETS.map((p) => p.value))
  const langRaw = v('asr_language')
  const langSelectValue = presetLangValues.has(langRaw) ? langRaw : ASR_LANG_CUSTOM

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
              本地 Whisper — 在机器上直接运行，无需网络。中文与时间轴建议 <code className="text-indigo-300 bg-slate-800 px-1 rounded">small</code> 起步，追求精度可用 <code className="text-indigo-300 bg-slate-800 px-1 rounded">medium</code> / <code className="text-indigo-300 bg-slate-800 px-1 rounded">large-v3</code>；有 NVIDIA GPU 时自动加速。
            </div>
            <SelectRow cfgKey="asr_model" label="模型规格（越大精度越高，速度越慢）" />
          </>
        )}

        {/* OpenAI 兼容 */}
        {asrProvider === 'openai' && (
          <>
            <div className="rounded-lg bg-green-500/5 border border-green-500/20 px-4 py-2.5 text-xs text-green-300">
              OpenAI 兼容 ASR — 支持 <code className="text-green-200 bg-slate-800 px-1 rounded">/audio/transcriptions</code>，
              也支持 Qwen ASR 兼容模式（<code className="text-green-200 bg-slate-800 px-1 rounded">chat.completions + input_audio</code>）。
            </div>
            <ApiTextField
              label="API 地址"
              value={v('asr_base_url')}
              onChange={(val) => onSet('asr_base_url', val)}
              placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
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
              keyLink={PROVIDER_KEY_LINKS[asrProvider]}
            />
            <ApiTextField
              label="模型名称"
              value={v('asr_openai_model')}
              onChange={(val) => onSet('asr_openai_model', val)}
              placeholder="qwen3-asr-flash（或 whisper-1）"
              dirty={isDirty('asr_openai_model')}
              saving={!!saving['asr_openai_model']}
              saved={!!saved['asr_openai_model']}
              onSave={() => onSave('asr_openai_model')}
            />
          </>
        )}

        {config.asr_language && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">识别语言</label>
            <p className="text-[11px] text-slate-500 leading-relaxed -mt-0.5">
              常用 ISO 639-1 代码；留空为自动检测。若网关要求特殊写法（如 zh-CN），请在右侧直接输入完整代码。
            </p>
            <div className="flex gap-2 flex-col sm:flex-row sm:items-start">
              <select
                value={langSelectValue}
                onChange={(e) => {
                  const nv = e.target.value
                  if (nv === ASR_LANG_CUSTOM) return
                  onSet('asr_language', nv)
                }}
                className="w-full sm:w-[min(100%,220px)] shrink-0 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
              >
                {ASR_LANGUAGE_PRESETS.map((p) => (
                  <option key={p.value === '' ? '_auto' : p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
                <option value={ASR_LANG_CUSTOM}>
                  {langSelectValue === ASR_LANG_CUSTOM ? '自定义（当前输入）' : '自定义…'}
                </option>
              </select>
              <input
                type="text"
                value={langRaw}
                onChange={(e) => onSet('asr_language', e.target.value)}
                placeholder="如 zh、en、ja，或 zh-CN / cmn-Hans"
                className="flex-1 min-w-0 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
              />
              <SaveBtn
                dirty={isDirty('asr_language')}
                saving={!!saving['asr_language']}
                saved={!!saved['asr_language']}
                onSave={() => onSave('asr_language')}
              />
            </div>
          </div>
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

        <div className="border-t border-slate-800/70 pt-2" />
        <p className="text-xs font-medium text-slate-500 -mt-1">LLM 校准</p>
        <p className="text-[11px] text-slate-500 leading-relaxed -mt-1">
          用 LLM 修正 ASR 识别错误（同音/形近错字、标点、断句），保留原句级时间轴。需配置 LLM Key。
          也可在「处理结果」抽屉里对单个片段手动点「LLM 校准」预览后应用。
        </p>
        {config.asr_auto_correct && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              流水线自动校准
              <span title="ASR 识别完成后自动调用 LLM 校准；失败不阻断流水线" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1">
                <select
                  value={v('asr_auto_correct')}
                  onChange={(e) => onSet('asr_auto_correct', e.target.value)}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
                >
                  <option value="false">关闭（默认，手动校准）</option>
                  <option value="true">开启（处理时自动校准）</option>
                </select>
              </div>
              <SaveBtn dirty={isDirty('asr_auto_correct')} saving={!!saving['asr_auto_correct']} saved={!!saved['asr_auto_correct']} onSave={() => onSave('asr_auto_correct')} />
            </div>
          </div>
        )}
        {config.asr_auto_correct_apply && v('asr_auto_correct') === 'true' && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              自动校准直接应用
              <span title="开启：校准后直接覆盖 ASR；关闭：仅生成不写库（需手动应用）" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1">
                <select
                  value={v('asr_auto_correct_apply')}
                  onChange={(e) => onSet('asr_auto_correct_apply', e.target.value)}
                  className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
                >
                  <option value="true">直接应用并覆盖（推荐）</option>
                  <option value="false">仅生成，不覆盖</option>
                </select>
              </div>
              <SaveBtn dirty={isDirty('asr_auto_correct_apply')} saving={!!saving['asr_auto_correct_apply']} saved={!!saved['asr_auto_correct_apply']} onSave={() => onSave('asr_auto_correct_apply')} />
            </div>
          </div>
        )}
        {config.asr_correct_hint && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              校准倾向提示词
              <span title="告诉 LLM 领域词汇/专有名词/口音特点，提升领域词修正率。如：这是面巾纸产品视频，面积纸应为面巾纸" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <p className="text-[11px] text-slate-500 leading-relaxed -mt-0.5">
              作为全局默认。手动校准时会预填到输入框（可临时改），流水线自动校准直接使用此值。
            </p>
            <div className="flex gap-2 items-start">
              <textarea
                value={v('asr_correct_hint')}
                onChange={(e) => onSet('asr_correct_hint', e.target.value)}
                rows={3}
                placeholder="例：这是面巾纸产品视频，ASR 中的「面积纸」应为「面巾纸」；品牌名「洁柔」勿改成「洁柔」以外字"
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors resize-y"
              />
              <SaveBtn dirty={isDirty('asr_correct_hint')} saving={!!saving['asr_correct_hint']} saved={!!saved['asr_correct_hint']} onSave={() => onSave('asr_correct_hint')} />
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
