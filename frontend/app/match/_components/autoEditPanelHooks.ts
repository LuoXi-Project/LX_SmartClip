'use client'

import { useEffect, useState } from 'react'
import { bgmApi, type AutoEditPlanApi, type BgmTrack } from '@/lib/api'
import { API_BASE_URL } from '@/lib/runtime-config'
import type { ClipMetaByClip } from './autoEditTypes'

export function useAutoEditBgmTracks() {
  const [bgmTracks, setBgmTracks] = useState<BgmTrack[]>([])
  const [bgmListError, setBgmListError] = useState('')

  useEffect(() => {
    let cancelled = false

    void bgmApi
      .list()
      .then((list) => {
        if (cancelled) return
        setBgmTracks(Array.isArray(list) ? list : [])
        setBgmListError('')
      })
      .catch(() => {
        if (cancelled) return
        setBgmListError('无法加载 BGM 列表')
        setBgmTracks([])
      })

    return () => {
      cancelled = true
    }
  }, [])

  return { bgmTracks, bgmListError }
}

export function useAutoEditClipMetaByPlans(autoPlans: AutoEditPlanApi[]) {
  const [clipMetaByClip, setClipMetaByClip] = useState<ClipMetaByClip>({})

  useEffect(() => {
    if (!autoPlans.length) return

    const ids = new Set<string>()
    for (const p of autoPlans) {
      for (const s of p.segments ?? []) {
        const cid = s.selected_clip_ids?.[0] || s.clip_group?.[0]?.clip_id
        if (cid) ids.add(cid)
      }
    }

    const ac = new AbortController()
    for (const cid of ids) {
      void fetch(`${API_BASE_URL}/api/videos/clips/${cid}`, { signal: ac.signal })
        .then(async (r) => {
          if (!r.ok) return
          const data = (await r.json()) as { video_id: string; start_time: number; end_time: number }
          if (!data?.video_id) return
          setClipMetaByClip((prev) => {
            if (prev[cid]) return prev
            return {
              ...prev,
              [cid]: {
                video_id: data.video_id,
                start_time: Number(data.start_time),
                end_time: Number(data.end_time),
              },
            }
          })
        })
        .catch(() => {})
    }

    return () => ac.abort()
  }, [autoPlans])

  return clipMetaByClip
}

