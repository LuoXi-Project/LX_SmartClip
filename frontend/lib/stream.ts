'use client'

/**
 * 统一的流式 / 进度传输层。
 *
 * 提供两个抽象层级：
 *  1. `readSSE` / `openEventSource` —— 低层、与协议无关的解析器，替换此前散落在
 *     agent-api / CopyGeneratorPanel / AIChatPanel / summary 等处的重复 SSE 解析
 *     （其中 CopyGeneratorPanel / AIChatPanel 的逐 chunk `split('\n')` 还存在跨
 *     chunk 边界丢数据的隐患，统一后一并修复）。
 *  2. `useStreamTask` —— 面向「通用 Job 进度协议」的高层 hook，封装状态机
 *     （stage / percent / logs / elapsed / cancel），供页面内 <StreamingProgress>
 *     与全局 <TaskHub> 直接消费。
 *
 * 纯逻辑文件：不放任何 Tailwind class（tailwind.config 的 content glob 不含 lib/）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { API_BASE_URL } from './runtime-config'

export const streamBase = (): string => (API_BASE_URL || '').replace(/\/$/, '')

// ─── 低层：fetch Response 的命名事件 SSE 解析 ─────────────────────────────────

export interface SSEHandlers {
  onEvent: (event: string, data: unknown) => void
  onError?: (err: Error) => void
}

/**
 * 从一个 fetch Response 逐块解析 SSE 命名事件。
 *
 * 规范行为：每个以空行分隔的事件块，`event:` 行决定事件名（缺省回退为 `message`，
 * 且每个块独立重置，符合 SSE 规范）；多行 `data:` 会拼接。循环结束后会 drain
 * 尾部未以空行收尾的缓冲，避免最后一帧丢失。
 */
export async function readSSE(
  res: Response,
  handlers: SSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    handlers.onError?.(new Error(err.detail || `HTTP ${res.status}`))
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  // 外部 abort 时主动取消 reader，让 read() 尽快抛出 AbortError
  if (signal) {
    const onAbort = () => {
      reader.cancel().catch(() => undefined)
    }
    if (signal.aborted) onAbort()
    else signal.addEventListener('abort', onAbort, { once: true })
  }

  const dispatchBlock = (block: string) => {
    const lines = block.split('\n')
    let eventName = 'message' // 每块独立重置，符合 SSE 规范
    let dataStr = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) eventName = line.slice(7).trim()
      else if (line.startsWith('data: ')) dataStr += line.slice(6)
      // data 行的续行（`data:`无空格）也按规范拼接
      else if (line.startsWith('data:')) dataStr += line.slice(5)
    }
    if (!dataStr) return
    if (dataStr.trim() === '[DONE]') {
      handlers.onEvent('done', '[DONE]')
      return
    }
    try {
      handlers.onEvent(eventName, JSON.parse(dataStr))
    } catch {
      handlers.onEvent(eventName, { raw: dataStr })
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const block of parts) {
        if (block.trim()) dispatchBlock(block)
      }
    }
    // 尾部 drain：处理未以空行收尾的最后一帧
    if (buffer.trim()) dispatchBlock(buffer)
  } catch (e) {
    if ((e as Error).name !== 'AbortError') handlers.onError?.(e as Error)
  }
}

/**
 * 发起一次 fetch + SSE 流式请求的便捷封装（含错误抽取与 AbortSignal 透传）。
 */
export async function fetchSSE(
  url: string,
  init: RequestInit | undefined,
  handlers: SSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, { ...init, signal })
  await readSSE(res, handlers, signal)
}

// ─── 低层：EventSource 命名事件适配（GET、自动重连）─────────────────────────────

export interface EventSourceHandlers {
  onEvent: (event: string, data: unknown) => void
  onError?: (err: Error) => void
  onOpen?: () => void
}

/**
 * 打开一个 EventSource 并按命名事件分发。返回一个 close 句柄。
 * EventSource 仅支持 GET、且会自动重连；适合服务端已提供 GET SSE 端点的场景。
 */
export function openEventSource(url: string, handlers: EventSourceHandlers): () => void {
  const es = new EventSource(url)
  if (handlers.onOpen) es.addEventListener('open', () => handlers.onOpen?.())
  es.onmessage = (ev) => {
    try {
      handlers.onEvent('message', JSON.parse(ev.data || '{}'))
    } catch {
      handlers.onEvent('message', { raw: ev.data })
    }
  }
  // 通用命名事件监听
  const knownEvents = ['progress', 'result', 'failed', 'done', 'error', 'stage', 'log']
  for (const name of knownEvents) {
    es.addEventListener(name, (ev) => {
      const data = (ev as MessageEvent).data
      try {
        handlers.onEvent(name, JSON.parse(data || '{}'))
      } catch {
        handlers.onEvent(name, { raw: data })
      }
    })
  }
  es.onerror = () => {
    // readyState === CLOSED 表示服务端关闭了流（正常结束或致命错误）
    if (es.readyState === EventSource.CLOSED) {
      handlers.onError?.(new Error('stream closed'))
    }
    // 否则 EventSource 会自动重连，不打断
  }
  return () => es.close()
}

