'use client'

import {
  useCallback,
  useMemo,
  useRef,
  type ComponentPropsWithoutRef,
  type RefObject,
} from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import GithubSlugger from 'github-slugger'
import { Play } from 'lucide-react'
import { API_BASE_URL } from '@/lib/runtime-config'

/** 将 `mm:ss` 或 `h:mm:ss` 转为从片头起的秒数 */
export function timeTokenToSec(t: string): number {
  const parts = t
    .trim()
    .split(':')
    .map((x) => parseInt(x, 10))
  if (parts.some((n) => Number.isNaN(n))) return 0
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  return 0
}

/** 秒数 → 与视频时间码一致的展示（含补零） */
export function formatSecondsAsTimecode(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
  return `${m}:${String(r).padStart(2, '0')}`
}

function resolveStorageSrc(src: string | undefined): string | undefined {
  if (!src) return src
  if (src.startsWith('/storage')) {
    const base = (API_BASE_URL || '').replace(/\/$/, '')
    return base ? `${base}${src}` : src
  }
  return src
}

function scrollElementIntoScrollParent(target: HTMLElement, scrollParent: HTMLElement, paddingTop = 12) {
  const pRect = scrollParent.getBoundingClientRect()
  const tRect = target.getBoundingClientRect()
  const nextTop = scrollParent.scrollTop + (tRect.top - pRect.top) - paddingTop
  scrollParent.scrollTo({ top: Math.max(0, nextTop), behavior: 'smooth' })
}

/** 去掉标题行末尾的时间/Content 标记，使 slug 与 rehype-slug（标题纯文本）一致 */
export function stripTrailingContentMarkerFromHeadingText(text: string): string {
  let t = text.trim()
  t = t.replace(/\s*\*Content-\[[^\]]+\]\s*$/i, '')
  t = t.replace(/\s*\*Content-\d{1,2}:\d{2}(?::\d{2})?\s*$/i, '')
  t = t.replace(/\s+\[[^\]]+\]\(video-time:\d+\)\s*$/g, '')
  return t.trim()
}

/** 仅处理 ##～######，去掉 *Content-* / 已替换的 video-time 链接，避免 slug 含杂质 */
function stripHeadingLinesContentMarkers(md: string): string {
  return md.replace(/^(#{2,6}\s+)(.+)$/gm, (_, pref: string, rest: string) => {
    return `${pref}${stripTrailingContentMarkerFromHeadingText(rest)}`
  })
}

/**
 * 独立一行的目录项 `[文字 0:00](#模型乱写的锚点)` → href 改为与 rehype-slug 一致的 #slug。
 * 与 rehype-slug 相同：github-slugger 按文中标题出现顺序生成 id。
 */
