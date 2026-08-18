'use client'

import { useEffect, useRef, useState } from 'react'
import { createSolarSystem, type SolarHandle } from './solar/createSolarSystem'
import { resolveQualityTier, type QualityTier } from './solar/quality'

const STATIC_BG_CLASS =
  'pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_75%,#1a1a2e44_0%,transparent_50%),radial-gradient(ellipse_at_50%_20%,#0c1929_0%,#000208_70%)]'

/** 太阳系 3D 背景（无 @react-three/fiber，兼容 Next.js 16 + Turbopack）
 *  交互：拖拽旋转 / 滚轮缩放 / 点击星球跟随。控制面板与描述信息已隐藏，
 *  仅保留「点击星球 → 相机锁定跟随」与固定慢速自转，供首页欣赏。
 *  画质：按机器配置分级（见 solar/quality.ts）——高配全特效；中配保留动画
 *  但降渲染规格；低配/软件渲染/移动设备完全不自转，只渲染一帧静态画面。
 *  动画运行期帧率不足会自动降档。手动覆盖：
 *  localStorage.setItem('smartclip.homeSceneQuality', 'high' | 'low' | 'static') */
export function HomeScene3D() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const solarRef = useRef<SolarHandle | null>(null)
  const [ready, setReady] = useState(false)
  const [reduced, setReduced] = useState(false)
  const [webglUnavailable, setWebglUnavailable] = useState(false)
  const [canvasKey, setCanvasKey] = useState(0)
  const [tier, setTier] = useState<QualityTier | null>(null)

  useEffect(() => {
    setReduced(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    setTier(resolveQualityTier())
    setReady(true)
  }, [])

  useEffect(() => {
    if (!ready || reduced || !tier || !canvasRef.current) return

    const handle = createSolarSystem(canvasRef.current, {
      tier,
      // 自动降档只影响当前会话（就地降级，不重建场景）；
      // 不持久化结论，避免机器临时高负载被误判后一直卡在低档。
      onDegrade: (t) => console.info(`[HomeScene] 帧率不足，太阳系自动降档 → ${t}`),
    })
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
  }, [ready, reduced, tier, canvasKey])

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
