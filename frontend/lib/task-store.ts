'use client'

import { create } from 'zustand'

import type { StreamStatus } from './stream'

/**
 * 全局后台任务的运行时状态（非持久化——job_id 不跨重启有效）。
 *
 * <TaskHub> 订阅本 store；Phase 5 的 job 消费端在拿到 job 后调用 upsert/patch 把
 * 实时进度（stage / percent / logs）推进来。与 toast-provider 的 task() 句柄互补：
 * toast 适合「轻量、短暂」的反馈，TaskHub 适合「可离开当前页、长耗时、多并行」的任务。
 */

export interface TaskEntry {
  id: string
  /** 展示标题，如「重编码视频」「成片渲染」*/
  title: string
  /** 任务种类（reencode|burn|export_original|realize|jianying|transcribe|slice|...）*/
  kind: string
  status: StreamStatus
  stage?: string
  percent: number | null
  logs: string[]
  elapsedSec: number
  error?: string | null
  result?: unknown
  /** 完成后的产物（下载链接等），便于在卡片上展示 */
  resultLabel?: string
  /** 关联视频名（process 任务用于卡片标题展示具体视频）*/
  videoName?: string
  /** 关联视频 id */
  videoId?: string
  /** 排队顺序（0=正在跑）；仅 process 队列任务有意义 */
  queueIndex?: number
  /** 跳回来源页 */
  href?: string
  /** 取消回调 */
  onCancel?: () => void
  /** 删除回调（停止+移除）；缺省时仅前端移除 */
  onRemove?: () => void
  createdAt: number
}

interface TaskStoreState {
  tasks: Record<string, TaskEntry>
  /** 整个 hub 是否收起为角标 */
  collapsed: boolean
  upsert: (task: TaskEntry) => void
  patch: (id: string, p: Partial<TaskEntry>) => void
  /** 追加一行日志（截断到最后 200 行）*/
  appendLog: (id: string, line: string) => void
  remove: (id: string) => void
  clearFinished: () => void
  setCollapsed: (v: boolean) => void
}

export const useTaskStore = create<TaskStoreState>((set) => ({
  tasks: {},
  collapsed: false,
  upsert: (task) =>
    set((state) => ({ tasks: { ...state.tasks, [task.id]: task } })),
  patch: (id, p) =>
    set((state) => {
      const cur = state.tasks[id]
      if (!cur) return state
      return { tasks: { ...state.tasks, [id]: { ...cur, ...p } } }
    }),
  appendLog: (id, line) =>
    set((state) => {
      const cur = state.tasks[id]
      if (!cur) return state
      return {
        tasks: { ...state.tasks, [id]: { ...cur, logs: [...cur.logs, line].slice(-200) } },
      }
    }),
  remove: (id) =>
    set((state) => {
      const next = { ...state.tasks }
      delete next[id]
      return { tasks: next }
    }),
  clearFinished: () =>
    set((state) => ({
      tasks: Object.fromEntries(
        Object.entries(state.tasks).filter(
          ([, t]) => t.status === 'running' || t.status === 'idle',
        ),
      ),
    })),
  setCollapsed: (v) => set({ collapsed: v }),
}))
