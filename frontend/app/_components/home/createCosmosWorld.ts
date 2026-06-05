import * as THREE from 'three'
import {
  createAtmosphereMaterial,
  createCometMaterial,
  createEarthMaterial,
  createMoonSurfaceMaterial,
  createNebulaMaterial,
  createStarMaterial,
} from './cosmos-shaders'

export type CosmosHandle = {
  setMouse: (x: number, y: number) => void
  dispose: () => void
}

function createRenderer(canvas: HTMLCanvasElement): THREE.WebGLRenderer | null {
  try {
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      failIfMajorPerformanceCaveat: false,
    })
    if (!renderer.getContext()) {
      renderer.dispose()
      return null
    }
    return renderer
  } catch {
    return null
  }
}

/** 程序化银河全景纹理 — 密集星点 + 辉光带 */
function milkyWayTexture() {
  const w = 2048
  const h = 1024
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#000000'
  ctx.fillRect(0, 0, w, h)

  const cx = w / 2
  const cy = h / 2
  for (let pass = 0; pass < 3; pass++) {
    const bandH = h * (0.22 - pass * 0.04)
    const grad = ctx.createLinearGradient(0, cy - bandH, 0, cy + bandH)
    const alpha = 0.08 - pass * 0.02
    grad.addColorStop(0, 'rgba(0,0,0,0)')
    grad.addColorStop(0.3, `rgba(60,80,160,${alpha * 0.5})`)
    grad.addColorStop(0.5, `rgba(140,160,220,${alpha})`)
    grad.addColorStop(0.7, `rgba(60,80,160,${alpha * 0.5})`)
    grad.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = grad
    ctx.fillRect(0, cy - bandH, w, bandH * 2)
  }

  for (let i = 0; i < 18000; i++) {
    const x = Math.random() * w
    const y = cy + (Math.random() + Math.random() + Math.random() - 1.5) * h * 0.14
    const dist = Math.abs(y - cy) / (h * 0.14)
    const fade = Math.exp(-dist * dist * 2.5)
    const r = Math.random() < 0.03 ? 0.8 + Math.random() * 1.2 : 0.15 + Math.random() * 0.5
    const bright = Math.random()
    const colors = ['255,255,255', '220,230,255', '255,245,220', '200,210,255', '255,220,240']
    const c = colors[Math.floor(Math.random() * colors.length)]
    ctx.globalAlpha = fade * (0.08 + bright * 0.42)
    ctx.fillStyle = `rgba(${c},1)`
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
    if (bright > 0.97 && r > 0.7) {
      ctx.globalAlpha = fade * 0.18
      ctx.strokeStyle = `rgba(${c},0.6)`
      ctx.lineWidth = 0.4
      ctx.beginPath()
      ctx.moveTo(x - r * 4, y)
      ctx.lineTo(x + r * 4, y)
      ctx.moveTo(x, y - r * 4)
      ctx.lineTo(x, y + r * 4)
      ctx.stroke()
    }
  }

  for (let i = 0; i < 8; i++) {
    const x = cx + (Math.random() - 0.5) * w * 0.7
    const y = cy + (Math.random() - 0.5) * h * 0.08
    const r = 30 + Math.random() * 60
    const g = ctx.createRadialGradient(x, y, 0, x, y, r)
    g.addColorStop(0, 'rgba(180,200,255,0.12)')
    g.addColorStop(0.5, 'rgba(100,130,220,0.04)')
    g.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = g
    ctx.fillRect(x - r, y - r, r * 2, r * 2)
  }

  ctx.globalAlpha = 1
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function glowTexture(inner: string, mid: string, outer: string) {
  const s = 512
  const canvas = document.createElement('canvas')
  canvas.width = s
  canvas.height = s
  const ctx = canvas.getContext('2d')!
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
  g.addColorStop(0, inner)
  g.addColorStop(0.05, mid)
  g.addColorStop(0.22, outer)
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, s, s)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

const GAL_AXIS = new THREE.Vector3(0.12, 0.88, 0.32).normalize()
const GAL_REF = new THREE.Vector3(1, 0, 0)
const GAL_TANGENT = new THREE.Vector3().crossVectors(GAL_AXIS, GAL_REF).normalize()
const GAL_BITANGENT = new THREE.Vector3().crossVectors(GAL_AXIS, GAL_TANGENT).normalize()

const STAR_PALETTE = [
  new THREE.Color('#ffffff'),
  new THREE.Color('#fffef5'),
  new THREE.Color('#fef9c3'),
  new THREE.Color('#e0f2fe'),
  new THREE.Color('#ddd6fe'),
  new THREE.Color('#fce7f3'),
  new THREE.Color('#fef08a'),
]

function fillStar(
  i: number,
  pos: THREE.Vector3,
  positions: Float32Array,
  sizes: Float32Array,
  phases: Float32Array,
  brights: Float32Array,
  colors: Float32Array,
  brightRatio: number,
  sizeMul = 1,
) {
  positions[i * 3] = pos.x
  positions[i * 3 + 1] = pos.y
  positions[i * 3 + 2] = pos.z
  const isBright = Math.random() < brightRatio
  sizes[i] = (isBright ? 1.1 + Math.random() * 1.8 : 0.22 + Math.random() * 0.65) * sizeMul
  phases[i] = Math.random() * Math.PI * 2
  brights[i] = isBright ? 0.6 + Math.random() * 0.2 : Math.random() < 0.08 ? 0.2 : 0.0
  const c = STAR_PALETTE[Math.floor(Math.random() * STAR_PALETTE.length)]
  colors[i * 3] = c.r
  colors[i * 3 + 1] = c.g
  colors[i * 3 + 2] = c.b
}

function buildStarField(
  count: number,
  radius: number,
  spread: number,
  brightRatio: number,
) {
  const geo = new THREE.BufferGeometry()
  const positions = new Float32Array(count * 3)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)
  const brights = new Float32Array(count)
  const colors = new Float32Array(count * 3)
  const pos = new THREE.Vector3()

  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    const r = radius + (Math.random() - 0.5) * spread
    pos.set(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.sin(phi) * Math.sin(theta),
      r * Math.cos(phi),
    )
    fillStar(i, pos, positions, sizes, phases, brights, colors, brightRatio)
  }
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aBright', new THREE.BufferAttribute(brights, 1))
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
  const mat = createStarMaterial()
  return { points: new THREE.Points(geo, mat), mat, geo }
}

