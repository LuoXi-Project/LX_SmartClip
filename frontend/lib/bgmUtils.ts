import type { BgmTrack } from '@/lib/api'

export type BgmTrackValueField = 'id' | 'filename'

export function getBgmTrackValue(track: BgmTrack, field: BgmTrackValueField): string {
  return field === 'id' ? track.id : track.filename
}

export function findBgmTrackByValue(
  tracks: BgmTrack[],
  value: string,
  field: BgmTrackValueField
): BgmTrack | undefined {
  if (!value) return undefined
  return tracks.find((t) => getBgmTrackValue(t, field) === value)
}

/** 与设置页 BGM 曲库一致的检索字段 */
export function filterBgmTracks(
  tracks: BgmTrack[],
  opts: { query?: string; mood?: string }
): BgmTrack[] {
  const q = (opts.query ?? '').trim().toLowerCase()
  const mood = (opts.mood ?? '').trim().toLowerCase()
  return tracks.filter((t) => {
    const moodText = String(t.mood || '').toLowerCase()
    const tags = (t.tags || []).map((x) => x.toLowerCase())
    const matchesQuery =
      !q ||
      [t.title, t.filename, moodText, String(t.bpm ?? ''), ...tags]
        .join(' ')
        .toLowerCase()
        .includes(q)
    const matchesMood = !mood || moodText === mood
    return matchesQuery && matchesMood
  })
}

export const BGM_MOOD_LABELS: Record<string, string> = {
  happy: '欢乐',
  calm: '平静',
  epic: '燃/史诗',
  sad: '伤感',
  tech: '科技',
  horror: '恐怖',
  suspense: '悬疑',
  action: '动作',
  romantic: '浪漫',
  inspiring: '励志',
  retro: '复古',
  fantasy: '奇幻',
}

export function formatBgmMood(mood?: string | null): string {
  if (!mood) return ''
  return BGM_MOOD_LABELS[mood] ?? mood
}

export function formatBgmTrackSubtitle(track: BgmTrack): string {
  const parts: string[] = []
  const mood = formatBgmMood(track.mood)
  if (mood) parts.push(mood)
  if (track.bpm) parts.push(`${track.bpm} BPM`)
  const tags = (track.tags || []).slice(0, 3)
  if (tags.length) parts.push(tags.join(' · '))
  return parts.join(' · ')
}
