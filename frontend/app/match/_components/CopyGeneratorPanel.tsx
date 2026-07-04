'use client'

import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle, Check, ChevronDown, ChevronUp,
  ClipboardCopy, Loader2, Sparkles, Wand2, RefreshCw, X,
} from 'lucide-react'
import { copyGenApi } from '@/lib/api'
import { readSSE } from '@/lib/stream'
import { VoiceInputControl } from '@/components/ui/voice-input'

interface CopyTemplate { id: string; label: string; emoji: string; prompt: string; style: string }

const TEMPLATES: CopyTemplate[] = [
  { id: 'product', label: '产品推广', emoji: '🛍️', prompt: '为这段视频撰写产品推广文案，突出产品亮点和卖点，激发购买欲望', style: '活泼有力' },
  { id: 'vlog', label: 'Vlog 旁白', emoji: '🎬', prompt: '以第一人称旁白方式，为这段 Vlog 写出自然流畅的叙事文案', style: '轻松日常' },
  { id: 'documentary', label: '纪录片解说', emoji: '🌍', prompt: '以专业纪录片解说员口吻，撰写深度解说文案，引发观众思考', style: '沉稳专业' },
  { id: 'hook', label: '开头钩子', emoji: '🪝', prompt: '只写视频开头3秒的抓眼球文案，让观众忍不住继续看下去', style: '强烈悬念' },
  { id: 'emotion', label: '情感共鸣', emoji: '❤️', prompt: '撰写能引发情感共鸣的文案，触动观众内心，让人产生代入感', style: '温暖感人' },
  { id: 'tutorial', label: '教程讲解', emoji: '📚', prompt: '以清晰易懂的教程风格撰写文案，分步骤说明，帮助观众理解流程', style: '清晰简洁' },
]

interface Props { selectedVideoIds: string[]; onApply: (segments: string[]) => void }
interface PropsWithReplicaGuide extends Props {
  /** 复刻模板向导的“提示词约束”，在用户未填创作诉求时自动注入 */
  replicaTemplateGuide?: string
}

