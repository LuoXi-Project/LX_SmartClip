'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  summaryApi,
  type SummaryGenerateRequest,
  type SummaryMode,
  type Video,
  videosApi,
  type VideoSummary,
} from '@/lib/api'
import { useToast } from '@/components/ui/toast-provider'
import { useConfirm } from '@/hooks/use-confirm'
import { readSSE } from '@/lib/stream'
import type { NoteLayoutOptions } from '../_lib/types'
import {
  formatStageAProgressMarkdown,
  type StageASegment,
} from '../_lib/stage-a-preview'

const defaultNoteOptions = (): NoteLayoutOptions => ({
  toc: true,
  timeJump: true,
  screenshot: true,
  aiSummary: true,
})

export function useSummaryPage() {
  const toast = useToast()
  const confirm = useConfirm()

  const [videos, setVideos] = useState<Video[]>([])
  const [videosQuery, setVideosQuery] = useState('')
  const [videosPage, setVideosPage] = useState(1)
  const [videosTotalPages, setVideosTotalPages] = useState(1)
  const [loadingVideos, setLoadingVideos] = useState(false)

  const [videoId, setVideoId] = useState('')
  const [mode] = useState<SummaryMode>('asr_vlm')
  const [userGoal] = useState('通用视频总结')
  const [styleText, setStyleText] = useState('')

  const [noteOptions, setNoteOptions] = useState<NoteLayoutOptions>(defaultNoteOptions)
  const [noteView, setNoteView] = useState<'preview' | 'edit'>('preview')

  const [loading, setLoading] = useState(false)
  const [current, setCurrent] = useState<VideoSummary | null>(null)

  const [markdown, setMarkdown] = useState('')
  const [streamStatus, setStreamStatus] = useState('')
  const [stageProgress, setStageProgress] = useState<{ idx: number; total: number } | null>(null)
  const stageSegmentsRef = useRef<StageASegment[]>([])
  const markdownRef = useRef<HTMLTextAreaElement | null>(null)
  const notePanelRef = useRef<HTMLDivElement | null>(null)

  const selectedVideo = useMemo(() => videos.find((v) => v.id === videoId) || null, [videos, videoId])

  /** 切换视频前拦截：有未保存的笔记修改时先确认，避免静默覆盖 */
  const changeVideo = async (id: string) => {
    if (id === videoId) return
    const dirty =
      !loading && markdown.trim() !== '' && markdown !== (current?.summary_markdown ?? '')
    if (dirty) {
      const ok = await confirm({
        title: '切换视频？',
        description: '当前笔记有未保存的修改，切换后将丢失。建议先点击「保存修改」。',
        confirmLabel: '放弃修改并切换',
        variant: 'danger',
      })
      if (!ok) return
    }
    setVideoId(id)
  }

  const fetchVideos = async (q: string, page: number) => {
    setLoadingVideos(true)
    try {
      const vs = await videosApi.list({ q: q || undefined, page, page_size: 50 })
      setVideos(vs.items || [])
      setVideosTotalPages(Math.max(1, Number(vs.total_pages || 1)))
      if (!videoId && (vs.items || []).length) {
        setVideoId(vs.items[0].id)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载视频列表失败'
      toast.error(msg)
    } finally {
      setLoadingVideos(false)
    }
  }

  useEffect(() => {
    ;(async () => {
      try {
        await fetchVideos('', 1)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '初始化失败'
        toast.error(msg)
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
    setVideosPage(1)
  }, [videosQuery])

  useEffect(() => {
    if (!videoId) return
    ;(async () => {
      try {
        const s = await summaryApi.latest(videoId, { mode })
        setCurrent(s)
        setMarkdown(s?.summary_markdown || '')
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '读取历史总结失败'
        toast.error(msg)
      }
    })()
  }, [videoId, mode, toast])

  const runGenerate = async () => {
    if (!videoId) {
      toast.error('请先选择视频')
      return
    }
    setLoading(true)
    setMarkdown('')
    setStreamStatus('开始生成...')
    setStageProgress(null)
    stageSegmentsRef.current = []
    try {
      const payload: SummaryGenerateRequest = {
        video_id: videoId,
        mode,
        user_goal: userGoal,
        extra_instructions: styleText.trim(),
        prompt_vars: {
          note_toc: noteOptions.toc,
          note_time_jump: noteOptions.timeJump,
          note_screenshot: noteOptions.screenshot,
          note_ai_summary: noteOptions.aiSummary,
        },
      }
      const resp = await summaryApi.generateStream(payload)
      let failed = false
      let failMsg = '生成失败'
      await readSSE(resp, {
        onEvent: (_event, data) => {
          if (data === '[DONE]') return
          const d = data as {
            type?: string
            message?: string
            content?: string
            summary?: VideoSummary
            detail?: string
            idx?: number
            total?: number
            segment?: StageASegment
          }
          if (d?.type === 'error') {
            failed = true
            failMsg = d.detail || '生成失败'
            return
          }
          if (d?.type === 'status') {
            const msg = String(d.message || '生成中...')
            setStreamStatus(msg)
            const seg = msg.match(/分段摘要\s+(\d+)\/(\d+)/)
            if (seg) {
              const current = Number(seg[1])
              const total = Number(seg[2])
              if (current > 0 && total > 0) {
                setStageProgress({ idx: current - 1, total })
                setStreamStatus(`正在分析第 ${current}/${total} 段…`)
              }
            }
          }
          if (d?.type === 'stage_a' && d.segment != null) {
            const idx = Number(d.idx) || stageSegmentsRef.current.length + 1
            const total = Number(d.total) || idx
            stageSegmentsRef.current = [...stageSegmentsRef.current, d.segment]
            setStageProgress({ idx, total })
            setStreamStatus(`分段分析 ${idx}/${total} 已完成`)
            setMarkdown(
              formatStageAProgressMarkdown(stageSegmentsRef.current, {
                idx,
                total,
                phase: 'stage_a',
              }),
            )
          }
          if (d?.type === 'markdown') {
            setStreamStatus('正在生成完整 Markdown 笔记（流式）…')
            const content = String(d.content || '')
            if (content.trim()) {
              setStageProgress(null)
              setMarkdown(content)
            } else if (stageSegmentsRef.current.length) {
              const total = stageSegmentsRef.current.length
              setStageProgress({ idx: total, total })
              setMarkdown(
                formatStageAProgressMarkdown(stageSegmentsRef.current, {
                  idx: total,
                  total,
                  phase: 'stage_b',
                }),
              )
            }
          }
          if (d?.type === 'done' && d.summary) {
            setCurrent(d.summary)
            const saved = d.summary.summary_markdown
            if (saved != null && saved !== '') setMarkdown(saved)
            setStreamStatus('生成完成')
            setStageProgress(null)
            stageSegmentsRef.current = []
            notePanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
        },
        onError: (err) => {
          failed = true
          failMsg = err.message
        },
      })
      if (failed) throw new Error(failMsg)
      toast.success('总结已生成')
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string }
      toast.error(err?.detail || err?.message || '生成失败')
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
      const s = await summaryApi.latest(videoId, { mode })
      setCurrent(s)
      setMarkdown(s?.summary_markdown || '')
      toast.success(s ? '已加载历史总结' : '暂无历史总结')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '加载历史总结失败'
      toast.error(msg)
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
      toast.success('已保存')
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string }
      toast.error(err?.detail || err?.message || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(markdown)
      toast.success('已复制 Markdown')
    } catch {
      toast.error('复制失败')
    }
  }

  const exportMarkdown = () => {
    const blob = new Blob([markdown || ''], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${selectedVideo?.name?.replace(/[\\/:*?"<>|]/g, '_') || '笔记'}.md`
    a.click()
    URL.revokeObjectURL(a.href)
    toast.success('已导出')
  }

  return {
    videos,
    videosQuery,
    setVideosQuery,
    videosPage,
    setVideosPage,
    videosTotalPages,
    loadingVideos,
    videoId,
    setVideoId: changeVideo,
    selectedVideo,
    styleText,
    setStyleText,
    noteOptions,
    setNoteOptions,
    noteView,
    setNoteView,
    loading,
    current,
    markdown,
    setMarkdown,
    streamStatus,
    stageProgress,
    markdownRef,
    notePanelRef,
    loadLatest,
    saveEdits,
    runGenerate,
    copyMarkdown,
    exportMarkdown,
  }
}
