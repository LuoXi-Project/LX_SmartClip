import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'
import AIChatPanel from './_components/AIChatPanel'
import { LicenseGate } from './_components/LicenseGate'
import { ToastProvider } from '@/components/ui/toast-provider'
import { ConfirmProvider } from '@/hooks/use-confirm'

export const metadata: Metadata = {
  title: '洛曦智剪 - AI智能剪辑工具',
  description: '本地轻量化AI智能素材匹配剪辑工具',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen flex flex-col">
        <nav className="fixed top-0 inset-x-0 z-50 border-b border-slate-800 bg-[#0d0f14]/90 backdrop-blur-md">
          <div className="max-w-6xl mx-auto px-6 h-12 flex items-center gap-6">
            <Link href="/" className="text-sm font-bold tracking-tight text-slate-100 hover:text-white transition-colors">
            洛曦智剪
            </Link>
            <div className="h-4 w-px bg-slate-700" />
            <Link href="/library" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">素材库</Link>
            <Link href="/process" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">素材处理</Link>
            <Link href="/search" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">素材检索</Link>
            <Link href="/match" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">智能剪辑</Link>
            <Link href="/summary" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">视频总结</Link>
            <Link href="/tts" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">TTS 配音</Link>
            <Link href="/bgm" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">BGM 音乐库</Link>
            <Link href="/logs" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">日志</Link>
            <Link href="/settings" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">设置</Link>
            <Link href="/license" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">卡密</Link>
            <Link href="/about" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">关于与支持</Link>
          </div>
        </nav>
        <ToastProvider>
          <ConfirmProvider>
            <div className="pt-12 flex-1">
              <LicenseGate>{children}</LicenseGate>
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
            <AIChatPanel />
          </ConfirmProvider>
        </ToastProvider>
      </body>
    </html>
  )
}
