'use client'

import { useMemo, useState } from 'react'
import { Download, Film, Loader2, Mic, Scissors, Volume2 } from 'lucide-react'
import type { AutoEditPlanApi } from '@/lib/api'
import { resolveStorageUrl } from '@/lib/studio-media-url'
import { autoEditApi, formatFastApiDetail } from '@/lib/api'
import { patchAgentWorkspace } from '@/lib/agent-api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'
import { toastRecommendJianyingParentDir } from '@/lib/jianying-parent-dir-hint'
import { useStudioStore } from '@/lib/studio-store'
import { useStudioMediaConfig } from './useStudioMediaConfig'
import {
  mergeBgmIntoPlan,
  readProductionProfile,
} from '@/lib/studio-media-config'
import { getExportPathsForPlan, getPlanModeGuide } from '@/lib/studio-export-guide'

type StudioPlanActionsProps = {
  plan: AutoEditPlanApi
}

export function StudioPlanActions({ plan }: StudioPlanActionsProps) {
  const toast = useToast()
  const confirm = useConfirm()
  const { sessionId, workspace, setWorkspace, setSelectedArtifact } = useStudioStore()
  const { media } = useStudioMediaConfig()
  const [realizing, setRealizing] = useState(false)
  const [exportingJY, setExportingJY] = useState(false)
  const [lastVideoUrl, setLastVideoUrl] = useState<string | null>(null)
  const [lastJyUrl, setLastJyUrl] = useState<string | null>(null)

  const modeGuide = useMemo(() => getPlanModeGuide(plan.mode), [plan.mode])
  const paths = useMemo(() => getExportPathsForPlan(plan), [plan])
  const mp4Path = paths.find((p) => p.id === 'mp4')
  const jyPath = paths.find((p) => p.id === 'jianying')

  const isVoiceover = plan.mode === 'voiceover' || plan.mode === 'auto'

  function buildRealizePayload(forceTts?: boolean) {
    const production_profile = readProductionProfile(workspace?.user_preferences)
    const planForExport = mergeBgmIntoPlan(plan, media)
    const useTts = forceTts ?? isVoiceover
    return {
      plan: planForExport,
      project_name: `studio_${(plan.title || plan.plan_id).slice(0, 24)}`,
      include_subtitle: media.subtitle.enabled,
      style: media.subtitle.style,
      production_profile,
      ...(useTts ? { force_tts_pipeline: true } : {}),
    }
  }

  async function persistExport(entry: Record<string, unknown>) {
    if (!sessionId || !workspace) return
    const last_exports = [...(workspace.last_exports || []), entry]
    const res = await patchAgentWorkspace(sessionId, {
      pipeline_phase: 'export',
      last_exports,
    })
    setWorkspace(res.workspace)
  }

  async function handleRealize(forceTts?: boolean) {
    const mp4 = mp4Path
    const ok = await confirm({
      title: plan.mode === 'original' && !forceTts ? '原声成片' : '配音成片',
      description: [
        mp4?.subtitle || '将按当前方案合成 MP4',
        '',
        '检查器：字幕',
        media.subtitle.enabled ? '开启' : '关闭',
        ' · BGM',
        media.bgm.enabled ? '开启' : '关闭',
        ' · 制作风格见「制作」Tab',
        '',
        plan.mode === 'original' && !forceTts
          ? '将保留素材原声；如需 AI 配音请用对话「不保留原声，进行 tts 配音」。'
          : '将合成 TTS 并按配音时长对齐字幕（耗时可能数分钟）。',
      ].join('\n'),
      confirmLabel: '开始渲染',
    })
    if (!ok) return

    setRealizing(true)
    try {
      const res = await autoEditApi.realize(buildRealizePayload(forceTts))
      const url = resolveStorageUrl(res.url)
      setLastVideoUrl(url)
      toast.success(res.mode === 'original' ? '原声成片已生成' : '配音成片已生成')
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
      await persistExport({
        kind: 'video',
        filename: res.filename,
        url,
        mode: res.mode,
        plan_id: plan.plan_id,
      })
    } catch (e: unknown) {
      toast.error(formatFastApiDetail(e) || (e as Error)?.message || '成片失败')
    } finally {
      setRealizing(false)
    }
  }

  async function handleJianying() {
    const ok = await confirm({
      title: '导出剪映草稿',
      description:
        '仅生成剪映工程（ZIP 或写入目录），不在此步渲染 MP4。最终效果取决于你在剪映中的剪辑与导出。',
      confirmLabel: '导出草稿',
    })
    if (!ok) return

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
      await persistExport({
        kind: 'jianying',
        filename: res.filename,
        url,
        local_path: res.local_path,
        mode: res.mode,
        plan_id: plan.plan_id,
      })
    } catch (e: unknown) {
      toast.error(formatFastApiDetail(e) || (e as Error)?.message || '剪映导出失败')
    } finally {
      setExportingJY(false)
    }
  }

  const mp4Label =
    plan.mode === 'original'
      ? '成片 MP4（原声）'
      : plan.mode === 'voiceover'
        ? '成片 MP4（配音）'
        : '成片 MP4'

  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">方案模式</span>
        <span className="text-xs font-medium text-slate-200 px-2 py-0.5 rounded-md border border-slate-600 bg-slate-800/80">
          {modeGuide.label}
        </span>
        <span className="text-[11px] text-slate-500">{modeGuide.short}</span>
      </div>

      {mp4Path?.caution ? (
        <p className="text-[11px] text-amber-400/90 leading-relaxed border border-amber-500/20 bg-amber-500/5 rounded-lg px-2.5 py-2">
          {mp4Path.caution}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void handleRealize(false)}
          disabled={realizing || exportingJY}
          className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg text-white text-sm disabled:opacity-50 ${
            mp4Path?.recommended
              ? 'bg-violet-600 hover:bg-violet-500 ring-1 ring-violet-400/30'
              : 'bg-slate-700 hover:bg-slate-600'
          }`}
        >
          {realizing ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : plan.mode === 'original' ? (
            <Volume2 className="w-4 h-4" />
          ) : (
            <Mic className="w-4 h-4" />
          )}
          {mp4Label}
          {mp4Path?.recommended ? (
            <span className="text-[10px] opacity-80">推荐</span>
          ) : null}
        </button>
        <button
          type="button"
          onClick={() => void handleJianying()}
          disabled={realizing || exportingJY}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-600 hover:border-slate-500 text-slate-200 text-sm disabled:opacity-50"
          title={jyPath?.caution}
        >
          {exportingJY ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Scissors className="w-4 h-4 text-indigo-300" />
          )}
          剪映草稿
        </button>
        {plan.mode === 'original' ? (
          <button
            type="button"
            onClick={() => void handleRealize(true)}
            disabled={realizing || exportingJY}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-amber-500/40 text-amber-100 text-sm hover:bg-amber-500/10 disabled:opacity-50"
          >
            <Film className="w-4 h-4" />
            强制配音成片
          </button>
        ) : null}
      </div>

      <p className="text-[10px] text-slate-500 leading-relaxed">
        也可在左侧对话发送与方案匹配的指令（如「导出成片（保留原声）」）。对话导出与按钮走同一套成片逻辑。
      </p>

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
            <a
              href={lastJyUrl}
              className="text-violet-300 hover:underline ml-1"
              target="_blank"
              rel="noreferrer"
            >
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
