'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Loader2, Music } from 'lucide-react'
import {
  audioLibraryApi,
  formatFastApiDetail,
  type AudioAccountResp,
  type AudioLibraryStatusResp,
  type AudioTaskResp,
  type SongMetaDTO,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { AccountPanel } from './_components/AccountPanel'
import { SearchPanel } from './_components/SearchPanel'
import { TaskList } from './_components/TaskList'

// 解析 result_json 里的歌曲列表（search 任务完成后）
function parseSearchSongs(task: AudioTaskResp | null): SongMetaDTO[] {
  if (!task?.result_json) return []
  try {
    const r = JSON.parse(task.result_json)
    return Array.isArray(r.songs) ? (r.songs as SongMetaDTO[]) : []
  } catch {
    return []
  }
}

export default function AudioLibraryPageClient() {
  const toast = useToast()
  const [status, setStatus] = useState<AudioLibraryStatusResp | null>(null)
  const [accounts, setAccounts] = useState<AudioAccountResp[]>([])
  const [tasks, setTasks] = useState<AudioTaskResp[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busySource, setBusySource] = useState<Record<string, 'login' | 'check' | undefined>>({})
  const [searchTaskId, setSearchTaskId] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<{ source: string; account: string } | null>(null)

  const loadStatus = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [st, acc, ts] = await Promise.all([
        audioLibraryApi.status(),
        audioLibraryApi.listAccounts(),
        audioLibraryApi.listTasks(),
      ])
      setStatus(st)
      setAccounts(acc.accounts)
      setTasks(ts.tasks)
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

  const hasRunningTask = tasks.some(
    (t) => t.status === 'running' || t.status === 'pending',
  )
  useEffect(() => {
    if (!hasRunningTask && !searchTaskId && Object.keys(busySource).length === 0) return
    const timer = setInterval(() => loadStatus(true), 3000)
    return () => clearInterval(timer)
  }, [hasRunningTask, searchTaskId, busySource, loadStatus])

  // 跟踪搜索任务结果
  const searchTask = useMemo(
    () => tasks.find((t) => t.id === searchTaskId) || null,
    [tasks, searchTaskId],
  )
  const searchSongs = useMemo(() => parseSearchSongs(searchTask), [searchTask])
  // 记录已 toast 过的终态任务，避免轮询刷新导致重复弹窗
  const notifiedSearchTaskIds = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (!searchTaskId || !searchTask) return
    const done = ['succeeded', 'failed', 'cancelled'].includes(searchTask.status)
    if (!done) return
    setSearching(false)
    // 幂等：同一 task 只提示一次
    if (notifiedSearchTaskIds.current.has(searchTaskId)) return
    notifiedSearchTaskIds.current.add(searchTaskId)
    if (searchTask.status === 'succeeded') {
      toast.success(`搜索完成，共 ${searchSongs.length} 首`)
    } else if (searchTask.status === 'failed') {
      toast.error('搜索失败，请查看任务日志')
    }
    // 清空 searchTaskId 打断轮询循环（searchTask 仍保留供结果展示）
  }, [searchTaskId, searchTask, searchSongs.length, toast])

  // 登录（网易云）
  const handleLogin = async (source: string, account = 'main') => {
    setBusySource((s) => ({ ...s, [source]: 'login' }))
    try {
      const r = await audioLibraryApi.login(source, account)
      toast.info(r.message || '已打开登录窗口，请在弹出的浏览器中登录')
      setTimeout(() => loadStatus(true), 2000)
    } catch (e) {
      toast.error(`登录启动失败：${formatFastApiDetail(e)}`)
    } finally {
      setTimeout(() => setBusySource((s) => ({ ...s, [source]: undefined })), 60000)
    }
  }

  // 校验登录态
  const handleCheck = async (source: string, account = 'main') => {
    setBusySource((s) => ({ ...s, [source]: 'check' }))
    try {
      const r = await audioLibraryApi.checkLogin(source, account)
      if (r.valid) {
        toast.success(`${source} 账号 ${account} 登录态有效`)
      } else {
        toast.error(`${source} 账号 ${account} 登录态失效：${r.message || ''}`)
      }
      await loadStatus(true)
    } catch (e) {
      toast.error(`校验失败：${formatFastApiDetail(e)}`)
    } finally {
      setBusySource((s) => ({ ...s, [source]: undefined }))
    }
  }

  // 删除账号
  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await audioLibraryApi.deleteAccount(pendingDelete.source, pendingDelete.account)
      toast.success('账号已删除')
      await loadStatus(true)
    } catch (e) {
      toast.error(`删除失败：${formatFastApiDetail(e)}`)
    } finally {
      setPendingDelete(null)
    }
  }

  // 搜索
  const handleSearch = async (source: string, keyword: string, account: string) => {
    setSearching(true)
    setSearchTaskId(null)
    try {
      const r = await audioLibraryApi.searchPreview({
        source,
        keyword,
        limit: 20,
        account,
      })
      setSearchTaskId(r.task_id)
      toast.info('搜索任务已提交')
    } catch (e) {
      setSearching(false)
      toast.error(`搜索失败：${formatFastApiDetail(e)}`)
    }
  }

  // 批量下载
  const handleDownload = async (source: string, account: string, songs: SongMetaDTO[]) => {
    if (songs.length === 0) {
      toast.error('请至少选择一首歌')
      return
    }
    try {
      const r = await audioLibraryApi.downloadBatch({ source, account, songs })
      toast.success(r.message || `下载任务已提交，共 ${songs.length} 首`)
      await loadStatus(true)
    } catch (e) {
      toast.error(`提交下载失败：${formatFastApiDetail(e)}`)
    }
  }

  // 取消任务
  const handleCancelTask = async (taskId: string) => {
    try {
      await audioLibraryApi.cancelTask(taskId)
      toast.info('已取消任务')
      await loadStatus(true)
    } catch (e) {
      toast.error(`取消失败：${formatFastApiDetail(e)}`)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-zinc-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> 加载中…
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-[#0d0f14] px-4 py-6 text-zinc-100 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl">
        {/* 顶栏 */}
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex items-center gap-1 text-sm text-zinc-400 transition hover:text-zinc-200"
            >
              <ArrowLeft className="h-4 w-4" /> 返回
            </Link>
            <div className="flex items-center gap-2">
              <Music className="h-5 w-5 text-emerald-400" />
              <h1 className="text-lg font-semibold">音频库</h1>
              <span className="text-xs text-zinc-500">音乐账号与爬取</span>
            </div>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* 左：账号管理 */}
          <section className="lg:col-span-1">
            <AccountPanel
              status={status}
              accounts={accounts}
              busySource={busySource}
              onLogin={handleLogin}
              onCheck={handleCheck}
              onDelete={(source, account) => setPendingDelete({ source, account })}
            />
          </section>

          {/* 中右：搜索 + 任务 */}
          <section className="space-y-6 lg:col-span-2">
            <SearchPanel
              status={status}
              searching={searching}
              searchSongs={searchSongs}
              onSearch={handleSearch}
              onDownload={handleDownload}
            />
            <TaskList tasks={tasks} onCancel={handleCancelTask} />
          </section>
        </div>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除账号"
        description={
          pendingDelete
            ? `确定删除 ${pendingDelete.source} / ${pendingDelete.account}？将清除其登录态。`
            : ''
        }
        confirmLabel="删除"
        cancelLabel="取消"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </main>
  )
}
