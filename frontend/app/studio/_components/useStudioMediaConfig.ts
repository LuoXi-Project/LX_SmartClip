'use client'

import { useCallback, useMemo } from 'react'
import { patchAgentWorkspace } from '@/lib/agent-api'
import {
  readStudioMediaConfig,
  type StudioMediaConfig,
} from '@/lib/studio-media-config'
import { useStudioStore } from '@/lib/studio-store'

export function useStudioMediaConfig() {
  const { sessionId, workspace, setWorkspace } = useStudioStore()

  const media = useMemo(
    () => readStudioMediaConfig(workspace?.user_preferences),
    [workspace?.user_preferences]
  )

  const patchMedia = useCallback(
    async (
      patch:
        | Partial<{ subtitle: Partial<StudioMediaConfig['subtitle']>; bgm: Partial<StudioMediaConfig['bgm']> }>
        | ((prev: StudioMediaConfig) => StudioMediaConfig)
    ) => {
      if (!sessionId || !workspace) return
      const prev = readStudioMediaConfig(workspace.user_preferences)
      let next: StudioMediaConfig
      if (typeof patch === 'function') {
        next = patch(prev)
      } else {
        next = {
          subtitle: {
            ...prev.subtitle,
            ...(patch.subtitle || {}),
            style: patch.subtitle?.style
              ? { ...prev.subtitle.style, ...patch.subtitle.style }
              : prev.subtitle.style,
          },
          bgm: { ...prev.bgm, ...(patch.bgm || {}) },
        }
      }
      const user_preferences = {
        ...workspace.user_preferences,
        media_config: next,
      }
      const res = await patchAgentWorkspace(sessionId, { user_preferences })
      setWorkspace(res.workspace)
    },
    [sessionId, workspace, setWorkspace]
  )

  return { media, patchMedia }
}
