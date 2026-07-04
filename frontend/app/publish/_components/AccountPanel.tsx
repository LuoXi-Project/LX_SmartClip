'use client'

import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, LogIn, RefreshCw, Trash2, UserPlus } from 'lucide-react'
import clsx from 'clsx'
import type { PlatformInfo, PublishAccount } from './types'

interface AccountPanelProps {
  platforms: PlatformInfo[]
  accounts: PublishAccount[]
  /** platform → 是否有登录中/校验中操作 */
  busyPlatform: Record<string, 'login' | 'check' | undefined>
  onLogin: (platform: string, account: string) => void
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
  // 每平台"添加账号"输入框的临时状态：platform → 输入的账号名
  const [addingPlatform, setAddingPlatform] = useState<string | null>(null)
  const [newAccountName, setNewAccountName] = useState('')

  // 按平台分组账号
  const accountsByPlatform = (platform: string) =>
    accounts.filter((a) => a.platform === platform)

  const handleAddAccount = (platform: string) => {
    const name = newAccountName.trim() || 'main'
    setAddingPlatform(null)
    setNewAccountName('')
    onLogin(platform, name)
  }

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">账号管理</h2>
        <span className="text-xs text-slate-500">支持多平台、多账号</span>
      </div>

      {/* 按平台分组展示（含未实现的，标灰） */}
      <div className="space-y-2.5 styled-scrollbar overflow-y-auto pr-1 max-h-[420px]">
        {platforms.map((p) => {
          const platformAccounts = accountsByPlatform(p.platform)
          const busy = busyPlatform[p.platform]
          const disabled = !p.implemented

          return (
            <div
              key={p.platform}
              className={clsx(
                'rounded-md border px-3 py-2.5 space-y-2',
                disabled
                  ? 'border-slate-800/60 bg-slate-900/20 opacity-60'
                  : 'border-slate-800 bg-slate-900/30',
              )}
            >
              {/* 平台标题行 */}
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-200">{p.label}</span>
                <RiskBadge risk={p.risk} />
                {disabled && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">
                    即将支持
                  </span>
                )}
                {!disabled && platformAccounts.length > 0 && (
                  <span className="text-[10px] text-slate-500">
                    {platformAccounts.filter((a) => a.login_status === 'logged_in').length} 个已登录
                  </span>
                )}
                <span className="ml-auto text-[10px] text-slate-600">
                  {platformAccounts.length > 0 ? `${platformAccounts.length} 个账号` : ''}
                </span>
              </div>

              {/* 该平台下的账号列表 */}
              {platformAccounts.length > 0 && (
                <div className="space-y-1.5">
                  {platformAccounts.map((acc) => {
                    const loggedIn = acc.login_status === 'logged_in'
                    return (
                      <div
                        key={`${acc.platform}-${acc.account}`}
                        className="flex items-center gap-2 rounded bg-slate-950/30 px-2 py-1.5"
                      >
                        <span className="text-xs text-slate-300 font-medium min-w-[60px]">
                          {acc.account}
                        </span>
                        {loggedIn ? (
                          <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                            <CheckCircle2 className="w-3 h-3" />已登录
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[11px] text-amber-400/80">
                            <AlertCircle className="w-3 h-3" />{acc.login_status === 'expired' ? '已失效' : '未登录'}
                          </span>
                        )}
                        {acc.last_error && (
                          <span className="text-[10px] text-red-400/70 truncate" title={acc.last_error}>
                            {acc.last_error.slice(0, 30)}
                          </span>
                        )}

                        <div className="ml-auto flex items-center gap-1 shrink-0">
                          {loggedIn && (
                            <>
                              <button
                                type="button"
                                disabled={!!busy}
                                onClick={() => onCheck(p.platform, acc.account)}
                                className="p-1 rounded text-slate-400 hover:text-slate-200 disabled:opacity-40"
                                title="校验登录态"
                              >
                                {busy === 'check' ? (
                                  <Loader2 className="w-3 h-3 animate-spin" />
                                ) : (
                                  <RefreshCw className="w-3 h-3" />
                                )}
                              </button>
                              <button
                                type="button"
                                disabled={!!busy}
                                onClick={() => onDelete(p.platform, acc.account)}
                                className="p-1 rounded text-slate-400 hover:text-red-300 disabled:opacity-40"
                                title="删除账号"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                              <button
                                type="button"
                                disabled={!!busy}
                                onClick={() => onLogin(p.platform, acc.account)}
                                className="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-400 hover:text-slate-200 disabled:opacity-40"
                                title="重新登录此账号"
                              >
                                重登
                              </button>
                            </>
                          )}
                          {!loggedIn && (
                            <button
                              type="button"
                              disabled={!!busy}
                              onClick={() => onLogin(p.platform, acc.account)}
                              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-indigo-500/40 text-indigo-300 hover:border-indigo-400/60 disabled:opacity-40"
                            >
                              {busy === 'login' ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <LogIn className="w-3 h-3" />
                              )}
                              登录
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* 添加账号 / 首次登录 */}
              {!disabled && (
                <div>
                  {addingPlatform === p.platform ? (
                    <div className="flex items-center gap-1.5">
                      <input
                        type="text"
                        value={newAccountName}
                        onChange={(e) => setNewAccountName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleAddAccount(p.platform)
                          if (e.key === 'Escape') {
                            setAddingPlatform(null)
                            setNewAccountName('')
                          }
                        }}
                        placeholder="账号标识（如 main、backup）"
                        autoFocus
                        className="flex-1 bg-slate-950/60 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                      />
                      <button
                        type="button"
                        onClick={() => handleAddAccount(p.platform)}
                        className="text-xs px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white"
                      >
                        确定
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setAddingPlatform(null)
                          setNewAccountName('')
                        }}
                        className="text-xs px-2 py-1 rounded text-slate-400 hover:text-slate-200"
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        if (platformAccounts.length === 0) {
                          // 无账号时直接登录默认 main
                          onLogin(p.platform, 'main')
                        } else {
                          setAddingPlatform(p.platform)
                          setNewAccountName('')
                        }
                      }}
                      className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-indigo-300 transition-colors"
                    >
                      {platformAccounts.length === 0 ? (
                        <>
                          <LogIn className="w-3 h-3" />扫码登录
                        </>
                      ) : (
                        <>
                          <UserPlus className="w-3 h-3" />添加账号
                        </>
                      )}
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <p className="text-xs text-slate-500 leading-relaxed">
        点击「扫码登录」会打开对应平台，用手机 App 扫码完成登录。同一平台可登录多个账号（矩阵运营），
        账号标识用于区分（如 main、backup）。登录态保存在本地。
      </p>
    </section>
  )
}
