'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Sparkles } from '@react-three/drei'
import * as THREE from 'three'
import './cosmos-materials'

type MouseRef = React.MutableRefObject<{ x: number; y: number }>

function useGalaxyTexture() {
  return useMemo(() => {
    const size = 256
    const canvas = document.createElement('canvas')
    canvas.width = size
    canvas.height = size
    const ctx = canvas.getContext('2d')!
    const cx = size / 2
    const cy = size / 2
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, cx)
    grad.addColorStop(0, 'rgba(220, 210, 255, 0.95)')
    grad.addColorStop(0.15, 'rgba(140, 100, 220, 0.55)')
    grad.addColorStop(0.4, 'rgba(60, 40, 120, 0.2)')
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, size, size)
    for (let i = 0; i < 6; i++) {
      ctx.save()
      ctx.translate(cx, cy)
      ctx.rotate((i / 6) * Math.PI * 2)
      ctx.scale(1, 0.22)
      ctx.globalAlpha = 0.35
      ctx.fillStyle = 'rgba(180, 160, 255, 0.5)'
      ctx.beginPath()
      ctx.arc(0, 0, cx * 0.85, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
    }
    const tex = new THREE.CanvasTexture(canvas)
    tex.colorSpace = THREE.SRGBColorSpace
    return tex
  }, [])
}

function NebulaSky({ mouse }: { mouse: MouseRef }) {
  const mat = useRef<THREE.ShaderMaterial & { uTime: number; uMouse: THREE.Vector2 }>(null)

  useFrame((state) => {
    if (!mat.current) return
    mat.current.uTime = state.clock.elapsedTime
    mat.current.uMouse.lerp(
      new THREE.Vector2(mouse.current.x, mouse.current.y),
      0.04,
    )
  })

  return (
    <mesh scale={[-1, 1, 1]}>
      <sphereGeometry args={[80, 64, 64]} />
      <nebulaSkyMaterial ref={mat} side={THREE.BackSide} depthWrite={false} />
    </mesh>
  )
}

function StarField({ count, radius, spread }: { count: number; radius: number; spread: number }) {
  const points = useRef<THREE.Points>(null)
  const mat = useRef<THREE.ShaderMaterial & { uTime: number; uPixelRatio: number }>(null)

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry()
    const positions = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const phases = new Float32Array(count)
    const colors = new Float32Array(count * 3)
    const palette = [
      new THREE.Color('#e0f2fe'),
      new THREE.Color('#c4b5fd'),
      new THREE.Color('#fef3c7'),
      new THREE.Color('#ffffff'),
    ]
    for (let i = 0; i < count; i++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      const r = radius + (Math.random() - 0.5) * spread
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta)
      positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      positions[i * 3 + 2] = r * Math.cos(phi)
      sizes[i] = 0.4 + Math.random() * 2.2
      phases[i] = Math.random() * Math.PI * 2
      const c = palette[Math.floor(Math.random() * palette.length)]
      colors[i * 3] = c.r
      colors[i * 3 + 1] = c.g
      colors[i * 3 + 2] = c.b
    }
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
    geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
    geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    return geo
  }, [count, radius, spread])

  useFrame((state) => {
    if (mat.current) {
      mat.current.uTime = state.clock.elapsedTime
      mat.current.uPixelRatio = state.viewport.dpr
    }
    if (points.current) {
      points.current.rotation.y = state.clock.elapsedTime * 0.008
    }
  })

  return (
    <points ref={points} geometry={geometry}>
      <starPointMaterial
        ref={mat}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}

function DistantGalaxies() {
  const tex = useGalaxyTexture()
  const group = useRef<THREE.Group>(null)
  const configs = useMemo(
    () => [
      { pos: [-14, 4, -22] as const, scale: 5, rot: 0.4 },
      { pos: [16, -3, -26] as const, scale: 4.2, rot: -0.8 },
      { pos: [-8, -6, -18] as const, scale: 3.2, rot: 1.2 },
    ],
    [],
  )

  useFrame((state) => {
    if (!group.current) return
    group.current.rotation.y = state.clock.elapsedTime * 0.015
  })

  return (
    <group ref={group}>
      {configs.map((c, i) => (
        <sprite key={i} position={c.pos} scale={[c.scale, c.scale, 1]} rotation={[0, 0, c.rot]}>
          <spriteMaterial map={tex} transparent opacity={0.55} depthWrite={false} blending={THREE.AdditiveBlending} />
        </sprite>
      ))}
    </group>
  )
}

