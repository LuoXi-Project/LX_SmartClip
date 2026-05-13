'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { ChevronDown, Loader2, Mic, Sparkles, Square } from 'lucide-react'
import { formatFastApiDetail, voiceInputApi } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'

export type VoiceInputMerge = 'replace' | 'append'

type Pipeline = 'asr' | 'asr_llm'

function mergeVoiceText(prev: string, incoming: string, merge: VoiceInputMerge): string {
  const t = incoming.trim()
  if (!t) return prev
  if (merge === 'replace') return t
  const p = prev.trimEnd()
  if (!p) return t
  return `${p}\n${t}`
}

function pickRecorderMime(): { mime: string; ext: string } {
  const cands = [
    { mime: 'audio/webm;codecs=opus', ext: 'webm' },
    { mime: 'audio/webm', ext: 'webm' },
    { mime: 'audio/mp4', ext: 'm4a' },
  ]
  for (const c of cands) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(c.mime)) {
      return c
    }
  }
  return { mime: '', ext: 'webm' }
}

export type VoiceInputControlProps = {
  /** 告诉 LLM 这个输入框是干什么的（搜索框 / 成片提示词 / 日志关键字等） */
  intent: string
  value: string
  onTextChange: (next: string) => void
  merge?: VoiceInputMerge
  disabled?: boolean
  /** 外层定位 class，例如 absolute right-2 top-1/2 -translate-y-1/2 z-10 */
  className?: string
  /** 控件尺寸 */
  size?: 'sm' | 'md'
}

/**
 * 语音输入：录音 → `/api/voice/transcribe`；可选 `/api/voice/refine` 用 LLM 按意图整理后再填入。
 * 放在 `relative` 容器内，用 `className` 贴到输入框角落，并给输入框预留右侧 padding 以免重叠。
 */
