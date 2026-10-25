'use client'

import clsx from 'clsx'
import { CheckSquare, Square } from 'lucide-react'
import type { WorkflowParamSpec } from '@/lib/api'
import { VideoIdsPicker } from './VideoIdsPicker'

/** 按 ParamSpec 声明自动渲染的参数表单（text/textarea/number/select/multiselect/switch） */
export function ParamForm({
  params,
  values,
  onChange,
  errors,
}: {
  params: WorkflowParamSpec[]
  values: Record<string, unknown>
  onChange: (name: string, value: unknown) => void
  errors?: Record<string, string>
}) {
  if (!params.length) {
    return <p className="text-xs text-slate-500">该工作流无需填写参数，可直接运行。</p>
  }
  return (
    <div className="space-y-3">
      {params.map((spec) => {
        const err = errors?.[spec.name]
        return (
        <div key={spec.name} className="space-y-1">
          <label className="flex items-center gap-1 text-xs font-medium text-slate-300">
            {spec.label}
            {spec.required && <span className="text-rose-400">*</span>}
          </label>
          <ParamField
            spec={spec}
            value={values[spec.name]}
            invalid={!!err}
            onChange={(v) => onChange(spec.name, v)}
          />
          {err ? (
            <p className="text-[11px] leading-4 text-rose-400">{err}</p>
          ) : spec.help ? (
            <p className="text-[11px] leading-4 text-slate-500">{spec.help}</p>
          ) : null}
        </div>
        )
      })}
    </div>
  )
}

function ParamField({
  spec,
  value,
  onChange,
  invalid,
}: {
  spec: WorkflowParamSpec
  value: unknown
  onChange: (value: unknown) => void
  invalid?: boolean
}) {
  const inputCls = clsx(
    'w-full rounded-md border bg-slate-900/70 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none',
    invalid
      ? 'border-rose-500/70 focus:border-rose-500'
      : 'border-slate-700 focus:border-cyan-500/60',
  )

  if (spec.type === 'video_ids') {
    return <VideoIdsPicker value={value} onChange={(v) => onChange(v)} />
  }
  if (spec.type === 'textarea') {
    return (
      <textarea
        className={clsx(inputCls, 'min-h-[96px] resize-y')}
        placeholder={spec.placeholder || ''}
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  if (spec.type === 'number') {
    return (
      <input
        type="number"
        className={inputCls}
        placeholder={spec.placeholder || ''}
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    )
  }
  if (spec.type === 'select') {
    return (
      <select
        className={inputCls}
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{spec.placeholder || '请选择'}</option>
        {(spec.options || []).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }
  if (spec.type === 'multiselect') {
    const selected = Array.isArray(value) ? (value as string[]) : []
    return (
      <div className="flex flex-wrap gap-1.5">
        {(spec.options || []).map((o) => {
          const on = selected.includes(o.value)
          return (
            <button
              key={o.value}
              type="button"
              onClick={() =>
                onChange(on ? selected.filter((v) => v !== o.value) : [...selected, o.value])
              }
              className={clsx(
                'flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors',
                on
                  ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                  : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-600 hover:text-slate-200',
              )}
            >
              {on ? <CheckSquare size={12} /> : <Square size={12} />}
              {o.label}
            </button>
          )
        })}
      </div>
    )
  }
  if (spec.type === 'switch') {
    const on = value === true || value === 'true'
    return (
      <button
        type="button"
        onClick={() => onChange(!on)}
        className={clsx(
          'flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors',
          on
            ? 'border-emerald-500/60 bg-emerald-500/15 text-emerald-200'
            : 'border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-600',
        )}
      >
        <span
          className={clsx(
            'relative h-4 w-7 rounded-full transition-colors',
            on ? 'bg-emerald-500/70' : 'bg-slate-700',
          )}
        >
          <span
            className={clsx(
              'absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all',
              on ? 'left-3.5' : 'left-0.5',
            )}
          />
        </span>
        {on ? '已开启' : '已关闭'}
      </button>
    )
  }
  return (
    <input
      type="text"
      className={inputCls}
      placeholder={spec.placeholder || ''}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}
