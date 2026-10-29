'use client'

import { useCallback, useEffect, useState } from 'react'
import clsx from 'clsx'
import {
  BookOpen,
  ChevronDown,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { agentSkillsApi, type AgentSkillItem } from '@/lib/agent-api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'

/**
 * Agent 技能管理：技能包 = 目录 + SKILL.md（name/description + 指导正文）。
 * 工作台对话时只把名称+描述注入提示词，模型命中后调 load_skill 载入全文。
 */
export function AgentSkillsSection() {
  const toast = useToast()
  const confirm = useConfirm()
  const [skills, setSkills] = useState<AgentSkillItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [contents, setContents] = useState<Record<string, string>>({})
  const [toggling, setToggling] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    agentSkillsApi
      .list()
      .then(setSkills)
      .catch(() => setError('技能列表加载失败，请确认后端服务正常'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const toggleContent = async (slug: string) => {
    if (expanded === slug) {
      setExpanded(null)
      return
    }
    setExpanded(slug)
    if (!contents[slug]) {
      try {
        const text = await agentSkillsApi.content(slug)
        setContents((prev) => ({ ...prev, [slug]: text }))
      } catch {
        setContents((prev) => ({ ...prev, [slug]: '（内容加载失败）' }))
      }
    }
  }

  const toggleEnabled = async (skill: AgentSkillItem) => {
    setToggling(skill.slug)
    try {
      await agentSkillsApi.setEnabled(skill.slug, !skill.enabled)
      setSkills((prev) =>
        prev.map((s) => (s.slug === skill.slug ? { ...s, enabled: !skill.enabled } : s)),
      )
      toast.success(`「${skill.name}」已${skill.enabled ? '停用' : '启用'}`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setToggling(null)
    }
  }

  const handleDelete = async (skill: AgentSkillItem) => {
    const ok = await confirm({
      title: '删除该技能？',
      description: `「${skill.name}」将被永久删除，不可恢复。`,
      confirmLabel: '删除',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await agentSkillsApi.remove(skill.slug)
      toast.success('已删除')
      load()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const enabledCount = skills.filter((s) => s.enabled).length

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div>
          <h2 className="font-semibold text-slate-100 flex items-center gap-1.5">
            <Sparkles className="w-4 h-4 text-violet-400" />
            Agent 技能
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            教工作台 Agent 特定剪辑套路（带货口播 / 影视解说等）；对话命中时自动加载遵循
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500">启用 {enabledCount}/{skills.length}</span>
          <button
            type="button"
            onClick={load}
            title="刷新"
            className="p-1.5 rounded-lg border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
          >
            <RefreshCw size={13} className={clsx(loading && 'animate-spin')} />
          </button>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            新建技能
          </button>
        </div>
      </div>

      <div className="px-6 py-5 space-y-3">
        {error && <p className="text-sm text-rose-300">{error}</p>}
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-4">
            <Loader2 className="w-4 h-4 animate-spin" />加载技能列表…
          </div>
        ) : skills.length === 0 && !showCreate ? (
          <p className="text-sm text-slate-500 py-4 text-center">
            暂无技能；点「新建技能」教 Agent 一个新套路
          </p>
        ) : (
          skills.map((skill) => (
            <div
              key={skill.slug}
              className={clsx(
                'rounded-xl border transition-colors',
                skill.enabled
                  ? 'border-violet-500/25 bg-violet-500/[0.04] hover:border-violet-500/40'
                  : 'border-slate-800 bg-slate-900/40 opacity-70',
              )}
            >
              <div className="flex items-start gap-3 p-3.5">
                <button
                  type="button"
                  onClick={() => void toggleContent(skill.slug)}
                  className="min-w-0 flex-1 text-left"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-sm font-medium text-slate-100">{skill.name}</span>
                    <span className="rounded border border-slate-700 px-1 py-px text-[10px] text-slate-400 font-mono">
                      {skill.slug}
                    </span>
                    {skill.source === 'builtin' ? (
                      <span className="rounded border border-violet-500/40 bg-violet-500/10 px-1 py-px text-[10px] text-violet-300">
                        内置
                      </span>
                    ) : (
                      <span className="rounded border border-cyan-500/40 bg-cyan-500/10 px-1 py-px text-[10px] text-cyan-300">
                        自建
                      </span>
                    )}
                  </div>
                  {skill.description && (
                    <p className="mt-1 text-xs leading-5 text-slate-400 line-clamp-2">
                      {skill.description}
                    </p>
                  )}
                </button>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void toggleEnabled(skill)}
                    disabled={toggling === skill.slug}
                    title={skill.enabled ? '停用（不注入对话）' : '启用'}
                    className={clsx(
                      'relative h-5 w-9 rounded-full transition-colors disabled:opacity-50',
                      skill.enabled ? 'bg-emerald-500/70' : 'bg-slate-700',
                    )}
                  >
                    <span
                      className={clsx(
                        'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all',
                        skill.enabled ? 'left-[18px]' : 'left-0.5',
                      )}
                    />
                  </button>
                  {skill.source === 'user' && (
                    <button
                      type="button"
                      onClick={() => void handleDelete(skill)}
                      title="删除"
                      className="p-1.5 rounded-lg text-slate-500 hover:text-rose-300 hover:bg-rose-500/10 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void toggleContent(skill.slug)}
                    title={expanded === skill.slug ? '收起' : '查看全文'}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-slate-200 transition-colors"
                  >
                    <ChevronDown
                      size={14}
                      className={clsx('transition-transform', expanded === skill.slug && 'rotate-180')}
                    />
                  </button>
                </div>
              </div>
              {expanded === skill.slug && (
                <div className="border-t border-slate-800/70 px-3.5 py-3">
                  <div className="mb-1.5 flex items-center gap-1 text-[10px] text-slate-500">
                    <BookOpen size={10} />
                    SKILL.md 全文（对话命中时由 Agent 自动加载，正文 {skill.body_chars} 字）
                  </div>
                  <pre className="max-h-72 overflow-auto styled-scrollbar whitespace-pre-wrap rounded-lg bg-slate-950/70 p-3 text-xs leading-5 text-slate-300">
                    {contents[skill.slug] || '加载中…'}
                  </pre>
                </div>
              )}
            </div>
          ))
        )}

        {showCreate && (
          <CreateSkillForm
            onDone={() => {
              setShowCreate(false)
              load()
            }}
            onCancel={() => setShowCreate(false)}
          />
        )}
      </div>
    </section>
  )
}

function CreateSkillForm({
  onDone,
  onCancel,
}: {
  onDone: () => void
  onCancel: () => void
}) {
  const toast = useToast()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [body, setBody] = useState('')
  const [slug, setSlug] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const inputCls =
    'w-full rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-indigo-500/60 focus:outline-none'

  const submit = async () => {
    if (!name.trim() || !body.trim()) {
      toast.error('技能名称与指导内容为必填')
      return
    }
    setSubmitting(true)
    try {
      const created = await agentSkillsApi.create({
        name: name.trim(),
        description: description.trim(),
        body: body.trim(),
        slug: slug.trim() || undefined,
      })
      toast.success(`技能「${created.name}」已创建并启用`)
      onDone()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/[0.04] p-4 space-y-3">
      <p className="text-sm font-medium text-slate-100">新建技能</p>
      <p className="text-[11px] leading-4 text-slate-500">
        用 Markdown 写清「什么场景用 + 怎么做」：描述写触发场景（何时用），正文写具体指导（节奏/字幕/BGM/文案结构等）。
        Agent 对话命中描述时会自动加载全文遵循。
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs text-slate-400">技能名称 *</label>
          <input
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如：小红书种草口播"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-400">标识 slug（可选，小写字母数字）</label>
          <input
            className={inputCls}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="留空按名称自动生成，如 xiaohongshu"
          />
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs text-slate-400">触发场景描述（何时使用该技能）</label>
        <input
          className={inputCls}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="如：当用户提到小红书、种草笔记、测评分享时使用"
        />
      </div>
      <div className="space-y-1">
        <label className="text-xs text-slate-400">指导内容（Markdown）*</label>
        <textarea
          className={clsx(inputCls, 'min-h-[140px] resize-y')}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={'# 节奏与结构\n1. 开场 3 秒抛体验冲突\n2. …\n\n# 剪辑参数\n- 节奏 medium，单镜头 2-4 秒\n- 字幕 …'}
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:text-slate-100 text-xs transition-colors"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => void submit()}
          disabled={submitting}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium disabled:opacity-50 transition-colors"
        >
          {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          创建并启用
        </button>
      </div>
    </div>
  )
}
