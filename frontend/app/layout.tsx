import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'LX SmartClip - AI智能剪辑工具',
  description: '本地轻量化AI智能素材匹配剪辑工具',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  )
}
