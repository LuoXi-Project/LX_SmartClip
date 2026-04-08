'use client'

import { useEffect, useMemo, useState } from 'react'
import { bgmApi, type BgmTrack } from '@/lib/api'
import Link from 'next/link'
import { Music2, UploadCloud, RefreshCcw, ExternalLink } from 'lucide-react'
import { useConfirm } from '@/hooks/use-confirm'
import { useToast } from '@/components/ui/toast-provider'
import { BgmUploadMetaPanel } from './BgmUploadMetaPanel'
import { BgmTrackCard } from './BgmTrackCard'

const BGM_TAG_OPTIONS = [
  '搞笑', '轻快', '欢乐', '活泼', '治愈', '舒缓', '安静', '温柔',
  '燃', '震撼', '史诗', '热血', '科技', '未来感', '赛博', '情绪',
  '恐怖', '惊悚', '悬疑', '诡异', '阴森',
  '悬念', '紧张', '压迫', '动作', '打斗', '追逐',
  '浪漫', '甜蜜', '恋爱', '励志', '希望', '成长',
  '复古', '怀旧', '奇幻', '魔幻', '空灵',
]

const MOOD_OPTIONS = [
  { value: '', label: '未设置' },
  { value: 'happy', label: '欢乐 / 轻快' },
  { value: 'calm', label: '平静 / 治愈' },
  { value: 'epic', label: '燃 / 史诗' },
  { value: 'sad', label: '伤感 / 抒情' },
  { value: 'tech', label: '科技 / 未来' },
  { value: 'horror', label: '恐怖 / 悬疑' },
  { value: 'suspense', label: '悬疑 / 紧张' },
  { value: 'action', label: '动作 / 高能' },
  { value: 'romantic', label: '浪漫 / 甜蜜' },
  { value: 'inspiring', label: '励志 / 希望' },
  { value: 'retro', label: '复古 / 怀旧' },
  { value: 'fantasy', label: '奇幻 / 神秘' },
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
  const toast = useToast()
  const [tracks, setTracks] = useState<BgmTrack[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Record<string, TrackEditState>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [moodFilter, setMoodFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
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

  useEffect(() => {
    setPage(1)
  }, [searchQuery, moodFilter, tagFilter, pageSize])

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
      toast.success('保存成功')
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

  const filteredTracks = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return tracks.filter((t) => {
      const moodText = String(t.mood || '').toLowerCase()
      const tags = (t.tags || []).map((x) => x.toLowerCase())
      const matchesQuery = !q || [
        t.title,
        t.filename,
        moodText,
        ...(t.tags || []),
      ].some((field) => String(field || '').toLowerCase().includes(q))
      const matchesMood = !moodFilter || moodText === moodFilter
      const matchesTag = !tagFilter || tags.includes(tagFilter.toLowerCase())
      return matchesQuery && matchesMood && matchesTag
    })
  }, [tracks, searchQuery, moodFilter, tagFilter])

  const totalPages = Math.max(1, Math.ceil(filteredTracks.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const paginatedTracks = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredTracks.slice(start, start + pageSize)
  }, [filteredTracks, currentPage, pageSize])

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

        <BgmUploadMetaPanel
          uploadMeta={uploadMeta}
          onUploadMetaChange={setUploadMeta}
          onToggleTag={toggleUploadTag}
          moodOptions={MOOD_OPTIONS}
          tagOptions={BGM_TAG_OPTIONS}
        />

        {loading && (
          <p className="text-xs text-slate-400">加载 BGM 列表中...</p>
        )}

        {!loading && tracks.length > 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="搜索标题 / 文件名 / 标签 / 情绪"
                className="md:col-span-2 rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
              />
              <select
                value={moodFilter}
                onChange={(e) => setMoodFilter(e.target.value)}
                className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
              >
                <option value="">全部情绪</option>
                {MOOD_OPTIONS.filter((x) => x.value).map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <select
                value={tagFilter}
                onChange={(e) => setTagFilter(e.target.value)}
                className="rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-xs outline-none focus:border-indigo-500 transition-colors"
              >
                <option value="">全部标签</option>
                {BGM_TAG_OPTIONS.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
              <p className="text-xs text-slate-400">
                共 {tracks.length} 首，命中 {filteredTracks.length} 首；第 {currentPage} / {totalPages} 页
              </p>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-500">每页</span>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-xs outline-none focus:border-indigo-500 transition-colors"
                >
                  {[10, 20, 50].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        {!loading && tracks.length === 0 && (
          <p className="text-xs text-slate-500">
            还没有任何 BGM。点击右上角「上传音频」添加背景音乐文件，推荐放一些 loop 友好的无版权音乐。
          </p>
        )}

        {!loading && tracks.length > 0 && filteredTracks.length === 0 && (
          <p className="text-xs text-slate-500">
            没有匹配结果，试试放宽关键词或清空筛选条件。
          </p>
        )}

        {!loading && tracks.length > 0 && filteredTracks.length > 0 && (
          <div className="space-y-3">
            {paginatedTracks.map((t) => (
              <BgmTrackCard
                key={t.id}
                track={t}
                editingState={editing[t.id]}
                moodOptions={MOOD_OPTIONS}
                tagOptions={BGM_TAG_OPTIONS}
                onFieldChange={onFieldChange}
                onToggleTrackTag={toggleTrackTag}
                onSave={onSave}
                onDelete={onDelete}
              />
            ))}
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-2.5 py-1 text-xs rounded-md border border-slate-700 bg-slate-900/70 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-800/80 transition-colors"
              >
                上一页
              </button>
              <button
                type="button"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="px-2.5 py-1 text-xs rounded-md border border-slate-700 bg-slate-900/70 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-800/80 transition-colors"
              >
                下一页
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

