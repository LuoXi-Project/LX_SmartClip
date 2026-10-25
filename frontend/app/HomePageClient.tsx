'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
// 字体已通过 layout.tsx 中的 <link> 从国内 CDN 加载，这里仅声明 className 常量
const noto = { className: 'font-sans-sc' } as const
const mono = { className: 'font-mono-jetbrains' } as const
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Brain,
  Film,
  Mic,
  Package,
  Scissors,
  Sparkles,
  Target,
} from 'lucide-react'
import { useAppStore } from '@/lib/store'
import logoPng from '../logo.png'
import apiClient from '@/lib/api'
import { HomeCosmosBackground } from './_components/home/HomeCosmosBackground'
import { useHomeGsap } from './_components/home/useHomeGsap'
import './_components/home/home.css'

const TITLE = '洛曦智剪'

const PIPELINE = [
  { label: '一句话智剪', icon: Sparkles },
  { label: '素材入库与切分', icon: Scissors },
  { label: '多模态理解', icon: Brain },
  { label: '智能匹配', icon: Target },
  { label: 'TTS 配音', icon: Mic },
  { label: '导出与发布', icon: Package },
] as const

const FEATURES = [
  {
    title: '素材库',
    description: '上传、管理、预览视频素材',
    href: '/library',
    icon: Film,
    accent: 'from-cyan-500/20 to-cyan-500/5',
    iconColor: 'text-cyan-400',
  },
  {
    title: '智能切分',
    description: '镜头识别 / 固定时长双模式',
    href: '/process',
    icon: Scissors,
    accent: 'from-violet-500/20 to-violet-500/5',
    iconColor: 'text-violet-400',
  },
  {
    title: '多模态理解',
    description: 'ASR + VLM 自动分析',
    href: '/process',
    icon: Brain,
    accent: 'from-fuchsia-500/20 to-fuchsia-500/5',
    iconColor: 'text-fuchsia-400',
  },
  {
    title: '三级匹配',
    description: 'RAG 初筛 → LLM 精排 → 人工选择',
    href: '/match',
    icon: Target,
    accent: 'from-indigo-500/20 to-indigo-500/5',
    iconColor: 'text-indigo-400',
  },
  {
    title: 'TTS 配音',
    description: '自动生成高质量配音',
    href: '/tts',
    icon: Mic,
    accent: 'from-emerald-500/20 to-emerald-500/5',
    iconColor: 'text-emerald-400',
  },
  {
    title: '工程导出',
    description: '导出剪辑工程文件',
    href: '/studio',
    icon: Package,
    accent: 'from-amber-500/20 to-amber-500/5',
    iconColor: 'text-amber-400',
  },
] as const

