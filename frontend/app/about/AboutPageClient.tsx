'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft,
  ExternalLink,
  Github,
  Globe,
  MessageSquarePlus,
  Sparkles,
  Users,
  Video,
  Zap,
} from 'lucide-react'

const LINKS = {
  issues: 'https://github.com/LuoXi-Project/LX_Official_Website/issues',
  official: 'http://luoxiai.dpdns.org/',
  bilibili: 'https://space.bilibili.com/3709626',
} as const

function ExternalCard({
  href,
  title,
  description,
  icon: Icon,
  accent,
  delayMs,
}: {
  href: string
  title: string
  description: string
  icon: typeof Globe
  accent: string
  delayMs: number
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{ animationDelay: `${delayMs}ms` }}
      className={`group relative overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-950/40 p-6 backdrop-blur-xl opacity-0 animate-about-in transition-all duration-300 hover:-translate-y-0.5 hover:border-slate-500/80 hover:shadow-lg ${accent}`}
    >
      <div className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-gradient-to-br from-white/10 to-transparent opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100" />
      <div className="relative flex items-start gap-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-600/60 bg-slate-900/80 text-slate-200 shadow-inner transition-colors group-hover:border-violet-500/40 group-hover:text-violet-200">
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-base font-semibold text-slate-100">
            {title}
            <ExternalLink className="h-3.5 w-3.5 shrink-0 text-slate-500 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100" />
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{description}</p>
        </div>
      </div>
    </a>
  )
}

