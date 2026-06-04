'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { licenseApi } from '@/lib/api'

/** 启用卡密时，在进入业务页面前的校验与跳转（/license 白名单）。 */
export function LicenseGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const [ready, setReady] = useState(false)
  /** 已通过校验后切换路由不再卸载子树（避免新手指引等状态被重置） */
  const passedOnceRef = useRef(false)

  useEffect(() => {
    if (pathname?.startsWith('/license')) {
      setReady(true)
      return
    }
    if (!pathname) {
      setReady(true)
      return
    }

    let cancelled = false
    licenseApi
      .status()
      .then((s) => {
        if (cancelled) return
        if (s.enforced && !s.valid) {
          passedOnceRef.current = false
          router.replace('/license')
          return
        }
        passedOnceRef.current = true
        setReady(true)
      })
      .catch(() => {
        if (!cancelled) {
          passedOnceRef.current = true
          setReady(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [pathname, router])

  if (pathname?.startsWith('/license')) {
    return <>{children}</>
  }

  if (!ready && !passedOnceRef.current) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-slate-400 text-sm">
        正在校验授权…
      </div>
    )
  }

  return <>{children}</>
}
