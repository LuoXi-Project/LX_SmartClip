'use client'

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

interface PaginationProps {
  page: number
  totalPages: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

const PAGE_SIZES = [12, 24, 48]

function buildPageNumbers(page: number, total: number): (number | '…')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  if (page <= 4) return [1, 2, 3, 4, 5, '…', total]
  if (page >= total - 3) return [1, '…', total - 4, total - 3, total - 2, total - 1, total]
  return [1, '…', page - 1, page, page + 1, '…', total]
}

function NavBtn({
  onClick,
  disabled,
  title,
  children,
}: {
  onClick: () => void
  disabled: boolean
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="w-8 h-8 flex items-center justify-center rounded text-slate-400 hover:text-slate-200 hover:bg-slate-700/60 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
    >
      {children}
    </button>
  )
}

export function Pagination({
  page,
  totalPages,
  pageSize,
  onPageChange,
  onPageSizeChange,
}: PaginationProps) {
  if (totalPages <= 1 && pageSize === PAGE_SIZES[0]) return null

  const pages = buildPageNumbers(page, totalPages)

  return (
    <div className="mt-8 flex items-center justify-between flex-wrap gap-4">
      {/* page size selector */}
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <span>每页</span>
        <div className="flex gap-1">
          {PAGE_SIZES.map((s) => (
            <button
              key={s}
              onClick={() => onPageSizeChange(s)}
              className={`w-9 h-7 rounded text-xs transition-colors ${
                pageSize === s
                  ? 'bg-cyan-600/80 text-white font-medium'
                  : 'bg-slate-800/60 text-slate-400 hover:bg-slate-700 hover:text-slate-300'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <span>个</span>
      </div>

      {/* page navigation */}
      {totalPages > 1 && (
        <div className="flex items-center gap-1">
          <NavBtn onClick={() => onPageChange(1)} disabled={page === 1} title="第一页">
            <ChevronsLeft className="w-4 h-4" />
          </NavBtn>
          <NavBtn onClick={() => onPageChange(page - 1)} disabled={page === 1} title="上一页">
            <ChevronLeft className="w-4 h-4" />
          </NavBtn>

          {pages.map((p, i) =>
            p === '…' ? (
              <span
                key={`ellipsis-${i}`}
                className="w-8 text-center text-slate-500 text-sm select-none"
              >
                …
              </span>
            ) : (
              <button
                key={p}
                onClick={() => onPageChange(p as number)}
                className={`w-8 h-8 rounded text-sm transition-colors ${
                  page === p
                    ? 'bg-cyan-600/80 text-white font-medium'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/60'
                }`}
              >
                {p}
              </button>
            )
          )}

          <NavBtn onClick={() => onPageChange(page + 1)} disabled={page === totalPages} title="下一页">
            <ChevronRight className="w-4 h-4" />
          </NavBtn>
          <NavBtn onClick={() => onPageChange(totalPages)} disabled={page === totalPages} title="最后一页">
            <ChevronsRight className="w-4 h-4" />
          </NavBtn>
        </div>
      )}
    </div>
  )
}
