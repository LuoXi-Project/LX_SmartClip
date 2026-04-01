'use client'

import { TTS_PROVIDERS, TTS_KEYS } from './constants'
import { ProviderSelector } from './ProviderSelector'
import { ConfigField } from './ConfigField'
import { SaveBtn } from './SaveBtn'
import { Save, Info } from 'lucide-react'
import type { ConfigMap, ProviderPreset } from './types'

interface Props {
  config: ConfigMap
  edits: Record<string, string>
  saving: Record<string, boolean>
  saved: Record<string, boolean>
  ttsProvider: string
  onSet: (key: string, value: string) => void
  onSave: (key: string) => void
  onSaveGroup: (keys: string[]) => void
  onApplyProvider: (p: ProviderPreset) => void
}

export function TtsSection({ config, edits, saving, saved, ttsProvider, onSet, onSave, onSaveGroup, onApplyProvider }: Props) {
  const v = (k: string) => edits[k] ?? config[k]?.value ?? ''
  const isDirty = (k: string) => edits[k] !== config[k]?.value
  const groupDirty = TTS_KEYS.some((k) => isDirty(k) && config[k])
  const concurrency = Math.max(1, parseInt(v('tts_concurrency') || '3', 10) || 3)

  const Row = ({ cfgKey, label, type = 'text', placeholder = '' }: { cfgKey: string; label: string; type?: string; placeholder?: string }) => (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2">
        <input type={type} value={v(cfgKey)} onChange={(e) => onSet(cfgKey, e.target.value)}
          className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
          placeholder={placeholder} />
        <SaveBtn dirty={isDirty(cfgKey)} saving={!!saving[cfgKey]} saved={!!saved[cfgKey]} onSave={() => onSave(cfgKey)} />
      </div>
    </div>
  )

  const SelectRow = ({ cfgKey, label }: { cfgKey: string; label: string }) => {
    if (!config[cfgKey]) return null
    return (
      <div className="space-y-1.5">
        <label className="text-xs text-slate-400">{label}</label>
        <div className="flex gap-2">
          <div className="flex-1"><ConfigField cfgKey={cfgKey} item={config[cfgKey]} value={v(cfgKey)} onChange={(val) => onSet(cfgKey, val)} /></div>
          <SaveBtn dirty={isDirty(cfgKey)} saving={!!saving[cfgKey]} saved={!!saved[cfgKey]} onSave={() => onSave(cfgKey)} />
        </div>
      </div>
    )
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100">TTS 配音</h2>
          <p className="text-xs text-slate-500 mt-0.5">文字转语音引擎与参数配置</p>
        </div>
        <div className="flex items-center gap-3">
          <ProviderSelector providers={TTS_PROVIDERS} selectedId={ttsProvider} onSelect={onApplyProvider} />
          {groupDirty && (
            <button onClick={() => onSaveGroup(TTS_KEYS)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors">
              <Save className="w-3.5 h-3.5" />保存全部
            </button>
          )}
        </div>
      </div>
      <div className="px-6 py-5 space-y-4">

        {/* edge-tts */}
        {ttsProvider === 'edge-tts' && (<>
          <Row cfgKey="tts_voice" label="语音角色" placeholder="zh-CN-XiaoxiaoNeural" />
          <Row cfgKey="tts_rate" label="语速 (如 +0%/-20%)" placeholder="+0%" />
          <Row cfgKey="tts_volume" label="音量 (如 +0%/+10%)" placeholder="+0%" />
        </>)}

        {/* openai */}
        {ttsProvider === 'openai' && (<>
          <Row cfgKey="tts_base_url" label="API 地址" placeholder="https://api.openai.com/v1" />
          <Row cfgKey="tts_api_key" label="API 密钥" type="password" placeholder="••••••••" />
          <Row cfgKey="tts_model" label="模型名 (如 tts-1 / tts-1-hd)" placeholder="tts-1" />
          <Row cfgKey="tts_voice" label="语音角色" placeholder="alloy" />
          <SelectRow cfgKey="tts_format" label="音频格式" />
        </>)}

        {/* bailian */}
        {ttsProvider === 'bailian' && (<>
          <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 px-4 py-2.5 text-xs text-amber-300">百炼 CosyVoice — 阿里云 DashScope，需填写 API-Key 与 App-Key</div>
          <Row cfgKey="tts_base_url" label="API 地址" placeholder="https://dashscope.aliyuncs.com/api/v1" />
          <Row cfgKey="tts_api_key" label="API-Key" type="password" placeholder="••••••••" />
          <Row cfgKey="bailian_app_key" label="App-Key" placeholder="your-app-key" />
          <Row cfgKey="tts_model" label="模型" placeholder="cosyvoice-v1" />
          <Row cfgKey="tts_voice" label="语音角色" placeholder="longxiaochun" />
        </>)}

        {/* volcengine */}
        {ttsProvider === 'volcengine' && (<>
          <div className="rounded-lg bg-orange-500/5 border border-orange-500/20 px-4 py-2.5 text-xs text-orange-300">火山引擎语音合成 — 需要 App ID、Token 和 Cluster</div>
          <Row cfgKey="tts_base_url" label="API 地址" placeholder="https://openspeech.bytedance.com" />
          <Row cfgKey="volcengine_app_id" label="App ID" placeholder="your-app-id" />
          <Row cfgKey="volcengine_cluster" label="Cluster" placeholder="volcano_tts" />
          <Row cfgKey="volcengine_token" label="Token" type="password" placeholder="••••••••" />
          <Row cfgKey="tts_voice" label="语音角色 (voice_type)" placeholder="zh_female_qiaoyuanzongcai_moon_bigtts" />
        </>)}

        {/* gpt-sovits */}
        {ttsProvider === 'gpt-sovits' && (<>
          <div className="rounded-lg bg-purple-500/5 border border-purple-500/20 px-4 py-2.5 text-xs text-purple-300">GPT-SoVITS 本地推理 — 默认端口 9880</div>
          <Row cfgKey="tts_base_url" label="API 地址" placeholder="http://127.0.0.1:9880" />
          <Row cfgKey="gsv_ref_audio" label="参考音频路径" placeholder="/path/to/ref.wav" />
          <Row cfgKey="gsv_ref_text" label="参考音频文本" placeholder="参考音频中说的内容" />
          <SelectRow cfgKey="gsv_lang" label="目标语言" />
        </>)}

        {/* index-tts */}
        {ttsProvider === 'index-tts' && (<>
          <div className="rounded-lg bg-cyan-500/5 border border-cyan-500/20 px-4 py-2.5 text-xs text-cyan-300">IndexTTS 本地推理 — Gradio API，默认端口 7860</div>
          <Row cfgKey="tts_base_url" label="API 地址" placeholder="http://127.0.0.1:7860" />
          <Row cfgKey="index_tts_ref_audio" label="参考音频路径" placeholder="/path/to/ref.wav" />
        </>)}

        {/* custom-http */}
        {ttsProvider === 'custom-http' && (<>
          <div className="rounded-lg bg-slate-700/30 border border-slate-600/40 px-4 py-3 text-xs text-slate-400 space-y-1">
            <div>自定义 HTTP — URL 与 Body 中均可用 <code className="text-indigo-300 bg-slate-800 px-1 rounded">{'{text}'}</code> 占位符替换合成文本。</div>
            <div className="text-slate-500">• <span className="text-slate-300">binary</span>：响应体直接为音频字节流 &nbsp;• <span className="text-slate-300">json</span>：按点号路径取音频 URL 再下载</div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400">请求方法 &amp; URL</label>
            <div className="flex gap-2">
              {config['custom_tts_method'] && (
                <select value={v('custom_tts_method')} onChange={(e) => onSet('custom_tts_method', e.target.value)}
                  className="rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors text-slate-200 cursor-pointer">
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                </select>
              )}
              <input type="text" value={v('custom_tts_url')} onChange={(e) => onSet('custom_tts_url', e.target.value)}
                className="flex-1 rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
                placeholder="http://your-api/tts?text={text}" />
              <SaveBtn dirty={isDirty('custom_tts_method') || isDirty('custom_tts_url')} saving={!!saving['custom_tts_url']} saved={!!saved['custom_tts_url']}
                onSave={() => { onSave('custom_tts_method'); onSave('custom_tts_url') }} />
            </div>
          </div>
          <Row cfgKey="custom_tts_headers" label='请求头 (JSON 格式，可选)' placeholder='{"Authorization": "Bearer xxx"}' />
          {v('custom_tts_method') === 'POST' && (
            <Row cfgKey="custom_tts_body" label='请求体 Body (JSON 模板，支持 {text} 占位符)' placeholder='{"text": "{text}", "voice": "default"}' />
          )}
          <SelectRow cfgKey="custom_tts_response_type" label="响应类型" />
          {v('custom_tts_response_type') === 'json' && (
            <div className="space-y-1.5">
              <Row cfgKey="custom_tts_audio_key" label="响应 JSON 音频字段路径" placeholder="audio_url 或 data.url 或 result.0.path" />
              <p className="text-xs text-slate-600">支持点号路径，如 <code className="text-slate-500">data.audio_url</code>、<code className="text-slate-500">result.0.url</code></p>
            </div>
          )}
        </>)}

        <div className="border-t border-slate-800/70 pt-2" />
        <p className="text-xs font-medium text-slate-500 -mt-1">并发控制</p>
        {config.tts_concurrency && (
          <div className="space-y-1.5">
            <label className="text-xs text-slate-400 flex items-center gap-1">
              并发数量
              <span title="同时并行合成语音（TTS）的任务数量" className="text-slate-600 cursor-help"><Info className="w-3 h-3" /></span>
            </label>
            <div className="flex gap-2 items-center">
              <div className="flex-1 flex items-center gap-3">
                <input type="range" min={1} max={16} step={1} value={concurrency}
                  onChange={(e) => onSet('tts_concurrency', e.target.value)}
                  className="flex-1 accent-indigo-500 cursor-pointer" />
                <input type="number" min={1} max={16} step={1} value={v('tts_concurrency')}
                  onChange={(e) => onSet('tts_concurrency', e.target.value)}
                  className="w-16 rounded-lg bg-slate-800 border border-slate-700 px-2 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono text-center" />
              </div>
              <SaveBtn dirty={isDirty('tts_concurrency')} saving={!!saving['tts_concurrency']} saved={!!saved['tts_concurrency']} onSave={() => onSave('tts_concurrency')} />
            </div>
            <p className="text-xs text-slate-500">
              当前并发 <span className="text-indigo-400 font-medium">{concurrency}</span> 个任务同时合成
              {concurrency >= 8 && <span className="text-amber-400 ml-1.5">· 注意 API 速率限制</span>}
            </p>
          </div>
        )}
      </div>
    </section>
  )
}
