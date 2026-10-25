'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft, Sparkles, ListVideo, Mic2, Link2, Clapperboard, Layers, Volume2, Film, Headphones, PenLine, FileVideo } from 'lucide-react'
import clsx from 'clsx'
import type { MatchWorkspaceMode } from './matchModeTypes'

type MatchPageHeaderProps = {
  mode: MatchWorkspaceMode
  onModeChange: (mode: MatchWorkspaceMode) => void
  onOpenVideoResult?: () => void
}

type ModeTabSpec = {
  m: MatchWorkspaceMode
  label: string
  icon: ReactNode | null
  tip: string
  beta?: boolean
}

/**
 * 模式导航 v2：按「用户手里有什么」分组，取代旧版 10 个彩色药丸平铺。
 * 分组语义与用户心智对齐：一句话需求 → 全自动；有文案/配音 → 按文案找画面；
 * 有素材 → 在素材上做加工。视觉统一为中性色 + 单一激活色（indigo）。
 */
const PRIMARY_MODE: ModeTabSpec = {
  m: 'auto',
  label: '自动一键成片',
  icon: <Sparkles className="w-3.5 h-3.5" />,
  tip: '只需一句剪辑诉求：AI 生成方案后自动完成匹配、配音、字幕与成片导出',
  beta: true,
}

const COPY_GROUP: ModeTabSpec[] = [
  {
    m: 'script_stock',
    label: '文案素材成片',
    icon: <Clapperboard className="w-3.5 h-3.5 opacity-80" />,
    tip: '输入文案，自动从在线素材库（Pexels / Pixabay 等）搜索无版权视频并合成成片，无需本地素材',
  },
  {
    m: 'manual',
    label: '手动匹配',
    icon: <PenLine className="w-3.5 h-3.5 opacity-80" />,
    tip: '粘贴文案拆段，逐段检索并勾选素材，自己掌控每一步匹配与配音',
  },
  {
    m: 'audio_match',
    label: '音频匹配素材',
    icon: <Headphones className="w-3.5 h-3.5 opacity-80" />,
    tip: '上传配音音频，按语音识别出的句段自动匹配素材，适合已有旁白的创作',
  },
]

const FOOTAGE_GROUP: ModeTabSpec[] = [
  {
    m: 'voiceover',
    label: '口播快剪',
    icon: <Mic2 className="w-3.5 h-3.5 opacity-80" />,
    tip: '已有口播录音/文案，按台词自动切出口播画面并去掉气口',
  },
  {
    m: 'mix_edit',
    label: '混剪',
    icon: <Layers className="w-3.5 h-3.5 opacity-80" />,
    tip: '多个素材按 AI 方案混合剪辑成一条视频，适合盘点/合集类内容',
  },
  {
    m: 'film_commentary',
    label: '影视解说',
    icon: <Film className="w-3.5 h-3.5 opacity-80" />,
    tip: '上传影视素材与解说文案，自动切分并生成分段解说视频',
    beta: true,
  },
  {
    m: 'video_dub',
    label: '视频配音',
    icon: <Volume2 className="w-3.5 h-3.5 opacity-80" />,
    tip: '为已有视频重新生成配音（TTS）并合成，适合翻译配音或换音色',
  },
  {
    m: 'replica',
    label: '链接复刻',
    icon: <Link2 className="w-3.5 h-3.5 opacity-80" />,
    tip: '粘贴一条参考视频链接，复刻它的剪辑节奏生成同款成片',
  },
]

function ModeTab({ spec, active, onClick }: { spec: ModeTabSpec; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={spec.tip}
      className={clsx(
        'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs transition-colors',
        active
          ? 'bg-indigo-600 text-white'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60',
      )}
    >
      {spec.icon}
      <span className="whitespace-nowrap">{spec.label}</span>
      {spec.beta && (
        <span
          className={clsx(
            'ml-0.5 px-1 py-px rounded text-[9px] leading-tight',
            active ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-500',
          )}
        >
          实验
        </span>
      )}
    </button>
  )
}

function ModeGroup({ label, modes, mode, onModeChange }: {
  label: string
  modes: ModeTabSpec[]
  mode: MatchWorkspaceMode
  onModeChange: (m: MatchWorkspaceMode) => void
}) {
  return (
    <div className="flex items-center gap-1 min-w-0 flex-wrap">
      <span className="px-1 text-[10px] text-slate-500 uppercase tracking-wider select-none shrink-0">{label}</span>
      {modes.map(spec => (
        <ModeTab key={spec.m} spec={spec} active={mode === spec.m} onClick={() => onModeChange(spec.m)} />
      ))}
    </div>
  )
}

export function MatchPageHeader({ mode, onModeChange, onOpenVideoResult }: MatchPageHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-3">
      <div className="flex items-center gap-3 shrink-0">
        <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
          <ArrowLeft className="w-4 h-4" />
          首页
        </Link>
        <div className="w-px h-4 bg-slate-700" />
      </div>
      <div className="flex flex-col gap-2.5 min-w-0 flex-1">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-400 shrink-0" />
          智能剪辑
        </h1>
        <div className="flex flex-col gap-1.5 rounded-xl bg-slate-900/70 border border-slate-700 px-3 py-2.5">
          {/* 主推路径：一句话全自动 */}
          <div className="flex items-center gap-2">
            <ModeTab spec={PRIMARY_MODE} active={mode === PRIMARY_MODE.m} onClick={() => onModeChange(PRIMARY_MODE.m)} />
            <span className="text-[11px] text-slate-500 hidden sm:inline">只要一句诉求，其余交给 AI</span>
          </div>
          <div className="h-px bg-slate-800" />
          {/* 经典路径：按输入分组 */}
          <ModeGroup label="有文案 / 配音" modes={COPY_GROUP} mode={mode} onModeChange={onModeChange} />
          <ModeGroup label="有素材" modes={FOOTAGE_GROUP} mode={mode} onModeChange={onModeChange} />
          <div className="flex items-center gap-1.5 text-[10px] text-slate-600 pl-1">
            <FileVideo className="w-3 h-3" />
            「有素材」模式需要先在素材库完成切分与识别
          </div>
        </div>
      </div>
      {!!onOpenVideoResult && (
        <button
          type="button"
          onClick={onOpenVideoResult}
          className="sm:ml-auto flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-800 bg-slate-900/30 hover:border-slate-600 text-sm text-slate-200 transition-colors shrink-0"
        >
          <ListVideo className="w-4 h-4 text-indigo-300" />
          查看处理结果
        </button>
      )}
    </div>
  )
}
