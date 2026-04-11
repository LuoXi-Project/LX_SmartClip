import type { VideoSummary } from '@/lib/api'

type CurrentSummaryMetaProps = {
  current: VideoSummary | null
}

export function CurrentSummaryMeta({ current }: CurrentSummaryMetaProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0d0f14] p-4">
      <div className="text-sm font-medium text-slate-200">当前总结</div>
      <div className="text-xs text-slate-500 mt-2 space-y-1">
        <div>id：{current?.id || '-'}</div>
        <div>模板 ID：{current?.template_id || '-'}</div>
        <div>指纹：{current?.input_fingerprint || '-'}</div>
        <div>更新时间：{current?.updated_at || '-'}</div>
      </div>
    </div>
  )
}
