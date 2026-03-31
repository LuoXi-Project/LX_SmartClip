'use client'

import Link from 'next/link'
import { ArrowLeft, Music2 } from 'lucide-react'
import { BgmSection } from '../settings/_components/BgmSection'

export default function BgmPage() {
  return (
    <main className="min-h-screen bg-[#0d0f14] text-slate-200">
      <div className="max-w-6xl mx-auto px-6 py-10 space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" />首页
          </Link>
          <div className="w-px h-4 bg-slate-700" />
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <Music2 className="w-5 h-5 text-indigo-400" />BGM 音乐库管理
          </h1>
        </div>

        <BgmSection fullPage />
      </div>
    </main>
  )
}