export default function Home() {
  const { backendStatus, setBackendStatus } = useAppStore()
  const [loading, setLoading] = useState(true)
  const mainRef = useRef<HTMLElement>(null)

  useHomeGsap(mainRef)

  useEffect(() => {
    const checkBackendHealth = async () => {
      try {
        setLoading(true)
        const data = await apiClient.get<unknown, { status: string }>('/health')
        if (data && data.status === 'ok') {
          setBackendStatus('connected')
        } else {
          setBackendStatus('disconnected')
        }
      } catch (error) {
        console.error('Backend health check failed:', error)
        setBackendStatus('disconnected')
      } finally {
        setLoading(false)
      }
    }

    checkBackendHealth()
    const interval = setInterval(async () => {
      if (useAppStore.getState().backendStatus === 'connected') {
        clearInterval(interval)
        return
      }
      await checkBackendHealth()
    }, 5000)
    return () => clearInterval(interval)
  }, [setBackendStatus])

  return (
    <main
      ref={mainRef}
      className={`${noto.className} relative min-h-full overflow-hidden bg-[#00040c] text-slate-100`}
    >
      <HomeCosmosBackground />

      <div className="pointer-events-none absolute inset-0 z-[1]">
        <div className="home-float absolute left-1/4 top-1/3 h-[360px] w-[360px] -translate-x-1/2 rounded-full bg-sky-400/[0.04] blur-[120px]" />
        <div className="home-float home-float-delay absolute right-1/4 top-2/5 h-[320px] w-[320px] translate-x-1/2 rounded-full bg-violet-400/[0.05] blur-[130px]" />
      </div>

      <div className="home-vignette absolute inset-0 z-[2]" aria-hidden />

      {/* z-10 内容层整体 pointer-events-none，仅真正的交互元素（按钮/链接）
          单独 pointer-events-auto —— 这样首页星球背景的空白区域可接收点击，
          让太阳系画布（位于下方 z-[3]）能拾取到「点击星球」事件。 */}
      <div className="relative z-10 pointer-events-none">
        <section className="relative flex min-h-[min(92vh,860px)] flex-col items-center justify-center px-4 pb-8 pt-20 sm:pt-24">
          <div data-hero="logo" className="mb-8 flex justify-center">
            <div className="home-logo-ring relative rounded-full p-1">
              <img
                src={logoPng.src ?? logoPng}
                alt="洛曦智剪"
                width={256}
                height={256}
                fetchPriority="high"
                decoding="async"
                className="relative z-10 size-[120px] rounded-full object-cover ring-1 ring-white/10 sm:size-[140px]"
              />
              <div
                className="absolute inset-0 rounded-full bg-gradient-to-tr from-cyan-400/30 via-transparent to-violet-500/30 blur-md"
                aria-hidden
              />
            </div>
          </div>

          <p
            data-hero="tag"
            className={`${mono.className} mb-4 text-[11px] uppercase tracking-[0.35em] text-cyan-400/80`}
          >
            LuoXi · SmartClip
          </p>

          <h1
            data-hero="title"
            className="mb-5 flex justify-center gap-0.5 text-center text-5xl font-black tracking-tight sm:text-6xl md:text-7xl"
            style={{ perspective: '900px' }}
          >
            {TITLE.split('').map((char, i) => (
              <span
                key={`${char}-${i}`}
                data-hero="title-char"
                className="home-title-shimmer inline-block bg-gradient-to-r from-cyan-300 via-white to-violet-300 bg-clip-text text-transparent"
                style={{ transformStyle: 'preserve-3d' }}
              >
                {char}
              </span>
            ))}
          </h1>

          <p
            data-hero="sub"
            className="max-w-2xl text-center text-lg font-light text-slate-300 sm:text-xl"
          >
            本地轻量化 AI 智能素材匹配剪辑工具
          </p>

          <p
            data-hero="desc"
            className="mt-3 max-w-3xl text-center text-sm text-slate-500 sm:text-base"
          >
            从素材入库到工程导出，全流程在本地完成 — 隐私可控、响应迅速
          </p>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
            <Link
              href="/studio"
              data-hero="cta"
              data-magnetic
              className="home-cta-primary pointer-events-auto group inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-cyan-600 via-violet-600 to-indigo-600 px-8 py-3.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition-shadow hover:shadow-cyan-500/35"
            >
              <Sparkles className="h-4 w-4" />
              开始智剪
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
            <Link
              href="/library"
              data-hero="cta"
              data-magnetic
              className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-8 py-3.5 text-sm font-medium text-slate-200 backdrop-blur-md transition-all hover:border-cyan-500/40 hover:bg-white/10"
            >
              <Film className="h-4 w-4 text-cyan-400/80" />
              素材库
            </Link>
          </div>

          <div data-hero="pipeline" className="mt-16 w-full max-w-5xl px-2">
            <p
              className={`${mono.className} mb-8 text-center text-[10px] uppercase tracking-[0.35em] text-slate-600`}
            >
              Pipeline · 全流程
            </p>
            <div className="grid grid-cols-3 gap-x-2 gap-y-8 sm:grid-cols-6 sm:gap-x-0">
              {PIPELINE.map((step, i) => {
                const Icon = step.icon
                return (
                  <div key={step.label} className="relative flex flex-col items-center text-center">
                    {i < PIPELINE.length - 1 && (
                      <div
                        className="pointer-events-none absolute left-[calc(50%+1.25rem)] top-5 hidden h-px w-[calc(100%-2.5rem)] bg-gradient-to-r from-cyan-500/35 via-violet-500/25 to-cyan-500/35 sm:block"
                        aria-hidden
                      />
                    )}
                    <div className="relative z-10 mb-2.5 flex size-10 items-center justify-center rounded-xl border border-white/[0.08] bg-slate-950/70 shadow-[0_0_20px_rgba(34,211,238,0.06)] ring-1 ring-cyan-500/15 backdrop-blur-sm">
                      <Icon className="size-4 text-cyan-400/90" />
                    </div>
                    <span className="text-[11px] leading-snug text-slate-400 sm:text-xs">
                      {step.label}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        {!loading && backendStatus !== 'connected' && (
          <section data-section="status" className="pointer-events-auto mx-auto max-w-md px-4 pb-14">
            <div className="home-status-border rounded-2xl p-[1px]">
              <div className="rounded-2xl bg-slate-950/80 p-6 backdrop-blur-xl">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                    系统状态
                  </h2>
                  <Activity className="h-4 w-4 text-rose-400" />
                </div>

                <div className="flex items-center gap-3 text-rose-400">
                  <AlertCircle className="h-5 w-5" />
                  <span className="font-medium">后端未连接</span>
                </div>

                <p className={`${mono.className} mt-4 text-xs text-slate-500`}>
                  API · 同域（当前站点）
                </p>
              </div>
            </div>
          </section>
        )}

        <section data-section="features" className="pointer-events-auto mx-auto max-w-6xl px-4 pb-24">
          <div data-section="features-header" className="mb-10 text-center">
            <p className={`${mono.className} text-xs uppercase tracking-[0.3em] text-slate-500`}>
              Capabilities · Universe
            </p>
            <h2 className="mt-2 text-2xl font-bold text-slate-100 sm:text-3xl">
              全流程能力矩阵
            </h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 lg:gap-5">
            {FEATURES.map((feature) => {
              const Icon = feature.icon
              return (
                <Link
                  key={feature.title}
                  href={feature.href}
                  data-feature-card
                  className="home-card-glow group block rounded-2xl border border-white/[0.06] bg-slate-950/60 p-6 backdrop-blur-md"
                  style={{ transformStyle: 'preserve-3d' }}
                >
                  <div
                    className={`mb-4 inline-flex rounded-xl bg-gradient-to-br ${feature.accent} p-3 ring-1 ring-white/5`}
                  >
                    <Icon className={`h-6 w-6 ${feature.iconColor}`} />
                  </div>
                  <h3 className="mb-2 text-lg font-semibold text-slate-100 transition-colors group-hover:text-cyan-200">
                    {feature.title}
                  </h3>
                  <p className="text-sm leading-relaxed text-slate-500">{feature.description}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-xs text-cyan-500/0 transition-all group-hover:text-cyan-400/90">
                    进入
                    <ArrowRight className="h-3 w-3 translate-x-0 transition-transform group-hover:translate-x-1" />
                  </span>
                </Link>
              )
            })}
          </div>
        </section>

        <section
          data-section="cta-bottom"
          className="pointer-events-auto border-t border-white/[0.04] bg-slate-950/50 py-16 backdrop-blur-sm"
        >
          <div className="mx-auto max-w-3xl px-4 text-center">
            <p className="text-slate-400">准备好把素材变成成片？</p>
            <Link
              href="/studio"
              data-magnetic
              className="home-cta-primary mt-6 inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-10 py-4 text-base font-semibold text-cyan-100 transition-colors hover:bg-cyan-500/20"
            >
              打开智剪工作台
              <ArrowRight className="h-5 w-5" />
            </Link>
          </div>
        </section>
      </div>
    </main>
  )
}
