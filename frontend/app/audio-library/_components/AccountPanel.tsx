'use client'

import { Loader2, LogIn, RefreshCw, Trash2, ShieldCheck, UserX, Music2 } from 'lucide-react'
import type {
  AudioAccountResp,
  AudioLibraryStatusResp,
} from '@/lib/api'

interface AccountPanelProps {
  status: AudioLibraryStatusResp | null
  accounts: AudioAccountResp[]
  busySource: Record<string, 'login' | 'check' | undefined>
  onLogin: (source: string, account?: string) => void
  onCheck: (source: string, account?: string) => void
  onDelete: (source: string, account: string) => void
  /** 登录等待中用户点「我已完成登录」：手动解除 busy 并刷新状态 */
  onDoneLogin?: (source: string) => void
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  logged_in: { label: '已登录', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  logged_out: { label: '未登录', cls: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30' },
  expired: { label: '已失效', cls: 'bg-red-500/15 text-red-400 border-red-500/30' },
  guest: { label: '免登录', cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
}

export function AccountPanel({
  status,
  accounts,
  busySource,
  onLogin,
  onCheck,
  onDelete,
  onDoneLogin,
}: AccountPanelProps) {
  const sources = status?.sources ?? []
  const browserReady = status?.browser?.ready ?? false

  return (
    <div className="rounded-xl border border-slate-700/50 bg-[#161922] p-4">
      <div className="mb-3 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-emerald-400" />
        <h2 className="text-sm font-semibold text-zinc-200">音乐账号</h2>
      </div>

      {!browserReady && (
        <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          浏览器引擎未就绪，扫码登录不可用。搜索/下载仍可使用（网易云未登录仅能下免费曲）。
        </div>
      )}

      <div className="space-y-3">
        {sources.map((src) => {
          const srcAccounts = accounts.filter((a) => a.source === src.source)
          const busy = busySource[src.source]
          return (
            <div
              key={src.source}
              className="rounded-lg border border-slate-700/40 bg-[#0d0f14]/60 p-3"
            >
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Music2 className="h-3.5 w-3.5 text-zinc-400" />
                  <span className="text-sm font-medium text-zinc-200">{src.label}</span>
                </div>
                <span className="text-[10px] text-zinc-500">
                  {src.needs_login ? '需登录' : '免登录'}
                </span>
              </div>

              {/* 免登录源（酷我）：静态展示 */}
              {!src.needs_login ? (
                <div className="flex items-center justify-between">
                  <span className="rounded-full border border-sky-500/30 bg-sky-500/15 px-2 py-0.5 text-[11px] text-sky-400">
                    免登录，可直接搜索
                  </span>
                </div>
              ) : (
                <>
                  {/* 需登录源：账号列表 */}
                  {srcAccounts.length === 0 ? (
                    <div className="py-1 text-xs text-zinc-500">暂无账号，点击下方添加</div>
                  ) : (
                    <div className="space-y-2">
                      {srcAccounts.map((acc) => {
                        const sm = STATUS_META[acc.login_status] || STATUS_META.logged_out
                        return (
                          <div
                            key={`${acc.source}:${acc.account}`}
                            className="rounded-md bg-slate-800/40 px-3 py-2"
                          >
                            <div className="flex items-center justify-between">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="truncate text-sm text-zinc-200">
                                    {acc.display_name || acc.account}
                                  </span>
                                  <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${sm.cls}`}>
                                    {sm.label}
                                  </span>
                                </div>
                                <div className="mt-0.5 truncate text-[11px] text-zinc-500">
                                  @{acc.account}
                                  {acc.last_login_at &&
                                    ` · 登录于 ${new Date(acc.last_login_at).toLocaleDateString()}`}
                                </div>
                                {acc.last_error && (
                                  <div className="mt-0.5 truncate text-[11px] text-red-400/80">
                                    {acc.last_error}
                                  </div>
                                )}
                              </div>
                              <div className="flex shrink-0 items-center gap-1">
                                <button
                                  title="校验登录态"
                                  onClick={() => onCheck(acc.source, acc.account)}
                                  className="rounded p-1 text-zinc-400 hover:bg-slate-700/50 hover:text-zinc-200"
                                >
                                  {busy === 'check' ? (
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <RefreshCw className="h-3.5 w-3.5" />
                                  )}
                                </button>
                                <button
                                  title="删除账号"
                                  onClick={() => onDelete(acc.source, acc.account)}
                                  className="rounded p-1 text-zinc-400 hover:bg-red-500/20 hover:text-red-400"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}

                  <button
                    onClick={() => onLogin(src.source, 'main')}
                    disabled={busy === 'login'}
                    className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    {busy === 'login' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <LogIn className="h-3.5 w-3.5" />
                    )}
                    {busy === 'login' ? '登录中…请在浏览器完成' : '添加账号（扫码登录）'}
                  </button>
                  {busy === 'login' && onDoneLogin && (
                    <button
                      onClick={() => onDoneLogin(src.source)}
                      className="mt-1.5 w-full rounded-md border border-slate-600 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-emerald-500/60 hover:text-emerald-300"
                      title="在浏览器完成登录后点击，立即刷新登录状态"
                    >
                      我已完成登录
                    </button>
                  )}
                </>
              )}
            </div>
          )
        })}

        {sources.length === 0 && (
          <div className="flex items-center gap-2 py-2 text-xs text-zinc-500">
            <UserX className="h-3.5 w-3.5" /> 暂无可用音乐源
          </div>
        )}
      </div>
    </div>
  )
}
