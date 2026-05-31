import type { AutoEditPlanApi } from '@/lib/api'

export type PipelinePhase =
  | 'idle'
  | 'ingest'
  | 'process'
  | 'match'
  | 'plan'
  | 'realize'
  | 'export'

export type ArtifactType = 'plan' | 'match_results' | 'process_job' | 'export' | 'video'

export interface WorkspaceState {
  session_id: string
  title: string
  selected_video_ids: string[]
  pipeline_phase: PipelinePhase
  active_plan_id?: string | null
  plans: AutoEditPlanApi[]
  match_segments: Record<string, unknown>[]
  jobs: {
    process_task_ids: string[]
    film_job_id?: string | null
    realize_job_id?: string | null
  }
  user_preferences: Record<string, unknown>
  checkpoints: Record<string, unknown>[]
  last_exports: Record<string, unknown>[]
}

export interface ArtifactRef {
  type: ArtifactType
  id: string
  payload: Record<string, unknown>
}

export type StudioMessage =
  | { id: string; type: 'user'; content: string }
  | { id: string; type: 'assistant'; content: string }
  | {
      id: string
      type: 'tool'
      name: string
      status: 'running' | 'done' | 'failed'
      summary?: string
      input?: Record<string, unknown>
    }
  | { id: string; type: 'artifact'; artifact: ArtifactRef }
  | {
      id: string
      type: 'confirm'
      callId: string
      tool: string
      risk: string
      preview: string
    }

export interface PendingConfirm {
  callId: string
  tool: string
  risk: string
  preview: string
}
