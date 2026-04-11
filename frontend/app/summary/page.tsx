'use client'

import { SummaryPageHeader } from './_components/summary-page-header'
import { VideoMaterialPanel } from './_components/video-material-panel'
import { NoteStylePanel } from './_components/note-style-panel'
import { CurrentSummaryMeta } from './_components/current-summary-meta'
import { NoteContentPanel } from './_components/note-content-panel'
import { useSummaryPage } from './_hooks/use-summary-page'

export default function SummaryPage() {
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

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-6">
      <SummaryPageHeader
        onLoadLatest={loadLatest}
        onSaveEdits={saveEdits}
        loading={loading}
        canSave={!!current?.id}
      />

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-[minmax(300px,380px)_minmax(0,1fr)] gap-4 lg:gap-6">
        <div className="space-y-4 min-w-0">
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

        <div className="space-y-4 min-w-0">
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
        </div>
      </div>
    </div>
  )
}
