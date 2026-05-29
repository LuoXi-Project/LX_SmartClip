'use client'

import {
  Fragment,
  isValidElement,
  useCallback,
  useMemo,
  useRef,
  type ComponentPropsWithoutRef,
  type ReactNode,
  type RefObject,
} from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeSlug from 'rehype-slug'
import GithubSlugger from 'github-slugger'
import { Play } from 'lucide-react'
import { API_BASE_URL } from '@/lib/runtime-config'
import { baseMarkdownComponents, markdownProseClassName } from '@/components/ui/markdown-content'

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

/** 与后端 `screenshots._SCREENSHOT_*_RE` 一致：先 [] 再裸时间码 */
const SCREENSHOT_BRACKET_PH = /\*Screenshot-\[(\d{1,2}:\d{2}(?::\d{2})?)\]\*?/g
const SCREENSHOT_RAW_PH = /\*Screenshot-(\d{1,2}:\d{2}(?::\d{2})?)\*?/g

function screenshotPlaceholderToPreviewBlock(_full: string, token: string): string {
  const t = token.trim()
  if (!t) return _full
  return `\n\n> **原片截图** @ \`${t}\`（生成完成后由服务端替换为图片）\n\n`
}

/** 去掉标题行末尾的时间/Content/Screenshot 标记，使 slug 与 rehype-slug（标题纯文本）一致 */
export function stripTrailingContentMarkerFromHeadingText(text: string): string {
  let t = text.trim()
  t = t.replace(/\s*\*Content-\[[^\]]+\]\*?\s*$/i, '')
  t = t.replace(/\s*\*Content-\d{1,2}:\d{2}(?::\d{2})?\*?\s*$/i, '')
  t = t.replace(/\s*\*Screenshot-\[(\d{1,2}:\d{2}(?::\d{2})?)\]\*?\s*$/i, '')
  t = t.replace(/\s*\*Screenshot-(\d{1,2}:\d{2}(?::\d{2})?)\*?\s*$/i, '')
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

/**
 * 目录行 `[标题 *Content-0:00](#…)` 中的 *Content 若被全局替换会变成嵌套 `[]()`，解析错乱。
 * 仅把目录链接文字里的 *Content 规范成「标题 + 空格 + 时间码」，与正文替换逻辑一致但不破坏链接。
 */
