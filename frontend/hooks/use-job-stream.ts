'use client'

import { useCallback } from 'react'
import { fetchSSE } from '@/lib/stream'
import { jobsApi } from '@/lib/api'
import { useTaskStore } from '@/lib/task-store'
import { useToast } from '@/components/ui/toast-provider'
import type { TaskHandle } from '@/components/ui/toast-provider'

/**
 * 统一的后台 Job 启动 + SSE 订阅 + task-store + toast 集成。
 *
 * 用法（以 reencode 为例）：
 *   const { startJob } = useJobStream()
 *   onSubmit = () => startJob({
 *     create: () => videosApi.reencode(videoId, payload),    // POST 返回 {job_id, stream_url}
 *     onDone: () => refreshVideoList(),
 *     title: '重编码视频',
 *     kind: 'reencode',
 *   })
 */

export interface StartJobOptions {
  /** 调用后端，返回 {job_id, stream_url, ws_url?, status?}。 */
  create: () => Promise<{
    job_id: string
    stream_url: string
    ws_url?: string
    status?: string
  }>
  title: string
  kind: string
  /** 完成后的产物文案，展示在卡片上 */
  resultLabel?: string
  /** 完成后回调（传入 result 事件 payload，供提取 filename/url 等） */
  onDone?: (result?: unknown) => void
}

export function useJobStream() {
  const toast = useToast()
  const upsert = useTaskStore((s) => s.upsert)
  const patch = useTaskStore((s) => s.patch)
  const appendLog = useTaskStore((s) => s.appendLog)

  const startJob = useCallback(
    async (opts: StartJobOptions) => {
      let jobId = ''
      let streamUrl = ''
      let taskHandle: TaskHandle | null = null

      try {
        const created = await opts.create()
        jobId = created.job_id
        streamUrl = (created.stream_url || '').startsWith('/')
          ? created.stream_url
          : `/api/jobs/${jobId}/stream`

        // 注册到全局 task-store
        upsert({
          id: jobId,
          title: opts.title,
          kind: opts.kind,
          status: 'running',
          percent: null,
          logs: [],
          elapsedSec: 0,
          createdAt: Date.now(),
          onCancel: () => {
            jobsApi.cancel(jobId).catch(() => undefined)
          },
        })

        // 持久 toast（indeterminate 进度）
        taskHandle = toast.task(opts.title)

        // SSE 订阅：把事件推入 task-store + toast
        const startTime = Date.now()
        await fetchSSE(
          streamUrl,
          undefined,
          {
            onEvent: (event, data) => {
              const m = data as Record<string, unknown> | null
              if (!m || event === 'done' || data === '[DONE]') return

              if (event === 'progress') {
                const step = (m?.step as string) || ''
                const msg = (m?.message as string) || ''
                const detail = (m?.detail as Record<string, unknown>) || {}
                const pct =
                  typeof detail.percent === 'number'
                    ? detail.percent
                    : typeof detail.current === 'number' && typeof detail.total === 'number' && detail.total > 0
                      ? Math.round((detail.current / detail.total) * 100)
                      : null

                patch(jobId, {
                  stage: step,
                  percent: pct,
                  elapsedSec: Math.floor((Date.now() - startTime) / 1000),
                })
                if (msg) appendLog(jobId, msg)

                taskHandle?.update({
                  message: `${opts.title}${pct !== null ? ` · ${pct}%` : ''}`,
                  percent: pct,
                  stage: msg,
                })
              }

              if (event === 'result') {
                patch(jobId, { status: 'done', result: m, percent: 100, resultLabel: opts.resultLabel })
                taskHandle?.done(opts.resultLabel || `${opts.title} 已完成`)
                opts.onDone?.(m as Record<string, unknown> | undefined)
              }

              if (event === 'failed') {
                const errMsg = (m?.message as string) || '处理失败'
                const cancelled = !!(m as Record<string, unknown>)?.cancelled
                patch(jobId, {
                  status: cancelled ? 'cancelled' : 'error',
                  error: errMsg,
                })
                if (cancelled) {
                  taskHandle?.done('已取消')
                } else {
                  taskHandle?.fail(errMsg)
                }
              }
            },
            onError: (err) => {
              patch(jobId, { status: 'error', error: err.message })
              taskHandle?.fail(err.message)
            },
          },
        )
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          const msg = (e as Error).message || '启动失败'
          if (jobId) {
            patch(jobId, { status: 'error', error: msg })
          }
          taskHandle?.fail(msg)
        }
      }
    },
    [toast, upsert, patch, appendLog],
  )

  return { startJob }
}
