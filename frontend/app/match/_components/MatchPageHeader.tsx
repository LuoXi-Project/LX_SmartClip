'use client'

import type { ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft, Sparkles, ListVideo, Mic2, Link2, Clapperboard, Layers, Volume2, Film, Headphones } from 'lucide-react'
import type { MatchWorkspaceMode } from './matchModeTypes'

type MatchPageHeaderProps = {
  mode: MatchWorkspaceMode
  onModeChange: (mode: MatchWorkspaceMode) => void
  onOpenVideoResult?: () => void
}

export function MatchPageHeader({ mode, onModeChange, onOpenVideoResult }: MatchPageHeaderProps) {
  const tab = (m: MatchWorkspaceMode, label: string, icon: ReactNode | null, activeClass: string, tip?: string) => (
    <button
      type="button"
      onClick={() => onModeChange(m)}
      title={tip}
      className={`inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-full text-xs transition-colors ${
        mode === m ? activeClass : 'text-slate-400 hover:text-slate-200'
      }`}
    >
      {icon}
      <span className="whitespace-nowrap">{label}</span>
    </button>
  )

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-3">
      <div className="flex items-center gap-3 shrink-0">
        <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
          <ArrowLeft className="w-4 h-4" />
          首页
        </Link>
        <div className="w-px h-4 bg-slate-700" />
      </div>
      <div className="flex flex-col gap-2 min-w-0 flex-1">
        <h1 className="text-xl font-semibold flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-400 shrink-0" />
          文案匹配 · 配音 · 成片
        </h1>
        <div className="inline-flex flex-col gap-1.5 rounded-xl bg-slate-900/70 border border-slate-700 px-1.5 py-1.5 text-xs">
          <p className="px-2 text-[10px] text-slate-500 uppercase tracking-wider">工作区</p>
          <div className="flex flex-wrap gap-1">
            {tab('manual', '手动匹配', null, 'bg-indigo-600 text-white', '粘贴文案拆段，逐段检索并勾选素材，自己掌控每一步匹配与配音')}
            {tab(
              'audio_match',
              '音频匹配素材',
              <Headphones className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-rose-600 text-white',
              '上传配音音频，按语音识别出的句段自动匹配素材，适合已有旁白的创作',
            )}
            {tab(
              'replica',
              '链接复刻',
              <Link2 className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-amber-500 text-slate-900',
              '粘贴一条参考视频链接，复刻它的剪辑节奏生成同款成片',
            )}
            {tab(
              'script_stock',
              '文案素材成片',
              <Clapperboard className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-sky-600 text-white',
              '输入文案，自动从在线素材库（Pexels / Pixabay 等）搜索无版权视频并合成成片，无需本地素材',
            )}
            {tab(
              'film_commentary',
              '影视解说（实验）',
              <Film className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-violet-600 text-white',
              '上传影视素材与解说文案，自动切分并生成分段解说视频',
            )}
            {tab(
              'auto',
              '自动一键成片（实验）',
              null,
              'bg-emerald-500 text-slate-900',
              '只需一句剪辑诉求：AI 生成方案后自动完成匹配、配音、字幕与成片导出',
            )}
            {tab(
              'voiceover',
              '口播快剪',
              <Mic2 className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-violet-600 text-white',
              '已有口播录音/文案，按台词自动切出口播画面并去掉气口',
            )}
            {tab(
              'mix_edit',
              '混剪',
              <Layers className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-indigo-600 text-white',
              '多个素材按 AI 方案混合剪辑成一条视频，适合盘点/合集类内容',
            )}
            {tab(
              'video_dub',
              '视频配音',
              <Volume2 className="w-3.5 h-3.5 opacity-90 hidden sm:inline" />,
              'bg-teal-600 text-white',
              '为已有视频重新生成配音（TTS）并合成，适合翻译配音或换音色',
            )}
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
