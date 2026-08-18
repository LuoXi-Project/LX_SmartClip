'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Search, Sparkles, QrCode, Loader2, AlertTriangle } from 'lucide-react'

import {
  externalSearchApi,
  type DouyinLoginStatus,
  type ExternalSearchExtraction,
  type ExternalSearchResultItem,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { useJobStream } from '@/hooks/use-job-stream'

import { ExternalSearchResultsModal } from './ExternalSearchResultsModal'

type Platform = 'douyin' | 'youtube'
type InputMode = 'keywords' | 'copy'

interface KeywordIngestPanelProps {
  /** 采集完成后刷新素材列表 */
  onIngested?: () => void
}

export function KeywordIngestPanel({ onIngested }: KeywordIngestPanelProps) {
  const toast = useToast()
  const { startJob } = useJobStream()

  const [inputMode, setInputMode] = useState<InputMode>('keywords')
  const [inputText, setInputText] = useState('')
  const [platforms, setPlatforms] = useState<Platform[]>(['douyin'])
  const [limitPerKeyword, setLimitPerKeyword] = useState(3)
  const [autoProcess, setAutoProcess] = useState(true)

  const [douyinStatus, setDouyinStatus] = useState<DouyinLoginStatus | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResults, setPreviewResults] = useState<{
    keywords: string[]
    results: ExternalSearchResultItem[]
    notes: string[]
    extraction?: ExternalSearchExtraction | null
  } | null>(null)

  const refreshDouyinStatus = useCallback(async () => {
    try {
      setDouyinStatus(await externalSearchApi.douyinLoginStatus())
    } catch {
      setDouyinStatus(null)
    }
  }, [])

  useEffect(() => {
    refreshDouyinStatus()
  }, [refreshDouyinStatus])

  const douyinEnabled = platforms.includes('douyin')
  const youtubeEnabled = platforms.includes('youtube')
  const douyinNeedsLogin = douyinEnabled && douyinStatus && !douyinStatus.cookie_ready

  const parsedKeywords = useMemo(() => {
    if (inputMode !== 'keywords') return []
    return inputText
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
  }, [inputMode, inputText])

  const hasInput = inputMode === 'keywords' ? parsedKeywords.length > 0 : inputText.trim().length > 0

  const togglePlatform = (p: Platform) => {
    setPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) || [] : [...prev, p],
    )
  }

  const buildSearchBody = () => ({
    keywords: inputMode === 'keywords' ? parsedKeywords : undefined,
    copy_text: inputMode === 'copy' ? inputText.trim() : undefined,
    platforms,
    limit_per_keyword: limitPerKeyword,
  })

  const handlePreview = async () => {
    if (!hasInput) {
      toast.error(inputMode === 'keywords' ? '请每行输入一个关键词' : '请粘贴文案或标题')
      return
    }
    if (platforms.length === 0) {
      toast.error('请至少选择一个平台')
      return
    }
    setPreviewLoading(true)
    try {
      const resp = await externalSearchApi.searchPreview(buildSearchBody())
      if (!resp.results || resp.results.length === 0) {
        const note = resp.notes?.[0] || '没有搜到可用结果'
        toast.error(`搜索完成但无结果：${note}`)
        return
      }
      setPreviewResults(resp)
      if (resp.notes?.length) toast.info(resp.notes.slice(0, 2).join('；'))
    } catch (error) {
      toast.error(`搜索预览失败：${(error as Error).message || '请检查网络/登录态'}`)
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleAutoIngest = () => {
    if (!hasInput) {
      toast.error(inputMode === 'keywords' ? '请每行输入一个关键词' : '请粘贴文案或标题')
      return
    }
    if (platforms.length === 0) {
      toast.error('请至少选择一个平台')
      return
    }
    startJob({
      create: () =>
        externalSearchApi.ingest({
          ...buildSearchBody(),
          auto_process: autoProcess,
        }),
      title: '关键词自动采集',
      kind: 'external_ingest',
      resultLabel: '采集完成，素材已入库',
      onDone: () => onIngested?.(),
    })
  }

  const handleDouyinLogin = () => {
    startJob({
      create: () => externalSearchApi.douyinLogin(),
      title: '抖音扫码登录',
      kind: 'douyin_login',
      resultLabel: '抖音登录成功',
      onDone: () => refreshDouyinStatus(),
    })
  }

  return (
    <div
      data-tour="page-library-keyword-ingest"
      className="mb-8 rounded-xl border border-slate-700/60 bg-slate-800/20 p-6"
    >
      <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-lg bg-fuchsia-600/20 flex items-center justify-center">
            <Sparkles className="w-5 h-5 text-fuchsia-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-100">关键词采集</h2>
            <p className="text-xs text-slate-500">
              按文案关键词搜索抖音 / YouTube 素材，下载后自动进入预处理队列
            </p>
          </div>
        </div>

        {/* 抖音登录态 */}
        {douyinStatus && (
          <div className="flex items-center gap-2 text-xs">
            {douyinStatus.cookie_ready ? (
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-emerald-500/10 text-emerald-400">
                抖音已登录
              </span>
            ) : (
              <>
                <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-amber-500/10 text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  抖音未登录
                </span>
                <button
                  type="button"
                  onClick={handleDouyinLogin}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-fuchsia-600 text-white hover:bg-fuchsia-500 transition-colors"
                >
                  <QrCode className="w-3.5 h-3.5" />
                  扫码登录
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="flex gap-2 mb-3">
        {(
          [
            ['keywords', '关键词（每行一个）'],
            ['copy', '整段文案 / 标题（AI 提取）'],
          ] as Array<[InputMode, string]>
        ).map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            onClick={() => setInputMode(mode)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              inputMode === mode
                ? 'bg-fuchsia-600/80 text-white'
                : 'bg-slate-900/60 text-slate-400 hover:text-slate-200 border border-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <textarea
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        rows={inputMode === 'keywords' ? 3 : 5}
        placeholder={
          inputMode === 'keywords'
            ? '例如：\n城市夜景航拍\n咖啡店日常\n海边日落'
            : '粘贴整段口播文案或视频标题，系统将自动提取搜索关键词（3~8 个）'
        }
        className="w-full rounded-lg bg-slate-900/80 border border-slate-700 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:ring-2 focus:ring-fuchsia-500/40 resize-y"
      />

      {/* 选项行 */}
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        {/* 平台 */}
        <div className="flex items-center gap-3">
          {(
            [
              ['douyin', '抖音'],
              ['youtube', 'YouTube'],
            ] as Array<[Platform, string]>
          ).map(([p, label]) => (
            <label key={p} className="inline-flex items-center gap-1.5 cursor-pointer text-slate-300">
              <input
                type="checkbox"
                checked={platforms.includes(p)}
                onChange={() => togglePlatform(p)}
                className="accent-fuchsia-500"
              />
              {label}
            </label>
          ))}
        </div>

        {/* 每词数量 */}
        <label className="inline-flex items-center gap-1.5 text-slate-400">
          每词采集
          <select
            value={limitPerKeyword}
            onChange={(e) => setLimitPerKeyword(Number(e.target.value))}
            className="h-8 rounded-md bg-slate-900/80 border border-slate-700 px-2 text-xs text-slate-200 outline-none"
          >
            {[1, 2, 3, 5, 8, 10].map((n) => (
              <option key={n} value={n}>
                {n} 条
              </option>
            ))}
          </select>
        </label>

        <label className="inline-flex items-center gap-1.5 cursor-pointer text-slate-300">
          <input
            type="checkbox"
            checked={autoProcess}
            onChange={(e) => setAutoProcess(e.target.checked)}
            className="accent-fuchsia-500"
          />
          自动预处理
        </label>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={handlePreview}
            disabled={previewLoading || !hasInput}
            className={`inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-sm font-medium transition-all ${
              previewLoading || !hasInput
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-slate-600 text-white hover:bg-slate-500 active:scale-95'
            }`}
          >
            {previewLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            搜索预览
          </button>
          <button
            type="button"
            onClick={handleAutoIngest}
            disabled={!hasInput}
            className={`inline-flex items-center gap-1.5 h-9 px-4 rounded-lg text-sm font-medium transition-all ${
              !hasInput
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-fuchsia-600 text-white hover:bg-fuchsia-500 active:scale-95 shadow-lg shadow-fuchsia-900/30'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            直接自动采集
          </button>
        </div>
      </div>

      {/* 提示 */}
      {douyinNeedsLogin && (
        <p className="mt-3 text-xs text-amber-400/90">
          抖音搜索需要主站登录态：点击右上角「扫码登录」完成一次扫码即可长期复用（与一键发布的登录互不影响）。
        </p>
      )}
      {youtubeEnabled && (
        <p className="mt-2 text-xs text-slate-600">
          YouTube 需在 设置 → external_search_proxy 配置代理（如 http://127.0.0.1:7890）。
        </p>
      )}

      {/* 预览结果弹窗 */}
      {previewResults && (
        <ExternalSearchResultsModal
          keywords={previewResults.keywords}
          results={previewResults.results}
          notes={previewResults.notes}
          extraction={previewResults.extraction}
          autoProcess={autoProcess}
          onClose={() => setPreviewResults(null)}
          onConfirm={(selected) => {
            setPreviewResults(null)
            startJob({
              create: () =>
                externalSearchApi.ingest({
                  selected_items: selected,
                  auto_process: autoProcess,
                }),
              title: '关键词采集（勾选下载）',
              kind: 'external_ingest',
              resultLabel: '采集完成，素材已入库',
              onDone: () => onIngested?.(),
            })
          }}
        />
      )}
    </div>
  )
}
