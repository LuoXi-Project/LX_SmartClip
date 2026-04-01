'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { licenseApi } from '@/lib/api'

/** 启用卡密时，在进入业务页面前的校验与跳转（/license 白名单）。 */
export function LicenseGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (pathname?.startsWith('/license')) {
      setReady(true)
      return
    }
    if (!pathname) {
      setReady(true)
      return
    }
    setReady(false)
    licenseApi
      .status()
      .then((s) => {
        if (s.enforced && !s.valid) {
          router.replace('/license')
        } else {
          setReady(true)
        }
      })
      .catch(() => setReady(true))
  }, [pathname, router])

  if (pathname?.startsWith('/license')) {
    return <>{children}</>
  }

  if (!ready) {
    return (
      <div className="min-h-[40vh] flex items-center justify-center text-slate-400 text-sm">
        正在校验授权…
      </div>
    )
  }
  return <>{children}</>
}
