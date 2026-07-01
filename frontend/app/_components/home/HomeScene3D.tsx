'use client'

import { useEffect, useRef, useState } from 'react'
import { createSolarSystem, type SolarHandle } from './solar/createSolarSystem'

const STATIC_BG_CLASS =
  'pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_75%,#1a1a2e44_0%,transparent_50%),radial-gradient(ellipse_at_50%_20%,#0c1929_0%,#000208_70%)]'

/** 太阳系 3D 背景（无 @react-three/fiber，兼容 Next.js 16 + Turbopack）
 *  交互：拖拽旋转 / 滚轮缩放 / 点击星球跟随。控制面板与描述信息已隐藏，
 *  仅保留「点击星球 → 相机锁定跟随」与固定慢速自转，供首页欣赏。 */
export function HomeScene3D() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const solarRef = useRef<SolarHandle | null>(null)
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

    const handle = createSolarSystem(canvasRef.current)
    if (!handle) {
      setWebglUnavailable(true)
      return
    }
    setWebglUnavailable(false)
    solarRef.current = handle
    return () => {
      solarRef.current?.dispose()
      solarRef.current = null
      setCanvasKey((k) => k + 1)
    }
  }, [ready, reduced, canvasKey])

  if (!ready) {
    return <div className="absolute inset-0 bg-[#00040c]" aria-hidden />
  }

  if (reduced || webglUnavailable) {
    return <div className={STATIC_BG_CLASS} aria-hidden />
  }

  return (
    // z-[3] 让画布位于装饰层（模糊光晕 z-[1]、暗角 z-[2]）之上；
    // 外层容器 pointer-events-none，仅画布自身 pointer-events-auto，
    // 这样：① 点击星球 → 落到画布触发拾取；
    //       ② 点击落在 z-10 的标题/按钮上时仍由这些 UI 元素接管（它们层级更高）。
    <div className="pointer-events-none absolute inset-0 z-[3]" aria-hidden>
      <canvas
        key={canvasKey}
        ref={canvasRef}
        className="pointer-events-auto absolute inset-0 h-full w-full"
        style={{ touchAction: 'none' }}
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_88%_68%_at_50%_34%,transparent_0%,#00010a_62%)] opacity-58" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#00010a]/22 via-transparent to-[#00010a]/82" />
    </div>
  )
}
