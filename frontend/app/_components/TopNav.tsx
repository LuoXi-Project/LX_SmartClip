'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navItems = [
  { href: '/library', label: '素材库' },
  { href: '/process', label: '素材处理' },
  { href: '/search', label: '素材检索' },
  { href: '/match', label: '智能剪辑' },
  { href: '/summary', label: '视频总结' },
  { href: '/tts', label: 'TTS 配音' },
  { href: '/bgm', label: 'BGM 音乐库' },
  { href: '/logs', label: '日志' },
  { href: '/settings', label: '设置' },
  { href: '/license', label: '卡密' },
  { href: '/about', label: '关于与支持' },
]

function isActive(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

export default function TopNav() {
  const pathname = usePathname()

  return (
    <>
      {navItems.map((item) => {
        const active = isActive(pathname, item.href)
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`text-sm transition-colors rounded-md px-2 py-1 border ${
              active
                ? 'text-slate-100 border-slate-500 bg-slate-800/70'
                : 'text-slate-400 border-transparent hover:text-slate-200 hover:border-slate-700'
            }`}
          >
            {item.label}
          </Link>
        )
      })}
    </>
  )
}
