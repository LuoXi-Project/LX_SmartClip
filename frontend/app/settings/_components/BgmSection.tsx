'use client'

import { useEffect, useState } from 'react'
import { bgmApi, type BgmTrack } from '@/lib/api'
import Link from 'next/link'
import { Music2, UploadCloud, Trash2, Save, RefreshCcw, ExternalLink } from 'lucide-react'
import { BgmMiniPlayer } from './BgmMiniPlayer'
import { useConfirm } from '@/hooks/use-confirm'

const BGM_TAG_OPTIONS = [
  '搞笑', '轻快', '欢乐', '活泼', '治愈', '舒缓', '安静', '温柔',
  '燃', '震撼', '史诗', '热血', '科技', '未来感', '赛博', '情绪'
]

const MOOD_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'happy', label: '欢乐 / 轻快' },
  { value: 'calm', label: '平静 / 治愈' },
  { value: 'epic', label: '燃 / 史诗' },
  { value: 'sad', label: '伤感 / 抒情' },
  { value: 'tech', label: '科技 / 未来' },
]

type TrackEditState = {
  title?: string
  mood?: string
  bpm?: number
  tags?: string[]
}

type UploadMetaState = {
  title: string
  mood: string
  bpm: string
  tags: string[]
}

interface BgmSectionProps {
  fullPage?: boolean
}

