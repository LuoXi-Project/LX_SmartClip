'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { X, Send, Trash2, Sparkles, ChevronDown, Copy, Check } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking?: boolean
}

function generateId() {
  return Math.random().toString(36).slice(2)
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
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

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-2.5 group ${
      isUser ? 'flex-row-reverse' : 'flex-row'
    }`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold mt-0.5 ${
        isUser
          ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white'
          : 'bg-gradient-to-br from-violet-600 to-purple-700 text-white'
      }`}>
        {isUser ? 'U' : <Sparkles className="w-3.5 h-3.5" />}
      </div>

      {/* Bubble */}
      <div className={`relative max-w-[82%] ${
        isUser ? 'items-end' : 'items-start'
      } flex flex-col gap-1`}>
        <div className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words ${
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-[#1e2535] text-slate-200 border border-slate-700/60 rounded-tl-sm'
        }`}>
          {msg.thinking ? (
            <span className="flex items-center gap-2 text-slate-400 italic text-xs">
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
              思考中
            </span>
          ) : msg.content}
        </div>
        {!isUser && !msg.thinking && (
          <div className="flex justify-start pl-1">
            <CopyButton text={msg.content} />
          </div>
        )}
      </div>
    </div>
  )
}

export default function AIChatPanel() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }, [input])

  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    setError(null)

    const userMsg: Message = { id: generateId(), role: 'user', content: text }
    const asstId = generateId()
    const thinkingMsg: Message = { id: asstId, role: 'assistant', content: '', thinking: true }

    setMessages(prev => [...prev, userMsg, thinkingMsg])
    setStreaming(true)

    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }))
    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await fetch(`${API_BASE}/api/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history, stream: true }),
        signal: ctrl.signal,
      })

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(errJson.detail || `HTTP ${res.status}`)
      }

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''

      // replace thinking placeholder immediately on first chunk
      let firstChunk = true

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })

        // parse SSE lines
        const lines = chunk.split('\n')
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = line.slice(6).trim()
          if (data === '[DONE]') continue
          try {
            const json = JSON.parse(data)
            const delta = json?.choices?.[0]?.delta?.content
            if (delta) {
              accumulated += delta
              if (firstChunk) {
                firstChunk = false
                setMessages(prev =>
                  prev.map(m =>
                    m.id === asstId ? { ...m, thinking: false, content: accumulated } : m
                  )
                )
              } else {
                setMessages(prev =>
                  prev.map(m =>
                    m.id === asstId ? { ...m, content: accumulated } : m
                  )
                )
              }
            }
          } catch { /* skip parse errors */ }
        }
      }

      // ensure thinking is cleared even if no content came through
      setMessages(prev =>
        prev.map(m =>
          m.id === asstId ? { ...m, thinking: false, content: accumulated || '（无响应）' } : m
        )
      )
    } catch (e: unknown) {
      if ((e as Error).name === 'AbortError') {
        setMessages(prev => prev.filter(m => m.id !== asstId))
      } else {
        const msg = (e as Error).message || '请求失败'
        setError(msg)
        setMessages(prev => prev.filter(m => m.id !== asstId))
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }, [input, messages, streaming])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const clearHistory = () => {
    if (streaming) abortRef.current?.abort()
    setMessages([])
    setError(null)
  }

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        aria-label="AI 助手"
        className={`
          fixed bottom-6 left-6 z-50
          w-12 h-12 rounded-full shadow-2xl
          bg-gradient-to-br from-violet-600 to-blue-600
          flex items-center justify-center
          transition-all duration-300
          hover:scale-110 hover:shadow-violet-500/40
          active:scale-95
          ${open ? 'rotate-12 shadow-violet-500/50' : ''}
        `}
      >
        {open
          ? <ChevronDown className="w-5 h-5 text-white" />
          : <Sparkles className="w-5 h-5 text-white" />}
      </button>

      {/* Panel */}
      <div
        className={`
          fixed bottom-24 left-6 z-50
          w-[380px] max-h-[580px]
          flex flex-col
          rounded-2xl overflow-hidden
          border border-slate-700/70
          bg-[#0f1421]/95 backdrop-blur-xl
          shadow-2xl shadow-black/60
          transition-all duration-300 origin-bottom-left
          ${
            open
              ? 'opacity-100 scale-100 translate-y-0 pointer-events-auto'
              : 'opacity-0 scale-95 translate-y-3 pointer-events-none'
          }
        `}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60 bg-[#141929]">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center">
              <Sparkles className="w-3.5 h-3.5 text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-100 leading-tight">AI 创作助手</div>
              <div className="text-[10px] text-slate-500">基于配置的 LLM 模型</div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={clearHistory}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors"
              title="清空对话"
            >
              <Trash2 className="w-4 h-4" />
            </button>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-white/5 transition-colors"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0"
          style={{ scrollbarWidth: 'thin', scrollbarColor: '#334155 transparent' }}
        >
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-3 py-8">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-600/20 to-blue-600/20 border border-violet-500/20 flex items-center justify-center">
                <Sparkles className="w-6 h-6 text-violet-400" />
              </div>
              <div className="text-center">
                <div className="text-sm font-medium text-slate-300 mb-1">AI 创作助手</div>
                <div className="text-xs text-slate-500 leading-relaxed max-w-[220px]">
                  可以帮你生成文案、撰写旁白、策划脚本等内容
                </div>
              </div>
              <div className="flex flex-col gap-2 w-full mt-2">
                {['帮我写一段产品介绍文案', '生成 30 秒短视频脚本', '优化这段解说词：'].map(s => (
                  <button
                    key={s}
                    onClick={() => { setInput(s); textareaRef.current?.focus() }}
                    className="text-left text-xs text-slate-400 hover:text-slate-200 bg-slate-800/60 hover:bg-slate-700/60 border border-slate-700/50 hover:border-slate-600 rounded-lg px-3 py-2 transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}

          {error && (
            <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
              ⚠ {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-3 pb-3 pt-2 border-t border-slate-700/60 bg-[#0f1421]">
          <div className="flex items-end gap-2 bg-[#1a2133] border border-slate-700/60 rounded-xl px-3 py-2 focus-within:border-violet-500/50 transition-colors">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息，Shift+Enter 换行…"
              rows={1}
              disabled={streaming}
              className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-500 resize-none outline-none leading-relaxed disabled:opacity-60"
              style={{ minHeight: '24px', maxHeight: '120px' }}
            />
            {streaming ? (
              <button
                onClick={() => abortRef.current?.abort()}
                className="flex-shrink-0 p-1.5 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 transition-colors text-xs font-medium"
              >
                停止
              </button>
            ) : (
              <button
                onClick={sendMessage}
                disabled={!input.trim()}
                className="flex-shrink-0 p-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className="text-[10px] text-slate-600 mt-1.5 pl-1">Enter 发送 · Shift+Enter 换行</div>
        </div>
      </div>
    </>
  )
}
