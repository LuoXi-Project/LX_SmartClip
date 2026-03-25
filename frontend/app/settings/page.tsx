'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, CheckCircle2, Loader2, Save, Settings2 } from 'lucide-react'
import apiClient from '@/lib/api'

interface ConfigItem {
  value: string
  type: string
  label: string
  options: string | null
}

type ConfigMap = Record<string, ConfigItem>

// 分组定义
const GROUPS = [
  {
    title: 'API / 模型',
    keys: ['vlm_base_url', 'vlm_api_key', 'vlm_model', 'vlm_provider', 'llm_model'],
  },
  {
    title: '视频处理',
    keys: ['split_mode', 'fixed_duration', 'scene_threshold', 'frame_fps', 'asr_model'],
  },
  {
    title: '向量检索',
    keys: ['vector_dimension', 'top_k', 'match_top_k', 'match_top_n', 'embedding_provider', 'embedding_base_url', 'embedding_model', 'embedding_api_key'],
  },
  {
    title: 'TTS 配音',
    keys: ['tts_provider', 'tts_voice', 'tts_rate', 'tts_volume'],
  },
]

function ConfigField({
  cfgKey,
  item,
  value,
  onChange,
}: {
  cfgKey: string
  item: ConfigItem
  value: string
  onChange: (v: string) => void
}) {
  const isPassword = cfgKey.includes('key') || cfgKey.includes('secret')

  if (item.type === 'select' && item.options) {
    let opts: string[] = []
    try { opts = JSON.parse(item.options) } catch { opts = [] }
    return (
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
      >
        {opts.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    )
  }

  if (item.type === 'number') {
    return (
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors"
      />
    )
  }

  return (
    <input
      type={isPassword ? 'password' : 'text'}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={isPassword ? '••••••••' : ''}
      className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-indigo-500 transition-colors font-mono"
    />
  )
}

export default function SettingsPage() {
  const [config, setConfig] = useState<ConfigMap>({})
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const [error, setError] = useState('')

  useEffect(() => {
    apiClient
      .get<unknown, ConfigMap>('/api/config')
      .then((data) => {
        setConfig(data || {})
        const initial: Record<string, string> = {}
        Object.entries(data || {}).forEach(([k, v]) => { initial[k] = v.value })
        setEdits(initial)
      })
      .catch(() => setError('加载配置失败，请检查后端服务。'))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (key: string) => {
    setSaving((p) => ({ ...p, [key]: true }))
    setError('')
    try {
      await apiClient.patch('/api/config', { key, value: edits[key] })
      setConfig((p) => ({
        ...p,
        [key]: { ...p[key], value: edits[key] },
      }))
      setSaved((p) => ({ ...p, [key]: true }))
      setTimeout(() => setSaved((p) => ({ ...p, [key]: false })), 2000)
    } catch {
      setError(`保存 "${key}" 失败`)
    } finally {
      setSaving((p) => ({ ...p, [key]: false }))
    }
  }

  const isDirty = (key: string) => edits[key] !== config[key]?.value

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">

        {/* 页头 */}
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" />首页
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-slate-400" />系统设置
          </h1>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />加载配置中...
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-600/30 bg-red-500/5 px-5 py-4 text-sm text-red-300">
            {error}
          </div>
        )}

        {!loading && GROUPS.map((group) => {
          const groupKeys = group.keys.filter((k) => config[k])
          if (groupKeys.length === 0) return null
          return (
            <section key={group.title} className="space-y-3">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-widest border-b border-slate-800 pb-2">
                {group.title}
              </h2>
              <div className="space-y-3">
                {groupKeys.map((key) => {
                  const item = config[key]
                  return (
                    <div key={key} className="grid sm:grid-cols-[1fr_auto] gap-2 items-end">
                      <div className="space-y-1">
                        <label className="text-xs text-slate-400">
                          {item.label || key}
                          <span className="ml-2 text-slate-600 font-mono">{key}</span>
                        </label>
                        <ConfigField
                          cfgKey={key}
                          item={item}
                          value={edits[key] ?? item.value}
                          onChange={(v) => setEdits((p) => ({ ...p, [key]: v }))}
                        />
                      </div>
                      <button
                        onClick={() => handleSave(key)}
                        disabled={!isDirty(key) || saving[key]}
                        className={`px-4 py-2 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors ${
                          saved[key]
                            ? 'bg-emerald-600/20 text-emerald-300 border border-emerald-600/30'
                            : isDirty(key)
                            ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                            : 'bg-slate-800 text-slate-600 cursor-not-allowed border border-slate-700'
                        }`}
                      >
                        {saving[key] ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : saved[key] ? (
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        ) : (
                          <Save className="w-3.5 h-3.5" />
                        )}
                        {saved[key] ? '已保存' : '保存'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </section>
          )
        })}
      </div>
    </main>
  )
}
