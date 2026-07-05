'use client'

import { useEffect } from 'react'
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
    headless: boolean,
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
  const { drafts, selectedTargets, setDraft, setSelectedTargets, publishHeadless, setPublishHeadless } = usePublishStore()

  const implemented = platforms.filter((p) => p.implemented)
  // 已登录账号（按平台分组），勾选只在这些账号里展开
  const loggedInAccountsByPlatform: Record<string, PublishAccount[]> = {}
  for (const a of accounts) {
    if (a.login_status !== 'logged_in') continue
    if (!implemented.some((p) => p.platform === a.platform)) continue
    (loggedInAccountsByPlatform[a.platform] ||= []).push(a)
  }
  // 有任意已登录账号的平台
  const loggedInPlatforms = implemented.filter((p) => (loggedInAccountsByPlatform[p.platform]?.length || 0) > 0)

  // 默认勾选补全：当 accounts 到来后，把"已登录但未在 selectedTargets 中的账号"补上。
  // 用户主动取消勾选的账号，只要仍处于"已登录"状态就会保留在 selectedTargets 里
  // （取消 = 从 selectedTargets 移除，但下次 accounts 变化触发的补全会再加回 —— 这是
  // "默认全选"语义的预期行为；如需持久化取消意图，可在后续迭代加白名单）。
  useEffect(() => {
    const expected: string[] = []
    for (const p of loggedInPlatforms) {
      for (const a of loggedInAccountsByPlatform[p.platform]) {
        expected.push(`${p.platform}:${a.account}`)
      }
    }
    if (expected.length === 0) return
    const current = new Set(selectedTargets)
    const missing = expected.filter((k) => !current.has(k))
    if (missing.length === 0) return
    // 合并：保留已有 + 补缺
    const next = Array.from(new Set([...selectedTargets, ...missing]))
    // 同时剔除已失效/已删除的脏 target（不在当前已登录集合里且不在 expected 里的）
    const validSet = new Set([...expected, ...selectedTargets.filter((k) => {
      const [plat, acc] = k.split(':')
      // 仍保留"未登录但勾选过的"，避免反复横跳；只清理平台/账号已不存在的
      return accounts.some((a) => a.platform === plat && a.account === acc)
    })])
    const cleaned = next.filter((k) => validSet.has(k))
    if (cleaned.length !== selectedTargets.length || cleaned.some((k, i) => k !== next[i])) {
      setSelectedTargets(cleaned)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts])

  const toggleAccount = (platform: string, account: string) => {
    const key = `${platform}:${account}`
    setSelectedTargets(
      selectedTargets.includes(key)
        ? selectedTargets.filter((x) => x !== key)
        : [...selectedTargets, key],
    )
  }

  // 平台级"全选/全不选"：点平台标题 checkbox 切换该平台下所有已登录账号
  const togglePlatformAll = (platform: string) => {
    const accs = loggedInAccountsByPlatform[platform] || []
    const keys = accs.map((a) => `${platform}:${a.account}`)
    const allChecked = keys.every((k) => selectedTargets.includes(k))
    if (allChecked) {
      // 全选 → 取消该平台全部
      setSelectedTargets(selectedTargets.filter((k) => !keys.includes(k)))
    } else {
      // 非全选 → 补全
      setSelectedTargets(Array.from(new Set([...selectedTargets, ...keys])))
    }
  }

  const handlePublish = () => {
    if (!selectedRender) return
    if (selectedTargets.length === 0) return
    // 把每个勾选目标展开为一条发布项（account 用实际账号标识，不再硬编码 main）
    const items = selectedTargets.map((key) => {
      const [platform, account] = key.split(':')
      const d: PublishDraftPerPlatform = drafts[platform] || { title: '', description: '', tags: [] }
      return {
        platform,
        account,
        title: d.title.trim(),
        description: d.description.trim(),
        tags: d.tags,
      }
    })
    // 用成片的 file_path（storage/... 相对路径）传给后端，resolve_stored_path 能解析
    onSubmit(selectedRender.file_path, items, publishHeadless)
  }

  const disabled = !selectedRender

  // 文案区：对"至少勾选了一个账号的平台"渲染草稿（仅 platform id 字符串数组）
  const platformsWithDraft = loggedInPlatforms
    .filter((p) => selectedTargets.some((k) => k.startsWith(`${p.platform}:`)))
    .map((p) => p.platform)
  // 统计：勾选的总账号数
  const totalSelectedAccounts = selectedTargets.length
  // 全局可选账号总数（所有已登录账号）
  const allTargetKeys = loggedInPlatforms.flatMap((p) =>
    (loggedInAccountsByPlatform[p.platform] || []).map((a) => `${p.platform}:${a.account}`),
  )
  const allSelected = allTargetKeys.length > 0 && allTargetKeys.every((k) => selectedTargets.includes(k))

  // 全局全选 / 取消全选
  const toggleSelectAll = () => {
    if (allSelected) {
      // 已全选 → 取消全部（仅清空这些可选目标，保留 selectedTargets 中其它不存在的脏数据无意义）
      const set = new Set(allTargetKeys)
      setSelectedTargets(selectedTargets.filter((k) => !set.has(k)))
    } else {
      // 非全选 → 全选
      setSelectedTargets(Array.from(new Set([...selectedTargets, ...allTargetKeys])))
    }
  }

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

      {/* 目标平台 + 账号勾选（平台块内逐账号勾选，支持矩阵运营） */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs text-slate-400">目标账号</label>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-500">
              {totalSelectedAccounts > 0 ? `已选 ${totalSelectedAccounts} 个账号` : '未选择'}
            </span>
            {allTargetKeys.length > 0 && (
              <button
                type="button"
                onClick={toggleSelectAll}
                disabled={disabled}
                className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400 hover:text-indigo-300 hover:border-indigo-500/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                title={allSelected ? '取消勾选所有账号' : '勾选所有已登录账号'}
              >
                {allSelected ? '取消全选' : '全选'}
              </button>
            )}
          </div>
        </div>
        <div className="space-y-1.5">
          {loggedInPlatforms.length === 0 && (
            <div className="text-[11px] text-slate-500 px-1 py-2">
              暂无已登录账号，请先在上方账号管理完成登录
            </div>
          )}
          {loggedInPlatforms.map((p) => {
            const accs = loggedInAccountsByPlatform[p.platform]
            const keys = accs.map((a) => `${p.platform}:${a.account}`)
            const checkedCount = keys.filter((k) => selectedTargets.includes(k)).length
            const allChecked = checkedCount === keys.length && keys.length > 0
            const someChecked = checkedCount > 0 && !allChecked
            return (
              <div
                key={p.platform}
                className="rounded-md border border-slate-800 bg-slate-950/30 px-2.5 py-2 space-y-1.5"
              >
                {/* 平台标题行：全选 checkbox */}
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={allChecked}
                    ref={(el) => { if (el) el.indeterminate = someChecked }}
                    onChange={() => togglePlatformAll(p.platform)}
                    disabled={disabled}
                    className="w-3.5 h-3.5 accent-indigo-500 rounded"
                  />
                  <span className="text-sm font-medium text-slate-200">{p.label}</span>
                  <span className="text-[10px] text-slate-500">
                    {checkedCount}/{keys.length}
                  </span>
                </label>
                {/* 该平台下的账号列表 */}
                <div className="flex flex-wrap gap-x-3 gap-y-1 pl-5">
                  {accs.map((a) => {
                    const key = `${p.platform}:${a.account}`
                    const checked = selectedTargets.includes(key)
                    const name = a.display_name || a.account
                    return (
                      <label
                        key={key}
                        className={clsx(
                          'flex items-center gap-1 text-xs cursor-pointer select-none',
                          disabled ? 'opacity-50' : 'text-slate-300',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleAccount(p.platform, a.account)}
                          disabled={disabled}
                          className="w-3 h-3 accent-indigo-500 rounded"
                        />
                        <span>{name}</span>
                        {a.display_name && (
                          <span className="text-[10px] text-slate-500">{a.account}</span>
                        )}
                      </label>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 每平台文案（同平台多账号共享一份草稿） */}
      {selectedRender &&
        platformsWithDraft
          .map((p) => {
            const meta = platforms.find((x) => x.platform === p)
            const d = drafts[p] || { title: '', description: '', tags: [], user_prompt: '' }
            const spec = getPlatformSpec(p)
            const titleLen = countByLang(d.title, spec.lang)
            const descLen = countByLang(d.description, spec.lang)
            const overTitle = titleLen > spec.title_max
            const overDesc = descLen > spec.desc_max
            const overTags = d.tags.length > spec.tags_max
            // 该平台勾选的账号数
            const accountCount = selectedTargets.filter((k) => k.startsWith(`${p}:`)).length
            return (
              <div key={p} className="rounded-md border border-slate-800 bg-slate-950/30 p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-medium text-slate-300 flex items-center gap-1.5">
                    {meta?.label} 文案
                    {accountCount > 1 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                        将发布到 {accountCount} 个账号
                      </span>
                    )}
                  </div>
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

      {/* 有头/无头模式开关：失败时可开「有头」显示浏览器窗口手动兜底 */}
      <label
        className="flex items-center justify-between gap-2 text-xs text-slate-400 cursor-pointer select-none"
        title={publishHeadless ? '当前后台运行（无界面）' : '当前显示浏览器窗口，可在失败时手动操作/排查'}
      >
        <span className="flex items-center gap-1">
          {publishHeadless ? '后台无头模式' : '🖥️ 有头模式（显示浏览器）'}
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={!publishHeadless}
          onClick={() => setPublishHeadless(!publishHeadless)}
          className={clsx(
            'relative w-9 h-5 rounded-full transition-colors shrink-0',
            publishHeadless ? 'bg-slate-700' : 'bg-indigo-600',
          )}
        >
          <span
            className={clsx(
              'absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform',
              !publishHeadless && 'translate-x-4',
            )}
          />
        </button>
      </label>
      {!publishHeadless && (
        <p className="text-[11px] text-amber-300/80 leading-relaxed -mt-2">
          发布时将弹出浏览器窗口，可观察流程、失败时手动完成投稿。适合排查问题或处理 B站分区等需手动操作的场景。
        </p>
      )}

      <button
        type="button"
        disabled={submitting || disabled || totalSelectedAccounts === 0}
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
              : totalSelectedAccounts === 0
                ? '请勾选要发布的账号'
                : `一键发布到 ${totalSelectedAccounts} 个账号`}
          </>
        )}
      </button>
    </section>
  )
}