export function BgmSection({ fullPage = false }: BgmSectionProps) {
  const confirm = useConfirm()
  const [tracks, setTracks] = useState<BgmTrack[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Record<string, TrackEditState>>({})
  const [uploadMeta, setUploadMeta] = useState<UploadMetaState>({
    title: '',
    mood: '',
    bpm: '',
    tags: [],
  })

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await bgmApi.list()
      setTracks(data || [])
    } catch {
      setError('加载 BGM 列表失败，请检查后端服务。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const onFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError('')
    try {
      await bgmApi.upload(file, {
        title: uploadMeta.title || undefined,
        mood: uploadMeta.mood || undefined,
        bpm: uploadMeta.bpm ? Number(uploadMeta.bpm) : undefined,
        tags: uploadMeta.tags,
      })
      await load()
      e.target.value = ''
      setUploadMeta({ title: '', mood: '', bpm: '', tags: [] })
    } catch {
      setError('上传 BGM 失败，请重试。')
    } finally {
      setUploading(false)
    }
  }

  const onFieldChange = (id: string, key: 'title' | 'mood' | 'bpm', value: string) => {
    setEditing((prev) => ({
      ...prev,
      [id]: {
        ...prev[id],
        [key]: key === 'bpm' ? (value ? Number(value) : undefined) : value,
      },
    }))
  }

  const toggleTrackTag = (id: string, currentTags: string[], tag: string) => {
    const base = editing[id]?.tags ?? currentTags
    const next = base.includes(tag)
      ? base.filter((t) => t !== tag)
      : [...base, tag]
    setEditing((prev) => ({
      ...prev,
      [id]: {
        ...prev[id],
        tags: next,
      },
    }))
  }

  const toggleUploadTag = (tag: string) => {
    setUploadMeta((prev) => {
      const next = prev.tags.includes(tag)
        ? prev.tags.filter((t) => t !== tag)
        : [...prev.tags, tag]
      return { ...prev, tags: next }
    })
  }

  const onSave = async (t: BgmTrack) => {
    const edit = editing[t.id] || {}
    const payload = {
      title: edit.title ?? t.title,
      mood: (edit.mood ?? t.mood) || null,
      bpm: typeof edit.bpm === 'number' ? edit.bpm : t.bpm ?? null,
      tags: edit.tags ?? t.tags,
    }
    try {
      const updated = await bgmApi.update(t.id, payload)
      setTracks((prev) => prev.map((x) => (x.id === t.id ? updated : x)))
    } catch {
      setError('保存 BGM 元数据失败。')
    }
  }

  const onDelete = async (t: BgmTrack) => {
    const ok = await confirm({
      title: '确认删除',
      description: `确定删除 BGM「${t.title}」吗？此操作不可恢复。`,
      confirmLabel: '删除',
      cancelLabel: '取消',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await bgmApi.delete(t.id)
      setTracks((prev) => prev.filter((x) => x.id !== t.id))
    } catch {
      setError('删除 BGM 失败。')
    }
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100 flex items-center gap-2">
            <Music2 className="w-4 h-4 text-indigo-400" />
            BGM 音乐库
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            管理自动成片使用的背景音乐，支持上传音频并配置情绪 / BPM / 标签。
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap justify-end">
          {!fullPage && (
            <Link
              href="/bgm"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-700 bg-slate-900/60 text-xs text-slate-300 hover:bg-slate-800/80 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              打开大页面
            </Link>
          )}
          <label className="relative inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-indigo-500/60 bg-indigo-500/10 text-indigo-200 cursor-pointer hover:bg-indigo-500/20 transition-colors">
            <UploadCloud className="w-3.5 h-3.5" />
            <span>{uploading ? '上传中...' : '上传音频'}</span>
            <input
              type="file"
              accept=".mp3,.wav,.m4a,.aac,.flac,.ogg"
              className="absolute inset-0 opacity-0 cursor-pointer"
              disabled={uploading}
              onChange={onFileChange}
            />
          </label>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-700 bg-slate-900/60 text-xs text-slate-300 hover:bg-slate-800/80 transition-colors"
          >
            <RefreshCcw className="w-3.5 h-3.5" />
            刷新
          </button>
        </div>
      </div>

      <div className="px-6 py-4 space-y-4">
        {error && (
          <div className="text-xs text-red-300 bg-red-500/5 border border-red-500/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 space-y-3">
          <p className="text-xs text-slate-400">上传时可直接配置元数据（可选）</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input
              type="text"
              value={uploadMeta.title}
              onChange={(e) => setUploadMeta((p) => ({ ...p, title: e.target.value }))}
              className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
              placeholder="曲目标题（可选）"
            />
            <select
              value={uploadMeta.mood}
              onChange={(e) => setUploadMeta((p) => ({ ...p, mood: e.target.value }))}
              className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
            >
              {MOOD_OPTIONS.map((opt) => (
                <option key={opt.value || 'none'} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <input
              type="number"
              value={uploadMeta.bpm}
              onChange={(e) => setUploadMeta((p) => ({ ...p, bpm: e.target.value }))}
              className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
              placeholder="BPM（可选）"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {BGM_TAG_OPTIONS.map((tag) => {
              const active = uploadMeta.tags.includes(tag)
              return (
                <button
                  key={tag}
                  type="button"
                  onClick={() => toggleUploadTag(tag)}
                  className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${
                    active
                      ? 'border-indigo-500/60 bg-indigo-500/20 text-indigo-200'
                      : 'border-slate-700 bg-slate-900/70 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tag}
                </button>
              )
            })}
          </div>
        </div>

        {loading && (
          <p className="text-xs text-slate-400">加载 BGM 列表中...</p>
        )}

        {!loading && tracks.length === 0 && (
          <p className="text-xs text-slate-500">
            还没有任何 BGM。点击右上角「上传音频」添加背景音乐文件，推荐放一些 loop 友好的无版权音乐。
          </p>
        )}

        {!loading && tracks.length > 0 && (
          <div className="space-y-3">
            {tracks.map((t) => {
              return (
                <div
                  key={t.id}
                  className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 flex flex-col md:flex-row md:items-center md:gap-4 gap-3"
                >
                  <div className="flex-1 space-y-1.5">
                    <div className="flex flex-col md:flex-row md:items-center md:gap-3 gap-1.5">
                      <input
                        type="text"
                        defaultValue={t.title}
                        onChange={(e) => onFieldChange(t.id, 'title', e.target.value)}
                        className="flex-1 rounded-lg bg-slate-900 border border-slate-700 px-3 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
                        placeholder="曲目标题"
                      />
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-500">情绪</span>
                        <select
                          defaultValue={t.mood || ''}
                          onChange={(e) => onFieldChange(t.id, 'mood', e.target.value)}
                          className="w-36 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
                        >
                          {MOOD_OPTIONS.map((opt) => (
                            <option key={opt.value || 'none'} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-500">BPM</span>
                        <input
                          type="number"
                          defaultValue={t.bpm ?? ''}
                          onChange={(e) => onFieldChange(t.id, 'bpm', e.target.value)}
                          className="w-20 rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
                          placeholder="120"
                        />
                      </div>
                    </div>
                    <div className="flex flex-col md:flex-row md:items-center md:gap-3 gap-1.5">
                      <div className="flex-1 space-y-1">
                        <span className="text-[10px] text-slate-500">标签（中文多选）</span>
                        <div className="flex flex-wrap gap-1.5">
                          {BGM_TAG_OPTIONS.map((tag) => {
                            const selected = (editing[t.id]?.tags ?? t.tags).includes(tag)
                            return (
                              <button
                                key={tag}
                                type="button"
                                onClick={() => toggleTrackTag(t.id, t.tags, tag)}
                                className={`px-2 py-0.5 rounded-full text-[11px] border transition-colors ${
                                  selected
                                    ? 'border-indigo-500/60 bg-indigo-500/20 text-indigo-200'
                                    : 'border-slate-700 bg-slate-900/70 text-slate-400 hover:text-slate-200'
                                }`}
                              >
                                {tag}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                      <BgmMiniPlayer
                        src={t.url}
                        downloadFilename={t.filename}
                        className="w-full md:min-w-[min(100%,380px)] md:max-w-lg mt-1.5 md:mt-0"
                      />
                    </div>
                    <p className="text-[10px] text-slate-500 break-all">
                      文件名：<span className="font-mono text-slate-400">{t.filename}</span>
                    </p>
                  </div>
                  <div className="flex flex-row md:flex-col items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onSave(t)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
                    >
                      <Save className="w-3.5 h-3.5" />
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(t)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-500/60 bg-red-500/10 text-red-200 text-xs hover:bg-red-500/20 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      删除
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}