export default function AboutPage() {
  const [shift, setShift] = useState({ x: 0, y: 0 })

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const x = (e.clientX / window.innerWidth - 0.5) * 28
      const y = (e.clientY / window.innerHeight - 0.5) * 28
      setShift({ x, y })
    }
    window.addEventListener('mousemove', onMove, { passive: true })
    return () => window.removeEventListener('mousemove', onMove)
  }, [])

  return (
    <main className="relative min-h-full overflow-hidden">
      <div
        className="pointer-events-none absolute inset-0 transition-transform duration-700 ease-out"
        style={{ transform: `translate(${shift.x * 0.35}px, ${shift.y * 0.35}px)` }}
      >
        <div className="absolute -left-32 top-0 h-[420px] w-[420px] rounded-full bg-violet-600/25 blur-[100px] animate-blob" />
        <div className="absolute right-0 top-24 h-[380px] w-[380px] rounded-full bg-cyan-500/20 blur-[90px] animate-blob-slow" />
        <div className="absolute bottom-0 left-1/3 h-[360px] w-[360px] rounded-full bg-fuchsia-600/20 blur-[95px] animate-blob-slower" />
      </div>
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.35] transition-transform duration-500 ease-out [background-image:linear-gradient(rgba(148,163,184,0.07)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.07)_1px,transparent_1px)] [background-size:48px_48px]"
        style={{ transform: `translate(${shift.x * -0.15}px, ${shift.y * -0.15}px)` }}
      />

      <div className="relative mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
        <Link
          href="/"
          className="mb-10 inline-flex items-center gap-2 text-sm text-slate-400 transition-colors hover:text-slate-200"
        >
          <ArrowLeft className="h-4 w-4" />
          返回首页
        </Link>

        <header className="mb-12 text-center sm:mb-16">
          <div
            className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-4 py-1.5 text-xs font-medium text-violet-200/90 shadow-[0_0_24px_-8px_rgba(139,92,246,0.6)] opacity-0 animate-about-in"
            style={{ animationDelay: '40ms' }}
          >
            <Sparkles className="h-3.5 w-3.5" />
            产品 · 团队 · 教程 · 反馈
          </div>
          <h1
            className="bg-gradient-to-br from-white via-slate-100 to-slate-400 bg-clip-text text-4xl font-bold tracking-tight text-transparent sm:text-5xl opacity-0 animate-about-in"
            style={{ animationDelay: '90ms' }}
          >
            关于与支持
          </h1>
          <p
            className="mx-auto mt-4 max-w-2xl text-base text-slate-400 sm:text-lg opacity-0 animate-about-in"
            style={{ animationDelay: '140ms' }}
          >
            一站式了解洛曦智剪、团队与洛曦生态，快速跳转官网教程、B 站视频与 GitHub 反馈渠道。
          </p>
        </header>

        <div className="grid gap-5 lg:grid-cols-12 lg:gap-6">
          <section
            className="relative overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-950/50 p-6 backdrop-blur-xl sm:p-8 lg:col-span-7 opacity-0 animate-about-in hover:border-slate-600/90 hover:shadow-[0_0_48px_-12px_rgba(59,130,246,0.25)] transition-all duration-300"
            style={{ animationDelay: '180ms' }}
          >
            <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-blue-500/10 via-transparent to-violet-600/10" />
            <div className="relative">
              <div className="mb-4 flex items-center gap-2 text-slate-200">
                <Zap className="h-5 w-5 text-amber-400" />
                <h2 className="text-lg font-semibold">产品基本信息</h2>
              </div>
              <p className="text-sm leading-relaxed text-slate-300 sm:text-[15px]">
                <strong className="text-slate-100">洛曦智剪</strong>
                是面向创作者与团队的本地轻量化{' '}
                <span className="text-violet-300/95">AI 智能素材匹配剪辑</span>
                工具：支持素材批量入库、多模式切分、ASR / 多模态理解、三级匹配精排、TTS 配音与工程导出，流程从素材到成片可在同一套工作流中完成。
              </p>
              <ul className="mt-5 grid gap-2 text-sm text-slate-400 sm:grid-cols-2">
                {['素材库与预览', '镜头 / 固定时长切分', 'RAG + LLM 匹配', 'TTS 与 BGM', '导出剪辑工程'].map((t) => (
                  <li key={t} className="flex items-center gap-2">
                    <span className="h-1 w-1 rounded-full bg-cyan-400/80" />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section
            className="relative overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-950/50 p-6 backdrop-blur-xl sm:p-8 lg:col-span-5 opacity-0 animate-about-in transition-all duration-300 hover:border-emerald-500/25 hover:shadow-[0_0_40px_-10px_rgba(16,185,129,0.2)]"
            style={{ animationDelay: '230ms' }}
          >
            <div className="pointer-events-none absolute -right-16 top-0 h-40 w-40 rounded-full bg-emerald-500/15 blur-3xl" />
            <div className="relative">
              <div className="mb-4 flex items-center gap-2 text-slate-200">
                <Users className="h-5 w-5 text-emerald-400" />
                <h2 className="text-lg font-semibold">团队与品牌</h2>
              </div>
              <p className="text-sm leading-relaxed text-slate-400">
                <strong className="text-slate-200">洛曦（LuoXi）</strong>
                专注 AI 与直播/内容生产工具，旗下涵盖虚拟主播、数字人、弹幕与剪辑等多条产品线。更多产品与定价请以官网为准。
              </p>
              <a
                href={LINKS.official}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-5 inline-flex items-center gap-2 rounded-xl border border-slate-600/70 bg-slate-900/60 px-4 py-2.5 text-sm font-medium text-slate-200 transition-all hover:border-violet-500/40 hover:bg-slate-900 hover:text-white"
              >
                <Globe className="h-4 w-4 text-violet-400" />
                访问洛曦官网
                <ExternalLink className="h-3.5 w-3.5 text-slate-500" />
              </a>
            </div>
          </section>

          <div className="lg:col-span-12">
            <h2
              className="mb-4 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-slate-500 opacity-0 animate-about-in"
              style={{ animationDelay: '280ms' }}
            >
              <span className="h-px flex-1 max-w-12 bg-slate-700" />
              教程与反馈
              <span className="h-px flex-1 bg-slate-700" />
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <ExternalCard
                href={LINKS.bilibili}
                title="B 站 · 视频教程"
                description="关注洛曦 B 站空间，观看更新教程与演示，上手更快。"
                icon={Video}
                accent="hover:shadow-cyan-500/10"
                delayMs={320}
              />
              <ExternalCard
                href={LINKS.official}
                title="官网 · 文档与下载"
                description="产品矩阵、说明与下载入口集中在洛曦官网，建议收藏。"
                icon={Globe}
                accent="hover:shadow-violet-500/15"
                delayMs={390}
              />
              <ExternalCard
                href={LINKS.issues}
                title="GitHub · 问题反馈"
                description="提交 Bug、功能建议或讨论，在 Issues 中与团队同步进展。"
                icon={Github}
                accent="hover:shadow-slate-400/10"
                delayMs={460}
              />
            </div>
          </div>

          <section
            className="relative overflow-hidden rounded-2xl border border-violet-500/35 bg-gradient-to-br from-violet-950/50 via-slate-950/60 to-slate-950/80 p-6 backdrop-blur-xl sm:p-8 lg:col-span-12 opacity-0 animate-about-in"
            style={{ animationDelay: '520ms' }}
          >
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(139,92,246,0.22),transparent_55%)]" />
            <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-violet-400/30 bg-violet-500/15 text-violet-200">
                  <MessageSquarePlus className="h-5 w-5" />
                </span>
                <div>
                  <h3 className="text-base font-semibold text-slate-100">有想法？直接开 Issue</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    功能建议、使用疑问或缺陷反馈，欢迎到 GitHub Issues 留言，我们会定期查看。
                  </p>
                </div>
              </div>
              <a
                href={LINKS.issues}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-900/40 transition-transform hover:scale-[1.02] hover:shadow-violet-600/30 active:scale-[0.99]"
              >
                <Github className="h-4 w-4" />
                前往 Issues
                <ExternalLink className="h-3.5 w-3.5 opacity-80" />
              </a>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}
