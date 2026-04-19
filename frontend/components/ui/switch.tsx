'use client'

import clsx from 'clsx'

export type SwitchProps = {
  id?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
  'aria-labelledby'?: string
}

/**
 * 无障碍开关（role="switch"），用于表单内布尔项。
 */
export function Switch({
  id,
  checked,
  onCheckedChange,
  disabled,
  className,
  'aria-labelledby': labelledBy,
}: SwitchProps) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      disabled={disabled}
      onClick={() => {
        if (!disabled) onCheckedChange(!checked)
      }}
      className={clsx(
        'relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border px-0.5 transition-colors',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-500',
        disabled && 'cursor-not-allowed opacity-50',
        checked ? 'border-violet-500/60 bg-violet-600' : 'border-slate-600 bg-slate-700',
        className,
      )}
    >
      <span
        aria-hidden
        className={clsx(
          'pointer-events-none block h-5 w-5 rounded-full bg-white shadow transition-transform',
          'translate-x-0',
          checked && 'translate-x-[1.375rem]',
        )}
      />
    </button>
  )
}
