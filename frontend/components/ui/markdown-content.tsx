'use client'

import type { ComponentPropsWithoutRef } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'

/** 暗色主题 Markdown 排版（不依赖 @tailwindcss/typography） */
export const markdownProseClassName =
  'text-slate-200 text-sm leading-relaxed break-words ' +
  '[&_h1]:text-xl [&_h1]:font-semibold [&_h1]:mt-4 [&_h1]:mb-2 ' +
  '[&_h2]:text-lg [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2 ' +
  '[&_h3]:text-base [&_h3]:font-medium [&_h3]:mt-3 [&_h3]:mb-1.5 ' +
  '[&_h4]:text-sm [&_h4]:font-medium [&_h4]:mt-2 [&_h4]:mb-1 ' +
  '[&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 ' +
  '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 ' +
  '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 ' +
  '[&_li]:my-0.5 ' +
  '[&_blockquote]:border-l-2 [&_blockquote]:border-slate-600 [&_blockquote]:pl-3 [&_blockquote]:my-3 [&_blockquote]:text-slate-300 ' +
  '[&_hr]:my-4 [&_hr]:border-slate-700 ' +
  '[&_strong]:font-semibold [&_strong]:text-slate-100 ' +
  '[&_em]:italic [&_em]:text-slate-300 ' +
  '[&_del]:text-slate-500 [&_del]:line-through ' +
  '[&_a]:text-cyan-400 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-cyan-300 ' +
  '[&_img]:max-w-full [&_img]:rounded-lg [&_img]:border [&_img]:border-slate-700 ' +
  '[&_input[type=checkbox]]:mr-2 [&_input[type=checkbox]]:accent-emerald-500'

export const baseMarkdownComponents: Components = {
  table: ({ children, ...props }: ComponentPropsWithoutRef<'table'>) => (
    <div className="my-3 w-full overflow-x-auto rounded-lg border border-slate-700/80 bg-slate-950/40">
      <table className="w-full min-w-full border-collapse text-xs" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }: ComponentPropsWithoutRef<'thead'>) => (
    <thead className="bg-slate-800/80" {...props}>
      {children}
    </thead>
  ),
  tbody: ({ children, ...props }: ComponentPropsWithoutRef<'tbody'>) => (
    <tbody className="divide-y divide-slate-800" {...props}>
      {children}
    </tbody>
  ),
  tr: ({ children, ...props }: ComponentPropsWithoutRef<'tr'>) => (
    <tr className="border-b border-slate-800 last:border-b-0" {...props}>
      {children}
    </tr>
  ),
  th: ({ children, ...props }: ComponentPropsWithoutRef<'th'>) => (
    <th
      className="border border-slate-700 px-2.5 py-1.5 text-left font-medium text-slate-100 whitespace-nowrap"
      {...props}
    >
      {children}
    </th>
  ),
  td: ({ children, ...props }: ComponentPropsWithoutRef<'td'>) => (
    <td className="border border-slate-800 px-2.5 py-1.5 text-slate-300 align-top" {...props}>
      {children}
    </td>
  ),
  pre: ({ children, ...props }: ComponentPropsWithoutRef<'pre'>) => (
    <pre
      className="my-3 overflow-x-auto rounded-lg bg-slate-900 border border-slate-800 p-3 text-[13px] leading-relaxed"
      {...props}
    >
      {children}
    </pre>
  ),
  code: ({ className, children, ...props }: ComponentPropsWithoutRef<'code'>) => {
    const isBlock = Boolean(className?.includes('language-'))
    if (isBlock) {
      return (
        <code className={clsx('text-cyan-200 font-mono', className)} {...props}>
          {children}
        </code>
      )
    }
    return (
      <code
        className="text-cyan-200 bg-slate-800/80 px-1.5 py-0.5 rounded text-[13px] font-mono"
        {...props}
      >
        {children}
      </code>
    )
  },
}

type MarkdownContentProps = {
  children: string
  className?: string
  components?: Components
}

export function MarkdownContent({ children, className, components }: MarkdownContentProps) {
  return (
    <div className={clsx(markdownProseClassName, className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ ...baseMarkdownComponents, ...components }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
