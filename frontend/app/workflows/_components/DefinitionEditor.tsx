'use client'

import { useEffect, useState } from 'react'
import { BookOpen, Braces, CheckCircle2, Loader2, Save, XCircle } from 'lucide-react'
import {
  workflowApi,
  type WorkflowActionCatalogItem,
  type WorkflowDefinition,
  type WorkflowValidationError,
} from '@/lib/api'

/** 空白定义模板（含注释式引导，帮助快速上手 JSON 结构） */
const TEMPLATE = JSON.stringify(
  {
    id: 'my_workflow',
    name: '我的工作流',
    description: '描述这个工作流做什么',
    category: '自定义',
    params: [
      { name: 'copy_text', label: '文案', type: 'textarea', required: true },
    ],
    steps: [
      {
        name: 'ingest',
        title: '素材采集',
        action: 'external_ingest',
        params: { copy_text: '${inputs.copy_text}', platforms: ['douyin'] },
      },
      {
        name: 'wait_process',
        title: '素材预处理',
        action: 'wait_process',
        params: { video_ids: '${steps.ingest.video_ids}' },
      },
    ],
  },
  null,
  2,
)

/** 自定义工作流 JSON 编辑器：校验（后端 validate API 即时反馈）→ 保存。
 *  这是「数据化定义」链路的人工入口；后期 Agent 创建的定义出现在同一列表。 */
export function DefinitionEditor({
  editing,
  onSaved,
}: {
  editing: WorkflowDefinition | null
  onSaved: () => void
}) {
  const [text, setText] = useState(TEMPLATE)
  const [actions, setActions] = useState<WorkflowActionCatalogItem[]>([])
  const [showCatalog, setShowCatalog] = useState(false)
  const [validating, setValidating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<WorkflowValidationError[] | null>(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    workflowApi
      .listActions()
      .then((r) => setActions(r.items))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (editing) {
      setText(JSON.stringify(editing.definition, null, 2))
      setErrors(null)
      setMessage('')
    }
  }, [editing])

  const parse = (): Record<string, unknown> | null => {
    try {
      const obj = JSON.parse(text)
      setMessage('')
      return obj
    } catch (e) {
      setErrors([{ field: 'json', message: `JSON 解析失败：${(e as Error).message}` }])
      return null
    }
  }

  const handleValidate = async () => {
    const obj = parse()
    if (!obj) return
    setValidating(true)
    try {
      const r = await workflowApi.validateDefinition(obj)
      setErrors(r.errors)
      setMessage(r.valid ? '校验通过 ✓' : `校验发现 ${r.errors.length} 个问题`)
    } catch (e) {
      setErrors([{ field: 'json', message: formatDetail(e) }])
    } finally {
      setValidating(false)
    }
  }

  const handleSave = async () => {
    const obj = parse()
    if (!obj) return
    setSaving(true)
    try {
      await workflowApi.saveDefinition(obj)
      setErrors(null)
      setMessage('已保存 ✓')
      onSaved()
    } catch (e) {
      setErrors(extractErrors(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <Braces size={15} className="text-violet-400" />
          {editing ? `编辑自定义工作流：${editing.name}` : '新建自定义工作流（JSON）'}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowCatalog((v) => !v)}
            className="flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 transition-colors hover:border-slate-500 hover:text-slate-100"
          >
            <BookOpen size={12} />
            动作目录（{actions.length}）
          </button>
          <button
            type="button"
            onClick={handleValidate}
            disabled={validating}
            className="flex items-center gap-1 rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-200 transition-colors hover:border-slate-500 disabled:opacity-50"
          >
            {validating ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            校验
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1 rounded-md border border-cyan-500/50 bg-cyan-500/15 px-2.5 py-1 text-xs text-cyan-200 transition-colors hover:bg-cyan-500/25 disabled:opacity-50"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            保存
          </button>
        </div>
      </div>

      {showCatalog && (
        <div className="mb-3 max-h-56 space-y-2 overflow-y-auto rounded-md border border-slate-800 bg-slate-950/60 p-2.5">
          {actions.map((a) => (
            <div key={a.name} className="text-[11px] leading-4">
              <span className="font-mono text-cyan-300">{a.name}</span>
              <span className="ml-1.5 text-slate-300">{a.title}</span>
              <span className="ml-1.5 text-slate-500">
                输入: {Object.keys(a.input_schema || {}).join(', ') || '无'}
              </span>
              <p className="text-slate-500">{a.description}</p>
            </div>
          ))}
        </div>
      )}

      <textarea
        className="h-72 w-full resize-y rounded-md border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs leading-5 text-slate-200 focus:border-violet-500/60 focus:outline-none"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      {message && !errors?.length && (
        <p className="mt-2 flex items-center gap-1 text-xs text-emerald-400">
          <CheckCircle2 size={12} /> {message}
        </p>
      )}
      {!!errors?.length && (
        <div className="mt-2 space-y-1 rounded-md border border-rose-500/30 bg-rose-500/10 p-2">
          {errors.map((e, i) => (
            <p key={i} className="flex items-start gap-1 text-xs text-rose-300">
              <XCircle size={12} className="mt-0.5 shrink-0" />
              <span>
                <span className="font-mono text-rose-200">{e.field || 'json'}</span>
                {e.field ? '：' : ''}
                {e.message}
              </span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function extractErrors(e: unknown): WorkflowValidationError[] {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (detail && typeof detail === 'object' && Array.isArray((detail as { errors?: unknown }).errors)) {
    return (detail as { errors: WorkflowValidationError[] }).errors
  }
  return [{ field: '', message: formatDetail(e) }]
}

function formatDetail(e: unknown): string {
  const anyE = e as { response?: { data?: { detail?: unknown } }; message?: string }
  const detail = anyE?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in (detail as object)) {
    return String((detail as { message?: unknown }).message)
  }
  return anyE?.message || '请求失败'
}
