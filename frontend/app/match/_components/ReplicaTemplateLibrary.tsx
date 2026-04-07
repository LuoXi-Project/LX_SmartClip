'use client'

import { useEffect, useMemo, useState } from 'react'
import { Trash2, Search, Check, Pencil } from 'lucide-react'
import { replicaApi, type ReplicaTemplateListItem } from '@/lib/api'
import { Pagination } from '@/app/library/_components/Pagination'

export function ReplicaTemplateLibrary({
  onUse,
}: {
  onUse: (payload: { templateId: string; guide: string }) => void
}) {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<'all' | 'confirmed' | 'draft'>('confirmed')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [items, setItems] = useState<ReplicaTemplateListItem[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)

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
  }, [q, statusParam, page, pageSize])

  async function handleUse(t: ReplicaTemplateListItem) {
    const data = await replicaApi.getTemplate(t.template_id)
    const guide = String(data?.template_guide || '').trim()
    if (!guide) return
    onUse({ templateId: t.template_id, guide })
  }

  async function handleDelete(t: ReplicaTemplateListItem) {
    if (!confirm('确认删除该复刻模板？删除后不可恢复。')) return
    setDeletingId(t.template_id)
    try {
      await replicaApi.deleteTemplate(t.template_id)
      // 重新拉取当前页
      const res = await replicaApi.listTemplates({
        q: q.trim() || undefined,
        status: statusParam,
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

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">模板库</p>
          <p className="text-[11px] text-slate-500 mt-1">复用已生成的复刻模板，无需重复下载与识别</p>
        </div>
        <div className="text-[11px] text-slate-500">共 {total} 个</div>
      </div>

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

