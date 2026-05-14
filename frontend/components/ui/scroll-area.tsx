'use client'

import { forwardRef, type HTMLAttributes, type ReactNode } from 'react'
import clsx from 'clsx'

export type ScrollAreaProps = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode
}

/**
 * 带美化滚动条的可滚动容器（依赖 `globals.css` 中的 `.styled-scrollbar`）。
 * 在 Windows / WebKit 下使用细圆角滑块，Firefox 使用 `scrollbar-width: thin`。
 */
export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(function ScrollArea(
  { className, children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={clsx('styled-scrollbar overflow-auto', className)} {...rest}>
      {children}
    </div>
  )
})
