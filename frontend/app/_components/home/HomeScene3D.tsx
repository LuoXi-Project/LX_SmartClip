'use client'

import { useEffect, useRef, useState } from 'react'
import { createCosmosWorld, type CosmosHandle } from './createCosmosWorld'

const STATIC_BG_CLASS =
  'pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_30%,#1e3a5f33_0%,transparent_55%),#00040c]'

/** 纯 Three.js 宇宙背景（无 @react-three/fiber，兼容 Next.js 16 + Turbopack） */
export function HomeScene3D() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cosmosRef = useRef<CosmosHandle | null>(null)
  const [ready, setReady] = useState(false)
  const [reduced, setReduced] = useState(false)
  const [webglUnavailable, setWebglUnavailable] = useState(false)
  const [canvasKey, setCanvasKey] = useState(0)

  useEffect(() => {
    setReduced(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    setReady(true)
  }, [])

  useEffect(() => {
    if (!ready || reduced || !canvasRef.current) return

    const handle = createCosmosWorld(canvasRef.current)
    if (!handle) {
      setWebglUnavailable(true)
      return
    }
    setWebglUnavailable(false)
    cosmosRef.current = handle
    return () => {
      cosmosRef.current?.dispose()
      cosmosRef.current = null
      setCanvasKey((k) => k + 1)
    }
  }, [ready, reduced, canvasKey])

  useEffect(() => {
    if (reduced) return
    const onMove = (e: PointerEvent) => {
      const el = wrapRef.current
      if (!el || !cosmosRef.current) return
      const rect = el.getBoundingClientRect()
      cosmosRef.current.setMouse(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      )
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => window.removeEventListener('pointermove', onMove)
  }, [reduced, ready])

  if (!ready) {
    return <div className="absolute inset-0 bg-[#00040c]" aria-hidden />
  }

  if (reduced || webglUnavailable) {
    return <div ref={wrapRef} className={STATIC_BG_CLASS} aria-hidden />
  }

  return (
    <div ref={wrapRef} className="absolute inset-0" aria-hidden>
      <canvas
        key={canvasKey}
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_70%_55%_at_50%_42%,transparent_0%,#00040c_68%)] opacity-80" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#00040c]/20 via-transparent to-[#00040c]/88" />
    </div>
  )
}
