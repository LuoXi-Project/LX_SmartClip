'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { BookOpen, Menu, X } from 'lucide-react'
import clsx from 'clsx'
import { NavDropdown, type NavDropdownItem } from '@/components/ui/nav-dropdown'
import { openOnboardingGuide } from './OnboardingGuide'
import {
  ONBOARDING_PREPARE_EVENT,
  TOUR_ANCHORS,
  tourAnchorProps,
} from '@/lib/onboarding-tour'

const editItems: NavDropdownItem[] = [
  { href: '/match', label: '经典模式', description: '分组工作台：文案 / 配音 / 素材多路径成片' },
  { href: '/summary', label: '视频总结', description: '长视频 AI 摘要' },
]

const audioItems: NavDropdownItem[] = [
  { href: '/tts', label: 'TTS 配音', description: '文字转语音' },
  { href: '/bgm', label: 'BGM 音乐库', description: '背景音乐管理' },
  { href: '/audio-library', label: '音频库', description: '音乐账号与爬取' },
]

/** 素材侧工具链：入库后的加工与检索，从一级导航收编为分组 */
const materialItems: NavDropdownItem[] = [
  { href: '/process', label: '素材处理', description: '切分与多模态分析' },
  { href: '/search', label: '素材检索', description: '语义搜索片段' },
  { href: '/workflows', label: '工作流', description: '一键自动化流水线' },
]

const moreItems: NavDropdownItem[] = [
  { href: '/about', label: '关于与支持' },
  { href: '/logs', label: '日志' },
  { href: '/license', label: '卡密' },
]

const mobileSections = [
  {
    title: '常用',
    items: [
      { href: '/studio', label: '智剪工作台', tour: TOUR_ANCHORS.navStudio },
      { href: '/library', label: '素材库', description: '上传、管理、预览', tour: TOUR_ANCHORS.navLibrary },
      { href: '/publish', label: '一键发布', description: '多平台视频分发' },
      { href: '/settings', label: '设置', tour: TOUR_ANCHORS.navSettings },
    ],
  },
  {
    title: '素材工具',
    items: [
      { href: '/process', label: '素材处理', description: '切分与多模态分析', tour: TOUR_ANCHORS.navProcess },
      { href: '/search', label: '素材检索', description: '语义搜索片段' },
      { href: '/workflows', label: '工作流', description: '一键自动化流水线' },
    ],
  },
  { title: '剪辑', items: editItems },
  { title: '音频', items: audioItems },
  { title: '更多', items: moreItems },
]

const guideMobileItem = { href: '#guide', label: '新手指引', description: '直接到工作台对话出片，缺什么补什么' }

