'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, RefreshCw, Sparkles } from 'lucide-react'
import { createProcessWebSocket, replicaApi, videosApi, type ProcessMessage, type Video } from '@/lib/api'

type Props = {
  onConfirmed: (payload: { templateId: string; guide: string; replicaType: 'short_video' | 'film_commentary' | 'scene_story' }) => void
  initialGuide?: string
  onTemplateSaved?: () => void
}

export function ReplicaTemplateWizard({ onConfirmed, initialGuide, onTemplateSaved }: Props) {
  const [open, setOpen] = useState(true)
  const [sourceType, setSourceType] = useState<'url' | 'library' | 'upload'>('url')
  const [replicaType, setReplicaType] = useState<'short_video' | 'film_commentary' | 'scene_story'>('short_video')
  const [styleProfile, setStyleProfile] = useState<string>('通用')
  const [qualityMode, setQualityMode] = useState<'balanced' | 'high_quality'>('high_quality')
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [libraryVideos, setLibraryVideos] = useState<Video[]>([])
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [selectedVideoId, setSelectedVideoId] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [skipVlm, setSkipVlm] = useState(true)
  const [maxClips, setMaxClips] = useState(80)

  const [templateId, setTemplateId] = useState<string | null>(null)
  const [draftJson, setDraftJson] = useState<any>(null)
  const [guideDraft, setGuideDraft] = useState<string>('')
  const [templateName, setTemplateName] = useState<string>('')
  const [confirmed, setConfirmed] = useState(false)

  const [loadingPhase, setLoadingPhase] = useState<'idle' | 'ingesting' | 'processing' | 'generating' | 'confirming'>('idle')
  const [error, setError] = useState('')
  const [processLogs, setProcessLogs] = useState<string[]>([])
  const styleOptions = useMemo(() => {
    if (replicaType === 'film_commentary') return ['电影讲解', '电视剧解说', '悬疑推理', '人物解析', '通用']
    if (replicaType === 'scene_story') return ['探店剧情', 'Vlog叙事', '情绪短片', '剧情反转', '通用']
    return ['带货口播', '知识讲解', '测评种草', '热点快评', '通用']
  }, [replicaType])

  useEffect(() => {
    if (replicaType === 'film_commentary' && maxClips < 100) setMaxClips(120)
    if (replicaType === 'scene_story' && maxClips < 90) setMaxClips(100)
    if (replicaType === 'short_video' && maxClips > 120) setMaxClips(80)
    if (!styleOptions.includes(styleProfile)) setStyleProfile(styleOptions[0] || '通用')
  }, [replicaType, styleOptions, styleProfile, maxClips])

  const structureCompleteness = useMemo(() => {
    const tj = draftJson && typeof draftJson === 'object' ? draftJson : null
    const chapters = Array.isArray(tj?.chapter_plan) ? tj.chapter_plan.length : 0
    const slots = Array.isArray(tj?.structure) ? tj.structure.length : 0
    const ok = chapters >= 3 && slots >= 5
    return { ok, chapters, slots }
  }, [draftJson])


  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (initialGuide?.trim() && !guideDraft.trim() && !confirmed) setGuideDraft(initialGuide)
  }, [initialGuide]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setLibraryLoading(true)
    videosApi
      .list({ page_size: 200, sort: 'created_desc' })
      .then((res) => {
        const items = res?.items || []
        setLibraryVideos(items.filter((v) => v.status === 'done' || v.status === 'pending'))
      })
      .catch(() => setLibraryVideos([]))
      .finally(() => setLibraryLoading(false))
  }, [])

  const canGenerate = useMemo(() => {
    if (loadingPhase !== 'idle') return false
    if (sourceType === 'url') return url.trim().length > 5
    if (sourceType === 'library') return !!selectedVideoId
    return !!uploadFile
  }, [loadingPhase, sourceType, url, selectedVideoId, uploadFile])

  async function generate() {
    setError('')
    setProcessLogs([])
    setConfirmed(false)
    setTemplateId(null)
    setDraftJson(null)
    setGuideDraft('')
    setTemplateName('')

    try {
      let sourceVideoId = ''
      let sourceLabel = ''
      let fromDownloadLink = false
      if (sourceType === 'url') {
        setLoadingPhase('ingesting')
        const ingestRes = await replicaApi.ingest({
          url: url.trim(),
          title: title.trim() || undefined,
          download_mode: 'best',
        })
        sourceVideoId = ingestRes.video_id
        sourceLabel = title.trim() || url.trim()
        fromDownloadLink = true
      } else if (sourceType === 'library') {
        sourceVideoId = selectedVideoId
        const picked = libraryVideos.find((v) => v.id === selectedVideoId)
        sourceLabel = picked?.name || '素材库视频'
      } else {
        if (!uploadFile) throw new Error('请先选择要复刻的本地视频')
        setLoadingPhase('ingesting')
        const uploaded = await videosApi.upload(uploadFile)
        sourceVideoId = uploaded.id
        sourceLabel = title.trim() || uploaded.name || uploadFile.name || '上传视频'
      }

      // 进入处理：只保留 asr（跳过抽帧、VLM、embedding）
      setLoadingPhase('processing')
      const skipSteps = ['extract_frames', 'vlm', 'embed']
      if (!skipVlm) {
        // 用户想开 VLM：只跳过 embedding，尽量让视觉描述辅助生成模板
        const idx = skipSteps.indexOf('vlm')
        if (idx !== -1) skipSteps.splice(idx, 1)
      }

      const picked = sourceType === 'library' ? libraryVideos.find((v) => v.id === selectedVideoId) : null
      const skipProcess = !!picked && picked.status === 'done' && picked.total_clips > 0
      if (!skipProcess) {
        const ws = createProcessWebSocket(sourceVideoId, skipSteps)
        wsRef.current = ws

        let processDone = false
        await new Promise<void>((resolve, reject) => {
          ws.addEventListener('message', async (ev) => {
            try {
              const msg = JSON.parse((ev as MessageEvent).data || '{}') as ProcessMessage
              const line = `[${msg.step}] ${msg.status} ${msg.message}`
              setProcessLogs((prev) => {
                const next = [...prev, line]
                // 防止日志无限增长
                return next.slice(Math.max(0, next.length - 80))
              })

              if (msg.step === 'done' && msg.status === 'done') {
                processDone = true
                try {
                  ws.close()
                } catch {
                  // ignore
                }
                resolve()
              }
              if (msg.status === 'error' || msg.step === 'error') {
                reject(new Error(msg.detail ? JSON.stringify(msg.detail) : msg.message || '处理失败'))
              }
            } catch (e) {
              reject(e as Error)
            }
          })
          ws.addEventListener('error', () => reject(new Error('处理进度连接失败')))
        })

        if (!processDone) throw new Error('参考视频处理未完成')
      } else {
        setProcessLogs((prev) => [...prev, '[done] done 复用已处理素材，跳过处理阶段'])
      }

      setLoadingPhase('generating')
      const draft = await replicaApi.generateTemplate(sourceVideoId, {
        skip_vlm: skipVlm,
        max_clips: maxClips,
        replica_type: replicaType,
        style_profile: styleProfile.trim() || '通用',
        quality_mode: qualityMode,
      })
      setTemplateId(draft.template_id)
      setDraftJson(draft.template_json)
      setGuideDraft(draft.template_guide)
      onTemplateSaved?.()
      // 默认模板名：优先使用用户填的标题，否则用来源信息兜底
      const t = title.trim()
      if (t) {
        setTemplateName(t)
      } else if (sourceType === 'url' && fromDownloadLink) {
        try {
          const u = new URL(url.trim())
          setTemplateName(`${u.hostname}复刻模板`)
        } catch {
          setTemplateName('复刻模板')
        }
      } else {
        setTemplateName(`${sourceLabel}复刻模板`)
      }
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || '生成复刻模板失败'
      setError(msg)
    } finally {
      setLoadingPhase('idle')
    }
  }

  async function confirm() {
    if (!templateId) return
    const nextGuide = guideDraft.trim()
    if (nextGuide.length < 10) return
    const name = templateName.trim()
    if (!name) return

    setError('')
    setLoadingPhase('confirming')
    try {
      await replicaApi.confirmTemplate(templateId, { name, template_guide: nextGuide, template_json: draftJson })
      setConfirmed(true)
      const rt = (draftJson?.replica_type as 'short_video' | 'film_commentary' | 'scene_story' | undefined) || replicaType
      onConfirmed({ templateId, guide: nextGuide, replicaType: rt })
      onTemplateSaved?.()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (e as any)?.message || '确认失败'
      setError(msg)
    } finally {
      setLoadingPhase('idle')
    }
  }

  const phaseLabel = useMemo(() => {
    if (loadingPhase === 'idle') return ''
    if (loadingPhase === 'ingesting') {
      if (sourceType === 'upload') return '正在上传参考视频...'
      if (sourceType === 'library') return '正在准备素材库参考视频...'
      return '正在下载参考视频...'
    }
    if (loadingPhase === 'processing') return '正在处理参考视频（ASR）...'
    if (loadingPhase === 'generating') return '正在生成复刻模板...'
    if (loadingPhase === 'confirming') return '正在确认模板...'
    return ''
  }, [loadingPhase])

  return (
    <section className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5 space-y-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-xl bg-amber-500/15 flex items-center justify-center shrink-0">
          <Sparkles className="w-4 h-4 text-amber-300" />
        </div>
        <div className="flex-1 space-y-1">
          <p className="text-sm font-semibold text-amber-100">视频复刻模板</p>
          <p className="text-[11px] text-slate-400 leading-relaxed">
            支持参考链接、素材库视频、本地上传三种来源。系统提取 ASR 后生成可复用的“节奏/话术/结构”模板，确认后即可复刻。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="text-xs text-slate-400 hover:text-slate-200 border border-slate-800 bg-slate-900/40 px-3 py-1 rounded-xl"
        >
          {open ? '收起' : '展开'}
        </button>
      </div>

      {open && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setSourceType('url')}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${sourceType === 'url' ? 'bg-amber-600/30 border-amber-400/50 text-amber-100' : 'bg-slate-900/50 border-slate-700 text-slate-300 hover:text-slate-100'}`}
            >
              链接下载
            </button>
            <button
              type="button"
              onClick={() => setSourceType('library')}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${sourceType === 'library' ? 'bg-amber-600/30 border-amber-400/50 text-amber-100' : 'bg-slate-900/50 border-slate-700 text-slate-300 hover:text-slate-100'}`}
            >
              素材库视频
            </button>
            <button
              type="button"
              onClick={() => setSourceType('upload')}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${sourceType === 'upload' ? 'bg-amber-600/30 border-amber-400/50 text-amber-100' : 'bg-slate-900/50 border-slate-700 text-slate-300 hover:text-slate-100'}`}
            >
              本地上传
            </button>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {sourceType === 'url' && (
              <div className="space-y-1.5">
                <label className="text-[11px] text-slate-400">参考链接</label>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="粘贴电影讲解/带货/测评视频链接..."
                  className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm text-slate-200 outline-none focus:border-amber-400 placeholder-slate-600"
                />
              </div>
            )}
            {sourceType === 'library' && (
              <div className="space-y-1.5">
                <label className="text-[11px] text-slate-400">选择素材库视频</label>
                <select
                  value={selectedVideoId}
                  onChange={(e) => setSelectedVideoId(e.target.value)}
                  className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm text-slate-200 outline-none focus:border-amber-400"
                >
                  <option value="">{libraryLoading ? '正在加载...' : '请选择一个视频'}</option>
                  {libraryVideos.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}（{v.status === 'done' ? '已处理' : '待处理'}）
                    </option>
                  ))}
                </select>
              </div>
            )}
            {sourceType === 'upload' && (
              <div className="space-y-1.5">
                <label className="text-[11px] text-slate-400">上传参考视频</label>
                <input
                  type="file"
                  accept="video/*"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-2.5 text-sm text-slate-200 outline-none focus:border-amber-400 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-700 file:px-3 file:py-1.5 file:text-xs file:text-slate-100"
                />
                {uploadFile && <p className="text-[11px] text-slate-400 truncate">已选择：{uploadFile.name}</p>}
              </div>
            )}
            <div className="space-y-1.5">
              <label className="text-[11px] text-slate-400">展示标题（可选）</label>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="例如：XX 电影讲解参考"
                className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm text-slate-200 outline-none focus:border-amber-400 placeholder-slate-600"
              />
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">复刻方向</span>
              <select
                value={replicaType}
                onChange={(e) => setReplicaType((e.target.value as 'short_video' | 'film_commentary' | 'scene_story') || 'short_video')}
                className="rounded-lg bg-slate-900/60 border border-slate-700 px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-400"
              >
                <option value="short_video">短视频模板（节奏紧凑）</option>
                <option value="film_commentary">影视解说（长叙事结构）</option>
                <option value="scene_story">场景剧情（镜头叙事）</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">风格标签</span>
              <select
                value={styleProfile}
                onChange={(e) => setStyleProfile(e.target.value || '通用')}
                className="rounded-lg bg-slate-900/60 border border-slate-700 px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-400"
              >
                {styleOptions.map((x) => (
                  <option key={x} value={x}>{x}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">质量模式</span>
              <select
                value={qualityMode}
                onChange={(e) => setQualityMode((e.target.value as 'balanced' | 'high_quality') || 'high_quality')}
                className="rounded-lg bg-slate-900/60 border border-slate-700 px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-400"
              >
                <option value="high_quality">高质量（更稳）</option>
                <option value="balanced">平衡（更快）</option>
              </select>
            </div>

            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={skipVlm}
                onChange={(e) => setSkipVlm(e.target.checked)}
                className="rounded border-slate-600 bg-slate-900 text-amber-500 focus:ring-amber-500/40"
              />
              <span className="text-xs text-slate-200">默认跳过视觉理解（更快，MVP）</span>
            </label>

            <label className="flex items-center gap-2">
              <span className="text-xs text-slate-400">引用片段上限</span>
              <input
                type="number"
                min={5}
                max={300}
                value={maxClips}
                onChange={(e) => setMaxClips(Math.max(5, Math.min(300, Number(e.target.value))))}
                className="w-24 rounded-lg bg-slate-900/60 border border-slate-700 px-3 py-2 text-sm text-slate-200 outline-none focus:border-amber-400"
              />
            </label>
            {replicaType === 'film_commentary' && maxClips < 100 && (
              <span className="text-[11px] text-amber-300">影视解说建议设为 100-160，叙事提取更完整</span>
            )}
            {replicaType === 'scene_story' && maxClips < 90 && (
              <span className="text-[11px] text-amber-300">场景剧情建议设为 90-140，角色与场景切换更完整</span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={generate}
              disabled={!canGenerate}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors shadow-lg shadow-amber-900/30"
            >
              {loadingPhase !== 'idle' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {sourceType === 'url' ? '下载并生成模板' : sourceType === 'upload' ? '上传并生成模板' : '生成模板'}
            </button>
            {phaseLabel && <div className="text-xs text-amber-300">{phaseLabel}</div>}
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-xl bg-red-500/10 border border-red-500/20 px-3 py-2.5">
              <p className="text-xs text-red-300">{error}</p>
            </div>
          )}

          {processLogs.length > 0 && (
            <div className="rounded-xl bg-slate-950/60 border border-slate-700/60 px-4 py-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">处理进度</p>
              <div className="mt-2 max-h-40 overflow-auto text-[11px] text-slate-300 whitespace-pre-wrap">
                {processLogs.join('\n')}
              </div>
            </div>
          )}

          {templateId && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-amber-100">模板向导（可编辑）</p>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmed(false)
                    setTemplateId(null)
                    setDraftJson(null)
                    setGuideDraft('')
                    setProcessLogs([])
                    setError('')
                  }}
                  className="flex items-center gap-2 text-xs text-slate-400 hover:text-amber-200 border border-slate-800 bg-slate-900/40 px-3 py-1 rounded-xl"
                  disabled={loadingPhase !== 'idle'}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  重新生成
                </button>
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] text-slate-400">模板名称（用于模板库检索）</label>
                <input
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="例如：电影解说·悬念快节奏 / 带货·强CTA"
                  className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-2.5 text-sm text-slate-200 outline-none focus:border-amber-400 placeholder-slate-600"
                />
                {!templateName.trim() && (
                  <p className="text-[11px] text-amber-300">请填写模板名，便于后续搜索与复用</p>
                )}
              </div>

              <textarea
                value={guideDraft}
                onChange={(e) => setGuideDraft(e.target.value)}
                rows={6}
                className="w-full rounded-xl bg-slate-900/60 border border-slate-700 px-4 py-3 text-sm text-slate-200 outline-none focus:border-amber-400 placeholder-slate-600 resize-none"
              />
              <div className={`text-[11px] ${structureCompleteness.ok ? 'text-emerald-300' : 'text-amber-300'}`}>
                结构完整度：章节 {structureCompleteness.chapters} / 槽位 {structureCompleteness.slots}
                {structureCompleteness.ok ? '（可用于长内容复刻）' : '（建议重试或提高片段上限）'}
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={confirm}
                  disabled={loadingPhase !== 'idle' || !guideDraft.trim() || !templateName.trim() || confirmed}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-colors shadow-lg shadow-emerald-900/30"
                >
                  {confirmed ? '已确认' : loadingPhase === 'confirming' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                  {confirmed ? '模板已生效' : '确认使用该模板'}
                </button>
                {confirmed && <span className="text-xs text-emerald-300">你现在可以选择本地视频生成文案和剪辑方案。</span>}
              </div>

              {draftJson && (
                <details className="text-xs text-slate-300">
                  <summary className="cursor-pointer text-slate-400 hover:text-slate-200">查看模板 JSON（调试用）</summary>
                  <pre className="mt-2 overflow-auto bg-slate-950/60 border border-slate-700/60 rounded-xl p-3 text-[11px] whitespace-pre-wrap">
                    {JSON.stringify(draftJson, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