function normalizeTocLinkContentMarkers(md: string): string {
  return md
    .split('\n')
    .map((line) => {
      const m = line.match(TOC_LINE_RE)
      if (!m) return line
      const bracket = m[2]
      const inner = bracket.slice(1, -1)
      const next = inner
        .replace(/\s*\*Content-\[(\d{1,2}:\d{2}(?::\d{2})?)\]\*?\s*/gi, ' $1')
        .replace(/\s*\*Content-(\d{1,2}:\d{2}(?::\d{2})?)\*?\s*/gi, ' $1')
        .replace(/\s+/g, ' ')
        .trim()
      if (next === inner) return line
      return line.replace(bracket, `[${next}]`)
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

/** 目录链接标签内换行会导致解析异常或露出 []()；压成一行；`] (` 间允许空白 */
function collapseHashLinkLabels(md: string): string {
  return md.replace(/\[([\s\S]*?)\]\s*\((#[^)]+)\)/g, (full, inner: string, dest: string, offset: number) => {
    if (offset > 0 && md[offset - 1] === '!') return full
    const oneLine = inner.replace(/\s+/g, ' ').trim()
    return `[${oneLine}](${dest})`
  })
}

function plainTextFromChildren(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(plainTextFromChildren).join('')
  if (isValidElement(node)) {
    const { type, props } = node
    const p = props as { children?: ReactNode }
    if (type === Fragment && p.children !== undefined && p.children !== null) {
      return plainTextFromChildren(p.children)
    }
    if (p.children !== undefined && p.children !== null) return plainTextFromChildren(p.children)
  }
  if (typeof node === 'object' && node !== null && 'props' in node) {
    const p = (node as { props?: { children?: ReactNode } }).props
    if (p?.children !== undefined && p.children !== null) return plainTextFromChildren(p.children)
  }
  return ''
}

/** 目录项「标题 0:00」拆成标题 + 时间，仅用于展示 */
function splitTocLabel(text: string): { title: string; time: string | null } {
  const t = text.replace(/\s+/g, ' ').trim()
  const m = t.match(/^(.*?)\s+(\d{1,2}:\d{2}(?::\d{2})?)$/)
  if (m) return { title: m[1].trim(), time: m[2] }
  return { title: t, time: null }
}

/**
 * *Content-[mm:ss] / *Content-mm:ss / 模型常写的行尾多一个 * → video-time 链接（**不会**生成截图；截图须用 *Screenshot-*）。
 * *Screenshot-*：流式/未落盘时占位符易被解析成强调，此处先规范为引用块；已替换的 `![](/storage/...)` 不受影响。
 */
export function preprocessNoteMarkdown(md: string): string {
  let s = md.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  s = stripHeadingLinesContentMarkers(s)
  s = collapseHashLinkLabels(s)
  s = normalizeTocLinkContentMarkers(s)
  s = realignTocAnchorLinks(s)
  const toLink = (_: string, t: string) => {
    const sec = timeTokenToSec(t)
    return `[${formatSecondsAsTimecode(sec)}](video-time:${sec})`
  }
  s = s.replace(/\*Content-\[(\d{1,2}:\d{2}(?::\d{2})?)\]\*?/g, toLink)
  s = s.replace(/\*Content-(\d{1,2}:\d{2}(?::\d{2})?)\*?/g, toLink)
  s = s.replace(SCREENSHOT_BRACKET_PH, screenshotPlaceholderToPreviewBlock)
  s = s.replace(SCREENSHOT_RAW_PH, screenshotPlaceholderToPreviewBlock)
  return s
}

const noteMarkdownClassName =
  `${markdownProseClassName} ` +
  '[&_h1]:scroll-mt-3 [&_h2]:scroll-mt-3 [&_h3]:scroll-mt-3 [&_h4]:scroll-mt-3'

type Props = {
  markdown: string
  videoId: string | null
  className?: string
  /** 笔记外层可滚动容器；传入后目录 `#锚点` 只在此区域内滚动，不带动整页 */
  scrollContainerRef?: RefObject<HTMLElement | null>
  /**
   * 传入后不在本组件内渲染 `<video>`，时间点跳转使用该 ref（由父级放在滚动区外）。
   */
  externalVideoRef?: RefObject<HTMLVideoElement | null>
}

export function SummaryNotePreview({
  markdown,
  videoId,
  className = '',
  scrollContainerRef,
  externalVideoRef,
}: Props) {
  const internalVideoRef = useRef<HTMLVideoElement>(null)
  const videoRef = externalVideoRef ?? internalVideoRef
  const embedVideo = externalVideoRef == null

  const seek = useCallback((sec: number) => {
    const el = videoRef.current
    if (!el || !Number.isFinite(sec)) return
    el.currentTime = Math.max(0, sec)
    void el.play().catch(() => {})
  }, [videoRef])

  const processed = useMemo(() => preprocessNoteMarkdown(markdown), [markdown])

  const streamUrl = useMemo(() => {
    if (!embedVideo || !videoId) return ''
    const base = (API_BASE_URL || '').replace(/\/$/, '')
    return `${base}/api/videos/${videoId}/stream`
  }, [embedVideo, videoId])

  const components = useMemo(
    () => ({
      ...baseMarkdownComponents,
      a: ({ href, children, onClick: upstreamOnClick, ...rest }: ComponentPropsWithoutRef<'a'>) => {
        if (href?.startsWith('video-time:')) {
          const raw = href.replace('video-time:', '')
          const sec = Math.max(0, Math.floor(Number.parseFloat(raw) || 0))
          const label = formatSecondsAsTimecode(sec)
          return (
            <button
              type="button"
              className="inline-flex items-center gap-1 align-middle rounded-md border border-cyan-700/50 bg-cyan-950/40 px-1.5 py-0.5 text-xs font-medium text-cyan-300 hover:border-cyan-500/70 hover:bg-cyan-900/40 hover:text-cyan-200 cursor-pointer"
              title={`跳转到视频 ${label}`}
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
          const label = plainTextFromChildren(children).replace(/\s+/g, ' ').trim()
          const { title, time } = splitTocLabel(label)
          const mainText = time ? title : label || title

          const onTocHeadingClick = (e: React.MouseEvent<HTMLButtonElement>) => {
            ;(upstreamOnClick as ((ev: React.MouseEvent<HTMLElement>) => void) | undefined)?.(e)
            if (e.defaultPrevented) return
            const root = scrollContainerRef?.current
            if (!root) return
            const target = findHeadingInContainer(root, href)
            if (!target) return
            e.preventDefault()
            scrollElementIntoScrollParent(target, root)
          }

          if (time != null) {
            const sec = timeTokenToSec(time)
            return (
              <div className="group flex w-full max-w-full items-center gap-1 rounded-md border border-transparent px-1 py-0.5 -mx-1 hover:bg-slate-800/55 hover:border-slate-700/80 focus-within:outline-none focus-within:ring-1 focus-within:ring-cyan-600/70">
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left rounded px-2 py-1.5 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-600/70"
                  title={label || '跳转到本节'}
                  aria-label={`跳转到本节：${mainText}`}
                  onClick={onTocHeadingClick}
                >
                  <span className="text-slate-200 group-hover:text-cyan-100/95">{mainText}</span>
                </button>
                <button
                  type="button"
                  className="inline-flex shrink-0 items-center gap-0.5 rounded-md border border-cyan-700/50 bg-cyan-950/40 px-1.5 py-0.5 text-xs font-medium text-cyan-300 hover:border-cyan-500/70 hover:bg-cyan-900/40 hover:text-cyan-200 cursor-pointer"
                  title={`跳转到视频 ${time}`}
                  aria-label={`跳转到视频 ${time}`}
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    seek(sec)
                  }}
                >
                  <Play className="h-3 w-3 shrink-0 fill-cyan-400/30 text-cyan-400" aria-hidden />
                  <span className="tabular-nums tracking-tight">{time}</span>
                </button>
              </div>
            )
          }

          return (
            <button
              type="button"
              className="group w-full max-w-full text-left rounded-md px-2 py-1.5 -mx-1 border border-transparent hover:bg-slate-800/55 hover:border-slate-700/80 focus:outline-none focus-visible:ring-1 focus-visible:ring-cyan-600/70"
              title={label || '跳转到本节'}
              onClick={onTocHeadingClick}
            >
              {label ? (
                <span className="text-slate-200 group-hover:text-cyan-100/95">{mainText}</span>
              ) : (
                <span className="text-slate-200 group-hover:text-cyan-100/95">{children}</span>
              )}
            </button>
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
      {embedVideo ? (
        /* 与外层滚动区 padding 对齐（常见为 px-3），避免长文滚动时视频滚出视区 */
        <div className="sticky top-0 z-10 -mx-3 px-3 pt-0 pb-3 mb-1 bg-[#0d0f14] border-b border-slate-800/80 shadow-[0_10px_24px_-10px_rgba(0,0,0,0.75)]">
          {streamUrl ? (
            <video
              ref={internalVideoRef}
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
        </div>
      ) : null}
      <div className={`${embedVideo ? 'pt-1 ' : ''}${noteMarkdownClassName}`}>
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