// ─── 高层：通用 Job 进度协议 + useStreamTask hook ──────────────────────────────

/**
 * 后端通用 Job 进度消息（与 backend/app/jobs/reporter.py 的 JobReporter.send 对齐，
 * 也兼容既有 process_job 的 WS 消息形状 {step, status, message, detail}）。
 */
export interface JobProgressMessage {
  step?: string
  status?: string // running | done | error | skip | cancelled
  message?: string
  detail?: {
    percent?: number
    current?: number
    total?: number
    metrics?: Record<string, unknown>
    [key: string]: unknown
  }
}

export type StreamStatus = 'idle' | 'running' | 'done' | 'error' | 'cancelled'

export interface StreamTaskHandlers {
  onStage?: (stage: string) => void
  onLog?: (line: string) => void
  onPercent?: (p: number) => void
  onResult?: (result: unknown) => void
  onError?: (err: Error) => void
}

export interface StreamTaskState {
  status: StreamStatus
  stage: string
  percent: number | null
  logs: string[]
  elapsedSec: number
  error: string | null
  result: unknown
}

export interface UseStreamTaskOptions {
  /** fetch + SSE 模式 */
  sse?: { url: string; init?: RequestInit }
  /** WebSocket 模式（消息体直接是 JobProgressMessage）*/
  ws?: string | (() => WebSocket)
  /** EventSource 模式（GET 命名事件，自动重连）*/
  eventSource?: string
  /**
   * 自定义事件分发：把 SSE 命名事件映射成对 handlers / 状态的影响。
   * 默认实现处理通用 Job 协议（progress / result / failed）以及 OpenAI 风格的
   * `data` 增量（delta.content）。返回 false 表示交给默认逻辑。
   */
  reduce?: (
    event: string,
    data: unknown,
    ctx: { setStatus: (s: StreamStatus) => void; apply: (m: JobProgressMessage) => void },
  ) => boolean
}

const EMPTY_STATE: StreamTaskState = {
  status: 'idle',
  stage: '',
  percent: null,
  logs: [],
  elapsedSec: 0,
  error: null,
  result: null,
}

/**
 * 面向「通用 Job 进度协议」的流式任务 hook。
 *
 * - 一个调用搞定：连接后端 → 解析事件 → 推进状态(stage/percent/logs) → 计时 → 可取消。
 * - 支持 SSE(fetch) / WebSocket / EventSource 三种传输。
 * - 自动维护 elapsedSec 计时器（running 时每秒 +1）。
 * - 返回 start()/cancel()；cancel() 会 abort 当前连接并把 status 置为 cancelled。
 */
