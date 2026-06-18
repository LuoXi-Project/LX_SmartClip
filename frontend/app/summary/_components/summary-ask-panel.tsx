'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Check,
  Copy,
  FileText,
  HelpCircle,
  Loader2,
  MessageCircle,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { MarkdownContent } from '@/components/ui/markdown-content'
import {
  summaryApi,
  type SummaryAskMessage,
  type SummaryAskSource,
  type Video,
} from '@/lib/api'
import { readSSE } from '@/lib/stream'

type ChatMessage = SummaryAskMessage & { id: string; thinking?: boolean }

function generateId() {
  return Math.random().toString(36).slice(2)
}

const SOURCE_OPTIONS: { id: SummaryAskSource; label: string; icon: typeof FileText; desc: string }[] = [
  { id: 'note', label: '笔记', icon: FileText, desc: '基于视频笔记作答' },
  { id: 'outline', label: '大纲', icon: BookOpen, desc: '基于智能大纲作答' },
  { id: 'both', label: '综合', icon: Sparkles, desc: '同时参考笔记与大纲' },
]

const SUGGESTED_BY_SOURCE: Record<SummaryAskSource, string[]> = {
  note: [
    '这篇视频的核心观点是什么？',
    '有哪些关键时间节点值得回看？',
    '用三句话概括视频内容',
    '笔记里提到了哪些重要概念？',
  ],
  outline: [
    '视频分为哪几个主要话题？',
    '哪个片段精彩度最高，为什么？',
    '第一个话题讲了什么？',
    '按时间线梳理视频结构',
  ],
  both: [
    '对比笔记和大纲，有没有遗漏的重点？',
    '视频的整体结构是怎样的？',
    '帮我找一下关于「XXX」的内容',
    '哪些部分适合二次剪辑引用？',
  ],
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-white/10 text-slate-400 hover:text-slate-200"
      title="复制"
    >
      {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  )
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-2.5 group ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold mt-0.5 ${
          isUser
            ? 'bg-gradient-to-br from-indigo-500 to-indigo-600 text-white'
            : 'bg-gradient-to-br from-emerald-600 to-teal-700 text-white'
        }`}
      >
        {isUser ? '我' : <Sparkles className="w-3.5 h-3.5" />}
      </div>
      <div className={`relative max-w-[88%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div
          className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed break-words ${
            isUser
              ? 'bg-indigo-600 text-white rounded-tr-sm whitespace-pre-wrap'
              : 'bg-[#1a2233] text-slate-200 border border-slate-700/60 rounded-tl-sm'
          }`}
        >
          {msg.thinking ? (
            <span className="flex items-center gap-2 text-slate-400 italic text-xs">
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
              正在查阅资料…
            </span>
          ) : isUser ? (
            msg.content
          ) : (
            <MarkdownContent>{msg.content}</MarkdownContent>
          )}
        </div>
        {!isUser && !msg.thinking && msg.content && (
          <div className="flex justify-start pl-1">
            <CopyButton text={msg.content} />
          </div>
        )}
      </div>
    </div>
  )
}

interface SummaryAskPanelProps {
  videoId: string
  selectedVideo: Video | null
  hasNote: boolean
  hasOutline: boolean
  onRefreshOutline?: () => void
}

export function SummaryAskPanel({
  videoId,
  selectedVideo,
  hasNote,
  hasOutline,
}: SummaryAskPanelProps) {
  const [source, setSource] = useState<SummaryAskSource>('both')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setMessages([])
    setError(null)
    setInput('')
  }, [videoId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [input])

  const sourceReady = useMemo(() => {
    if (source === 'note') return hasNote
    if (source === 'outline') return hasOutline
    return hasNote || hasOutline
  }, [source, hasNote, hasOutline])

  const suggested = SUGGESTED_BY_SOURCE[source]

  const sendQuestion = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || streaming || !videoId || !sourceReady) return
      setInput('')
      setError(null)

      const userMsg: ChatMessage = { id: generateId(), role: 'user', content: question }
      const asstId = generateId()
      const thinkingMsg: ChatMessage = { id: asstId, role: 'assistant', content: '', thinking: true }

      const history: SummaryAskMessage[] = messages
        .filter((m) => !m.thinking && m.content)
        .map((m) => ({ role: m.role, content: m.content }))

      setMessages((prev) => [...prev, userMsg, thinkingMsg])
      setStreaming(true)

      const ctrl = new AbortController()
      abortRef.current = ctrl

      try {
        const res = await summaryApi.askStream(videoId, { question, source, history })

        let accumulated = ''
        let firstChunk = true
        // 用对象持有错误，避免 TS 把闭包内的赋值在 await 后收窄为 null
        const failure = { err: null as Error | null }

        await readSSE(res, {
          onEvent: (_event, data) => {
            if (data === '[DONE]') return
            const d = data as { type?: string; content?: string; detail?: string }
            if (d.type === 'error') {
              failure.err = new Error(d.detail || '问答失败')
              return
            }
            if (d.type === 'content' && d.content != null) {
              accumulated = d.content
              if (firstChunk) {
                firstChunk = false
                setMessages((prev) =>
                  prev.map((m) => (m.id === asstId ? { ...m, thinking: false, content: accumulated } : m)),
                )
              } else {
                setMessages((prev) =>
                  prev.map((m) => (m.id === asstId ? { ...m, content: accumulated } : m)),
                )
              }
            }
          },
          onError: (err) => {
            failure.err = err
          },
        })

        if (failure.err && failure.err.name !== 'AbortError') throw failure.err

        setMessages((prev) =>
          prev.map((m) =>
            m.id === asstId ? { ...m, thinking: false, content: accumulated || '（无响应）' } : m,
          ),
        )
      } catch (e: unknown) {
        if ((e as Error).name === 'AbortError') {
          setMessages((prev) => prev.filter((m) => m.id !== asstId))
        } else {
          const msg = (e as Error).message || '请求失败'
          setError(msg)
          setMessages((prev) => prev.filter((m) => m.id !== asstId))
        }
      } finally {
        setStreaming(false)
        abortRef.current = null
      }
    },
    [videoId, source, sourceReady, messages, streaming],
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendQuestion(input)
    }
  }

  const clearHistory = () => {
    if (streaming) abortRef.current?.abort()
    setMessages([])
    setError(null)
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-[#0d0f14] flex flex-col min-h-[560px] lg:flex-1 lg:min-h-0">
      {/* Header */}
      <div className="shrink-0 px-4 pt-4 pb-3 border-b border-slate-800/80">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <MessageCircle className="w-4 h-4 text-emerald-400 shrink-0" />
              <h3 className="text-sm font-medium text-slate-100">视频内容问答</h3>
            </div>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              针对已生成的
              <span className="text-slate-400">笔记</span>或
              <span className="text-slate-400">大纲</span>
              提问，查找细节、理解内容、梳理结构——不会编造未记录的信息。
            </p>
            {selectedVideo?.name && (
              <p className="text-[11px] text-slate-600 mt-1 truncate">当前素材：{selectedVideo.name}</p>
            )}
          </div>
          <button
            type="button"
            onClick={clearHistory}
            disabled={messages.length === 0 && !streaming}
            className="shrink-0 p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors disabled:opacity-30"
            title="清空对话"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>

        {/* Source selector */}
        <div className="mt-3 flex flex-wrap gap-2">
          {SOURCE_OPTIONS.map((opt) => {
            const Icon = opt.icon
            const disabled =
              (opt.id === 'note' && !hasNote) ||
              (opt.id === 'outline' && !hasOutline) ||
              (opt.id === 'both' && !hasNote && !hasOutline)
            const active = source === opt.id
            return (
              <button
                key={opt.id}
                type="button"
                disabled={disabled}
                onClick={() => setSource(opt.id)}
                title={disabled ? '暂无对应资料' : opt.desc}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                  active
                    ? 'bg-emerald-600/20 border-emerald-500/50 text-emerald-200'
                    : disabled
                      ? 'border-slate-800 text-slate-600 cursor-not-allowed'
                      : 'border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {opt.label}
              </button>
            )
          })}
        </div>

        {/* Availability badges */}
        <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${
              hasNote ? 'border-indigo-800/50 text-indigo-300 bg-indigo-950/40' : 'border-slate-800 text-slate-600'
            }`}
          >
            <FileText className="w-3 h-3" />
            笔记 {hasNote ? '已就绪' : '未生成'}
          </span>
          <span
            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border ${
              hasOutline ? 'border-violet-800/50 text-violet-300 bg-violet-950/40' : 'border-slate-800 text-slate-600'
            }`}
          >
            <BookOpen className="w-3 h-3" />
            大纲 {hasOutline ? '已就绪' : '未生成'}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0"
        style={{ scrollbarWidth: 'thin', scrollbarColor: '#334155 transparent' }}
      >
        {!videoId ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 py-12 text-center">
            <HelpCircle className="w-10 h-10 text-slate-700" />
            <p className="text-sm text-slate-500">请先在左侧选择视频素材</p>
          </div>
        ) : !sourceReady ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 py-10 text-center max-w-sm mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-slate-800/60 border border-slate-700 flex items-center justify-center">
              <MessageCircle className="w-6 h-6 text-slate-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-300">还没有可问答的资料</p>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                请切换到「视频笔记」生成笔记，或切换到「智能大纲」生成大纲后，即可在此提问。
              </p>
            </div>
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-6">
            <div className="text-center max-w-md">
              <p className="text-sm text-slate-300 font-medium">可以试着问：</p>
              <p className="text-xs text-slate-500 mt-1">
                回答仅基于
                {source === 'note' ? '笔记' : source === 'outline' ? '大纲' : '笔记 + 大纲'}
                ，适合查找、理解、对比类问题
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
              {suggested.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => sendQuestion(q)}
                  className="text-left text-xs text-slate-400 hover:text-slate-200 bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-600 rounded-lg px-3 py-2.5 transition-all"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}

        {error && (
          <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="shrink-0 px-3 pb-3 pt-2 border-t border-slate-800/80">
        <div
          className={`flex items-end gap-2 bg-slate-950 border rounded-xl px-3 py-2 transition-colors ${
            sourceReady ? 'border-slate-700/60 focus-within:border-emerald-500/40' : 'border-slate-800 opacity-60'
          }`}
        >
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              !videoId
                ? '请先选择视频…'
                : !sourceReady
                  ? '请先生成笔记或大纲…'
                  : '输入问题，例如：第三段讲了什么？有哪些关键时间点？'
            }
            rows={1}
            disabled={streaming || !videoId || !sourceReady}
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 resize-none outline-none leading-relaxed disabled:opacity-60"
            style={{ minHeight: '24px', maxHeight: '120px' }}
          />
          {streaming ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="flex-shrink-0 p-1.5 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors text-xs font-medium"
            >
              停止
            </button>
          ) : (
            <button
              type="button"
              onClick={() => sendQuestion(input)}
              disabled={!input.trim() || !sourceReady}
              className="flex-shrink-0 p-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {streaming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          )}
        </div>
        <div className="text-[10px] text-slate-600 mt-1.5 pl-1 flex justify-between">
          <span>Enter 发送 · Shift+Enter 换行</span>
          <span className="text-slate-700">仅依据已生成资料，不访问原视频</span>
        </div>
      </div>
    </div>
  )
}