function TemplatesGrid({ templates, active, onSelect }: { templates: CopyTemplate[]; active: string | null; onSelect: (t: CopyTemplate) => void }) {
  return (
    <div className="pt-4 space-y-2">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">快速模板</p>
      <div className="grid grid-cols-3 gap-2">
        {templates.map((t) => (
          <button key={t.id} onClick={() => onSelect(t)}
            className={`flex flex-col items-start gap-0.5 px-3 py-2.5 rounded-xl border text-left transition-all ${
              active === t.id ? 'border-indigo-500 bg-indigo-500/15 text-indigo-200' : 'border-slate-700 bg-slate-800/40 text-slate-400 hover:border-slate-600 hover:text-slate-300'
            }`}>
            <span className="text-base leading-none">{t.emoji}</span>
            <span className="text-[11px] font-medium leading-tight mt-1">{t.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function PromptArea({
  prompt,
  onChange,
  disabled,
}: {
  prompt: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">创作诉求</label>
      <div className="relative">
        <textarea
          value={prompt}
          onChange={(e) => onChange(e.target.value)}
          placeholder="描述你想要的文案风格、主题或用途，例如：为这个旅行视频写一段有代入感的旁白..."
          rows={3}
          disabled={disabled}
          className="w-full rounded-xl bg-slate-900/70 border border-slate-700 px-4 py-3 pr-14 pt-11 text-sm text-slate-200 outline-none focus:border-indigo-500 placeholder-slate-600 resize-none transition-colors disabled:opacity-50"
        />
        <div className="absolute right-2 top-2 z-10">
          <VoiceInputControl
            intent="这是「AI 智能文案生成」的创作诉求输入框：把口述整理成给模型用的中文说明（风格、主题、用途、受众、语气等），不要输出引号或 Markdown。"
            value={prompt}
            onTextChange={onChange}
            merge="append"
            disabled={disabled}
          />
        </div>
      </div>
    </div>
  )
}

function StyleAndSegs({
  style,
  maxSegs,
  onStyleChange,
  onMaxSegsChange,
  disabled,
}: {
  style: string
  maxSegs: number
  onStyleChange: (v: string) => void
  onMaxSegsChange: (v: number) => void
  disabled?: boolean
}) {
  return (
    <div className="flex gap-3">
      <div className="flex-1 space-y-1.5">
        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">风格</label>
        <div className="relative">
          <input
            type="text"
            value={style}
            onChange={(e) => onStyleChange(e.target.value)}
            placeholder="活泼 / 专业 / 温暖..."
            disabled={disabled}
            className="w-full rounded-xl bg-slate-900/70 border border-slate-700 pl-3 pr-24 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500 placeholder-slate-600 transition-colors disabled:opacity-50"
          />
          <div className="absolute right-1.5 top-1/2 -translate-y-1/2">
            <VoiceInputControl
              intent="这是文案生成里的「风格」短描述：把口述整理成几个词或短语（如 活泼、专业、温暖），不要长段落。"
              value={style}
              onTextChange={onStyleChange}
              merge="replace"
              disabled={disabled}
              className="relative"
            />
          </div>
        </div>
      </div>
      <div className="w-28 space-y-1.5">
        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">段落数</label>
        <input
          type="number"
          min={1}
          max={1000}
          value={maxSegs}
          disabled={disabled}
          onChange={(e) => onMaxSegsChange(Math.max(1, Math.min(1000, +e.target.value)))}
          className="w-full rounded-xl bg-slate-900/70 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-500 text-center transition-colors disabled:opacity-50"
        />
      </div>
    </div>
  )
}

function NoVideoWarning() {
  return (
    <div className="flex items-center gap-2 rounded-xl bg-amber-500/5 border border-amber-500/20 px-3 py-2.5">
      <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
      <p className="text-xs text-amber-300">请先在上方选择至少一个视频，AI 将读取该视频的台词和画面描述来生成文案</p>
    </div>
  )
}

function GenerateBar({ generating, disabled, onGenerate, onAbort }: { generating: boolean; disabled: boolean; onGenerate: () => void; onAbort: () => void }) {
  return (
    <div className="flex items-center gap-3">
      {generating
        ? <button onClick={onAbort} className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 text-red-300 text-sm font-medium transition-colors"><X className="w-4 h-4" />停止生成</button>
        : <button onClick={onGenerate} disabled={disabled} className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors shadow-lg shadow-indigo-900/30"><Sparkles className="w-4 h-4" />AI 生成文案</button>}
      {generating && <div className="flex items-center gap-2 text-xs text-indigo-300"><Loader2 className="w-3.5 h-3.5 animate-spin" />正在根据视频内容创作中...</div>}
    </div>
  )
}

function ErrorBar({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-red-500/10 border border-red-500/20 px-3 py-2.5">
      <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
      <p className="text-xs text-red-300">{message}</p>
    </div>
  )
}

function OutputSection({ generated, generating, copied, outputRef, onCopy, onRegenerate, onApply }: {
  generated: string; generating: boolean; copied: boolean
  outputRef: React.RefObject<HTMLDivElement>
  onCopy: () => void; onRegenerate: () => void; onApply: () => void
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          生成结果{generating && <span className="ml-2 text-indigo-400 normal-case animate-pulse">◍</span>}
        </p>
        {generated && !generating && (
          <div className="flex items-center gap-3">
            <button onClick={onCopy} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors">
              {copied ? <><Check className="w-3 h-3 text-emerald-400" />已复制</> : <><ClipboardCopy className="w-3 h-3" />复制</>}
            </button>
            <button onClick={onRegenerate} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-slate-300 transition-colors">
              <RefreshCw className="w-3 h-3" />重新生成
            </button>
          </div>
        )}
      </div>
      <div ref={outputRef} className="max-h-64 overflow-y-auto styled-scrollbar rounded-xl bg-slate-950/60 border border-slate-700/60 px-4 py-3 text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
        {generated || <span className="text-slate-600 animate-pulse">思考中...</span>}
      </div>
      {generated && !generating && (
        <button onClick={onApply} className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold transition-colors shadow-lg shadow-emerald-900/30">
          <Check className="w-4 h-4" />将文案填入段落 · 开始匹配
        </button>
      )}
    </div>
  )
}

export function CopyGeneratorPanel({ selectedVideoIds, onApply, replicaTemplateGuide }: PropsWithReplicaGuide) {
  const [open, setOpen] = useState(true)
  const [prompt, setPrompt] = useState('')
  const [style, setStyle] = useState('')
  const [maxSegs, setMaxSegs] = useState(5)
  const [activeTemplate, setActiveTemplate] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const outputRef = useRef<HTMLDivElement>(null)
  const noVideos = selectedVideoIds.length === 0

  useEffect(() => {
    if (!replicaTemplateGuide?.trim()) return
    // 只在用户尚未输入时自动注入，避免覆盖用户手工编辑
    if (!prompt.trim()) {
      setPrompt(replicaTemplateGuide.trim())
    }
  }, [replicaTemplateGuide]) // eslint-disable-line react-hooks/exhaustive-deps

  function applyTemplate(t: CopyTemplate) {
    setActiveTemplate(t.id)
    // 快速模板应保持“所见即所得”，不混入复刻约束前缀，避免用户误判模板内容。
    setPrompt(t.prompt)
    setStyle(t.style)
  }

  async function generate() {
    if (!prompt.trim() || generating) return
    setGenerating(true); setGenerated(''); setError(''); setCopied(false)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    let accumulated = ''
    // 用对象持有错误，避免 TS 把闭包内的赋值在 await 后收窄为 null
    const failure = { err: null as Error | null }
    try {
      const res = await copyGenApi.generateStream({
        video_ids: selectedVideoIds, user_prompt: prompt.trim(),
        style: style.trim() || undefined, max_segments: maxSegs, stream: true,
      })
      await readSSE(res, {
        onEvent: (_event, data) => {
          if (data === '[DONE]') return
          const json = data as {
            error?: string
            detail?: string
            choices?: Array<{ delta?: { content?: string } }>
            content?: string
          }
          if (json?.error) {
            failure.err = new Error(json.detail || json.error)
            return
          }
          const delta = json?.choices?.[0]?.delta?.content ?? json?.content
          if (delta) {
            accumulated += delta
            setGenerated(accumulated)
            setTimeout(() => outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight, behavior: 'smooth' }), 0)
          }
        },
        onError: (err) => {
          failure.err = err
        },
      }, ctrl.signal)
      if (failure.err && failure.err.name !== 'AbortError') throw failure.err
    } catch (e: unknown) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message || '生成失败，请重试')
    } finally {
      setGenerating(false); abortRef.current = null
    }
  }

  function abort() { abortRef.current?.abort(); setGenerating(false) }

  function handleApply() {
    if (!generated.trim()) return
    let parts = generated.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = generated.split(/(?<=[。！？!?])\s*/).map((p) => p.trim()).filter(Boolean)
    if (parts.length <= 1) parts = generated.split(/\n/).map((p) => p.trim()).filter(Boolean)
    if (parts.length === 0) return
    onApply(parts)
  }

  async function copyText() {
    if (!generated) return
    await navigator.clipboard.writeText(generated)
    setCopied(true); setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="rounded-2xl border border-indigo-500/20 bg-gradient-to-b from-indigo-950/30 to-slate-900/40 overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-3 px-5 py-4 hover:bg-white/[0.02] transition-colors">
        <div className="w-7 h-7 rounded-xl bg-indigo-500/20 flex items-center justify-center shrink-0">
          <Wand2 className="w-4 h-4 text-indigo-400" />
        </div>
        <div className="text-left flex-1">
          <p className="text-sm font-semibold text-slate-100">AI 智能文案生成</p>
          <p className="text-[11px] text-slate-500 mt-0.5">基于选中视频的台词与画面描述自动创作</p>
        </div>
        <div className="flex items-center gap-2">
          {noVideos && <span className="text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-full px-2 py-0.5">请先选择视频</span>}
          {!noVideos && <span className="text-[10px] text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 rounded-full px-2 py-0.5">{selectedVideoIds.length} 个视频</span>}
          {open ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
        </div>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-4 border-t border-slate-800/60">
          <TemplatesGrid templates={TEMPLATES} active={activeTemplate} onSelect={applyTemplate} />
          <PromptArea
            prompt={prompt}
            onChange={(v) => {
              setPrompt(v)
              setActiveTemplate(null)
            }}
            disabled={generating}
          />
          <StyleAndSegs
            style={style}
            maxSegs={maxSegs}
            onStyleChange={setStyle}
            onMaxSegsChange={setMaxSegs}
            disabled={generating}
          />
          {noVideos && <NoVideoWarning />}
          <GenerateBar generating={generating} disabled={!prompt.trim() || noVideos} onGenerate={generate} onAbort={abort} />
          {error && <ErrorBar message={error} />}
          {(generated || generating) && (
            <OutputSection
              generated={generated} generating={generating} copied={copied}
              outputRef={outputRef as React.RefObject<HTMLDivElement>}
              onCopy={copyText} onRegenerate={generate} onApply={handleApply}
            />
          )}
        </div>
      )}
    </div>
  )
}
