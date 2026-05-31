'use client'

import { Info } from 'lucide-react'
import { useStudioStore } from '@/lib/studio-store'

export function InspectorPanel() {
  const { workspace, selectedArtifact } = useStudioStore()

  return (
    <div className="flex flex-col h-full border-l border-slate-800 bg-[#0d0f14]">
      <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
        <Info className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-medium text-slate-200">检查器</span>
      </div>
      <div className="flex-1 overflow-auto p-4 text-xs text-slate-400 space-y-4">
        {workspace && (
          <section>
            <h3 className="text-slate-500 uppercase tracking-wider mb-2">工作区</h3>
            <pre className="whitespace-pre-wrap break-all text-[11px] bg-slate-900/50 rounded-lg p-2 border border-slate-800">
              {JSON.stringify(
                {
                  title: workspace.title,
                  phase: workspace.pipeline_phase,
                  videos: workspace.selected_video_ids,
                  plans: workspace.plans?.length ?? 0,
                  active_plan_id: workspace.active_plan_id,
                  checkpoints: workspace.checkpoints?.length ?? 0,
                  exports: workspace.last_exports?.length ?? 0,
                },
                null,
                2
              )}
            </pre>
          </section>
        )}
        {selectedArtifact && (
          <section>
            <h3 className="text-slate-500 uppercase tracking-wider mb-2">选中产物</h3>
            <pre className="whitespace-pre-wrap break-all text-[11px] bg-slate-900/50 rounded-lg p-2 border border-slate-800 max-h-64 overflow-auto">
              {JSON.stringify(selectedArtifact, null, 2)}
            </pre>
          </section>
        )}
      </div>
    </div>
  )
}
