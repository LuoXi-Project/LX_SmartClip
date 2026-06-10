'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  Download,
  ExternalLink,
  HardDriveDownload,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import apiClient from '@/lib/api'

interface VersionInfo {
  app_version: string
  schema_version: number
  current_schema_version: number
  release_repo: string
}

interface UpdateCheckResult {
  current_version: string
  latest_version: string
  tag: string
  has_update: boolean
  download_url: string
  asset_name: string
  release_url: string
  published_at: string
  release_notes: string
  breaking: boolean
  requires_backup: boolean
  min_schema_version: number
  target_schema_version: number
  schema_version: number
}

export function UpdateSection() {
  const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null)
  const [checkResult, setCheckResult] = useState<UpdateCheckResult | null>(null)
  const [loadingVersion, setLoadingVersion] = useState(true)
  const [checking, setChecking] = useState(false)
  const [backingUp, setBackingUp] = useState(false)
  const [applying, setApplying] = useState(false)
  const [backupConfirmed, setBackupConfirmed] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    apiClient
      .get<unknown, VersionInfo>('/api/system/version')
      .then(setVersionInfo)
      .catch(() => setError('无法读取版本信息'))
      .finally(() => setLoadingVersion(false))
  }, [])

  const handleCheck = useCallback(async (force = false) => {
    setChecking(true)
    setError('')
    setMessage('')
    try {
      const data = await apiClient.get<unknown, UpdateCheckResult>(
        `/api/system/update/check${force ? '?force=true' : ''}`
      )
      setCheckResult(data)
      if (!data.has_update) {
        setMessage('当前已是最新版本')
      }
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '检查更新失败，请确认网络与 release.config.json 中的公开发版仓库'
      setError(String(detail))
    } finally {
      setChecking(false)
    }
  }, [])

  const handleBackup = async () => {
    setBackingUp(true)
    setError('')
    try {
      const res = await apiClient.post<unknown, { ok: boolean; backup: { path: string } }>(
        '/api/system/backup',
        { note: 'manual-before-update' }
      )
      setMessage(`备份已保存：${res.backup.path}`)
      setBackupConfirmed(true)
    } catch {
      setError('备份失败')
    } finally {
      setBackingUp(false)
    }
  }

  const handleApply = async () => {
    if (!checkResult?.has_update || !checkResult.download_url) return
    if (checkResult.requires_backup && !backupConfirmed) {
      setError('请先完成数据备份并勾选确认')
      return
    }
    setApplying(true)
    setError('')
    try {
      let sha256: string | undefined
      try {
        const sha = await apiClient.get<unknown, { sha256: string }>(
          `/api/system/update/sha256?version=${encodeURIComponent(checkResult.latest_version)}`
        )
        sha256 = sha.sha256
      } catch {
        // Release 未附带 sha256 时仍可升级（脚本会跳过校验）
      }

      const res = await apiClient.post<
        unknown,
        { ok: boolean; message: string }
      >('/api/system/update/apply', {
        tag: checkResult.tag,
        download_url: checkResult.download_url,
        sha256,
        requires_backup: checkResult.requires_backup,
        backup_confirmed: backupConfirmed || !checkResult.requires_backup,
      })
      setMessage(res.message || '升级程序已启动，请等待窗口自动重启')
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        '启动升级失败'
      setError(String(detail))
    } finally {
      setApplying(false)
    }
  }

  const needsBackupGate = Boolean(checkResult?.requires_backup)
  const schemaTooOld =
    checkResult &&
    checkResult.has_update &&
    versionInfo &&
    versionInfo.schema_version < checkResult.min_schema_version

  return (
    <section
      id="update"
      className="scroll-mt-28 rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden"
    >
      <div className="px-6 py-4 border-b border-slate-800 bg-slate-900/70 flex items-center gap-2">
        <Download className="w-4 h-4 text-indigo-400" />
        <h2 className="text-sm font-semibold text-slate-200">软件更新</h2>
      </div>

      <div className="p-6 space-y-4">
        {loadingVersion ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="w-4 h-4 animate-spin" />读取版本…
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 text-sm">
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3">
              <p className="text-xs text-slate-500">当前版本</p>
              <p className="mt-1 font-mono text-slate-200">{versionInfo?.app_version ?? '—'}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3">
              <p className="text-xs text-slate-500">数据库 schema</p>
              <p className="mt-1 font-mono text-slate-200">
                v{versionInfo?.schema_version ?? '—'} / v{versionInfo?.current_schema_version ?? '—'}
              </p>
            </div>
          </div>
        )}

        {versionInfo?.release_repo && (
          <p className="text-xs text-slate-500">
            更新源：<span className="font-mono text-slate-400">{versionInfo.release_repo}</span>
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => handleCheck(true)}
            disabled={checking}
            className="inline-flex items-center gap-2 rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-4 py-2 text-sm text-indigo-200 hover:bg-indigo-500/20 disabled:opacity-50"
          >
            {checking ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            检查更新
          </button>
          <button
            type="button"
            onClick={handleBackup}
            disabled={backingUp}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            {backingUp ? <Loader2 className="w-4 h-4 animate-spin" /> : <HardDriveDownload className="w-4 h-4" />}
            备份数据
          </button>
        </div>

        {checkResult?.has_update && (
          <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-indigo-100">
                发现新版本 <span className="font-mono font-semibold">{checkResult.latest_version}</span>
              </p>
              {checkResult.release_url && (
                <a
                  href={checkResult.release_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200"
                >
                  Release 页面 <ExternalLink className="w-3 h-3" />
                </a>
              )}
            </div>

            {(checkResult.breaking || checkResult.requires_backup) && (
              <div className="flex gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium">本次为破坏性/需备份升级</p>
                  <p className="mt-1 text-amber-100/80">
                    升级前请先备份 <code className="text-amber-50">data/</code> 与{' '}
                    <code className="text-amber-50">config.json</code>。备份完成后勾选下方确认。
                  </p>
                </div>
              </div>
            )}

            {schemaTooOld && (
              <div className="flex gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                当前数据库版本过低（v{versionInfo?.schema_version}），需先升级到中间版本或联系支持。
              </div>
            )}

            {needsBackupGate && (
              <label className="flex items-start gap-2 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={backupConfirmed}
                  onChange={(e) => setBackupConfirmed(e.target.checked)}
                />
                我已备份数据，了解升级风险并继续
              </label>
            )}

            <button
              type="button"
              onClick={handleApply}
              disabled={applying || Boolean(schemaTooOld) || (needsBackupGate && !backupConfirmed)}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
              立即升级
            </button>
          </div>
        )}

        {message && (
          <p className="text-sm text-emerald-300/90">{message}</p>
        )}
        {error && (
          <p className="text-sm text-red-300">{error}</p>
        )}

        {checkResult?.release_notes && checkResult.has_update && (
          <details className="text-xs text-slate-400">
            <summary className="cursor-pointer hover:text-slate-300">更新说明</summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-slate-400">
              {checkResult.release_notes}
            </pre>
          </details>
        )}
      </div>
    </section>
  )
}
