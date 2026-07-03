'use client'

import { useEffect, useMemo, useState } from 'react'
import { Trash2, Search, Check, Pencil, Plus, Loader2 } from 'lucide-react'
import { replicaApi, videosApi, type ReplicaTemplateListItem, type Video } from '@/lib/api'
import { Pagination } from '@/app/library/_components/Pagination'
import { useConfirm } from '@/hooks/use-confirm'

export function ReplicaTemplateLibrary({
  onUse,
  refreshSignal = 0,
}: {
  onUse: (payload: { templateId: string; guide: string; replicaType: 'short_video' | 'film_commentary' | 'scene_story'; templatePresetId?: string }) => void
  refreshSignal?: number
}) {
  const confirm = useConfirm()
  const TEMPLATE_PAGE_SIZES = [6, 12, 24]
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<'all' | 'confirmed' | 'draft'>('confirmed')
  const [replicaType, setReplicaType] = useState<'all' | 'short_video' | 'film_commentary' | 'scene_story'>('all')
  const [styleProfile, setStyleProfile] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(6)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [items, setItems] = useState<ReplicaTemplateListItem[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [genOpen, setGenOpen] = useState(false)
  const [genVideos, setGenVideos] = useState<Video[]>([])
  const [genVideosLoading, setGenVideosLoading] = useState(false)
  const [genVideoId, setGenVideoId] = useState('')
  const [genReplicaType, setGenReplicaType] = useState<'short_video' | 'film_commentary' | 'scene_story'>('short_video')
  const [genLoading, setGenLoading] = useState(false)
  const [genError, setGenError] = useState('')

  const statusParam = useMemo(() => {
    if (status === 'all') return undefined
    return status
  }, [status])

  useEffect(() => {
    let mounted = true
    setLoading(true)
    setError('')
    replicaApi
      .listTemplates({
        q: q.trim() || undefined,
        status: statusParam,
        replica_type: replicaType === 'all' ? undefined : replicaType,
        style_profile: styleProfile.trim() || undefined,
        sort: 'updated_desc',
        page,
        page_size: pageSize,
      })
      .then((res) => {
        if (!mounted) return
        setItems(res.items || [])
        setTotalPages(res.total_pages || 1)
        setTotal(res.total || 0)
      })
      .catch((e: unknown) => {
        if (!mounted) return
        const msg = (e as { message?: string })?.message || '加载模板库失败'
        setError(msg)
      })
      .finally(() => {
        if (!mounted) return
        setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [q, statusParam, replicaType, styleProfile, page, pageSize, refreshSignal])

  async function handleUse(t: ReplicaTemplateListItem) {
    const data = await replicaApi.getTemplate(t.template_id)
    const guide = String(data?.template_guide || '').trim()
    if (!guide) return
    const rt = (data?.template_json?.replica_type || t.replica_type || 'short_video') as 'short_video' | 'film_commentary' | 'scene_story'
    // 后端 list/get 已返回 template_preset_id（仅 confirmed 模板有值）
    onUse({ templateId: t.template_id, guide, replicaType: rt, templatePresetId: data?.template_preset_id || undefined })
  }

  async function handleDelete(t: ReplicaTemplateListItem) {
    const ok = await confirm({
      title: '确认删除模板',
      description: `确定删除模板「${t.name?.trim() || '未命名模板'}」吗？删除后不可恢复。`,
      confirmLabel: '删除',
      cancelLabel: '取消',
      variant: 'danger',
    })
    if (!ok) return
    setDeletingId(t.template_id)
    try {
      await replicaApi.deleteTemplate(t.template_id)
      // 重新拉取当前页
      const res = await replicaApi.listTemplates({
        q: q.trim() || undefined,
        status: statusParam,
        replica_type: replicaType === 'all' ? undefined : replicaType,
        style_profile: styleProfile.trim() || undefined,
        sort: 'updated_desc',
        page,
        page_size: pageSize,
      })
      setItems(res.items || [])
      setTotalPages(res.total_pages || 1)
      setTotal(res.total || 0)
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || '删除失败'
      setError(msg)
    } finally {
      setDeletingId(null)
    }
  }

  async function handleRename(t: ReplicaTemplateListItem) {
    const cur = (t.name || '').trim() || '复刻模板'
    const next = prompt('输入新的模板名称', cur)
    if (next == null) return
    const name = next.trim()
    if (!name) return
    setRenamingId(t.template_id)
    try {
      await replicaApi.renameTemplate(t.template_id, name)
      // 局部更新
      setItems((prev) => prev.map((x) => (x.template_id === t.template_id ? { ...x, name } : x)))
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || '重命名失败'
      setError(msg)
    } finally {
      setRenamingId(null)
    }
  }

  async function openGenPanel() {
    setGenOpen(true)
    if (genVideos.length === 0) {
      setGenVideosLoading(true)
      try {
        const res = await videosApi.list({ page_size: 200, sort: 'created_desc' })
        const items = (res?.items || []).filter((v) => v.status === 'done' && v.total_clips > 0)
        setGenVideos(items)
      } catch {
        setGenVideos([])
      } finally {
        setGenVideosLoading(false)
      }
    }
  }

  async function handleGenFromExisting() {
    if (!genVideoId) return
    setGenLoading(true)
    setGenError('')
    try {
      await replicaApi.generateFromExisting(genVideoId, {
        skip_vlm: false,
        replica_type: genReplicaType,
        style_profile: '通用',
        quality_mode: 'high_quality',
      })
      // 生成后刷新列表并收起面板
      setGenOpen(false)
      setGenVideoId('')
      // 触发外层刷新：直接调用一次 listTemplates
      const res = await replicaApi.listTemplates({
        q: q.trim() || undefined,
        status: statusParam,
        replica_type: replicaType === 'all' ? undefined : replicaType,
        style_profile: styleProfile.trim() || undefined,
        sort: 'updated_desc',
        page,
        page_size: pageSize,
      })
      setItems(res.items || [])
      setTotalPages(res.total_pages || 1)
      setTotal(res.total || 0)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail
        || (e as { message?: string })?.message
        || '从库生成模板失败'
      setGenError(msg)
    } finally {
      setGenLoading(false)
    }
  }

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">模板库</p>
          <p className="text-[11px] text-slate-500 mt-1">复用已生成的复刻模板，或从已处理视频秒出新模板</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={openGenPanel}
            disabled={genLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-cyan-500/40 bg-cyan-500/10 hover:bg-cyan-500/15 text-cyan-200 text-xs font-semibold transition-colors disabled:opacity-40"
          >
            {genLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            从已处理视频生成
          </button>
          <div className="text-[11px] text-slate-500">共 {total} 个</div>
        </div>
      </div>

      {genOpen && (
        <div className="rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4 space-y-3">
          <p className="text-xs font-semibold text-cyan-200">从库内已处理视频直接生成复刻模板</p>
          <p className="text-[11px] text-slate-500 leading-relaxed">
            选择状态为「已处理」的视频，后端复用其完整多模态 clips（ASR+画面+情绪+关键词）秒出模板，无需重新下载与识别。
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={genVideoId}
              onChange={(e) => setGenVideoId(e.target.value)}
              className="flex-1 min-w-[200px] rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 outline-none"
            >
              <option value="">{genVideosLoading ? '加载中…' : '选择已处理视频'}</option>
              {genVideos.map((v) => (
                <option key={v.id} value={v.id}>{v.name}（{v.total_clips} 片段）</option>
              ))}
            </select>
            <select
              value={genReplicaType}
              onChange={(e) => setGenReplicaType((e.target.value as 'short_video' | 'film_commentary' | 'scene_story') || 'short_video')}
              className="rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 outline-none"
            >
              <option value="short_video">短视频</option>
              <option value="film_commentary">影视解说</option>
              <option value="scene_story">场景剧情</option>
            </select>
            <button
              type="button"
              onClick={handleGenFromExisting}
              disabled={!genVideoId || genLoading}
              className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors"
            >
              {genLoading ? '生成中…' : '生成模板'}
            </button>
            <button
              type="button"
              onClick={() => { setGenOpen(false); setGenError('') }}
              className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-900/40 text-slate-400 text-sm hover:border-slate-600"
            >
              取消
            </button>
          </div>
          {genError && <p className="text-xs text-red-300">{genError}</p>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-xl bg-slate-900/60 border border-slate-700 px-3 py-2">
          <Search className="w-4 h-4 text-slate-500" />
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setPage(1)
            }}
            placeholder="搜索链接/模板内容..."
            className="bg-transparent outline-none text-sm text-slate-200 placeholder-slate-600 w-56"
          />
        </div>
        <div className="flex items-center gap-1 text-xs">
          {([
            { id: 'confirmed', label: '已确认' },
            { id: 'draft', label: '草稿' },
            { id: 'all', label: '全部' },
          ] as const).map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => {
                setStatus(opt.id)
                setPage(1)
              }}
              className={`px-3 py-2 rounded-xl border transition-colors ${
                status === opt.id
                  ? 'border-cyan-500/70 bg-cyan-500/10 text-cyan-200'
                  : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <select
          value={replicaType}
          onChange={(e) => {
            setReplicaType((e.target.value as 'all' | 'short_video' | 'film_commentary' | 'scene_story') || 'all')
            setPage(1)
          }}
          className="rounded-xl border border-slate-700 bg-slate-900/40 text-slate-300 text-xs px-3 py-2"
        >
          <option value="all">全部类型</option>
          <option value="short_video">短视频</option>
          <option value="film_commentary">影视解说</option>
          <option value="scene_story">场景剧情</option>
        </select>
        <input
          value={styleProfile}
          onChange={(e) => {
            setStyleProfile(e.target.value)
            setPage(1)
          }}
          placeholder="风格标签筛选（如电影讲解）"
          className="rounded-xl border border-slate-700 bg-slate-900/40 text-slate-300 text-xs px-3 py-2 w-44 outline-none"
        />
      </div>

      {error && <div className="text-xs text-red-300">{error}</div>}
      {loading ? (
        <div className="text-xs text-slate-500">加载中…</div>
      ) : items.length === 0 ? (
        <div className="text-xs text-slate-500">暂无模板</div>
      ) : (
        <div className="space-y-3">
          {items.map((t) => (
            <div key={t.template_id} className="rounded-xl border border-slate-800 bg-slate-950/30 p-4 space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-slate-200">
                      {t.name?.trim() ? t.name : (t.status === 'confirmed' ? '已确认模板' : '草稿模板')}
                    </span>
                    {t.pace && <span className="text-[10px] text-slate-500 border border-slate-700 rounded-full px-2 py-0.5">pace={t.pace}</span>}
                    {t.tone && <span className="text-[10px] text-slate-500 border border-slate-700 rounded-full px-2 py-0.5">tone={t.tone}</span>}
                    {t.replica_type && <span className="text-[10px] text-cyan-300 border border-cyan-500/30 rounded-full px-2 py-0.5">{t.replica_type}</span>}
                    {t.style_profile && <span className="text-[10px] text-violet-300 border border-violet-500/30 rounded-full px-2 py-0.5">{t.style_profile}</span>}
                    {t.has_slots && (
                      <span className="text-[10px] text-amber-300 border border-amber-500/30 rounded-full px-2 py-0.5" title="该模板已提取真实槽位，下游一键成片将按参考视频结构编排">
                        真实槽位
                      </span>
                    )}
                    {t.quality_signals && (
                      <span className="text-[10px] text-emerald-300 border border-emerald-500/30 rounded-full px-2 py-0.5">
                        Q={((
                          Number(t.quality_signals.coverage || 0) +
                          Number(t.quality_signals.coherence || 0) +
                          Number(t.quality_signals.density_stability || 0)
                        ) / 3).toFixed(2)}
                      </span>
                    )}
                  </div>
                  {t.source_url && (
                    <div className="mt-1 text-[11px] text-slate-500 truncate" title={t.source_url}>
                      {t.source_url}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => handleRename(t)}
                    disabled={renamingId === t.template_id}
                    className="px-3 py-2 rounded-xl border border-slate-700 bg-slate-900/40 hover:border-slate-500 text-slate-300 text-xs transition-colors disabled:opacity-40"
                    title="重命名"
                  >
                    <Pencil className="w-3.5 h-3.5 inline mr-1" />
                    改名
                  </button>
                  <button
                    type="button"
                    onClick={() => handleUse(t)}
                    className="px-3 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-colors"
                  >
                    <Check className="w-3.5 h-3.5 inline mr-1" />
                    使用
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(t)}
                    disabled={deletingId === t.template_id}
                    className="px-3 py-2 rounded-xl border border-red-500/30 bg-red-500/10 hover:bg-red-500/15 text-red-300 text-xs transition-colors disabled:opacity-40"
                  >
                    <Trash2 className="w-3.5 h-3.5 inline mr-1" />
                    删除
                  </button>
                </div>
              </div>
              <div className="text-[11px] text-slate-300 whitespace-pre-wrap leading-relaxed">
                {t.guide_preview}
              </div>
              <div className="text-[10px] text-slate-600">
                更新：{t.updated_at}
              </div>
            </div>
          ))}

          <Pagination
            page={page}
            totalPages={totalPages}
            pageSize={pageSize}
            pageSizes={TEMPLATE_PAGE_SIZES}
            onPageChange={setPage}
            onPageSizeChange={(s) => {
              setPageSize(s)
              setPage(1)
            }}
          />
        </div>
      )}
    </section>
  )
}