function CosmicPlanet({ mouse }: { mouse: MouseRef }) {
  const group = useRef<THREE.Group>(null)
  const planetMat = useRef<THREE.ShaderMaterial & { uTime: number }>(null)
  const ringMats = useRef<Array<THREE.ShaderMaterial & { uTime: number }>>([])

  useFrame((state) => {
    const t = state.clock.elapsedTime
    const mx = mouse.current.x
    const my = mouse.current.y

    if (planetMat.current) planetMat.current.uTime = t
    ringMats.current.forEach((m) => {
      if (m) m.uTime = t
    })

    if (group.current) {
      group.current.rotation.y = THREE.MathUtils.lerp(
        group.current.rotation.y,
        mx * 0.35 + t * 0.06,
        0.03,
      )
      group.current.rotation.x = THREE.MathUtils.lerp(
        group.current.rotation.x,
        my * 0.2 + Math.sin(t * 0.35) * 0.05,
        0.03,
      )
    }
  })

  return (
    <group ref={group}>
      <mesh>
        <sphereGeometry args={[1.35, 128, 128]} />
        <planetSurfaceMaterial ref={planetMat} />
      </mesh>

      <mesh scale={1.42}>
        <sphereGeometry args={[1.35, 64, 64]} />
        <atmosphereMaterial
          transparent
          depthWrite={false}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          uColor={new THREE.Color('#7dd3fc')}
          uIntensity={0.95}
        />
      </mesh>

      <mesh rotation={[1.15, 0.2, 0.35]}>
        <ringGeometry args={[2.0, 3.4, 128]} />
        <ringGlowMaterial
          ref={(el: THREE.ShaderMaterial & { uTime: number }) => {
            if (el) ringMats.current[0] = el
          }}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
          uColor={new THREE.Color('#c7d2fe')}
        />
      </mesh>

      <mesh rotation={[1.22, 0.5, 0.6]} scale={0.92}>
        <ringGeometry args={[3.5, 4.6, 96]} />
        <ringGlowMaterial
          ref={(el: THREE.ShaderMaterial & { uTime: number }) => {
            if (el) ringMats.current[1] = el
          }}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
          uColor={new THREE.Color('#818cf8')}
        />
      </mesh>

      <pointLight position={[2, 1, 3]} intensity={2.5} color="#bae6fd" distance={14} />
      <pointLight position={[-3, -1, 2]} intensity={1.2} color="#a78bfa" distance={12} />
    </group>
  )
}

function AsteroidBelt() {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const count = 180

  useLayoutEffect(() => {
    if (!mesh.current) return
    const dummy = new THREE.Object3D()
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2 + Math.random() * 0.4
      const radius = 5.8 + Math.random() * 1.8
      const y = (Math.random() - 0.5) * 0.5
      dummy.position.set(Math.cos(angle) * radius, y, Math.sin(angle) * radius)
      dummy.rotation.set(
        Math.random() * Math.PI,
        Math.random() * Math.PI,
        Math.random() * Math.PI,
      )
      const s = 0.02 + Math.random() * 0.05
      dummy.scale.setScalar(s)
      dummy.updateMatrix()
      mesh.current.setMatrixAt(i, dummy.matrix)
    }
    mesh.current.instanceMatrix.needsUpdate = true
  }, [])

  useFrame((state) => {
    if (!mesh.current) return
    mesh.current.rotation.y = state.clock.elapsedTime * 0.04
  })

  return (
    <instancedMesh ref={mesh} count={count} frustumCulled={false}>
      <icosahedronGeometry args={[1, 0]} />
      <meshStandardMaterial
        color="#94a3b8"
        emissive="#475569"
        emissiveIntensity={0.35}
        roughness={0.75}
        metalness={0.4}
      />
    </instancedMesh>
  )
}

