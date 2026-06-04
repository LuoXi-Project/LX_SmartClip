'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { KeyRound, Loader2 } from 'lucide-react'
import { licenseApi } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'

export default function LicensePage() {
  const toastApi = useToast()
  const [card, setCard] = useState('')
  const [loading, setLoading] = useState(false)
  const [statusLoading, setStatusLoading] = useState(true)
  const [enforced, setEnforced] = useState(false)
  const [hasServerConfig, setHasServerConfig] = useState(false)
  const [valid, setValid] = useState(false)

  useEffect(() => {
    licenseApi
      .status()
      .then((s) => {
        setEnforced(s.enforced)
        setHasServerConfig(s.has_server_config)
        setValid(s.valid)
      })
      .catch(() => toastApi.error('无法连接后端，请确认服务已启动。'))
      .finally(() => setStatusLoading(false))
  }, [toastApi])

  async function onActivate() {
    setLoading(true)
    try {
      const r = await licenseApi.activate(card.trim())
      toastApi.success(r.message || '激活成功')
      setValid(true)
      setCard('')
    } catch (e: unknown) {
      const msg =
        typeof e === 'object' && e !== null && 'response' in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined
      toastApi.error(typeof msg === 'string' ? msg : '激活失败')
    } finally {
      setLoading(false)
    }
  }

  if (statusLoading) {
    return (
      <div className="max-w-md mx-auto px-6 py-16 flex justify-center text-slate-400">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    )
  }

  if (!enforced) {
    return (
      <div className="max-w-md mx-auto px-6 py-16 space-y-4">
        <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <KeyRound className="h-5 w-5" />
          卡密授权（开发模式）
        </h1>
        <p className="text-slate-400 text-sm">
          当前后端返回未强制鉴权状态。新版本后端默认强制卡密校验，请确保前后端版本一致。
        </p>
        <Link href="/" className="text-sm text-sky-400 hover:text-sky-300">
          返回首页
        </Link>
      </div>
    )
  }

  if (!hasServerConfig) {
    return (
      <div className="max-w-md mx-auto px-6 py-16 space-y-4">
        <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <KeyRound className="h-5 w-5" />
          缺少卡密服务器配置
        </h1>
        <p className="text-slate-400 text-sm">
          请在 <code className="text-slate-300">backend</code> 目录放置 <code className="text-slate-300">config.json</code>
          ，并填写 <code className="text-slate-300">卡密服务器.API地址</code>（可参考 <code className="text-slate-300">config.example.json</code>
          ）。未配置时所有业务接口不可用，无法通过删除配置文件绕过。
        </p>
        <p className="text-amber-200/80 text-xs">本地开发同样需要配置卡密服务器地址，未配置时无法激活与使用业务接口。</p>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto px-6 py-16 space-y-6">
      <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
        <KeyRound className="h-5 w-5" />
        卡密激活
      </h1>
      {valid ? (
        <p className="text-emerald-400/90 text-sm">当前设备已通过验证，可返回应用使用。</p>
      ) : (
        <p className="text-slate-400 text-sm">
          请先输入卡密完成激活。卡密会保存在本机数据库中，不会出现在「设置」配置列表里。
        </p>
      )}
      <div className="space-y-2">
        <label className="text-xs text-slate-500">卡密</label>
        <input
          type="password"
          autoComplete="off"
          value={card}
          onChange={(e) => setCard(e.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500"
          placeholder="输入卡密"
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={loading || !card.trim()}
          onClick={() => void onActivate()}
          className="inline-flex items-center gap-2 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          激活
        </button>
        {valid ? (
          <Link
            href="/"
            className="inline-flex items-center rounded-md border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800/80"
          >
            进入应用
          </Link>
        ) : null}
      </div>
    </div>
  )
}
