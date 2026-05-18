/** 时间轴上一个可编辑片段（轨道块） */
export type TimelineClipBlock = {
  id: string
  /** 轨道内展示标签 */
  label: string
  /** 在成片时间轴上的起止（秒） */
  timelineStart: number
  timelineEnd: number
  /** 源素材上的起止（秒），用于预览 seek */
  sourceStart: number
  sourceEnd: number
  color?: string
  excluded?: boolean
  /** 透传业务索引，便于回调更新 */
  segmentIndex?: number
  subtitleText?: string
  clipId?: string
}

export type TimelineTrackKind = 'video' | 'audio' | 'subtitle'

export type TimelineTrackState = {
  /** 视频/字幕轨：是否在预览中显示 */
  visible?: boolean
  /** 音频轨：是否静音 */
  muted?: boolean
}

export type TimelineTrack = {
  id: string
  kind: TimelineTrackKind
  label: string
  clips: TimelineClipBlock[]
  muted?: boolean
}

export type TimelineSelection = {
  clipId: string
  trackId: string
} | null

export type TimelineEdgeDrag = 'start' | 'end' | 'move' | 'playhead' | null

export type TimelineEditorProps = {
  tracks: TimelineTrack[]
  totalDuration: number
  /** 秒 */
  playheadSec: number
  onPlayheadChange: (sec: number) => void
  selection: TimelineSelection
  onSelectionChange: (sel: TimelineSelection) => void
  editable?: boolean
  /** 拖拽调整出入点/移动块 */
  onClipResize?: (args: {
    clipId: string
    trackId: string
    edge: 'start' | 'end'
    timelineStart: number
    timelineEnd: number
    sourceStart: number
    sourceEnd: number
  }) => void
  onClipMove?: (args: {
    clipId: string
    trackId: string
    deltaSec: number
    timelineStart: number
    timelineEnd: number
  }) => void
  className?: string
  /** 每秒像素，受控或非受控缩放 */
  pxPerSec?: number
  onPxPerSecChange?: (v: number) => void
  minPxPerSec?: number
  maxPxPerSec?: number
  /** 播放时自动滚动使播放头保持在可视区内 */
  followPlayhead?: boolean
  /** 拖拽裁剪出入点时为 true，父级可锁定播放头 */
  onTrimDragChange?: (active: boolean) => void
  /** 轨道显隐/静音，key 为 track.id */
  trackStates?: Record<string, TimelineTrackState>
  onTrackStateChange?: (trackId: string, patch: Partial<TimelineTrackState>) => void
}