export function useStreamTask(opts: UseStreamTaskOptions, handlers: StreamTaskHandlers = {}) {
  const [state, setState] = useState<StreamTaskState>(EMPTY_STATE)

  const abortRef = useRef<AbortController | null>(null)
  const closeWsRef = useRef<(() => void) | null>(null)
  const closeEsRef = useRef<(() => void) | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedAtRef = useRef<number>(0)
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const optsRef = useRef(opts)
  optsRef.current = opts

  const clearTimers = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const stopTransports = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    closeWsRef.current?.()
    closeWsRef.current = null
    closeEsRef.current?.()
    closeEsRef.current = null
  }, [])

  const applyMessage = useCallback((m: JobProgressMessage) => {
    setState((prev) => {
      const next = { ...prev }
      if (m.step) next.stage = m.step
      if (m.message) {
        next.logs = [...prev.logs, m.message].slice(-200)
        handlersRef.current.onLog?.(m.message)
      }
      if (typeof m.detail?.percent === 'number') {
        next.percent = Math.max(0, Math.min(100, m.detail.percent))
      } else if (
        typeof m.detail?.current === 'number' &&
        typeof m.detail?.total === 'number' &&
        m.detail.total > 0
      ) {
        next.percent = Math.round((m.detail.current / m.detail.total) * 100)
      }
      if (m.step) handlersRef.current.onStage?.(m.step)
      if (next.percent !== null) handlersRef.current.onPercent?.(next.percent)
      if (m.status === 'done') next.status = 'done'
      else if (m.status === 'error') {
        next.status = 'error'
        next.error = m.message || '处理失败'
      } else if (m.status === 'cancelled') next.status = 'cancelled'
      else if (m.status === 'running' && prev.status !== 'error') next.status = 'running'
      return next
    })
  }, [])

  const defaultReduce = useCallback(
    (
      event: string,
      data: unknown,
      ctx: { setStatus: (s: StreamStatus) => void; apply: (m: JobProgressMessage) => void },
    ): boolean => {
      // 通用 Job 命名事件协议
      if (event === 'progress') {
        ctx.apply((data ?? {}) as JobProgressMessage)
        return true
      }
      if (event === 'result') {
        setState((prev) => ({ ...prev, status: 'done', result: data }))
        handlersRef.current.onResult?.(data)
        return true
      }
      if (event === 'failed' || event === 'error') {
        const msg = (data as { message?: string; detail?: string })?.message
          || (data as { detail?: string })?.detail
          || '处理失败'
        setState((prev) => ({ ...prev, status: 'error', error: msg }))
        handlersRef.current.onError?.(new Error(msg))
        return true
      }
      // 直接的 JobProgressMessage（WS / 无 event: 前缀的 data）
      if (event === 'message' && data && typeof data === 'object' && ('step' in data || 'status' in data)) {
        ctx.apply(data as JobProgressMessage)
        return true
      }
      return false
    },
    [],
  )

  const finish = useCallback(
    (status: StreamStatus) => {
      clearTimers()
      setState((prev) => {
        if (prev.status === 'done' || prev.status === 'error' || prev.status === 'cancelled') {
          return prev
        }
        return { ...prev, status }
      })
    },
    [clearTimers],
  )

  const start = useCallback(async () => {
    stopTransports()
    clearTimers()
    setState({ ...EMPTY_STATE, status: 'running' })
    startedAtRef.current = Date.now()
    timerRef.current = setInterval(() => {
      setState((prev) =>
        prev.status === 'running'
          ? { ...prev, elapsedSec: Math.floor((Date.now() - startedAtRef.current) / 1000) }
          : prev,
      )
    }, 1000)

    const ctx = {
      setStatus: (s: StreamStatus) => setState((prev) => ({ ...prev, status: s })),
      apply: applyMessage,
    }
    const reduce = optsRef.current.reduce ?? defaultReduce
    const onEvent = (event: string, data: unknown) => {
      reduce(event, data, ctx)
    }
    const onError = (err: Error) => {
      handlersRef.current.onError?.(err)
      finish('error')
      setState((prev) => (prev.error ? prev : { ...prev, error: err.message }))
    }

    try {
      if (optsRef.current.sse) {
        const ctrl = new AbortController()
        abortRef.current = ctrl
        const { url, init } = optsRef.current.sse
        await fetchSSE(url, init, { onEvent, onError }, ctrl.signal)
        finish('done')
      } else if (optsRef.current.ws) {
        await new Promise<void>((resolve) => {
          const ws = typeof optsRef.current.ws === 'function' ? optsRef.current.ws!() : new WebSocket(optsRef.current.ws as string)
          closeWsRef.current = () => {
            try {
              ws.close()
            } catch {
              /* noop */
            }
          }
          ws.onmessage = (ev) => {
            try {
              const data = JSON.parse(ev.data)
              if (data && typeof data === 'object' && 'step' in data) {
                applyMessage(data as JobProgressMessage)
                if (data.status === 'done' || data.status === 'error' || data.status === 'cancelled') {
                  resolve()
                }
              } else {
                reduce(data?.event ?? 'message', data, ctx)
              }
            } catch {
              /* ignore malformed frame */
            }
          }
          ws.onerror = () => onError(new Error('连接中断'))
          ws.onclose = () => resolve()
        })
        finish('done')
      } else if (optsRef.current.eventSource) {
        await new Promise<void>((resolve) => {
          closeEsRef.current = openEventSource(optsRef.current.eventSource!, {
            onEvent,
            onError: (err) => {
              onError(err)
              resolve()
            },
          })
          // result / failed 事件后由 reduce 决定终止；这里监听状态收尾
          const poll = setInterval(() => {
            setState((s) => {
              if (s.status === 'done' || s.status === 'error' || s.status === 'cancelled') {
                clearInterval(poll)
                resolve()
              }
              return s
            })
          }, 300)
          // 兜底：把 poll 也纳入清理
          const prevClose = closeEsRef.current
          closeEsRef.current = () => {
            clearInterval(poll)
            prevClose?.()
          }
        })
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') onError(e as Error)
    } finally {
      clearTimers()
      stopTransports()
    }
  }, [applyMessage, clearTimers, defaultReduce, finish, stopTransports])

  const cancel = useCallback(() => {
    stopTransports()
    clearTimers()
    setState((prev) =>
      prev.status === 'running' || prev.status === 'idle'
        ? { ...prev, status: 'cancelled' }
        : prev,
    )
  }, [clearTimers, stopTransports])

  // 卸载时清理所有连接与计时器
  useEffect(() => {
    return () => {
      stopTransports()
      clearTimers()
    }
  }, [stopTransports, clearTimers])

  return { state, start, cancel }
}
