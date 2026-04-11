type SummaryPageHeaderProps = {
  onLoadLatest: () => void
  onSaveEdits: () => void
  loading: boolean
  canSave: boolean
}

export function SummaryPageHeader({ onLoadLatest, onSaveEdits, loading, canSave }: SummaryPageHeaderProps) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">视频总结</h1>
        <p className="text-sm text-slate-400 mt-1">
          左侧填写<strong className="text-slate-300">笔记风格</strong>并勾选版式（目录、跳转、截图位、AI 总结等），一次生成整篇笔记；右侧预览与编辑 Markdown。
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 justify-end">
        <button
          type="button"
          onClick={onLoadLatest}
          disabled={loading}
          className="px-3 py-2 rounded-lg border border-slate-700 hover:border-slate-500 disabled:opacity-50 text-slate-200 text-sm"
        >
          加载历史总结
        </button>
        <button
          type="button"
          onClick={onSaveEdits}
          disabled={loading || !canSave}
          className="px-3 py-2 rounded-lg border border-slate-700 hover:border-slate-500 disabled:opacity-50 text-slate-200 text-sm"
        >
          保存编辑
        </button>
      </div>
    </div>
  )
}
