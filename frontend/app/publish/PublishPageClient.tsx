'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Clapperboard, Loader2, Rocket } from 'lucide-react'
import { publishApi, formatFastApiDetail } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { RenderGrid } from './_components/RenderGrid'
import { AccountPanel } from './_components/AccountPanel'
import { PublishForm } from './_components/PublishForm'
import { TaskList } from './_components/TaskList'
import type { PlatformInfo, PublishAccount, PublishStatus, PublishTask, RenderItem } from './_components/types'

export default function PublishPageClient() {
  const toast = useToast()
  const [status, setStatus] = useState<PublishStatus | null>(null)
  const [accounts, setAccounts] = useState<PublishAccount[]>([])
  const [tasks, setTasks] = useState<PublishTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyPlatform, setBusyPlatform] = useState<Record<string, 'login' | 'check' | undefined>>({})
  const [submitting, setSubmitting] = useState(false)
  const [selectedRender, setSelectedRender] = useState<RenderItem | null>(null)

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

  const handleDelete = async (platform: string, account: string) => {
    if (!confirm(`确定删除 ${platform} 账号「${account}」？本地 cookie 将被清除。`)) return
    try {
      await publishApi.deleteAccount(platform, account)
      toast.success(`已删除 ${platform} 账号`)
      await loadStatus(true)
    } catch (e) {
      toast.error(`删除失败：${formatFastApiDetail(e)}`)
    }
  }

  const handleSubmit = async (
    videoPath: string,
    items: Array<{ platform: string; account: string; title: string; description: string; tags: string[] }>,
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
      })
      toast.success(`任务已创建，正在发布到 ${items.length} 个平台`)
      await loadStatus(true)
    } catch (e) {
      toast.error(`发布失败：${formatFastApiDetail(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = async (taskId: string) => {
    try {
      await publishApi.cancelTask(taskId)
      toast.info('已取消任务')
      await loadStatus(true)
    } catch (e) {
      toast.error(`取消失败：${formatFastApiDetail(e)}`)
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
                onLogin={handleLogin}
                onCheck={handleCheck}
                onDelete={handleDelete}
              />
              <PublishForm
                platforms={platforms}
                accounts={accounts}
                selectedRender={selectedRender}
                submitting={submitting}
                onSubmit={handleSubmit}
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
    </main>
  )
}
