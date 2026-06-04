'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Clapperboard,
  FolderOpen,
  Settings2,
  Sparkles,
  X,
  Workflow,
} from 'lucide-react'
import clsx from 'clsx'
import {
  loadOnboardingState,
  saveOnboardingStatus,
  shouldAutoShowOnboarding,
  type OnboardingStatus,
} from '@/lib/onboarding'

export const ONBOARDING_REOPEN_EVENT = 'lx-smartclip-onboarding-open'

type StepDef = {
  id: string
  title: string
  subtitle: string
  icon: typeof Settings2
  href: string
  accent: string
  bullets: string[]
}

const STEPS: StepDef[] = [
  {
    id: 'settings',
    title: '配置 API 与模型',
    subtitle: '先完成系统设置，后续 AI 能力才能正常工作',
    icon: Settings2,
    href: '/settings',
    accent: 'from-cyan-600/25 to-slate-900/40 border-cyan-500/35',
    bullets: [
      '在「设置」中填写 LLM、VLM、向量检索（Embedding）的 API 地址与密钥，并选择模型。',
      '素材处理还需配置 ASR（语音识别）；需要配音时再配置 TTS。',
      '视频处理参数（切分模式、抽帧等）可按素材类型调整，默认即可先跑通流程。',
    ],
  },
  {
    id: 'library',
    title: '素材库上传视频',
    subtitle: '把原始素材导入本地库，供后续切分与检索',
    icon: FolderOpen,
    href: '/library',
    accent: 'from-emerald-600/20 to-slate-900/40 border-emerald-500/35',
    bullets: [
      '支持本地上传或链接导入，上传后可在列表预览、重命名与批量管理。',
      '建议先上传 1～2 条代表性素材试跑，确认格式与时长符合预期。',
    ],
  },
  {
    id: 'process',
    title: '素材处理（切分与分析）',
    subtitle: '生成可检索的片段：ASR、视觉描述、向量索引',
    icon: Workflow,
    href: '/process',
    accent: 'from-amber-600/20 to-slate-900/40 border-amber-500/35',
    bullets: [
      '在「素材处理」选择视频，启动流水线：切分 → 抽帧 → ASR → VLM → 向量化。',
      '处理完成后状态为「已完成」，即可在「素材检索」或智剪工作台中使用这些片段。',
    ],
  },
  {
    id: 'studio',
    title: '智剪工作台 · 对话式制作',
    subtitle: '用自然语言描述诉求，由 Agent 规划并成片',
    icon: Sparkles,
    href: '/studio',
    accent: 'from-violet-600/30 to-slate-900/40 border-violet-500/45',
    bullets: [
      '在智剪工作台新建会话，描述目标时长、风格与叙事结构。',
      'Agent 会结合已处理素材自动匹配片段、生成方案；你可在右侧检视并导出成片或工程。',
      '经典「匹配剪辑」、视频总结等能力在顶部导航「剪辑」菜单中，可按需探索。',
    ],
  },
]

function persistStatus(status: OnboardingStatus) {
  void saveOnboardingStatus(status)
}

export function OnboardingGuide() {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)
  const [hydrated, setHydrated] = useState(false)

  const openWizard = useCallback((fromStep = 0) => {
    setStep(fromStep)
    setOpen(true)
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const state = await loadOnboardingState()
      if (cancelled) return
      setHydrated(true)
      if (shouldAutoShowOnboarding(state)) {
        openWizard(0)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [openWizard])

  useEffect(() => {
    const handler = () => openWizard(0)
    window.addEventListener(ONBOARDING_REOPEN_EVENT, handler)
    return () => window.removeEventListener(ONBOARDING_REOPEN_EVENT, handler)
  }, [openWizard])

  // 卡密页不弹引导
  if (pathname?.startsWith('/license')) return null
  if (!hydrated && !open) return null
  if (!open) return null

  const current = STEPS[step]
  const Icon = current.icon
  const isLast = step === STEPS.length - 1

  const close = (status: OnboardingStatus) => {
    setOpen(false)
    persistStatus(status)
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 sm:p-6"
      aria-modal="true"
      role="dialog"
      aria-labelledby="onboarding-title"
    >
      <div
        className="absolute inset-0 bg-black/65 backdrop-blur-sm"
        onClick={() => close('skipped')}
        aria-hidden
      />

      <div className="relative z-10 w-full max-w-lg bg-[#12141c] border border-slate-700/70 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <div className="px-5 pt-5 pb-3 border-b border-slate-800/80 flex items-start justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-violet-400/90 font-medium mb-1">
              新手指引 · {step + 1} / {STEPS.length}
            </p>
            <h2 id="onboarding-title" className="text-lg font-semibold text-slate-100">
              欢迎使用洛曦智剪
            </h2>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              按推荐顺序完成四步即可上手。状态保存在本机数据库，与访问端口无关。
            </p>
          </div>
          <button
            type="button"
            onClick={() => close('skipped')}
            className="shrink-0 p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/80 transition-colors"
            aria-label="关闭新手指引"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 flex gap-1.5">
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setStep(i)}
              className={clsx(
                'h-1 flex-1 rounded-full transition-colors',
                i === step ? 'bg-violet-500' : i < step ? 'bg-violet-500/40' : 'bg-slate-700',
              )}
              aria-label={`第 ${i + 1} 步：${s.title}`}
            />
          ))}
        </div>

        <div
          className={clsx(
            'mx-5 rounded-xl border bg-gradient-to-br p-4',
            current.accent,
          )}
        >
          <div className="flex items-start gap-3">
            <div className="shrink-0 w-10 h-10 rounded-xl bg-slate-950/50 border border-slate-700/60 flex items-center justify-center text-violet-300">
              <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-base font-medium text-slate-100">{current.title}</h3>
              <p className="text-xs text-slate-400 mt-0.5">{current.subtitle}</p>
            </div>
          </div>
          <ul className="mt-3 space-y-2 text-sm text-slate-300 leading-relaxed list-disc pl-4 marker:text-slate-600">
            {current.bullets.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>

        <div className="px-5 py-4 flex flex-wrap items-center gap-2">
          <Link
            href={current.href}
            onClick={() => {
              if (isLast) close('completed')
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500 transition-colors"
          >
            <Clapperboard className="w-3.5 h-3.5" />
            {current.id === 'settings'
              ? '前往设置'
              : current.id === 'library'
                ? '前往素材库'
                : current.id === 'process'
                  ? '前往素材处理'
                  : '前往智剪工作台'}
          </Link>
          <button
            type="button"
            onClick={() => close('skipped')}
            className="text-sm text-slate-500 hover:text-slate-300 px-2 py-2 transition-colors"
          >
            跳过引导
          </button>
        </div>

        <div className="px-5 pb-5 flex items-center justify-between gap-2 border-t border-slate-800/60 pt-4">
          <button
            type="button"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            className="inline-flex items-center gap-1 px-3 py-2 text-sm text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:pointer-events-none rounded-lg hover:bg-slate-800/50 transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            上一步
          </button>
          <div className="flex items-center gap-2">
            {!isLast ? (
              <button
                type="button"
                onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
                className="inline-flex items-center gap-1 px-4 py-2 text-sm font-medium text-white bg-slate-700 hover:bg-slate-600 rounded-lg transition-colors"
              >
                下一步
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => close('completed')}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 rounded-lg transition-colors"
              >
                <BookOpen className="w-4 h-4" />
                知道了，开始使用
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export function openOnboardingGuide() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(ONBOARDING_REOPEN_EVENT))
}
