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
import type { NoteLayoutOptions } from '../_lib/types'

const defaultNoteOptions = (): NoteLayoutOptions => ({
  toc: true,
  timeJump: true,
  screenshot: true,
  aiSummary: true,
})

export function useSummaryPage() {
  const toast = useToast()

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
  const markdownRef = useRef<HTMLTextAreaElement | null>(null)
  const notePanelRef = useRef<HTMLDivElement | null>(null)

  const selectedVideo = useMemo(() => videos.find((v) => v.id === videoId) || null, [videos, videoId])

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
          const line = evt.split('\n').find((x) => x.startsWith('data: '))
          if (!line) continue
          const raw = line.slice(6).trim()
          if (!raw || raw === '[DONE]') continue
          let data: unknown = null
          try {
            data = JSON.parse(raw)
          } catch {
            continue
          }
          const d = data as {
            type?: string
            message?: string
            content?: string
            summary?: VideoSummary
            detail?: string
          }
          if (d?.type === 'status') setStreamStatus(String(d.message || '生成中...'))
          if (d?.type === 'markdown') setMarkdown(String(d.content || ''))
          if (d?.type === 'done' && d.summary) {
            setCurrent(d.summary)
            const saved = d.summary.summary_markdown
            if (saved != null && saved !== '') setMarkdown(saved)
            setStreamStatus('生成完成')
            notePanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }
          if (d?.type === 'error') {
            throw new Error(d.detail || '生成失败')
          }
        }
      }
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
    setVideoId,
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
    markdownRef,
    notePanelRef,
    loadLatest,
    saveEdits,
    runGenerate,
    copyMarkdown,
    exportMarkdown,
  }
}