/** 沿银道面密集分布的星河星场 */
function buildGalaxyStarField(count: number, radius: number) {
  const geo = new THREE.BufferGeometry()
  const positions = new Float32Array(count * 3)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)
  const brights = new Float32Array(count)
  const colors = new Float32Array(count * 3)
  const pos = new THREE.Vector3()

  for (let i = 0; i < count; i++) {
    const lon = Math.random() * Math.PI * 2
    const lat = (Math.random() + Math.random() + Math.random() - 1.5) * 0.18
    const r = radius + (Math.random() - 0.5) * 6
    pos
      .copy(GAL_TANGENT)
      .multiplyScalar(Math.cos(lon) * Math.cos(lat) * r)
      .addScaledVector(GAL_BITANGENT, Math.sin(lon) * Math.cos(lat) * r)
      .addScaledVector(GAL_AXIS, Math.sin(lat) * r)
    const inCore = Math.exp(-lat * lat * 40)
    fillStar(i, pos, positions, sizes, phases, brights, colors, 0.08 + inCore * 0.18, 0.85 + inCore * 0.25)
  }
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aBright', new THREE.BufferAttribute(brights, 1))
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
  const mat = createStarMaterial()
  return { points: new THREE.Points(geo, mat), mat, geo }
}

/** 星团 — 局部高密度璀璨星群 */
function buildStarCluster(count: number, center: THREE.Vector3, spread: number) {
  const geo = new THREE.BufferGeometry()
  const positions = new Float32Array(count * 3)
  const sizes = new Float32Array(count)
  const phases = new Float32Array(count)
  const brights = new Float32Array(count)
  const colors = new Float32Array(count * 3)
  const pos = new THREE.Vector3()

  for (let i = 0; i < count; i++) {
    pos
      .set(
        (Math.random() - 0.5) * spread,
        (Math.random() - 0.5) * spread * 0.6,
        (Math.random() - 0.5) * spread,
      )
      .add(center)
    fillStar(i, pos, positions, sizes, phases, brights, colors, 0.28, 0.95)
  }
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aBright', new THREE.BufferAttribute(brights, 1))
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
  const mat = createStarMaterial()
  return { points: new THREE.Points(geo, mat), mat, geo }
}

type Comet = {
  active: boolean
  life: number
  maxLife: number
  pos: THREE.Vector3
  vel: THREE.Vector3
  dir: THREE.Vector3
  line: THREE.Line
  mat: THREE.ShaderMaterial
}

