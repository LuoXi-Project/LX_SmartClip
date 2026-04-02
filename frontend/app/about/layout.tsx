import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: '关于与支持 · 洛曦智剪',
  description: '产品简介、团队与官网、视频教程、问题反馈与建议',
}

export default function AboutLayout({ children }: { children: React.ReactNode }) {
  return children
}
