'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Clapperboard, Loader2, Rocket } from 'lucide-react'
import { publishApi, formatFastApiDetail } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { usePublishStore } from '@/lib/store'
import { RenderGrid } from './_components/RenderGrid'
import { AccountPanel } from './_components/AccountPanel'
import { PublishForm } from './_components/PublishForm'
import { TaskList } from './_components/TaskList'
import type { PlatformInfo, PublishAccount, PublishStatus, PublishTask, RenderItem } from './_components/types'

export default function PublishPageClient() {
  const toast = useToast()
  const confirm = useConfirm()
  const [status, setStatus] = useState<PublishStatus | null>(null)
  const [accounts, setAccounts] = useState<PublishAccount[]>([])
  const [tasks, setTasks] = useState<PublishTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyPlatform, setBusyPlatform] = useState<Record<string, 'login' | 'check' | undefined>>({})
  const [submitting, setSubmitting] = useState(false)
  const [generatingPlatform, setGeneratingPlatform] = useState<string | null>(null)
  const [selectedRender, setSelectedRender] = useState<RenderItem | null>(null)
  const [pendingDeleteAccount, setPendingDeleteAccount] = useState<{ platform: string; account: string } | null>(null)
  const [renamingKey, setRenamingKey] = useState<string | null>(null)

  // 加载 status + accounts + tasks
  const loadStatus = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [st, acc, ts] = await Promise.all([
        publishApi.status(),
        publishApi.listAccounts(),
        publishApi.listTasks(),
      ])
      setStatus(st as unknown as PublishStatus)
      setAccounts(acc.accounts as unknown as PublishAccount[])
      setTasks(ts.tasks as unknown as PublishTask[])
      setError('')
    } catch (e) {
      if (!silent) setError(formatFastApiDetail(e))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  // 轮询：有运行中任务或登录中操作时刷新
  const hasRunningTask = tasks.some(
    (t) => t.running || t.status === 'running' || t.status === 'pending',
  )
  useEffect(() => {
    if (!hasRunningTask && Object.keys(busyPlatform).length === 0) return
    const timer = setInterval(() => loadStatus(true), 3000)
    return () => clearInterval(timer)
  }, [hasRunningTask, busyPlatform, loadStatus])

  // 登录等待中：轮询发现该平台已有任一账号变为已登录时，立即解除 busy（不等 60s 超时）
  useEffect(() => {
    const logged = (plat: string) =>
      accounts.some((a) => a.platform === plat && a.login_status === 'logged_in')
    const done = Object.entries(busyPlatform).filter(([plat, mode]) => mode === 'login' && logged(plat))
    if (done.length === 0) return
    setBusyPlatform((prev) => {
      const next = { ...prev }
      for (const [plat] of done) delete next[plat]
      return next
    })
    for (const [plat] of done) toast.success(`${plat} 登录成功`)
  }, [accounts, busyPlatform, toast])

  /** 用户在浏览器完成扫码后手动解除登录等待（兜底：轮询未及时捕捉时用） */
  const handleDoneLogin = (platform: string) => {
    setBusyPlatform((s) => ({ ...s, [platform]: undefined }))
    void loadStatus(true)
  }

  // 登录
  const handleLogin = async (platform: string, account: string = 'main') => {
    setBusyPlatform((s) => ({ ...s, [platform]: 'login' }))
    try {
      const r = await publishApi.login(platform, account)
      toast.info(r.message || '已打开登录窗口，请在弹出的浏览器中扫码')
      setTimeout(() => loadStatus(true), 2000)
    } catch (e) {
      toast.error(`登录启动失败：${formatFastApiDetail(e)}`)
    } finally {
      setTimeout(() => setBusyPlatform((s) => ({ ...s, [platform]: undefined })), 60000)
    }
  }

  const handleCheck = async (platform: string, account: string) => {
    setBusyPlatform((s) => ({ ...s, [platform]: 'check' }))
    try {
      const r = await publishApi.checkLogin(platform, account)
      if (r.valid) {
        toast.success(`${platform} 登录态有效`)
      } else {
        toast.error(`${platform} 登录态已失效，请重新登录`)
      }
      await loadStatus(true)
    } catch (e) {
      toast.error(`校验失败：${formatFastApiDetail(e)}`)
    } finally {
      setBusyPlatform((s) => ({ ...s, [platform]: undefined }))
    }
  }

  // 重命名账号（设置/清除自定义备注名）
  const handleRename = async (platform: string, account: string, displayName: string) => {
    const key = `${platform}-${account}`
    setRenamingKey(key)
    try {
      await publishApi.updateAccount(platform, account, { display_name: displayName })
      toast.success(displayName ? `已将账号备注名设为「${displayName}」` : '已清除账号备注名')
      await loadStatus(true)
    } catch (e) {
      toast.error(`重命名失败：${formatFastApiDetail(e)}`)
    } finally {
      setRenamingKey(null)
    }
  }

  // 点删除 → 打开确认弹窗
  const handleDelete = (platform: string, account: string) => {
    setPendingDeleteAccount({ platform, account })
  }

  // 确认删除账号
  const handleDeleteAccountConfirm = async () => {
    const target = pendingDeleteAccount
    setPendingDeleteAccount(null)
    if (!target) return
    try {
      await publishApi.deleteAccount(target.platform, target.account)
      toast.success(`已删除 ${target.platform} 账号`)
      await loadStatus(true)
    } catch (e) {
      toast.error(`删除失败：${formatFastApiDetail(e)}`)
    }
  }

  const handleSubmit = async (
    videoPath: string,
    items: Array<{ platform: string; account: string; title: string; description: string; tags: string[] }>,
    headless: boolean,
  ) => {
    setSubmitting(true)
    try {
      await publishApi.createTask({
        video_path: videoPath,
        items: items.map((it) => ({
          ...it,
          cover_path: null,
          publish_strategy: 'immediate' as const,
          publish_date: null,
        })),
        headless,
      })
      toast.success(
        `任务已创建，正在发布到 ${items.length} 个平台${headless ? '' : '（有头模式，浏览器窗口已弹出）'}`,
      )
      await loadStatus(true)
    } catch (e) {
      toast.error(`发布失败：${formatFastApiDetail(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (taskId: string) => {
    const ok = await confirm({
      title: '取消该发布任务？',
      description: '进行中的发布将被终止；已成功发布的部分不会撤回。',
      confirmLabel: '取消任务',
      variant: 'danger',
    })
    if (!ok) return
    try {
      await publishApi.cancelTask(taskId)
      toast.info('已取消任务')
      await loadStatus(true)
    } catch (e) {
      toast.error(`取消失败：${formatFastApiDetail(e)}`)
    }
  }

  // AI 生成文案：先清空该平台的旧文案（保留 user_prompt），调后端生成，填回草稿
  const { setDraft, drafts } = usePublishStore()
  const handleGenerateCopy = async (platform: string) => {
    if (!selectedRender) {
      toast.error('请先选择一个成片')
      return
    }
    // 先清空旧文案，避免新旧混淆；保留用户输入的提示词
    setDraft(platform, { title: '', description: '', tags: [] })
    setGeneratingPlatform(platform)
    const handle = toast.task(`正在为「${platform}」生成文案…`, {
      stage: '解析成片内容（ASR/VLM）并调用大模型',
    })
    try {
      const userPrompt = (drafts[platform]?.user_prompt || '').trim()
      const r = await publishApi.generateCopy(selectedRender.id, {
        platform,
        user_prompt: userPrompt || undefined,
      })
      setDraft(platform, {
        title: r.title || '',
        description: r.description || '',
        tags: r.tags || [],
      })
      // 执行情况汇总：依据来源 + 缓存命中 + 字数达标情况
      const used: string[] = []
      if (r.source.material_title) used.push('原素材')
      if (r.source.plan) used.push('方案')
      if (r.source.asr) used.push('ASR')
      if (r.source.vlm) used.push('VLM')
      const cachedParts: string[] = []
      if (r.cached.asr) cachedParts.push('ASR')
      if (r.cached.vlm) cachedParts.push('VLM')
      const lim = r.limits
      const len = r.lengths
      // 字数达标判断（标题/描述/标签数量都在平台上限内）
      const over: string[] = []
      if (lim && len) {
        if (len.title > lim.title_max) over.push(`标题 ${len.title}/${lim.title_max}`)
        if (len.description > lim.desc_max) over.push(`描述 ${len.description}/${lim.desc_max}`)
        if (len.tags > lim.tags_max) over.push(`标签 ${len.tags}/${lim.tags_max}`)
      }
      const lines = [
        `${platform} 文案已生成`,
        used.length ? `依据：${used.join(' + ')}` : '依据：通用经验（未取到 ASR/方案等上下文）',
        cachedParts.length ? `命中缓存：${cachedParts.join(' / ')}（未重复调用）` : '本次新解析（ASR/VLM）',
        lim && len
          ? `字数：标题 ${len.title}/${lim.title_max} · 描述 ${len.description}/${lim.desc_max} · 标签 ${len.tags}/${lim.tags_max}（${lim.lang === 'en' ? '字符' : '字'}）`
          : '',
        r.trimmed ? '⚠️ 内容超长已被自动截断，请复核' : '',
        over.length ? `⚠️ 仍有超限：${over.join('、')}` : '',
        userPrompt ? `用户提示词：${userPrompt}` : '',
      ].filter(Boolean)
      handle.done(lines.join('\n'))
    } catch (e) {
      handle.fail(`AI 生成失败：${formatFastApiDetail(e)}`)
    } finally {
      setGeneratingPlatform(null)
    }
  }

  // 选中成片被删除时清空选中态
  const handleRenderDeleted = (id: string) => {
    if (selectedRender?.id === id) setSelectedRender(null)
  }

  const platforms: PlatformInfo[] = status?.platforms || []

  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-7xl mx-auto px-6 py-8 space-y-5">
        {/* 标题栏 */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />首页
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Clapperboard className="w-5 h-5 text-indigo-400" />
            成片中心 · 一键发布
          </h1>
          {status?.browser && (
            <span className="text-xs text-slate-500 ml-auto">
              浏览器引擎：{status.browser.label}
              {status.browser.kind === 'chromium' && '（内置兜底）'}
            </span>
          )}
        </div>

        {/* 浏览器未就绪提示 */}
        {status && !status.ready && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
            ⚠️ 浏览器引擎未就绪：未检测到本地 Chrome/Edge，且包内 Chromium 不可用。
            发布功能需要浏览器引擎支持，请安装 Chrome 或 Edge 浏览器后重试。
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中…
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {!loading && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* 左侧：成片列表（占 7 列） */}
            <div className="lg:col-span-7 rounded-lg border border-slate-800 bg-slate-900/30 p-4">
              <h2 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <Rocket className="w-4 h-4 text-indigo-400" />成片列表
                <span className="text-xs text-slate-500 font-normal">点击选中后可在右侧发布</span>
              </h2>
              <div className="h-[calc(100vh-280px)] min-h-[400px]">
                <RenderGrid
                  selectedId={selectedRender?.id || null}
                  onSelect={setSelectedRender}
                  onDeleted={handleRenderDeleted}
                />
              </div>
            </div>

            {/* 右侧：发布配置（占 5 列） */}
            <div className="lg:col-span-5 space-y-4">
              <AccountPanel
                platforms={platforms}
                accounts={accounts}
                busyPlatform={busyPlatform}
                renamingKey={renamingKey}
                onLogin={handleLogin}
                onCheck={handleCheck}
                onDelete={handleDelete}
                onRename={handleRename}
                onDoneLogin={handleDoneLogin}
              />
              <PublishForm
                platforms={platforms}
                accounts={accounts}
                selectedRender={selectedRender}
                submitting={submitting}
                generatingPlatform={generatingPlatform}
                onSubmit={handleSubmit}
                onGenerateCopy={handleGenerateCopy}
              />
              <TaskList tasks={tasks} onCancel={handleCancel} />
            </div>
          </div>
        )}

        {/* 使用须知 */}
        <div className="rounded-lg border border-slate-800 bg-slate-900/30 p-3 text-xs text-slate-500 leading-relaxed">
          <p className="font-medium text-slate-400 mb-1">使用须知</p>
          <ul className="list-disc pl-4 space-y-0.5">
            <li>成片来自智剪、影视解说、文案素材等模块的合成/导出产物，左侧列表可浏览、检索、删除。</li>
            <li>发布基于浏览器自动化模拟人工操作，请合理使用，遵守各平台用户协议。</li>
            <li>各平台对自动化操作有风控，频繁发布可能导致账号限制，建议控制发布频率。</li>
          </ul>
        </div>
      </div>

      {/* 删除账号确认弹窗 */}
      <ConfirmDialog
        open={pendingDeleteAccount !== null}
        title="删除账号"
        description={
          pendingDeleteAccount
            ? (() => {
                const acc = accounts.find(
                  (a) =>
                    a.platform === pendingDeleteAccount.platform &&
                    a.account === pendingDeleteAccount.account,
                )
                const shown = acc?.display_name || pendingDeleteAccount.account
                return `确定删除 ${pendingDeleteAccount.platform} 账号「${shown}」？本地 cookie 将被清除。`
              })()
            : ''
        }
        confirmLabel="删除"
        cancelLabel="取消"
        variant="danger"
        onConfirm={handleDeleteAccountConfirm}
        onCancel={() => setPendingDeleteAccount(null)}
      />
    </main>
  )
}
