import type { Video } from '@/lib/api'

type VideoMaterialPanelProps = {
  videos: Video[]
  videosQuery: string
  onVideosQueryChange: (q: string) => void
  videoId: string
  onVideoIdChange: (id: string) => void
  videosPage: number
  videosTotalPages: number
  onVideosPageChange: (page: number) => void
  loadingVideos: boolean
  selectedVideo: Video | null
}

export function VideoMaterialPanel({
  videos,
  videosQuery,
  onVideosQueryChange,
  videoId,
  onVideoIdChange,
  videosPage,
  videosTotalPages,
  onVideosPageChange,
  loadingVideos,
  selectedVideo,
}: VideoMaterialPanelProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
      <div className="text-sm font-medium text-slate-200">素材</div>

      <div className="mt-3 space-y-3">
        <label className="block">
          <div className="text-xs text-slate-400 mb-1">选择视频</div>
          <input
            value={videosQuery}
            onChange={(e) => onVideosQueryChange(e.target.value)}
            className="w-full rounded-lg bg-slate-900 border border-slate-800 px-3 py-2 text-sm text-slate-200 mb-2"
            placeholder="搜索视频名称…"
          />
          <select
            value={videoId}
            onChange={(e) => onVideoIdChange(e.target.value)}
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
              onClick={() => onVideosPageChange(Math.max(1, videosPage - 1))}
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
              onClick={() => onVideosPageChange(Math.min(videosTotalPages, videosPage + 1))}
              className="px-2 py-1 rounded-md border border-slate-800 text-xs text-slate-300 hover:border-slate-600 disabled:opacity-50"
            >
              下一页
            </button>
          </div>
          {selectedVideo?.duration != null ? (
            <div className="text-xs text-slate-500 mt-1">时长：{Math.round(selectedVideo.duration)} 秒</div>
          ) : null}
        </label>
      </div>
    </div>
  )
}
