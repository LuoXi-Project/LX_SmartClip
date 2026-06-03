'use client'

import { useState } from 'react'
import { Download, Film, Loader2, Scissors } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import { resolveStorageUrl } from '@/lib/studio-media-url'
import { autoEditApi, formatFastApiDetail } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'
import { toastRecommendJianyingParentDir } from '@/lib/jianying-parent-dir-hint'
import { useStudioStore } from '@/lib/studio-store'
import { useStudioMediaConfig } from './useStudioMediaConfig'
import {
  mergeBgmIntoPlan,
  readProductionProfile,
} from '@/lib/studio-media-config'

type StudioPlanActionsProps = {
  plan: AutoEditPlanApi
}

export function StudioPlanActions({ plan }: StudioPlanActionsProps) {
  const toast = useToast()
  const confirm = useConfirm()
  const { workspace, setWorkspace, setSelectedArtifact } = useStudioStore()
  const { media } = useStudioMediaConfig()
  const [realizing, setRealizing] = useState(false)
  const [exportingJY, setExportingJY] = useState(false)
  const [lastVideoUrl, setLastVideoUrl] = useState<string | null>(null)
  const [lastJyUrl, setLastJyUrl] = useState<string | null>(null)

  const isVoiceover = plan.mode === 'voiceover' || plan.mode === 'auto'

  function buildRealizePayload() {
    const production_profile = readProductionProfile(workspace?.user_preferences)
    const planForExport = mergeBgmIntoPlan(plan, media)
    return {
      plan: planForExport,
      project_name: `studio_${(plan.title || plan.plan_id).slice(0, 24)}`,
      include_subtitle: media.subtitle.enabled,
      style: media.subtitle.style,
      production_profile,
      ...(isVoiceover ? { force_tts_pipeline: true } : {}),
    }
  }

  async function handleRealize() {
    const ok = await confirm({
      title: '生成成片',
      description:
        '将按当前方案、字幕样式与 BGM 设置合成视频，耗时可能数分钟，是否继续？',
      confirmLabel: '开始成片',
    })
    if (!ok) return

    setRealizing(true)
    try {
      const res = await autoEditApi.realize(buildRealizePayload())
      const url = resolveStorageUrl(res.url)
      setLastVideoUrl(url)
      toast.success('成片已生成')
      setSelectedArtifact({
        type: 'export',
        id: res.filename,
        payload: {
          kind: 'video',
          filename: res.filename,
          url,
          mode: res.mode,
          plan_id: plan.plan_id,
        },
      })
      if (workspace) {
        setWorkspace({
          ...workspace,
          pipeline_phase: 'export',
          last_exports: [
            ...(workspace.last_exports || []),
            { kind: 'video', filename: res.filename, url, plan_id: plan.plan_id },
          ],
        })
      }
    } catch (e: unknown) {
      toast.error(formatFastApiDetail(e) || (e as Error)?.message || '成片失败')
    } finally {
      setRealizing(false)
    }
  }

  async function handleJianying() {
    setExportingJY(true)
    try {
      const payload = buildRealizePayload()
      const res = await autoEditApi.exportJianyingDraft({
        ...payload,
        project_name: `jy_${(plan.title || plan.plan_id).slice(0, 24)}`,
      })
      if (res.mode === 'zip') {
        toastRecommendJianyingParentDir(toast)
      }
      const url =
        res.mode === 'direct' && res.local_path
          ? res.local_path
          : resolveStorageUrl(res.url)
      setLastJyUrl(url)
      toast.success(res.mode === 'direct' ? '已写入剪映草稿目录' : '剪映草稿 ZIP 已生成')
      setSelectedArtifact({
        type: 'export',
        id: res.filename,
        payload: {
          kind: 'jianying',
          filename: res.filename,
          url,
          local_path: res.local_path,
          mode: res.mode,
          plan_id: plan.plan_id,
        },
      })
    } catch (e: unknown) {
      toast.error(formatFastApiDetail(e) || (e as Error)?.message || '剪映导出失败')
    } finally {
      setExportingJY(false)
    }
  }

  return (
    <div className="mb-4 rounded-xl border border-slate-700 bg-slate-900/60 p-3 space-y-3">
      <p className="text-xs text-slate-400">
        成片将使用右侧检查器中的<strong className="text-slate-300">字幕</strong>与
        <strong className="text-slate-300"> BGM</strong> 设置；制作风格（转场/响度）见「制作」Tab。
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleRealize()}
          disabled={realizing || exportingJY}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm disabled:opacity-50"
        >
          {realizing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Film className="w-4 h-4" />}
          一键成片
        </button>
        <button
          type="button"
          onClick={() => void handleJianying()}
          disabled={realizing || exportingJY}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-slate-500 text-slate-200 text-sm disabled:opacity-50"
        >
          {exportingJY ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Scissors className="w-4 h-4 text-indigo-300" />
          )}
          导出剪映草稿
        </button>
      </div>
      {lastVideoUrl && (
        <a
          href={lastVideoUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-sm text-violet-300 hover:underline"
        >
          <Download className="w-3.5 h-3.5" />
          下载成片
        </a>
      )}
      {lastJyUrl && (
        <div className="text-sm text-slate-300">
          剪映：
          {lastJyUrl.startsWith('http') ? (
            <a href={lastJyUrl} className="text-violet-300 hover:underline ml-1" target="_blank" rel="noreferrer">
              下载 ZIP
            </a>
          ) : (
            <span className="text-emerald-400 ml-1 break-all">{lastJyUrl}</span>
          )}
        </div>
      )}
    </div>
  )
}
