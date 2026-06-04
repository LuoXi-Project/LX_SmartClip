'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Noto_Sans_SC, JetBrains_Mono } from 'next/font/google'
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Brain,
  CheckCircle,
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
import { HomeCanvas } from './_components/home/HomeCanvas'
import './_components/home/home.css'

const noto = Noto_Sans_SC({
  subsets: ['latin'],
  weight: ['300', '400', '500', '700', '900'],
  display: 'swap',
})

const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  display: 'swap',
})

const PIPELINE = [
  '批量素材入库',
  '多模式切分',
  '多模态理解',
  '三级精准匹配',
  'TTS 配音',
  '导出工程',
]

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

  const marqueeItems = [...PIPELINE, ...PIPELINE]

  return (
    <main
      className={`${noto.className} relative min-h-full overflow-hidden bg-[#030712] text-slate-200`}
    >
      {/* Ambient layers */}
      <div className="pointer-events-none absolute inset-0">
        <div className="home-float absolute -left-32 top-1/4 h-[420px] w-[420px] rounded-full bg-cyan-500/10 blur-[100px]" />
        <div className="home-float home-float-delay absolute -right-24 top-1/3 h-[380px] w-[380px] rounded-full bg-violet-600/12 blur-[110px]" />
        <div className="absolute bottom-0 left-1/2 h-[300px] w-[600px] -translate-x-1/2 rounded-full bg-indigo-600/8 blur-[120px]" />
      </div>

      <HomeCanvas />
      <div className="home-scanlines absolute inset-0 z-[1] opacity-30" aria-hidden />
      <div className="home-vignette absolute inset-0 z-[2]" aria-hidden />

      <div className="relative z-10">
        {/* Hero */}
        <section className="relative flex min-h-[min(88vh,820px)] flex-col items-center justify-center px-4 pb-8 pt-20 sm:pt-24">
          <div className="home-hero-in mb-8 flex justify-center">
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
            className={`${mono.className} home-hero-in home-hero-in-delay-1 mb-4 text-[11px] uppercase tracking-[0.35em] text-cyan-400/80`}
          >
            LX AI · Smart Clip
          </p>

          <h1 className="home-hero-in home-hero-in-delay-2 mb-5 text-center text-5xl font-black tracking-tight sm:text-6xl md:text-7xl">
            <span className="home-title-shimmer bg-gradient-to-r from-cyan-300 via-white to-violet-300 bg-clip-text text-transparent">
              洛曦智剪
            </span>
          </h1>

          <p className="home-hero-in home-hero-in-delay-3 max-w-2xl text-center text-lg font-light text-slate-300 sm:text-xl">
            本地轻量化 AI 智能素材匹配剪辑工具
          </p>

          <p className="home-hero-in home-hero-in-delay-4 mt-3 max-w-3xl text-center text-sm text-slate-500 sm:text-base">
            从素材入库到工程导出，全流程在本地完成 — 隐私可控、响应迅速
          </p>

          <div className="home-hero-in home-hero-in-delay-5 mt-10 flex flex-wrap items-center justify-center gap-3 sm:gap-4">
            <Link
              href="/studio"
              className="home-cta-primary group inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-cyan-600 via-violet-600 to-indigo-600 px-8 py-3.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition-shadow hover:shadow-cyan-500/35"
            >
              <Sparkles className="h-4 w-4" />
              开始智剪
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
            <Link
              href="/library"
              className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-8 py-3.5 text-sm font-medium text-slate-200 backdrop-blur-md transition-all hover:border-cyan-500/40 hover:bg-white/10"
            >
              素材库
            </Link>
          </div>

          {/* Pipeline marquee */}
          <div className="home-hero-in home-hero-in-delay-6 relative mt-16 w-full max-w-4xl overflow-hidden">
            <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-[#030712] to-transparent" />
            <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-[#030712] to-transparent" />
            <div className="flex animate-home-marquee whitespace-nowrap">
              {marqueeItems.map((step, i) => (
                <span
                  key={`${step}-${i}`}
                  className={`${mono.className} mx-6 inline-flex items-center gap-3 text-xs text-slate-500 sm:text-sm`}
                >
                  <span className="text-cyan-500/60">◆</span>
                  {step}
                </span>
              ))}
            </div>
            <div className="home-pipeline-flow mx-auto mt-3 h-px w-48 max-w-full rounded-full opacity-60" />
          </div>
        </section>

        {/* Status */}
        <section className="mx-auto max-w-md px-4 pb-14">
          <div className="home-hero-in home-hero-in-delay-6 home-status-border rounded-2xl p-[1px]">
            <div className="rounded-2xl bg-slate-950/80 p-6 backdrop-blur-xl">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                  系统状态
                </h2>
                <Activity className="h-4 w-4 text-cyan-400" />
              </div>

              {loading ? (
                <div className="flex items-center gap-3 text-slate-400">
                  <span className="relative flex h-3 w-3">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
                    <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-400" />
                  </span>
                  <span>检查中...</span>
                </div>
              ) : backendStatus === 'connected' ? (
                <div className="flex items-center gap-3 text-emerald-400">
                  <CheckCircle className="h-5 w-5" />
                  <span className="font-medium">后端已连接</span>
                </div>
              ) : (
                <div className="flex items-center gap-3 text-rose-400">
                  <AlertCircle className="h-5 w-5" />
                  <span className="font-medium">后端未连接</span>
                </div>
              )}

              <p className={`${mono.className} mt-4 text-xs text-slate-500`}>
                API · 同域（当前站点）
              </p>
            </div>
          </div>
        </section>

        {/* Features */}
        <section className="mx-auto max-w-6xl px-4 pb-24">
          <div className="mb-10 text-center">
            <p className={`${mono.className} text-xs uppercase tracking-[0.3em] text-slate-500`}>
              Capabilities
            </p>
            <h2 className="mt-2 text-2xl font-bold text-slate-100 sm:text-3xl">
              全流程能力矩阵
            </h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 lg:gap-5">
            {FEATURES.map((feature, idx) => {
              const Icon = feature.icon
              return (
                <Link
                  key={feature.title}
                  href={feature.href}
                  className="home-card-glow group block rounded-2xl border border-white/[0.06] bg-slate-950/50 p-6 backdrop-blur-md"
                  style={{ animationDelay: `${0.08 * idx}s` }}
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

        {/* Bottom CTA strip */}
        <section className="border-t border-white/[0.04] bg-slate-950/40 py-16 backdrop-blur-sm">
          <div className="mx-auto max-w-3xl px-4 text-center">
            <p className="text-slate-400">
              准备好把素材变成成片？
            </p>
            <Link
              href="/studio"
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
