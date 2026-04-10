'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { summaryApi, type SummaryMode, type SummaryTemplate, type Video, videosApi, type VideoSummary, type VideoSummarySection } from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'

function modeLabel(m: SummaryMode) {
  if (m === 'asr') return '仅ASR'
  if (m === 'vlm') return '仅VLM'
  return 'ASR+VLM'
}

export default function SummaryPage() {
  const toast = useToast()

  const [videos, setVideos] = useState<Video[]>([])
  const [videosQuery, setVideosQuery] = useState<string>('')
  const [videosPage, setVideosPage] = useState<number>(1)
  const [videosTotalPages, setVideosTotalPages] = useState<number>(1)
  const [loadingVideos, setLoadingVideos] = useState<boolean>(false)
  const [templates, setTemplates] = useState<SummaryTemplate[]>([])

  const [videoId, setVideoId] = useState<string>('')
  const [templateId, setTemplateId] = useState<string>('default_general')
  const [mode] = useState<SummaryMode>('asr_vlm')

  const [userGoal] = useState<string>('通用视频总结')
  const [preferenceText, setPreferenceText] = useState<string>('')

  const [loading, setLoading] = useState(false)
  const [sectionLoading, setSectionLoading] = useState<Record<string, boolean>>({})
  const [current, setCurrent] = useState<VideoSummary | null>(null)
  const [sections, setSections] = useState<VideoSummarySection[]>([])

  const [markdown, setMarkdown] = useState<string>('')
  const [streamStatus, setStreamStatus] = useState<string>('')
  const markdownRef = useRef<HTMLTextAreaElement | null>(null)
  const overviewSection = useMemo(
    () => sections.find((s) => s.section_key === 'overview')?.content_json || {},
    [sections],
  )
  const chaptersSection = useMemo(
    () => sections.find((s) => s.section_key === 'chapters')?.content_json || {},
    [sections],
  )
  const highlightsSection = useMemo(
    () => sections.find((s) => s.section_key === 'highlights')?.content_json || {},
    [sections],
  )

  const loadSections = async (summaryId: string) => {
    try {
      const res = await summaryApi.sections(summaryId)
      setSections(res.sections || [])
    } catch (e: any) {
      toast.error(e?.message || '读取分块总结失败')
      setSections([])
    }
  }


  const selectedVideo = useMemo(() => videos.find((v) => v.id === videoId) || null, [videos, videoId])

  const fetchVideos = async (q: string, page: number) => {
    setLoadingVideos(true)
    try {
      const vs = await videosApi.list({ q: q || undefined, page, page_size: 50 })
      setVideos(vs.items || [])
      setVideosTotalPages(Math.max(1, Number(vs.total_pages || 1)))
      // 默认选中：仅在尚未选择的情况下
      if (!videoId && (vs.items || []).length) {
        setVideoId(vs.items[0].id)
      }
      // 若当前选中的视频不在本页结果里，不强制清空（用户可能只是翻页/搜索）
    } catch (e: any) {
      toast.error(e?.message || '加载视频列表失败')
    } finally {
      setLoadingVideos(false)
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        const [_, tpls] = await Promise.all([fetchVideos('', 1), summaryApi.templates()])
        setTemplates(tpls || [])
      } catch (e: any) {
        toast.error(e?.message || '初始化失败')
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const handle = setTimeout(() => {
      fetchVideos(videosQuery, videosPage)
    }, 250)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videosQuery, videosPage])

  useEffect(() => {
    // 搜索词变化时回到第一页
    setVideosPage(1)
  }, [videosQuery])

  useEffect(() => {
    if (!videoId) return
    ;(async () => {
      try {
        const s = await summaryApi.latest(videoId, { template_id: templateId, mode })
        setCurrent(s)
        setMarkdown(s?.summary_markdown || '')
        if (s?.id) {
          await loadSections(s.id)
        } else {
          setSections([])
        }
      } catch (e: any) {
        toast.error(e?.message || '读取历史总结失败')
      }
    })()
  }, [videoId, templateId, mode, toast])

  const runGenerate = async () => {
    if (!videoId) {
      toast.error('请先选择视频')
      return
    }
    setLoading(true)
    setStreamStatus('开始生成...')
    try {
      const payload = {
        video_id: videoId,
        template_id: templateId,
        mode,
        user_goal: userGoal,
        extra_instructions: preferenceText.trim(),
      }
      const resp = await summaryApi.generateStream(payload)
      if (!resp.ok || !resp.body) {
        throw new Error(`流式请求失败: ${resp.status}`)
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const evt of events) {
          const line = evt
            .split('\n')
            .find((x) => x.startsWith('data: '))
          if (!line) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          let data: any = null
          try {
            data = JSON.parse(raw)
          } catch {
            continue
          }
          if (data?.type === 'status') setStreamStatus(String(data.message || '生成中...'))
          if (data?.type === 'section') {
            setSections((prev) => {
              const idx = prev.findIndex((s) => s.section_key === data.section_key)
              const next = [...prev]
              const item: VideoSummarySection = {
                id: `temp_${data.section_key}`,
                summary_id: current?.id || '',
                section_key: data.section_key,
                status: 'done',
                content_json: data.content_json || {},
                content_markdown: '',
                created_at: '',
                updated_at: '',
              }
              if (idx >= 0) next[idx] = item
              else next.push(item)
              return next
            })
          }
          if (data?.type === 'markdown') setMarkdown(String(data.content || ''))
          if (data?.type === 'done' && data.summary) {
            setCurrent(data.summary)
            if (data.summary?.id) await loadSections(data.summary.id)
            setStreamStatus('生成完成')
            markdownRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
          if (data?.type === 'error') {
            throw new Error(data.detail || '生成失败')
          }
        }
      }
      toast.success('总结已生成')
    } catch (e: any) {
      toast.error(e?.detail || e?.message || '生成失败')
      setStreamStatus('生成失败')
    } finally {
      setLoading(false)
    }
  }

  const loadLatest = async () => {
    if (!videoId) {
      toast.error('请先选择视频')
      return
    }
    setLoading(true)
    try {
      const s = await summaryApi.latest(videoId, { template_id: templateId, mode })
      setCurrent(s)
      setMarkdown(s?.summary_markdown || '')
      if (s?.id) await loadSections(s.id)
      else setSections([])
      toast.success(s ? '已加载历史总结' : '暂无历史总结')
    } catch (e: any) {
      toast.error(e?.message || '加载历史总结失败')
    } finally {
      setLoading(false)
    }
  }

  const saveEdits = async () => {
    if (!current?.id) {
      toast.error('当前没有可保存的总结')
      return
    }
    setLoading(true)
    try {
      const res = await summaryApi.update(current.id, { summary_markdown: markdown, source: 'user' })
      setCurrent(res)
      if (res?.id) {
        await loadSections(res.id)
      }
      toast.success('已保存')
    } catch (e: any) {
      toast.error(e?.detail || e?.message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const regenerateOneSection = async (sectionKey: 'overview' | 'chapters' | 'highlights') => {
    if (!current?.id) {
      toast.error('请先生成或加载一份总结')
      return
    }
    setSectionLoading((prev) => ({ ...prev, [sectionKey]: true }))
    try {
      const res = await summaryApi.regenerateSection(current.id, sectionKey)
      setMarkdown(res.summary_markdown || '')
      await loadSections(current.id)
      setCurrent((prev) => (prev ? { ...prev, updated_at: res.updated_at } : prev))
      const labelMap: Record<'overview' | 'chapters' | 'highlights', string> = {
        overview: '总览',
        chapters: '章节',
        highlights: '重点与行动',
      }
      toast.success(`已重生${labelMap[sectionKey]}`)
      markdownRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } catch (e: any) {
      const labelMap: Record<'overview' | 'chapters' | 'highlights', string> = {
        overview: '总览',
        chapters: '章节',
        highlights: '重点与行动',
      }
      toast.error(e?.detail || e?.message || `重生${labelMap[sectionKey]}失败`)
    } finally {
      setSectionLoading((prev) => ({ ...prev, [sectionKey]: false }))
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-6 py-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">视频总结</h1>
          <p className="text-sm text-slate-400 mt-1">
            基于 ASR / VLM / ASR+VLM 生成：总览、分章节、重点、金句、行动项等，可编辑、可保存、可重新生成。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runGenerate}
            disabled={loading}
            className="px-3 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm"
          >
            {loading ? '生成中…' : '生成/重新生成'}
          </button>
          <button
            onClick={loadLatest}
            disabled={loading}
            className="px-3 py-2 rounded-lg border border-slate-700 hover:border-slate-500 disabled:opacity-50 text-slate-200 text-sm"
          >
            加载历史总结
          </button>
          <button
            onClick={saveEdits}
            disabled={loading || !current?.id}
            className="px-3 py-2 rounded-lg border border-slate-700 hover:border-slate-500 disabled:opacity-50 text-slate-200 text-sm"
          >
            保存编辑
          </button>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-4">
          <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
            <div className="text-sm font-medium text-slate-200">输入</div>

            <div className="mt-3 space-y-3">
              <label className="block">
                <div className="text-xs text-slate-400 mb-1">选择视频</div>
                <input
                  value={videosQuery}
                  onChange={(e) => setVideosQuery(e.target.value)}
                  className="w-full rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 text-sm text-slate-200 mb-2"
                  placeholder="搜索视频名称…"
                />
                <select
                  value={videoId}
                  onChange={(e) => setVideoId(e.target.value)}
                  className="w-full rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 text-sm text-slate-200"
                >
                  {!videos.length ? (
                    <option value="" disabled>
                      {loadingVideos ? '加载中…' : '暂无结果'}
                    </option>
                  ) : null}
                  {videos.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    disabled={loadingVideos || videosPage <= 1}
                    onClick={() => setVideosPage((p) => Math.max(1, p - 1))}
                    className="px-2 py-1 rounded-md border border-slate-800 text-xs text-slate-300 hover:border-slate-600 disabled:opacity-50"
                  >
                    上一页
                  </button>
                  <div className="text-xs text-slate-500">
                    第 {videosPage} / {videosTotalPages} 页
                    {loadingVideos ? '（加载中…）' : ''}
                  </div>
                  <button
                    type="button"
                    disabled={loadingVideos || videosPage >= videosTotalPages}
                    onClick={() => setVideosPage((p) => Math.min(videosTotalPages, p + 1))}
                    className="px-2 py-1 rounded-md border border-slate-800 text-xs text-slate-300 hover:border-slate-600 disabled:opacity-50"
                  >
                    下一页
                  </button>
                </div>
                {selectedVideo?.duration != null ? (
                  <div className="text-xs text-slate-500 mt-1">时长：{Math.round(selectedVideo.duration)} 秒</div>
                ) : null}
              </label>

              <label className="block">
                <div className="text-xs text-slate-400 mb-1">总结模板</div>
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(e.target.value)}
                  className="w-full rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 text-sm text-slate-200"
                >
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
                {templates.find((t) => t.id === templateId)?.description ? (
                  <div className="text-xs text-slate-500 mt-1">{templates.find((t) => t.id === templateId)?.description}</div>
                ) : null}
              </label>

              <label className="block">
                <div className="text-xs text-slate-400 mb-1">总结偏好（可选）</div>
                <textarea
                  value={preferenceText}
                  onChange={(e) => setPreferenceText(e.target.value)}
                  className="w-full h-24 rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 text-sm text-slate-200"
                  placeholder="例如：结论先行，300字内，按章节输出，重点写可执行动作与风险。"
                />
                <div className="text-xs text-slate-500 mt-1">直接写风格、长度、结构、重点方向即可。</div>
              </label>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
            <div className="text-sm font-medium text-slate-200">当前总结</div>
            <div className="text-xs text-slate-500 mt-2 space-y-1">
              <div>id：{current?.id || '-'}</div>
              <div>模板：{current?.template_id || '-'}</div>
              <div>指纹：{current?.input_fingerprint || '-'}</div>
              <div>更新时间：{current?.updated_at || '-'}</div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
            <div className="text-sm font-medium text-slate-200">分块结果（总览 / 章节 / 重点）</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                <div className="text-xs text-slate-400 mb-2 flex items-center justify-between">
                  <span>总览</span>
                  <button
                    onClick={() => regenerateOneSection('overview')}
                    disabled={!!sectionLoading.overview || loading || !current?.id}
                    className="px-2 py-0.5 rounded border border-slate-700 text-[11px] text-slate-300 hover:border-slate-500 disabled:opacity-50"
                  >
                    {sectionLoading.overview ? '重生中…' : '重生本块'}
                  </button>
                </div>
                <div className="text-xs text-slate-500 mb-1">标题</div>
                <div className="text-sm text-slate-200">{overviewSection?.title || '-'}</div>
                <div className="text-xs text-slate-500 mt-2 mb-1">概述</div>
                <div className="text-sm text-slate-300 whitespace-pre-wrap">{overviewSection?.overview || '-'}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                <div className="text-xs text-slate-400 mb-2 flex items-center justify-between">
                  <span>章节</span>
                  <button
                    onClick={() => regenerateOneSection('chapters')}
                    disabled={!!sectionLoading.chapters || loading || !current?.id}
                    className="px-2 py-0.5 rounded border border-slate-700 text-[11px] text-slate-300 hover:border-slate-500 disabled:opacity-50"
                  >
                    {sectionLoading.chapters ? '重生中…' : '重生本块'}
                  </button>
                </div>
                <div className="text-xs text-slate-300">
                  {Array.isArray(chaptersSection?.chapters) ? `共 ${chaptersSection.chapters.length} 章` : '无章节'}
                </div>
                <div className="mt-2 max-h-40 overflow-auto space-y-1">
                  {Array.isArray(chaptersSection?.chapters) && chaptersSection.chapters.length ? (
                    chaptersSection.chapters.map((c: any, idx: number) => (
                      <div key={idx} className="text-xs text-slate-300">
                        {idx + 1}. {c?.title || `章节 ${idx + 1}`}
                      </div>
                    ))
                  ) : (
                    <div className="text-xs text-slate-500">-</div>
                  )}
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                <div className="text-xs text-slate-400 mb-2 flex items-center justify-between">
                  <span>重点与行动</span>
                  <button
                    onClick={() => regenerateOneSection('highlights')}
                    disabled={!!sectionLoading.highlights || loading || !current?.id}
                    className="px-2 py-0.5 rounded border border-slate-700 text-[11px] text-slate-300 hover:border-slate-500 disabled:opacity-50"
                  >
                    {sectionLoading.highlights ? '重生中…' : '重生本块'}
                  </button>
                </div>
                <div className="text-xs text-slate-300">
                  重点：{Array.isArray(highlightsSection?.key_points) ? highlightsSection.key_points.length : 0}
                </div>
                <div className="text-xs text-slate-300">
                  行动项：{Array.isArray(highlightsSection?.action_items) ? highlightsSection.action_items.length : 0}
                </div>
                <div className="text-xs text-slate-300">
                  金句：{Array.isArray(highlightsSection?.quotes) ? highlightsSection.quotes.length : 0}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium text-slate-200">Markdown（可编辑）</div>
              <div className="text-xs text-slate-500">{loading ? streamStatus || '生成中…' : '建议：先编辑再保存；或直接点“重新生成”覆盖。'}</div>
            </div>
            <textarea
              ref={markdownRef}
              value={markdown}
              onChange={(e) => setMarkdown(e.target.value)}
              className="mt-3 w-full h-[420px] rounded-lg bg-slate-950 border border-slate-800 px-3 py-2 text-sm text-slate-200 font-mono"
              placeholder="这里会显示生成的总结（Markdown）。"
            />
          </div>

        </div>
      </div>
    </div>
  )
}

