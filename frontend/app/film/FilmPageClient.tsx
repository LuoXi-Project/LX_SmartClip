'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import { useMatchStore } from '@/lib/store'

/** 独立路由保留兼容：重定向到智能剪辑 · 影视解说工作区 */
export default function FilmRedirectPage() {
  const router = useRouter()
  const setMatchMode = useMatchStore((s) => s.setMatchMode)

  useEffect(() => {
    setMatchMode('film_commentary')
    router.replace('/match')
  }, [router, setMatchMode])

  return (
    <div className="min-h-[40vh] flex items-center justify-center text-slate-400 text-sm gap-2">
      <Loader2 className="w-4 h-4 animate-spin" />
      正在打开智能剪辑 · 影视解说…
    </div>
  )
}
