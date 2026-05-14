'use client'

import { useEffect, useState } from 'react'
import { SummaryPageHeader } from './_components/summary-page-header'
import { VideoMaterialPanel } from './_components/video-material-panel'
import { NoteStylePanel } from './_components/note-style-panel'
import { CurrentSummaryMeta } from './_components/current-summary-meta'
import { NoteContentPanel } from './_components/note-content-panel'
import { SmartOutlinePanel } from './_components/smart-outline-panel'
import { useSummaryPage } from './_hooks/use-summary-page'

type RightTab = 'note' | 'outline'

export default function SummaryPage() {
  const [rightTab, setRightTab] = useState<RightTab>('note')
  const {
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
  } = useSummaryPage()

  useEffect(() => {
    setRightTab('note')
  }, [videoId])

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6">
      <SummaryPageHeader
        onLoadLatest={loadLatest}
        onSaveEdits={saveEdits}
        loading={loading}
        canSave={!!current?.id}
      />

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-[minmax(280px,360px)_minmax(0,1fr)] gap-4 lg:gap-6">
        <div className="space-y-4 min-w-0 lg:h-full">
          <VideoMaterialPanel
            videos={videos}
            videosQuery={videosQuery}
            onVideosQueryChange={setVideosQuery}
            videoId={videoId}
            onVideoIdChange={setVideoId}
            videosPage={videosPage}
            videosTotalPages={videosTotalPages}
            onVideosPageChange={setVideosPage}
            loadingVideos={loadingVideos}
            selectedVideo={selectedVideo}
          />

          <NoteStylePanel
            noteOptions={noteOptions}
            onNoteOptionsChange={setNoteOptions}
            styleText={styleText}
            onStyleTextChange={setStyleText}
            loading={loading}
            hasVideo={!!videoId}
            onGenerate={runGenerate}
          />

          <CurrentSummaryMeta current={current} />
        </div>

        <div className="min-w-0 lg:h-full lg:flex lg:flex-col lg:min-h-0">
          <div className="mb-3 flex shrink-0 rounded-xl border border-slate-800 bg-slate-900/50 p-1">
            <button
              type="button"
              onClick={() => setRightTab('note')}
              className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                rightTab === 'note'
                  ? 'bg-indigo-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              视频笔记
            </button>
            <button
              type="button"
              onClick={() => setRightTab('outline')}
              className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                rightTab === 'outline'
                  ? 'bg-violet-600 text-white shadow'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              智能大纲
            </button>
          </div>

          {rightTab === 'note' ? (
            <NoteContentPanel
              notePanelRef={notePanelRef}
              markdownRef={markdownRef}
              noteView={noteView}
              onNoteViewChange={setNoteView}
              markdown={markdown}
              onMarkdownChange={setMarkdown}
              videoId={videoId}
              loading={loading}
              streamStatus={streamStatus}
              onCopy={copyMarkdown}
              onExport={exportMarkdown}
            />
          ) : (
            <div className="flex-1 min-h-0 flex flex-col">
              <SmartOutlinePanel videoId={videoId} selectedVideo={selectedVideo} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