function ShootingStars() {
  const group = useRef<THREE.Group>(null)
  const pool = useMemo(
    () =>
      Array.from({ length: 8 }, () => ({
        active: false,
        life: 0,
        maxLife: 1.2 + Math.random() * 0.8,
        pos: new THREE.Vector3(),
        vel: new THREE.Vector3(),
        mesh: null as THREE.Mesh | null,
      })),
    [],
  )

  useFrame((_state, delta) => {
    if (!group.current) return
    const spawnChance = delta * 0.35
    for (const s of pool) {
      if (!s.active && Math.random() < spawnChance) {
        s.active = true
        s.life = 0
        s.maxLife = 1 + Math.random() * 1.2
        const theta = Math.random() * Math.PI * 2
        const r = 8 + Math.random() * 6
        s.pos.set(
          Math.cos(theta) * r,
          2 + Math.random() * 4,
          Math.sin(theta) * r,
        )
        s.vel.set(
          -Math.cos(theta) * (4 + Math.random() * 3),
          -1 - Math.random() * 2,
          -Math.sin(theta) * (4 + Math.random() * 3),
        )
      }
      if (!s.active) continue
      s.life += delta
      if (s.life > s.maxLife) {
        s.active = false
        continue
      }
      s.pos.addScaledVector(s.vel, delta)
    }
    group.current.children.forEach((child, i) => {
      const s = pool[i]
      child.visible = s.active
      if (s.active) {
        child.position.copy(s.pos)
        const fade = 1 - s.life / s.maxLife
        ;(child as THREE.Mesh).scale.setScalar(0.15 * fade)
      }
    })
  })

  return (
    <group ref={group}>
      {pool.map((_, i) => (
        <mesh key={i} visible={false}>
          <sphereGeometry args={[1, 8, 8]} />
          <meshBasicMaterial color="#e0f2fe" transparent opacity={0.9} blending={THREE.AdditiveBlending} />
        </mesh>
      ))}
    </group>
  )
}

function CameraRig({ mouse }: { mouse: MouseRef }) {
  const { camera } = useThree()
  const target = useRef(new THREE.Vector3(0, 0.15, 9))

  useFrame(() => {
    target.current.x = THREE.MathUtils.lerp(target.current.x, mouse.current.x * 0.55, 0.025)
    target.current.y = THREE.MathUtils.lerp(target.current.y, mouse.current.y * 0.28 + 0.2, 0.025)
    camera.position.lerp(target.current, 0.04)
    camera.lookAt(0, 0, 0)
  })

  return null
}

function SceneContent({ mouse }: { mouse: MouseRef }) {
  return (
    <>
      <color attach="background" args={['#010409']} />
      <fog attach="fog" args={['#010409', 18, 42]} />

      <ambientLight intensity={0.12} />
      <directionalLight position={[8, 6, 10]} intensity={0.35} color="#e0f2fe" />

      <NebulaSky mouse={mouse} />
      <StarField count={4200} radius={28} spread={14} />
      <StarField count={1200} radius={12} spread={5} />

      <Sparkles
        count={320}
        size={1.8}
        scale={[28, 14, 28]}
        position={[0, 0, 0]}
        speed={0.22}
        opacity={0.35}
        color="#a5f3fc"
      />
      <Sparkles
        count={180}
        size={2.4}
        scale={[20, 10, 20]}
        position={[0, 1, 0]}
        speed={0.15}
        opacity={0.2}
        color="#c4b5fd"
      />

      <DistantGalaxies />
      <AsteroidBelt />
      <ShootingStars />
      <CosmicPlanet mouse={mouse} />
      <CameraRig mouse={mouse} />
    </>
  )
}

export function HomeScene3D() {
  const mouse = useRef({ x: 0, y: 0 })
  const wrapRef = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)
  const [reduced, setReduced] = useState(false)

  useEffect(() => {
    setReduced(window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    setReady(true)
  }, [])

  useEffect(() => {
    if (reduced) return
    const onMove = (e: PointerEvent) => {
      const el = wrapRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      mouse.current.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.current.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    return () => window.removeEventListener('pointermove', onMove)
  }, [reduced])

  if (!ready) {
    return <div className="absolute inset-0 bg-[#010409]" aria-hidden />
  }

  if (reduced) {
    return (
      <div
        ref={wrapRef}
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,#1e1b4b_0%,transparent_50%),radial-gradient(ellipse_at_70%_60%,#0c4a6e_0%,transparent_45%),#010409]"
        aria-hidden
      />
    )
  }

  return (
    <div ref={wrapRef} className="absolute inset-0" aria-hidden>
      <Canvas
        camera={{ position: [0, 0.2, 9], fov: 38 }}
        dpr={[1, 1.75]}
        gl={{
          antialias: true,
          alpha: false,
          powerPreference: 'high-performance',
          toneMapping: THREE.ACESFilmicToneMapping,
          toneMappingExposure: 1.05,
        }}
        className="!absolute inset-0 h-full w-full"
      >
        <SceneContent mouse={mouse} />
      </Canvas>
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_45%,transparent_0%,#010409_75%)] opacity-90" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-[#010409]/30 via-transparent to-[#010409]/95" />
    </div>
  )
}
