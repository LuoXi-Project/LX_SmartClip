'use client'

import { AlertCircle, CheckCircle2, Loader2, LogIn, RefreshCw, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import type { PlatformInfo, PublishAccount } from './types'

interface AccountPanelProps {
  platforms: PlatformInfo[]
  accounts: PublishAccount[]
  /** platform → 是否有登录中/校验中操作 */
  busyPlatform: Record<string, 'login' | 'check' | undefined>
  onLogin: (platform: string) => void
  onCheck: (platform: string, account: string) => void
  onDelete: (platform: string, account: string) => void
}

/** 风控等级标签。 */
function RiskBadge({ risk }: { risk: string }) {
  if (risk === 'strict') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/15 text-red-300 border border-red-500/30">
        风控严
      </span>
    )
  }
  if (risk === 'low') {
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
        稳定
      </span>
    )
  }
  return null
}

export function AccountPanel({
  platforms,
  accounts,
  busyPlatform,
  onLogin,
  onCheck,
  onDelete,
}: AccountPanelProps) {
  // 仅展示已实现的平台
  const implemented = platforms.filter((p) => p.implemented)

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">账号管理</h2>
        <span className="text-xs text-slate-500">扫码登录各平台创作者中心</span>
      </div>

      {implemented.length === 0 ? (
        <div className="text-sm text-slate-500 py-2">暂无可用的发布平台</div>
      ) : (
        <div className="space-y-2">
          {implemented.map((p) => {
            const acc = accounts.find(
              (a) => a.platform === p.platform && a.login_status === 'logged_in',
            )
            const busy = busyPlatform[p.platform]
            const loggedIn = !!acc
            return (
              <div
                key={p.platform}
                className="flex items-center gap-3 rounded-md border border-slate-800 bg-slate-900/30 px-3 py-2.5"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-200">{p.label}</span>
                    <RiskBadge risk={p.risk} />
                    {loggedIn ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                        <CheckCircle2 className="w-3 h-3" />已登录
                        {acc?.last_login_at && (
                          <span className="text-slate-500">
                            {new Date(acc.last_login_at).toLocaleDateString()}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-slate-500">
                        <AlertCircle className="w-3 h-3" />未登录
                      </span>
                    )}
                  </div>
                  {acc?.last_error && (
                    <div className="text-xs text-red-400 mt-0.5 truncate">{acc.last_error}</div>
                  )}
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {loggedIn && (
                    <>
                      <button
                        type="button"
                        disabled={!!busy}
                        onClick={() => onCheck(p.platform, acc.account)}
                        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-700 text-slate-300 hover:border-slate-600 hover:text-slate-100 disabled:opacity-50 transition-colors"
                        title="校验登录态是否仍有效"
                      >
                        {busy === 'check' ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <RefreshCw className="w-3 h-3" />
                        )}
                        校验
                      </button>
                      <button
                        type="button"
                        disabled={!!busy}
                        onClick={() => onDelete(p.platform, acc.account)}
                        className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-700 text-slate-400 hover:border-red-500/50 hover:text-red-300 disabled:opacity-50 transition-colors"
                        title="删除账号（清除本地 cookie）"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() => onLogin(p.platform)}
                    className={clsx(
                      'inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded border transition-colors disabled:opacity-50',
                      loggedIn
                        ? 'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                        : 'border-indigo-500/40 text-indigo-300 hover:border-indigo-400/60 hover:text-indigo-200 bg-indigo-600/10',
                    )}
                  >
                    {busy === 'login' ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <LogIn className="w-3 h-3" />
                    )}
                    {loggedIn ? '重新登录' : '扫码登录'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <p className="text-xs text-slate-500 leading-relaxed">
        点击「扫码登录」会在新窗口打开对应平台，用手机 App 扫码完成登录。登录态保存在本地，
        关闭软件后仍有效。各平台 cookie 有时效，过期后需重新登录。
      </p>
    </section>
  )
}
