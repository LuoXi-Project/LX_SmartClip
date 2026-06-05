'use client'

import clsx from 'clsx'
import { GripVertical } from 'lucide-react'
import {
  Group,
  Panel,
  Separator,
  type GroupProps,
  type PanelImperativeHandle,
  type PanelProps,
  type SeparatorProps,
} from 'react-resizable-panels'

export {
  Group,
  Panel,
  Separator,
  type GroupProps,
  type PanelImperativeHandle,
  type PanelProps,
  type SeparatorProps,
}

export function ResizablePanelGroup({ className, ...props }: GroupProps) {
  return (
    <Group
      className={clsx('flex h-full w-full data-[orientation=vertical]:flex-col', className)}
      {...props}
    />
  )
}

export function ResizablePanel(props: PanelProps) {
  return <Panel {...props} />
}

export function ResizableHandle({
  className,
  withHandle,
  ...props
}: SeparatorProps & { withHandle?: boolean }) {
  return (
    <Separator
      className={clsx(
        'relative flex w-px items-center justify-center bg-slate-800 transition-colors',
        'after:absolute after:inset-y-0 after:left-1/2 after:w-1 after:-translate-x-1/2',
        'hover:bg-violet-500/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-violet-500/50',
        'data-[orientation=vertical]:h-px data-[orientation=vertical]:w-full',
        'data-[orientation=vertical]:after:left-0 data-[orientation=vertical]:after:h-1',
        'data-[orientation=vertical]:after:w-full data-[orientation=vertical]:after:translate-x-0',
        className
      )}
      {...props}
    >
      {withHandle ? (
        <div className="z-10 flex h-6 w-3 items-center justify-center rounded-sm border border-slate-700 bg-slate-900">
          <GripVertical className="h-2.5 w-2.5 text-slate-500" />
        </div>
      ) : null}
    </Separator>
  )
}
