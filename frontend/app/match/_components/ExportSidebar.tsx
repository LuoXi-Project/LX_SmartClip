import { Subtitles, Loader2 } from 'lucide-react'
import type { ExportMode, Segment } from './types'
import type { MatchWorkspaceMode } from './matchModeTypes'
import { isAutoLikeMode, isManualLikeMode } from './matchModeTypes'
import type { TtsVideoAlignConfigApi } from '@/lib/api'
import { TtsAlignPolicySelect } from './TtsAlignPolicySelect'

export function ExportSidebar({
  segments,
  exportMode,
  setExportMode,
  exporting,
  exportError,
  onExport,
  subtitleEnabled,
  onToggleSubtitle,
  srtReady,
  generatingSrt,
  ttsAlign,
  onTtsAlignChange,
  /** 方案驱动模式（自动 / 模板 / 口播快剪）：隐藏段落进度与底部导出，成片在主区方案卡片 */
  matchMode = 'manual',
}: {
  segments: Segment[]
  exportMode: ExportMode
  setExportMode: (m: ExportMode) => void
  exporting: boolean
  exportError: string
  onExport: () => void
  subtitleEnabled: boolean
  onToggleSubtitle: (v: boolean) => void
  srtReady: boolean
  generatingSrt: boolean
  /** 手动匹配成片：画面时长 < 配音时的补足策略 */
  ttsAlign: TtsVideoAlignConfigApi
  onTtsAlignChange: (patch: Partial<TtsVideoAlignConfigApi>) => void
  matchMode?: MatchWorkspaceMode
}) {
  const readySegs  = segments.filter((s) => s.clips.length > 0)
  const matchedCount = readySegs.length
  const selectedSegs = segments.filter((s) => (s.selectedClipIds?.length ?? 0) > 0)
  const selectedCount = selectedSegs.length
  const ttsCount = readySegs.filter((s) => s.ttsFilename).length
  const totalCount = segments.length
  const audioReadyLabel =
    exportMode === 'subtitle' || exportMode === 'jianying_tts'
      ? matchMode === 'audio_match'
        ? '原声就绪'
        : '配音就绪'
      : exportMode === 'original' || exportMode === 'jianying_original'
        ? '原声就绪'
        : '素材就绪'
  const audioReadyCount =
    exportMode === 'subtitle' || exportMode === 'jianying_tts'
      ? ttsCount
      : exportMode === 'original' || exportMode === 'jianying_original'
        ? selectedCount
        : matchedCount
  const doneCount =
    exportMode === 'original' || exportMode === 'jianying_original' ? selectedCount : matchedCount

  const modeLabel: Record<ExportMode, { icon: string; title: string; desc: string; color: string; active: string }> = {
    zip:      { icon: '📦', title: '素材压缩包',     desc: '视频切片 + 音频 ZIP',     color: 'indigo', active: 'border-indigo-500 bg-indigo-500/10 text-indigo-200' },
    subtitle: { icon: '💬', title: '成片 MP4',       desc: '配音 + 字幕烧录',         color: 'cyan',   active: 'border-cyan-500   bg-cyan-500/10   text-cyan-200'   },
    original: { icon: '🔇', title: '原声成片',       desc: '保留原声拼接 + 可选字幕 MP4', color: 'slate', active: 'border-slate-500 bg-slate-500/10 text-slate-200' },
    jianying_tts: { icon: '✂️', title: '剪映草稿', desc: '音视频时间轴（不导出 MP4）', color: 'emerald', active: 'border-emerald-500 bg-emerald-500/10 text-emerald-200' },
    jianying_original: { icon: '✂️', title: '剪映草稿(原声)', desc: '原声时间轴（不导出 MP4）', color: 'emerald', active: 'border-emerald-500 bg-emerald-500/10 text-emerald-200' },
  }

  return (
    <div className="fixed right-0 top-0 h-screen w-64 bg-[#0b0d12] border-l border-slate-800 flex flex-col z-40 shadow-2xl">
      {/* header */}
      <div className="px-5 pt-6 pb-4 border-b border-slate-800">
        <p className="text-xs font-semibold text-slate-300 uppercase tracking-widest">导出</p>
        <p className="text-[10px] text-slate-500 mt-1.5 leading-relaxed">
          成片 MP4 与剪映草稿 ZIP 请分开选择，勿混在同一轮导出。
        </p>
      </div>

      {/* progress — 仅手动匹配（段落级） */}
      {isManualLikeMode(matchMode) && (
        <div className="px-5 py-4 space-y-3 border-b border-slate-800">
          <StatRow label="总段落"  value={totalCount} total={totalCount} color="slate"  />
          <StatRow label="已匹配"  value={matchedCount}  total={totalCount} color="indigo" />
          <StatRow label={audioReadyLabel} value={audioReadyCount} total={totalCount} color="violet" />
        </div>
      )}

      {/* mode toggle — 仅手动匹配 */}
      {isManualLikeMode(matchMode) && (
        <div className="px-5 py-4 space-y-2 border-b border-slate-800">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">导出格式</p>
          {(Object.entries(modeLabel) as [ExportMode, typeof modeLabel[ExportMode]][]).map(([mode, cfg]) => (
            <button
              key={mode}
              onClick={() => setExportMode(mode)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-sm transition-colors ${
                exportMode === mode ? cfg.active : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'
              }`}
            >
              <span className="text-lg leading-none">{cfg.icon}</span>
              <div className="text-left">
                <p className="text-xs font-medium">{cfg.title}</p>
                <p className="text-[10px] text-slate-500 mt-0.5">{cfg.desc}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* 成片时长策略：画面时长 < 配音时如何补足；zip 仅打包素材不合成，隐藏 */}
      {isManualLikeMode(matchMode) && exportMode !== 'zip' && (
        <div className="px-5 py-4 border-b border-slate-800">
          <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">成片时长策略</p>
          <TtsAlignPolicySelect
            value={ttsAlign}
            onChange={onTtsAlignChange}
            basicOnly
            className="!space-y-0"
          />
        </div>
      )}

      {/* 剪映草稿：与成片 MP4 / 原声成片互斥 */}
      {isManualLikeMode(matchMode) &&
        (exportMode === 'jianying_tts' || exportMode === 'jianying_original') && (
          <div className="px-5 py-3 border-b border-slate-800 space-y-1.5">
            <p className="text-xs font-medium text-emerald-200/90">剪映草稿说明</p>
            <ul className="text-[10px] text-slate-400 leading-relaxed list-disc list-inside space-y-0.5">
              <li>不调用 ffmpeg 烧录，生成可导入剪映的草稿（可在设置中配置父目录以跳过 ZIP、直接写入）。</li>
              <li>
                {exportMode === 'jianying_tts'
                  ? '需各段配音已就绪；字幕时间轴与「成片 MP4」同源逻辑。'
                  : '按已选素材拼接时间轴；字幕是否进草稿由下方「添加字幕」开关决定。'}
              </li>
              <li>未配置父目录时：下载 ZIP，解压后按包内 bat 修补路径；已配置时：无需解压，直接在目标文件夹生成草稿。</li>
            </ul>
          </div>
        )}

      {/* 添加字幕：方案模式在主内容区；此处仅服务手动匹配（zip 时隐藏） */}
      {isManualLikeMode(matchMode) && exportMode !== 'zip' && (
        <div className="px-5 py-3 border-b border-slate-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Subtitles className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-xs text-slate-300">添加字幕</span>
            </div>
            <button
              onClick={() => onToggleSubtitle(!subtitleEnabled)}
              className={`relative w-9 h-5 rounded-full transition-colors ${
                subtitleEnabled ? 'bg-cyan-600' : 'bg-slate-700'
              }`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
                subtitleEnabled ? 'translate-x-4' : 'translate-x-0'
              }`} />
            </button>
          </div>
          {subtitleEnabled && (
            <p className={`mt-1.5 text-[10px] ${
              srtReady ? 'text-cyan-500' : generatingSrt ? 'text-amber-400' : 'text-slate-600'
            }`}>
              {srtReady ? '✓ 时间轴已生成' : generatingSrt ? '⏳ 生成时间轴...' : '导出时自动生成时间轴'}
            </p>
          )}
        </div>
      )}

      <div className="flex-1" />

      {/* export button */}
      <div className="px-5 py-5 space-y-3">
        {isAutoLikeMode(matchMode) ? (
          <p className="text-[11px] text-slate-500 leading-snug text-center">
            {matchMode === 'film_commentary'
              ? '影视解说：主区启动一键成片任务；方案生成后可「载入方案卡片」在下方一键成片或导出剪映草稿。'
              : matchMode === 'script_stock'
              ? '文案素材成片：主区「合成配音成片」导出 MP4；「导出剪映草稿」单独生成 ZIP（与成片互斥）。自动 / 模板 / 口播快剪 / 混剪：方案卡片上同样分「一键成片」与「仅导出剪映草稿」。'
              : matchMode === 'mix_edit'
                ? '混剪：生成方案后在下方卡片「一键成片」；模式二选 AI 配音时将走 TTS 管线。'
                : '自动 / 模板 / 口播快剪：方案卡片上「一键成片」导出 MP4；「仅导出剪映草稿」单独生成 ZIP，二者互斥、勿同时当作一步完成。'}
          </p>
        ) : (
          <>
            {exportError && <p className="text-[11px] text-red-400 leading-snug">{exportError}</p>}
            <button
              onClick={onExport}
              disabled={exporting || doneCount === 0}
              className={`w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all ${
                exportMode === 'subtitle' || exportMode.startsWith('jianying_')
                  ? exportMode.startsWith('jianying_')
                    ? 'bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600'
                    : 'bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-600'
                  : 'bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600'
              }`}
            >
              {exporting ? (
                <><Loader2 className="w-4 h-4 animate-spin" />导出中...</>
              ) : (
                <><span>{modeLabel[exportMode].icon}</span> {modeLabel[exportMode].title} ({doneCount}段)</>
              )}
            </button>
            {doneCount === 0 && <p className="text-[10px] text-slate-600 text-center">请先匹配并选择片段</p>}
          </>
        )}
      </div>
    </div>
  )
}

function StatRow({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total === 0 ? 0 : (value / total) * 100
  const bar = color === 'indigo' ? 'bg-indigo-500' : color === 'violet' ? 'bg-violet-500' : 'bg-slate-600'
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-500">{label}</span>
        <span className="text-[11px] text-slate-300 tabular-nums">{value}/{total}</span>
      </div>
      <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