function isActive(pathname: string, href: string) {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

function groupActive(pathname: string, items: NavDropdownItem[]) {
  return items.some((item) => isActive(pathname, item.href))
}

function navLinkClass(active: boolean, accent?: boolean) {
  return clsx(
    'text-sm transition-colors rounded-md px-2.5 py-1.5 border whitespace-nowrap',
    accent
      ? active
        ? 'text-white border-violet-500/60 bg-violet-600/30'
        : 'text-violet-200 border-violet-500/30 bg-violet-600/10 hover:text-white hover:border-violet-400/50 hover:bg-violet-600/20'
      : active
        ? 'text-slate-100 border-slate-500 bg-slate-800/70'
        : 'text-slate-400 border-transparent hover:text-slate-200 hover:border-slate-700',
  )
}

export default function TopNav() {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)
  const mobileRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!mobileOpen) return
    const close = (e: MouseEvent) => {
      if (mobileRef.current?.contains(e.target as Node)) return
      setMobileOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [mobileOpen])

  useEffect(() => {
    const onPrepare = (e: Event) => {
      const detail = (e as CustomEvent<{ openMobileNav?: boolean; scrollToId?: string }>).detail
      if (detail?.openMobileNav && window.innerWidth < 768) {
        setMobileOpen(true)
      }
    }
    window.addEventListener(ONBOARDING_PREPARE_EVENT, onPrepare)
    return () => window.removeEventListener(ONBOARDING_PREPARE_EVENT, onPrepare)
  }, [])

  return (
    <div ref={mobileRef} className="flex items-center flex-1 min-w-0">
      <nav className="hidden md:flex items-center flex-1 min-w-0 gap-1">
        <Link
          href="/studio"
          {...tourAnchorProps(TOUR_ANCHORS.navStudio)}
          className={navLinkClass(isActive(pathname, '/studio'), true)}
        >
          智剪工作台
        </Link>
        <Link
          href="/library"
          {...tourAnchorProps(TOUR_ANCHORS.navLibrary)}
          className={navLinkClass(isActive(pathname, '/library'))}
        >
          素材库
        </Link>
        {/* 素材工具链（处理/检索/工作流）收编为分组；navProcess 锚点挂在分组按钮上，指引时高亮此处 */}
        <div {...tourAnchorProps(TOUR_ANCHORS.navProcess)}>
          <NavDropdown label="素材工具" items={materialItems} active={groupActive(pathname, materialItems)} />
        </div>
        <NavDropdown label="剪辑" items={editItems} active={groupActive(pathname, editItems)} />
        <NavDropdown label="音频" items={audioItems} active={groupActive(pathname, audioItems)} />
        <Link
          href="/publish"
          className={navLinkClass(isActive(pathname, '/publish'), true)}
        >
          一键发布
        </Link>

        <div className="ml-auto flex items-center gap-1 pl-2">
          <button
            type="button"
            onClick={() => openOnboardingGuide()}
            className={clsx(
              'text-sm transition-colors rounded-md px-2.5 py-1.5 border whitespace-nowrap',
              'text-slate-400 border-transparent hover:text-violet-200 hover:border-violet-500/30 hover:bg-violet-600/10',
            )}
            title="查看新手指引"
          >
            <span className="inline-flex items-center gap-1">
              <BookOpen className="w-3.5 h-3.5" />
              指引
            </span>
          </button>
          <Link
            href="/settings"
            {...tourAnchorProps(TOUR_ANCHORS.navSettings)}
            className={navLinkClass(isActive(pathname, '/settings'))}
          >
            设置
          </Link>
          <NavDropdown
            label="更多"
            items={moreItems}
            active={groupActive(pathname, moreItems)}
            align="right"
          />
        </div>
      </nav>

      <div className="md:hidden flex items-center flex-1 justify-end">
        <button
          type="button"
          onClick={() => setMobileOpen((v) => !v)}
          className="p-2 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 transition-colors"
          aria-label={mobileOpen ? '关闭菜单' : '打开菜单'}
        >
          {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {mobileOpen ? (
        <div className="md:hidden absolute top-12 inset-x-0 border-b border-slate-800 bg-[#0d0f14]/98 backdrop-blur-md shadow-lg shadow-black/30 z-40">
          <div className="px-4 py-3 space-y-4 max-h-[calc(100vh-3rem)] overflow-y-auto styled-scrollbar">
            {mobileSections.map((section) => (
              <div key={section.title}>
                <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500 px-2 mb-1">
                  {section.title}
                </p>
                <div className="space-y-0.5">
                  {section.title === '常用' ? (
                    <button
                      type="button"
                      onClick={() => {
                        setMobileOpen(false)
                        openOnboardingGuide()
                      }}
                      className="w-full text-left block rounded-md px-3 py-2 text-sm text-violet-200 hover:bg-violet-600/15 transition-colors"
                    >
                      {guideMobileItem.label}
                      <span className="block text-xs text-slate-500 mt-0.5">{guideMobileItem.description}</span>
                    </button>
                  ) : null}
                  {section.items.map((item) => {
                    const active = isActive(pathname, item.href)
                    const accent = item.href === '/studio'
                    const tour = 'tour' in item ? item.tour : undefined
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        {...(tour ? tourAnchorProps(tour) : {})}
                        className={clsx(
                          'block rounded-md px-3 py-2 text-sm transition-colors',
                          accent
                            ? active
                              ? 'text-white bg-violet-600/25'
                              : 'text-violet-200 hover:bg-violet-600/15'
                            : active
                              ? 'text-slate-100 bg-slate-800/70'
                              : 'text-slate-300 hover:text-slate-100 hover:bg-slate-800/50',
                        )}
                      >
                        {item.label}
                        {'description' in item && item.description ? (
                          <span className="block text-xs text-slate-500 mt-0.5">{item.description}</span>
                        ) : null}
                      </Link>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
