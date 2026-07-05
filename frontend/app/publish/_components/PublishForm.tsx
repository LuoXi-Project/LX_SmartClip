'use client'

import { Loader2, Send, Sparkles } from 'lucide-react'
import clsx from 'clsx'
import { usePublishStore, type PublishDraftPerPlatform } from '@/lib/store'
import type { PlatformInfo, PublishAccount, RenderItem } from './types'
import { getPlatformSpec, countByLang } from './types'

interface PublishFormProps {
  platforms: PlatformInfo[]
  accounts: PublishAccount[]
  selectedRender: RenderItem | null
  submitting: boolean
  /** 正在为某平台生成文案的平台 key（null=空闲） */
  generatingPlatform: string | null
  onSubmit: (
    videoPath: string,
    items: Array<{
      platform: string
      account: string
      title: string
      description: string
      tags: string[]
    }>,
  ) => void
  /** 触发 AI 生成文案（单平台）。父组件实现 toast 与 API 调用 */
  onGenerateCopy: (platform: string) => void
}

export function PublishForm({
  platforms,
  accounts,
  selectedRender,
  submitting,
  generatingPlatform,
  onSubmit,
  onGenerateCopy,
}: PublishFormProps) {
  const { drafts, selectedPlatforms, setDraft, setSelectedPlatforms } = usePublishStore()

  const implemented = platforms.filter((p) => p.implemented)
  const loggedInPlatforms = implemented.filter((p) =>
    accounts.some((a) => a.platform === p.platform && a.login_status === 'logged_in'),
  )

  const togglePlatform = (p: string) => {
    setSelectedPlatforms(
      selectedPlatforms.includes(p)
        ? selectedPlatforms.filter((x) => x !== p)
        : [...selectedPlatforms, p],
    )
  }

  const handlePublish = () => {
    if (!selectedRender) return
    const targets = selectedPlatforms.filter((p) =>
      loggedInPlatforms.some((lp) => lp.platform === p),
    )
    if (targets.length === 0) return
    const items = targets.map((p) => {
      const d: PublishDraftPerPlatform = drafts[p] || { title: '', description: '', tags: [] }
      return {
        platform: p,
        account: 'main',
        title: d.title.trim(),
        description: d.description.trim(),
        tags: d.tags,
      }
    })
    // 用成片的 file_path（storage/... 相对路径）传给后端，resolve_stored_path 能解析
    onSubmit(selectedRender.file_path, items)
  }

  const disabled = !selectedRender

  return (
    <section
      className={clsx(
        'rounded-lg border bg-slate-900/40 p-4 space-y-4 transition-opacity',
        disabled ? 'border-slate-800 opacity-60' : 'border-slate-800',
      )}
    >
      <h2 className="text-sm font-semibold text-slate-200">发布内容</h2>

      {/* 选中的成片 */}
      <div className="space-y-1.5">
        <label className="text-xs text-slate-400">当前选中成片</label>
        {selectedRender ? (
          <div className="rounded-md border border-indigo-500/30 bg-indigo-950/20 px-3 py-2">
            <div className="text-sm text-indigo-200 truncate" title={selectedRender.filename}>
              {selectedRender.title || selectedRender.filename}
            </div>
            <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-2">
              <span>{selectedRender.source_label}</span>
              <span>·</span>
              <span>
                {Math.floor(selectedRender.duration / 60)}:
                {Math.floor(selectedRender.duration % 60)
                  .toString()
                  .padStart(2, '0')}
              </span>
            </div>
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-slate-700 px-3 py-3 text-center text-xs text-slate-500">
            请从左侧成片列表中选择一个要发布的视频
          </div>
        )}
      </div>

      {/* 平台勾选 */}
      <div className="space-y-1.5">
        <label className="text-xs text-slate-400">目标平台</label>
        <div className="flex flex-wrap gap-2">
          {implemented.map((p) => {
            const loggedIn = accounts.some(
              (a) => a.platform === p.platform && a.login_status === 'logged_in',
            )
            const checked = selectedPlatforms.includes(p.platform)
            return (
              <button
                key={p.platform}
                type="button"
                disabled={!loggedIn || disabled}
                onClick={() => togglePlatform(p.platform)}
                className={clsx(
                  'text-xs px-2.5 py-1 rounded border transition-colors',
                  checked
                    ? 'border-indigo-500 bg-indigo-600/20 text-indigo-200'
                    : 'border-slate-700 text-slate-400',
                  (!loggedIn || disabled) && 'opacity-40 cursor-not-allowed',
                )}
                title={loggedIn ? '' : '请先在上方完成该平台登录'}
              >
                {p.label}
                {!loggedIn && '（未登录）'}
              </button>
            )
          })}
        </div>
      </div>

      {/* 每平台文案 */}
      {selectedRender &&
        selectedPlatforms
          .filter((p) => accounts.some((a) => a.platform === p && a.login_status === 'logged_in'))
          .map((p) => {
            const meta = platforms.find((x) => x.platform === p)
            const d = drafts[p] || { title: '', description: '', tags: [], user_prompt: '' }
            const spec = getPlatformSpec(p)
            const titleLen = countByLang(d.title, spec.lang)
            const descLen = countByLang(d.description, spec.lang)
            const overTitle = titleLen > spec.title_max
            const overDesc = descLen > spec.desc_max
            const overTags = d.tags.length > spec.tags_max
            return (
              <div key={p} className="rounded-md border border-slate-800 bg-slate-950/30 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-medium text-slate-300">{meta?.label} 文案</div>
                  <button
                    type="button"
                    disabled={!!generatingPlatform || !selectedRender}
                    onClick={() => onGenerateCopy(p)}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border border-indigo-500/40 bg-indigo-600/10 text-indigo-200 hover:bg-indigo-600/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    title="基于成片内容（ASR/VLM + 原素材/方案）自动生成标题、描述和标签"
                  >
                    {generatingPlatform === p ? (
                      <>
                        <Loader2 className="w-3 h-3 animate-spin" />
                        生成中…
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-3 h-3" />
                        AI 生成
                      </>
                    )}
                  </button>
                </div>
                {/* AI 生成提示词（可选）：影响下一次 AI 生成的语言/风格/修正/特定要求 */}
                <input
                  type="text"
                  value={d.user_prompt}
                  onChange={(e) => setDraft(p, { user_prompt: e.target.value })}
                  placeholder="AI 生成提示词（可选）：如 用英文输出 / 突出洁柔品牌 / 偏悬疑口吻"
                  maxLength={200}
                  className="w-full bg-slate-900/40 border border-slate-700/70 border-dashed rounded px-2 py-1.5 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                />
                {/* 标题（按平台字数硬约束限制 + 实时计数器） */}
                <div>
                  <input
                    type="text"
                    value={d.title}
                    onChange={(e) => setDraft(p, { title: e.target.value })}
                    placeholder={`标题（${spec.lang === 'en' ? '≤' : '建议 ≤'}${spec.title_max}${spec.lang === 'en' ? ' 字符' : ' 字'}）`}
                    className={`w-full bg-slate-900/60 border rounded px-2 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 ${
                      overTitle ? 'border-red-500/60' : 'border-slate-700'
                    }`}
                  />
                  <div className={`text-[10px] mt-0.5 text-right ${overTitle ? 'text-red-400' : 'text-slate-500'}`}>
                    {titleLen}/{spec.title_max}{spec.lang === 'en' ? ' 字符' : ' 字'}
                  </div>
                </div>
                {/* 描述 */}
                <div>
                  <textarea
                    value={d.description}
                    onChange={(e) => setDraft(p, { description: e.target.value })}
                    placeholder="描述（可选）"
                    rows={2}
                    className={`w-full bg-slate-900/60 border rounded px-2 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 resize-none ${
                      overDesc ? 'border-red-500/60' : 'border-slate-700'
                    }`}
                  />
                  <div className={`text-[10px] mt-0.5 text-right ${overDesc ? 'text-red-400' : 'text-slate-500'}`}>
                    {descLen}/{spec.desc_max}{spec.lang === 'en' ? ' 字符' : ' 字'}
                  </div>
                </div>
                {/* 标签 */}
                <div>
                  <input
                    type="text"
                    value={d.tags.join(' ')}
                    onChange={(e) =>
                      setDraft(p, {
                        tags: e.target.value
                          .split(/[\s,，]+/)
                          .map((t) => t.replace(/^#/, '').trim())
                          .filter(Boolean),
                      })
                    }
                    placeholder={`话题标签，空格分隔（最多 ${spec.tags_max} 个）`}
                    className={`w-full bg-slate-900/60 border rounded px-2 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 ${
                      overTags ? 'border-red-500/60' : 'border-slate-700'
                    }`}
                  />
                  <div className={`text-[10px] mt-0.5 text-right ${overTags ? 'text-red-400' : 'text-slate-500'}`}>
                    {d.tags.length}/{spec.tags_max} 个
                  </div>
                </div>
              </div>
            )
          })}

      <button
        type="button"
        disabled={submitting || disabled || loggedInPlatforms.length === 0}
        onClick={handlePublish}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
      >
        {submitting ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            发布中…
          </>
        ) : (
          <>
            <Send className="w-4 h-4" />
            {disabled
              ? '请先选择成片'
              : `一键发布到 ${selectedPlatforms.filter((p) => accounts.some((a) => a.platform === p && a.login_status === 'logged_in')).length} 个平台`}
          </>
        )}
      </button>
    </section>
  )
}