function makeSprite(
  tex: THREE.Texture,
  pos: THREE.Vector3,
  scale: number,
  opacity: number,
) {
  const spr = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: tex,
      transparent: true,
      opacity,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  )
  spr.position.copy(pos)
  spr.scale.setScalar(scale)
  return spr
}

export function createCosmosWorld(canvas: HTMLCanvasElement): CosmosHandle | null {
  const renderer = createRenderer(canvas)
  if (!renderer) return null

  const mouse = { x: 0, y: 0 }
  const clock = new THREE.Clock()
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.05

  const scene = new THREE.Scene()
  scene.background = new THREE.Color('#00010a')
  scene.fog = new THREE.FogExp2('#00010a', 0.008)

  const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 200)
  camera.position.set(0, 0.22, 0.55)

  const sunDir = new THREE.Vector3(0.55, 0.18, 0.8).normalize()
  scene.add(new THREE.AmbientLight(0x1a1040, 0.12))
  const sun = new THREE.DirectionalLight(0xfff0d4, 1.6)
  sun.position.copy(sunDir.clone().multiplyScalar(40))
  scene.add(sun)

  const nebulaMat = createNebulaMaterial()
  const nebula = new THREE.Mesh(new THREE.SphereGeometry(120, 72, 72), nebulaMat)
  nebula.scale.set(-1, 1, 1)
  scene.add(nebula)

  const farStars = buildStarField(6500, 62, 20, 0.07)
  const galaxyStars = buildGalaxyStarField(5000, 58)
  const nearStars = buildStarField(900, 22, 8, 0.26)
  scene.add(farStars.points, galaxyStars.points, nearStars.points)

  const clusterGeos: THREE.BufferGeometry[] = []
  const clusterCenters = [
    [-18, 12, -38],
    [14, 16, -42],
    [-8, 22, -35],
    [22, 8, -45],
    [-25, 6, -40],
    [6, 18, -36],
  ] as const
  for (const [x, y, z] of clusterCenters) {
    const cluster = buildStarCluster(120, new THREE.Vector3(x, y, z), 3.5)
    clusterGeos.push(cluster.geo)
    scene.add(cluster.points)
  }

  const milkyTex = milkyWayTexture()
  const milkyGroup = new THREE.Group()
  const milkyMat = new THREE.MeshBasicMaterial({
    map: milkyTex,
    transparent: true,
    opacity: 0.36,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  })
  for (const cfg of [
    { pos: [-6, 15, -44] as const, rot: [0.15, 0.4, 0.1] as const, w: 90, h: 28 },
    { pos: [8, 17, -46] as const, rot: [0.1, -0.3, -0.05] as const, w: 80, h: 26 },
    { pos: [0, 19, -42] as const, rot: [0.2, 0.05, 0.0] as const, w: 70, h: 22 },
  ]) {
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(cfg.w, cfg.h), milkyMat)
    plane.position.set(cfg.pos[0], cfg.pos[1], cfg.pos[2])
    plane.rotation.set(cfg.rot[0], cfg.rot[1], cfg.rot[2])
    milkyGroup.add(plane)
  }
  scene.add(milkyGroup)

  const moonMat = createMoonSurfaceMaterial()
  const moonGround = new THREE.Mesh(
    new THREE.PlaneGeometry(140, 140, 220, 220),
    moonMat,
  )
  moonGround.rotation.x = -Math.PI / 2
  moonGround.position.set(0, 0, -10)
  scene.add(moonGround)

  const earthGroup = new THREE.Group()
  const earthRadius = 3.1
  const earthMat = createEarthMaterial()
  earthMat.uniforms.uSunDir.value.copy(sunDir)
  earthGroup.add(
    new THREE.Mesh(new THREE.SphereGeometry(earthRadius, 128, 128), earthMat),
  )

  const atmosMats: THREE.ShaderMaterial[] = []
  for (const [color, intensity, scale, pulse] of [
    ['#38bdf8', 0.7, 1.07, true],
    ['#60a5fa', 0.48, 1.14, false],
    ['#fbbf24', 0.22, 1.2, true],
  ] as const) {
    const am = createAtmosphereMaterial(color, intensity, pulse)
    am.uniforms.uSunDir.value.copy(sunDir)
    atmosMats.push(am)
    const shell = new THREE.Mesh(new THREE.SphereGeometry(earthRadius, 72, 72), am)
    shell.scale.setScalar(scale)
    earthGroup.add(shell)
  }

  earthGroup.position.set(0, 2.6, -30)
  scene.add(earthGroup)

  const earthLight = new THREE.PointLight(0x60a5fa, 1.4, 40)
  earthLight.position.set(0, 2.6, -28)
  scene.add(earthLight)

  const textures: THREE.Texture[] = []
  const sunCoreTex = glowTexture(
    'rgba(255,252,240,1)',
    'rgba(255,220,150,0.85)',
    'rgba(255,160,60,0.2)',
  )
  const sunHaloTex = glowTexture(
    'rgba(255,200,100,0.6)',
    'rgba(255,140,50,0.25)',
    'rgba(200,80,20,0.05)',
  )
  const earthBloomTex = glowTexture(
    'rgba(100,180,255,0.5)',
    'rgba(60,140,255,0.2)',
    'rgba(30,80,200,0.03)',
  )
  const flareTex = glowTexture(
    'rgba(255,255,255,0.9)',
    'rgba(200,220,255,0.3)',
    'rgba(100,150,255,0.05)',
  )
  textures.push(sunCoreTex, sunHaloTex, earthBloomTex, flareTex, milkyTex)

  const sunPos = new THREE.Vector3(5.5, 3.8, -24)
  const sunSprites = [
    makeSprite(sunCoreTex, sunPos, 5.5, 0.55),
    makeSprite(sunHaloTex, sunPos, 18, 0.28),
    makeSprite(sunHaloTex, sunPos, 35, 0.1),
  ]
  sunSprites.forEach((s) => scene.add(s))

  const earthBloom = makeSprite(
    earthBloomTex,
    new THREE.Vector3(0, 2.6, -30),
    18,
    0.22,
  )
  scene.add(earthBloom)

  const flareGhosts: THREE.Sprite[] = []
  for (let i = 0; i < 6; i++) {
    const t = (i + 1) / 7
    const ghost = makeSprite(
      flareTex,
      new THREE.Vector3().lerpVectors(
        new THREE.Vector3(0, 2.6, -30),
        sunPos,
        t,
      ),
      0.3 + (i % 2) * 0.25,
      0.04 + (1 - t) * 0.07,
    )
    flareGhosts.push(ghost)
    scene.add(ghost)
  }

  const dustCount = 200
  const dustGeo = new THREE.BufferGeometry()
  const dustPos = new Float32Array(dustCount * 3)
  for (let i = 0; i < dustCount; i++) {
    dustPos[i * 3] = (Math.random() - 0.5) * 30
    dustPos[i * 3 + 1] = Math.random() * 14
    dustPos[i * 3 + 2] = -Math.random() * 25 - 2
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3))
  const dust = new THREE.Points(
    dustGeo,
    new THREE.PointsMaterial({
      size: 0.06,
      color: '#93c5fd',
      transparent: true,
      opacity: 0.28,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  )
  scene.add(dust)

  const comets: Comet[] = []
  const cometGroup = new THREE.Group()
  for (let i = 0; i < 6; i++) {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3))
    geo.setAttribute('aAlong', new THREE.BufferAttribute(new Float32Array([1, 0]), 1))
    const cmat = createCometMaterial()
    const line = new THREE.Line(geo, cmat)
    line.visible = false
    cometGroup.add(line)
    comets.push({
      active: false,
      life: 0,
      maxLife: 1,
      pos: new THREE.Vector3(),
      vel: new THREE.Vector3(),
      dir: new THREE.Vector3(),
      line,
      mat: cmat,
    })
  }
  scene.add(cometGroup)

  const lookTarget = new THREE.Vector3(0, 2.0, -30)
  const camBase = new THREE.Vector3(0, 0.22, 0.55)
  let raf = 0

  const resize = () => {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    if (w === 0 || h === 0) return
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
  }

  const ro = new ResizeObserver(resize)
  ro.observe(canvas)
  resize()

  const animate = () => {
    raf = requestAnimationFrame(animate)
    const t = clock.getElapsedTime()
    const delta = clock.getDelta()

    nebulaMat.uniforms.uTime.value = t
    const um = nebulaMat.uniforms.uMouse.value as THREE.Vector2
    um.lerp(new THREE.Vector2(mouse.x, mouse.y), 0.03)

    for (const { mat, points } of [farStars, galaxyStars, nearStars]) {
      mat.uniforms.uTime.value = t
      mat.uniforms.uPixelRatio.value = renderer.getPixelRatio()
      points.rotation.y = t * 0.002
    }
    milkyGroup.rotation.y = t * 0.0015

    moonMat.uniforms.uTime.value = t
    moonMat.uniforms.uEarthGlow.value = 0.55 + Math.sin(t * 0.5) * 0.12
    earthMat.uniforms.uTime.value = t
    atmosMats.forEach((m) => {
      m.uniforms.uTime.value = t
    })
    earthGroup.rotation.y = t * 0.05 + mouse.x * 0.12

    const breathe = Math.sin(t * 0.35) * 0.04
    const camX = camBase.x + mouse.x * 0.28 + Math.sin(t * 0.2) * 0.03
    const camY = camBase.y + mouse.y * 0.1 + breathe
    camera.position.set(camX, camY, camBase.z + breathe * 0.5)
    lookTarget.x = THREE.MathUtils.lerp(lookTarget.x, mouse.x * 0.8, 0.025)
    lookTarget.y = THREE.MathUtils.lerp(lookTarget.y, 2.0 + mouse.y * 0.2, 0.025)
    camera.lookAt(lookTarget)

    sunSprites[0].material.opacity = 0.5 + Math.sin(t * 0.9) * 0.06
    sunSprites[1].scale.setScalar(18 + Math.sin(t * 0.5) * 1.2)
    sunSprites[2].scale.setScalar(35 + Math.sin(t * 0.3) * 2)
    earthBloom.material.opacity = 0.18 + Math.sin(t * 0.6) * 0.05
    earthBloom.scale.setScalar(18 + Math.sin(t * 0.4) * 1.2)
    earthLight.intensity = 1.2 + Math.sin(t * 0.7) * 0.25

    dust.rotation.y = t * 0.008
    const dustPosAttr = dustGeo.getAttribute('position') as THREE.BufferAttribute
    for (let i = 0; i < dustCount; i++) {
      dustPosAttr.setY(i, (dustPosAttr.getY(i) + delta * 0.15) % 14)
    }
    dustPosAttr.needsUpdate = true

    for (const s of comets) {
      if (!s.active && Math.random() < delta * 0.18) {
        s.active = true
        s.life = 0
        s.maxLife = 0.5 + Math.random() * 0.5
        const theta = Math.random() * Math.PI * 2
        const r = 12 + Math.random() * 8
        s.pos.set(Math.cos(theta) * r, 6 + Math.random() * 5, Math.sin(theta) * r - 10)
        s.vel
          .set(-Math.cos(theta) * 0.3, -0.5, -Math.sin(theta) * 0.3 - 1)
          .normalize()
          .multiplyScalar(18 + Math.random() * 10)
        s.dir.copy(s.vel).normalize()
      }
      if (!s.active) {
        s.line.visible = false
        continue
      }
      s.life += delta
      s.mat.uniforms.uTime.value = t
      if (s.life > s.maxLife) {
        s.active = false
        s.line.visible = false
        continue
      }
      s.pos.addScaledVector(s.vel, delta)
      s.line.visible = true
      const tailLen = 2.5 * (1 - s.life / s.maxLife)
      const posAttr = s.line.geometry.getAttribute('position') as THREE.BufferAttribute
      posAttr.setXYZ(0, s.pos.x, s.pos.y, s.pos.z)
      posAttr.setXYZ(
        1,
        s.pos.x - s.dir.x * tailLen,
        s.pos.y - s.dir.y * tailLen,
        s.pos.z - s.dir.z * tailLen,
      )
      posAttr.needsUpdate = true
    }

    renderer.render(scene, camera)
  }

  animate()

  return {
    setMouse(x: number, y: number) {
      mouse.x = x
      mouse.y = y
    },
    dispose() {
      cancelAnimationFrame(raf)
      ro.disconnect()
      renderer.forceContextLoss()
      renderer.dispose()
      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh || obj instanceof THREE.Points || obj instanceof THREE.Line) {
          obj.geometry.dispose()
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
          mats.forEach((m) => m.dispose())
        }
        if (obj instanceof THREE.Sprite) {
          obj.material.dispose()
        }
      })
      textures.forEach((t) => t.dispose())
      milkyMat.dispose()
      milkyGroup.traverse((obj) => {
        if (obj instanceof THREE.Mesh) obj.geometry.dispose()
      })
      farStars.geo.dispose()
      galaxyStars.geo.dispose()
      nearStars.geo.dispose()
      clusterGeos.forEach((g) => g.dispose())
    },
  }
}
