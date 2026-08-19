'use client'

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 工作流参数记忆：按工作流 id 持久化上次填写的输入（localStorage） */
interface WorkflowPrefState {
  values: Record<string, Record<string, unknown>>
  setParam: (workflowId: string, name: string, value: unknown) => void
  resetWorkflow: (workflowId: string) => void
}

export const useWorkflowPrefStore = create<WorkflowPrefState>()(
  persist(
    (set) => ({
      values: {},
      setParam: (workflowId, name, value) =>
        set((s) => ({
          values: {
            ...s.values,
            [workflowId]: { ...(s.values[workflowId] || {}), [name]: value },
          },
        })),
      resetWorkflow: (workflowId) =>
        set((s) => {
          const next = { ...s.values }
          delete next[workflowId]
          return { values: next }
        }),
    }),
    { name: 'lx-workflow-prefs' },
  ),
)
