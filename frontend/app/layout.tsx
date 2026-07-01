import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'
import { LicenseGate } from './_components/LicenseGate'
import { ToastProvider } from '@/components/ui/toast-provider'
import { ConfirmProvider } from '@/hooks/use-confirm'
import { TaskHub } from '@/components/ui/task-hub'
import TopNav from './_components/TopNav'
import { OnboardingGuide } from './_components/OnboardingGuide'
import FontsLoader from './_components/FontsLoader'

export const metadata: Metadata = {
  title: '洛曦智剪 - AI智能剪辑工具',
  description: '本地轻量化AI智能素材匹配剪辑工具',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        {/*
          非阻塞字体加载（见 FontsLoader）：fonts.loli.net 卡死/超时/失败时不再
          阻塞首屏渲染，页面继续用系统字体，绝不白屏；CDN 正常时字体静默替换。
        */}
        <FontsLoader />
      </head>
      <body className="min-h-screen flex flex-col" suppressHydrationWarning>
        <nav className="fixed top-0 inset-x-0 z-50 border-b border-slate-800 bg-[#0d0f14]/90 backdrop-blur-md">
          <div className="w-full px-4 sm:px-6 h-12 flex items-center gap-3 sm:gap-4">
            <Link
              href="/"
              className="text-sm font-bold tracking-tight text-slate-100 hover:text-white transition-colors shrink-0"
            >
              洛曦智剪
            </Link>
            <div className="h-4 w-px bg-slate-700 shrink-0 hidden md:block" />
            <TopNav />
          </div>
        </nav>
        <ToastProvider>
          <ConfirmProvider>
            <TaskHub />
            <div className="pt-12 flex-1">
              <LicenseGate>{children}</LicenseGate>
              <OnboardingGuide />
            </div>
            <footer className="border-t border-slate-800 bg-[#0d0f14]">
              <div className="max-w-6xl mx-auto px-6 py-4 text-xs text-slate-400 flex flex-col sm:flex-row gap-2 sm:items-center sm:justify-between">
                <div>© {new Date().getFullYear()} 洛曦</div>
                <a
                  href="http://luoxiai.dpdns.org/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-slate-400 hover:text-slate-200 transition-colors"
                >
                  官网：luoxiai.dpdns.org
                </a>
              </div>
            </footer>
          </ConfirmProvider>
        </ToastProvider>
      </body>
    </html>
  )
}