export function VoiceInputControl({
  intent,
  value,
  onTextChange,
  merge = 'replace',
  disabled = false,
  className,
  size = 'sm',
}: VoiceInputControlProps) {
  const toast = useToast()
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [pipeline, setPipeline] = useState<Pipeline>('asr')
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuStyle, setMenuStyle] = useState<CSSProperties>({})

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  /** 整块控件（录音 + 下拉里），用于点击外部关闭 */
  const rootRef = useRef<HTMLDivElement | null>(null)
  /** 下拉锚点：用于 fixed 定位，避免祖先 overflow-hidden 裁切 */
  const menuAnchorRef = useRef<HTMLButtonElement | null>(null)
  const menuPortalRef = useRef<HTMLDivElement | null>(null)

  const updateMenuPosition = useCallback(() => {
    const btn = menuAnchorRef.current
    if (!btn) return
    const rect = btn.getBoundingClientRect()
    const mw = 168
    const mh = 80
    const pad = 6
    let top = rect.top - mh - pad
    if (top < 8) top = rect.bottom + pad
    let left = rect.right - mw
    left = Math.min(Math.max(8, left), window.innerWidth - mw - 8)
    top = Math.min(top, window.innerHeight - mh - 8)
    setMenuStyle({
      position: 'fixed',
      top,
      left,
      width: mw,
      zIndex: 9999,
    })
  }, [])

  useLayoutEffect(() => {
    if (!menuOpen) return
    updateMenuPosition()
  }, [menuOpen, updateMenuPosition])

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => {
      const t = e.target as Node
      if (rootRef.current?.contains(t)) return
      if (menuPortalRef.current?.contains(t)) return
      setMenuOpen(false)
    }
    const onReposition = () => updateMenuPosition()
    document.addEventListener('mousedown', close)
    window.addEventListener('scroll', onReposition, true)
    window.addEventListener('resize', onReposition)
    return () => {
      document.removeEventListener('mousedown', close)
      window.removeEventListener('scroll', onReposition, true)
      window.removeEventListener('resize', onReposition)
    }
  }, [menuOpen, updateMenuPosition])

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
  }, [])

  const processBlob = useCallback(
    async (blob: Blob, filename: string) => {
      setBusy(true)
      try {
        const tr = await voiceInputApi.transcribe(blob, filename)
        const raw = (tr.text || '').trim()
        if (!raw) {
          toast.error('未识别到有效语音内容')
          return
        }
        let finalText = raw
        if (pipeline === 'asr_llm') {
          const refined = await voiceInputApi.refine({
            transcript: raw,
            intent,
            current_value: value,
            mode: merge,
          })
          finalText = (refined.text || '').trim()
          if (!finalText) {
            toast.error('LLM 返回为空')
            return
          }
        }
        onTextChange(mergeVoiceText(value, finalText, merge))
        toast.success(pipeline === 'asr_llm' ? '已填入（LLM 整理）' : '已填入语音识别结果')
      } catch (e) {
        toast.error(formatFastApiDetail(e))
      } finally {
        setBusy(false)
      }
    },
    [intent, merge, onTextChange, pipeline, toast, value],
  )

  const stopRecording = useCallback(() => {
    const mr = mediaRecorderRef.current
    if (!mr || mr.state === 'inactive') {
      setRecording(false)
      return
    }
    mr.onstop = () => {
      stopTracks()
      const { mime, ext } = pickRecorderMime()
      const type = mr.mimeType || mime || 'audio/webm'
      const blob = new Blob(chunksRef.current, { type })
      chunksRef.current = []
      mediaRecorderRef.current = null
      setRecording(false)
      void processBlob(blob, `recording.${ext}`)
    }
    mr.stop()
  }, [processBlob, stopTracks])

  const startRecording = useCallback(async () => {
    if (disabled || busy) return
    if (!navigator.mediaDevices?.getUserMedia) {
      toast.error('当前环境不支持麦克风录音')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []
      const { mime } = pickRecorderMime()
      const mr = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream)
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      mediaRecorderRef.current = mr
      mr.start(100)
      setRecording(true)
    } catch (e) {
      stopTracks()
      toast.error(e instanceof Error ? e.message : '无法打开麦克风')
    }
  }, [busy, disabled, stopTracks, toast])

  const toggleRecord = () => {
    if (recording) stopRecording()
    else void startRecording()
  }

  const btn = size === 'md' ? 'h-9 w-9' : 'h-8 w-8'
  const icon = size === 'md' ? 'w-4 h-4' : 'w-3.5 h-3.5'

  const menuPanel =
    menuOpen && typeof document !== 'undefined'
      ? createPortal(
          <div
            ref={menuPortalRef}
            style={menuStyle}
            className="rounded-lg border border-slate-700 bg-[#12141c] py-1 shadow-xl text-left"
            role="menu"
          >
            <button
              type="button"
              className={clsx(
                'w-full px-3 py-2 text-[11px] text-left hover:bg-slate-800/80 flex items-center gap-2',
                pipeline === 'asr' && 'text-cyan-300',
              )}
              onClick={() => {
                setPipeline('asr')
                setMenuOpen(false)
              }}
            >
              <Mic className="w-3 h-3 shrink-0 opacity-70" />
              仅语音识别
            </button>
            <button
              type="button"
              className={clsx(
                'w-full px-3 py-2 text-[11px] text-left hover:bg-slate-800/80 flex items-center gap-2',
                pipeline === 'asr_llm' && 'text-violet-300',
              )}
              onClick={() => {
                setPipeline('asr_llm')
                setMenuOpen(false)
              }}
            >
              <Sparkles className="w-3 h-3 shrink-0 opacity-70" />
              识别 + LLM 整理
            </button>
          </div>,
          document.body,
        )
      : null

  return (
    <div className={clsx('inline-flex items-center gap-0.5', className)} ref={rootRef}>
      <button
        type="button"
        disabled={disabled || busy}
        onClick={toggleRecord}
        title={recording ? '停止并识别' : pipeline === 'asr_llm' ? '点击开始录音（结束后走 LLM 整理）' : '点击开始录音（仅语音识别）'}
        className={clsx(
          btn,
          'rounded-lg border flex items-center justify-center transition-colors shrink-0',
          recording
            ? 'border-red-500/60 bg-red-500/15 text-red-300 animate-pulse'
            : 'border-slate-600/80 bg-slate-900/80 text-slate-300 hover:border-cyan-500/50 hover:text-cyan-200',
          (disabled || busy) && 'opacity-40 cursor-not-allowed',
        )}
      >
        {busy ? (
          <Loader2 className={clsx(icon, 'animate-spin')} />
        ) : recording ? (
          <Square className={icon} />
        ) : (
          <Mic
            className={clsx(
              icon,
              pipeline === 'asr_llm' ? 'text-violet-300' : 'text-slate-300',
            )}
          />
        )}
      </button>
      <div className="relative shrink-0">
        <button
          ref={menuAnchorRef}
          type="button"
          disabled={disabled || busy || recording}
          onClick={() => setMenuOpen((v) => !v)}
          title="识别模式"
          className={clsx(
            size === 'md' ? 'h-9 w-7' : 'h-8 w-6',
            'rounded-lg border border-slate-600/80 bg-slate-900/80 text-slate-400 hover:text-slate-200 flex items-center justify-center',
            (disabled || busy || recording) && 'opacity-40 cursor-not-allowed',
          )}
        >
          <ChevronDown className="w-3 h-3" />
        </button>
      </div>
      {menuPanel}
    </div>
  )
}
