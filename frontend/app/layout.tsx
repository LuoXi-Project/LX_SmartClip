import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'
import AIChatPanel from './_components/AIChatPanel'
import { ToastProvider } from '@/components/ui/toast-provider'
import { ConfirmProvider } from '@/hooks/use-confirm'

export const metadata: Metadata = {
  title: '洛曦智剪 - AI智能剪辑工具',
  description: '本地轻量化AI智能素材匹配剪辑工具',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <nav className="fixed top-0 inset-x-0 z-50 border-b border-slate-800 bg-[#0d0f14]/90 backdrop-blur-md">
          <div className="max-w-6xl mx-auto px-6 h-12 flex items-center gap-6">
            <Link href="/" className="text-sm font-bold tracking-tight text-slate-100 hover:text-white transition-colors">
            洛曦智剪
            </Link>
            <div className="h-4 w-px bg-slate-700" />
            <Link href="/library" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">素材库</Link>
            <Link href="/process" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">素材处理</Link>
            <Link href="/match" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">文案匹配</Link>
            <Link href="/tts" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">TTS 配音</Link>
            <Link href="/bgm" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">BGM 音乐库</Link>
            <Link href="/settings" className="text-sm text-slate-400 hover:text-slate-200 transition-colors">设置</Link>
          </div>
        </nav>
        <ToastProvider>
          <ConfirmProvider>
            <div className="pt-12">{children}</div>
            <AIChatPanel />
          </ConfirmProvider>
        </ToastProvider>
      </body>
    </html>
  )
}
