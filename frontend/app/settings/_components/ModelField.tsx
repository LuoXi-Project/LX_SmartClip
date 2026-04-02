'use client'

import type { ReactNode } from 'react'
import { ModelPicker } from './ModelPicker'
import { SaveBtn } from './SaveBtn'

interface Props {
  label: string
  value: string
  baseUrl: string
  apiKey: string
  placeholder?: string
  onChange: (v: string) => void
  dirty: boolean
  saving: boolean
  saved: boolean
  onSave: () => void
  description?: ReactNode
}

export function ModelField({
  label,
  value,
  baseUrl,
  apiKey,
  placeholder,
  onChange,
  dirty,
  saving,
  saved,
  onSave,
  description,
}: Props) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs text-slate-400">{label}</label>
      <div className="flex gap-2 items-start">
        <div className="flex-1">
          <ModelPicker value={value} onChange={onChange} baseUrl={baseUrl} apiKey={apiKey} placeholder={placeholder} />
        </div>
        <SaveBtn dirty={dirty} saving={saving} saved={saved} onSave={onSave} />
      </div>
      {description ? <div className="text-xs text-slate-500">{description}</div> : null}
    </div>
  )
}