const TOC_LINE_RE =
  /^(\s*(?:[-*+]\s+|\d+\.\s+)?)(\[[^\]]+\])(\()#[^)]+(\)\s*)$/

function realignTocAnchorLinks(md: string): string {
  const lines = md.split('\n')
  const slugger = new GithubSlugger()
  const headings: { level: number; slug: string }[] = []

  for (const line of lines) {
    const hm = line.match(/^(#{1,6})\s+(.+)$/)
    if (!hm) continue
    const level = hm[1].length
    const core = stripTrailingContentMarkerFromHeadingText(hm[2].trim())
    headings.push({ level, slug: slugger.slug(core) })
  }

  const slugsH2 = headings.filter((h) => h.level >= 2).map((h) => h.slug)
  const slugsAll = headings.map((h) => h.slug)
  const tocLines = lines.filter((ln) => TOC_LINE_RE.test(ln))

  let slugSeq: string[] = []
  if (tocLines.length > 0 && tocLines.length === slugsH2.length) {
    slugSeq = slugsH2
  } else if (tocLines.length > 0 && tocLines.length === slugsAll.length) {
    slugSeq = slugsAll
  } else if (tocLines.length > 0 && slugsH2.length > 0) {
    const n = Math.min(tocLines.length, slugsH2.length)
    slugSeq = slugsH2.slice(0, n)
  } else {
    return md
  }

  let si = 0
  return lines
    .map((line) => {
      const m = line.match(TOC_LINE_RE)
      if (!m || si >= slugSeq.length) return line
      const next = `${m[1]}${m[2]}${m[3]}#${slugSeq[si]}${m[4]}`
      si += 1
      return next
    })
    .join('\n')
}

function findHeadingInContainer(container: HTMLElement, href: string): HTMLElement | null {
  const raw = href.startsWith('#') ? href.slice(1) : href
  let id = raw
  try {
    id = decodeURIComponent(raw)
  } catch {
    /* keep raw */
  }
  if (!id) return null
  const el = container.querySelector(`#${CSS.escape(id)}`)
  return el instanceof HTMLElement ? el : null
}

function summaryUrlTransform(url: string): string {
  if (url.startsWith('video-time:')) return url
  return defaultUrlTransform(url)
}

/**
 * *Content-[mm:ss] 或模型常写的 *Content-mm:ss → video-time 链接（正文内由按钮+播放图标渲染）。
 * 截图由后端替换为图片，此处不处理 *Screenshot-*。
 */
export function preprocessNoteMarkdown(md: string): string {
  let s = stripHeadingLinesContentMarkers(md)
  s = realignTocAnchorLinks(s)
  const toLink = (_: string, t: string) => {
    const sec = timeTokenToSec(t)
    return `[${formatSecondsAsTimecode(sec)}](video-time:${sec})`
  }
  s = s.replace(/\*Content-\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, toLink)
  s = s.replace(/\*Content-(\d{1,2}:\d{2}(?::\d{2})?)/g, toLink)
  return s
}

const mdContainer =
  'text-slate-200 text-sm leading-relaxed [&_h1]:text-xl [&_h1]:font-semibold [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:scroll-mt-3 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:scroll-mt-3 [&_h3]:text-base [&_h3]:font-medium [&_h3]:mt-3 [&_h3]:scroll-mt-3 [&_h4]:scroll-mt-3 [&_p]:my-2 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5 [&_blockquote]:border-l-2 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_blockquote]:my-3 [&_blockquote]:text-slate-300 [&_code]:text-cyan-200 [&_code]:bg-slate-800/80 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[13px] [&_pre]:bg-slate-900 [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:overflow-x-auto [&_a]:break-words [&_img]:max-w-full [&_img]:rounded-lg [&_img]:border [&_img]:border-slate-700'

type Props = {
  markdown: string
  videoId: string | null
  className?: string
  /** 笔记外层可滚动容器；传入后目录 `#锚点` 只在此区域内滚动，不带动整页 */
  scrollContainerRef?: RefObject<HTMLElement | null>
}

export function SummaryNotePreview({
  markdown,
  videoId,
  className = '',
  scrollContainerRef,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)

  const seek = useCallback((sec: number) => {
    const el = videoRef.current
    if (!el || !Number.isFinite(sec)) return
    el.currentTime = Math.max(0, sec)
    void el.play().catch(() => {})
  }, [])

  const processed = useMemo(() => preprocessNoteMarkdown(markdown), [markdown])

  const streamUrl = videoId
    ? `${(API_BASE_URL || '').replace(/\/$/, '')}/api/videos/${videoId}/stream`
    : ''

  const components = useMemo(
    () => ({
      a: ({ href, children, onClick: upstreamOnClick, ...rest }: ComponentPropsWithoutRef<'a'>) => {
        if (href?.startsWith('video-time:')) {
          const raw = href.replace('video-time:', '')
          const sec = Math.max(0, Math.floor(Number.parseFloat(raw) || 0))
          const label = formatSecondsAsTimecode(sec)
          return (
            <button
              type="button"
              className="inline-flex items-center gap-1 align-middle rounded-md border border-cyan-700/50 bg-cyan-950/40 px-1.5 py-0.5 text-xs font-medium text-cyan-300 hover:border-cyan-500/70 hover:bg-cyan-900/40 hover:text-cyan-200 cursor-pointer"
              title={`在上方预览中跳转到 ${label}`}
              aria-label={`跳转到视频 ${label}`}
              onClick={(e) => {
                e.preventDefault()
                seek(sec)
              }}
            >
              <Play className="w-3.5 h-3.5 shrink-0 fill-cyan-400/30 text-cyan-400" aria-hidden />
              <span className="tabular-nums tracking-tight">{label}</span>
            </button>
          )
        }
        if (href?.startsWith('#')) {
          return (
            <a
              href={href}
              className="text-cyan-400/90 underline hover:text-cyan-300"
              {...rest}
              onClick={(e) => {
                upstreamOnClick?.(e)
                if (e.defaultPrevented) return
                const root = scrollContainerRef?.current
                if (!root) return
                const target = findHeadingInContainer(root, href)
                if (!target) return
                e.preventDefault()
                scrollElementIntoScrollParent(target, root)
              }}
            >
              {children}
            </a>
          )
        }
        if (href && /^https?:\/\//i.test(href)) {
          return (
            <a
              href={href}
              className="text-cyan-400/90 underline hover:text-cyan-300"
              target="_blank"
              rel="noreferrer"
              {...rest}
            >
              {children}
            </a>
          )
        }
        return (
          <a href={href} className="text-cyan-400/90 underline hover:text-cyan-300" {...rest}>
            {children}
          </a>
        )
      },
      img: ({ src, alt, ...rest }: ComponentPropsWithoutRef<'img'>) => {
        const resolved = resolveStorageSrc(src || undefined)
        return (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt={alt || ''}
            className="max-w-full rounded-lg border border-slate-700 my-2"
            loading="lazy"
            {...rest}
          />
        )
      },
    }),
    [seek, scrollContainerRef],
  )

  return (
    <div className={className}>
      {streamUrl ? (
        <video
          ref={videoRef}
          src={streamUrl}
          controls
          className="w-full max-h-[min(280px,40vh)] rounded-lg border border-slate-800 bg-black object-contain"
          preload="metadata"
        />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/50 p-6 text-center text-sm text-slate-500">
          选择素材视频后，此处可预览画面；笔记里带时间点的链接可点击跳转。
        </div>
      )}
      <div className={`mt-4 ${mdContainer}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSlug]}
          urlTransform={summaryUrlTransform}
          components={components}
        >
          {processed || '（暂无内容）'}
        </ReactMarkdown>
      </div>
    </div>
  )
}
