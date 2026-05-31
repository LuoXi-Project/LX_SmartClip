'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { ChevronDown } from 'lucide-react'
import clsx from 'clsx'

export interface NavDropdownItem {
  href: string
  label: string
  description?: string
}

interface NavDropdownProps {
  label: string
  items: NavDropdownItem[]
  active?: boolean
  align?: 'left' | 'right'
}

export function NavDropdown({ label, items, active, align = 'left' }: NavDropdownProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          'inline-flex items-center gap-1 text-sm transition-colors rounded-md px-2.5 py-1.5 border whitespace-nowrap',
          active
            ? 'text-slate-100 border-slate-500 bg-slate-800/70'
            : 'text-slate-400 border-transparent hover:text-slate-200 hover:border-slate-700',
          open && 'text-slate-200 border-slate-700 bg-slate-800/50',
        )}
      >
        {label}
        <ChevronDown className={clsx('w-3.5 h-3.5 opacity-70 transition-transform', open && 'rotate-180')} />
      </button>
      {open ? (
        <div
          className={clsx(
            'absolute top-full mt-1.5 min-w-[196px] py-1 rounded-lg border border-slate-700 bg-[#151820] shadow-xl shadow-black/40 z-50',
            align === 'right' ? 'right-0' : 'left-0',
          )}
        >
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="block px-3 py-2 text-sm text-slate-300 hover:text-slate-100 hover:bg-slate-800/80 transition-colors"
            >
              <span className="font-medium">{item.label}</span>
              {item.description ? (
                <span className="block text-xs text-slate-500 mt-0.5">{item.description}</span>
              ) : null}
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  )
}
