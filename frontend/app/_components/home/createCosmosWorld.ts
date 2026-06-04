import * as THREE from 'three'
import {
  createAtmosphereMaterial,
  createCometMaterial,
  createNebulaMaterial,
  createPlanetMaterial,
  createRingMaterial,
  createStarMaterial,
} from './cosmos-shaders'

export type CosmosHandle = {
  setMouse: (x: number, y: number) => void
  dispose: () => void
}

const WEBGL_ATTRS: WebGLContextAttributes = {
  alpha: false,
  antialias: true,
  failIfMajorPerformanceCaveat: false,
}

/** 沙箱/无 GPU 环境下 WebGL 可能失败，返回 null 由 UI 降级为 CSS 背景 */
function createRenderer(canvas: HTMLCanvasElement): THREE.WebGLRenderer | null {
  const tryWithContext = (gl: WebGL2RenderingContext | WebGLRenderingContext) => {
    try {
      const renderer = new THREE.WebGLRenderer({
        canvas,
        context: gl,
        alpha: false,
        antialias: WEBGL_ATTRS.antialias,
      })
      return renderer.getContext() ? renderer : null
    } catch {
      return null
    }
  }

  for (const type of ['webgl2', 'webgl'] as const) {
    try {
      const gl = canvas.getContext(type, WEBGL_ATTRS)
      if (!gl) continue
      const renderer = tryWithContext(gl)
      if (renderer) return renderer
    } catch {
      return null
    }
  }

  try {
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      failIfMajorPerformanceCaveat: false,
    })
    return renderer.getContext() ? renderer : null
  } catch {
    return null
  }
}

function glowTexture() {
  const s = 512
  const canvas = document.createElement('canvas')
  canvas.width = s
  canvas.height = s
  const ctx = canvas.getContext('2d')!
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2)
  g.addColorStop(0, 'rgba(255,255,255,1)')
  g.addColorStop(0.08, 'rgba(200,240,255,0.65)')
  g.addColorStop(0.25, 'rgba(120,180,255,0.18)')
  g.addColorStop(1, 'rgba(0,0,0,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, s, s)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

function galaxyTexture() {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')!
  const cx = size / 2
  const grad = ctx.createRadialGradient(cx, cx, 0, cx, cx, cx)
  grad.addColorStop(0, 'rgba(240, 248, 255, 0.9)')
  grad.addColorStop(0.12, 'rgba(180, 200, 255, 0.45)')
  grad.addColorStop(0.35, 'rgba(100, 140, 220, 0.12)')
  grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, size, size)
  for (let i = 0; i < 5; i++) {
    ctx.save()
    ctx.translate(cx, cx)
    ctx.rotate((i / 5) * Math.PI * 2 + 0.2)
    ctx.scale(1, 0.18)
    ctx.globalAlpha = 0.22
    ctx.fillStyle = 'rgba(200, 220, 255, 0.6)'
    ctx.beginPath()
    ctx.ellipse(0, 0, cx * 0.8, cx * 0.25, 0, 0, Math.PI * 2)
    ctx.fill()
    ctx.restore()
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
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
  const colors = new Float32Array(count * 3)
  const white = new THREE.Color('#f8fafc')
  const cyan = new THREE.Color('#bae6fd')
  const violet = new THREE.Color('#ddd6fe')

  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2
    const phi = Math.acos(2 * Math.random() - 1)
    const r = radius + (Math.random() - 0.5) * spread
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta)
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
    positions[i * 3 + 2] = r * Math.cos(phi)
    const isBright = Math.random() < brightRatio
    sizes[i] = isBright ? 1.2 + Math.random() * 1.8 : 0.25 + Math.random() * 0.9
    phases[i] = Math.random() * Math.PI * 2
    const c = Math.random() < 0.7 ? white : Math.random() < 0.5 ? cyan : violet
    colors[i * 3] = c.r
    colors[i * 3 + 1] = c.g
    colors[i * 3 + 2] = c.b
  }
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
  geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
  const mat = createStarMaterial()
  const points = new THREE.Points(geo, mat)
  return { points, mat }
}

type Comet = {
  active: boolean
  life: number
  maxLife: number
  pos: THREE.Vector3
  vel: THREE.Vector3
  dir: THREE.Vector3
  line: THREE.Line
}

export function createCosmosWorld(canvas: HTMLCanvasElement): CosmosHandle | null {
  const renderer = createRenderer(canvas)
  if (!renderer) return null

  const mouse = { x: 0, y: 0 }
  const clock = new THREE.Clock()
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.18

  const scene = new THREE.Scene()
  scene.background = new THREE.Color('#00040c')
  scene.fog = new THREE.Fog('#00040c', 22, 50)

  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120)
  camera.position.set(0, 0.12, 9.2)

  scene.add(new THREE.AmbientLight(0xe0f2fe, 0.18))
  const sun = new THREE.DirectionalLight(0xf0f9ff, 0.45)
  sun.position.set(10, 8, 12)
  scene.add(sun)

  const nebulaMat = createNebulaMaterial()
  const nebula = new THREE.Mesh(new THREE.SphereGeometry(90, 72, 72), nebulaMat)
  nebula.scale.set(-1, 1, 1)
  scene.add(nebula)

  const farStars = buildStarField(2600, 32, 12, 0.08)
  const nearStars = buildStarField(520, 10, 4, 0.35)
  scene.add(farStars.points, nearStars.points)

  const dustGeo = new THREE.BufferGeometry()
  const dustCount = 140
  const dustPos = new Float32Array(dustCount * 3)
  for (let i = 0; i < dustCount; i++) {
    dustPos[i * 3] = (Math.random() - 0.5) * 24
    dustPos[i * 3 + 1] = (Math.random() - 0.5) * 12
    dustPos[i * 3 + 2] = (Math.random() - 0.5) * 24
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3))
  const dust = new THREE.Points(
    dustGeo,
    new THREE.PointsMaterial({
      size: 0.04,
      color: '#bae6fd',
      transparent: true,
      opacity: 0.35,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  )
  scene.add(dust)

  const corona = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: glowTexture(),
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  )
  corona.position.set(0, 0.2, -2.5)
  corona.scale.set(14, 14, 1)
  scene.add(corona)

  const galTex = galaxyTexture()
  const galaxies = new THREE.Group()
  for (const cfg of [
    { pos: [-16, 5, -24] as const, scale: 4.5 },
    { pos: [18, -2, -28] as const, scale: 3.8 },
  ]) {
    const spr = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: galTex,
        transparent: true,
        opacity: 0.32,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    )
    spr.position.set(cfg.pos[0], cfg.pos[1], cfg.pos[2])
    spr.scale.set(cfg.scale, cfg.scale, 1)
    galaxies.add(spr)
  }
  scene.add(galaxies)

  const planet = new THREE.Group()
  const planetMat = createPlanetMaterial()
  planet.add(new THREE.Mesh(new THREE.SphereGeometry(1.28, 128, 128), planetMat))

  const atmos1 = new THREE.Mesh(
    new THREE.SphereGeometry(1.28, 72, 72),
    createAtmosphereMaterial('#93c5fd', 0.75),
  )
  atmos1.scale.setScalar(1.38)
  planet.add(atmos1)

  const atmos2 = new THREE.Mesh(
    new THREE.SphereGeometry(1.28, 48, 48),
    createAtmosphereMaterial('#c4b5fd', 0.35),
  )
  atmos2.scale.setScalar(1.52)
  planet.add(atmos2)

  const ringMats: THREE.ShaderMaterial[] = []
  for (const [rot, args, color] of [
    [[1.12, 0.15, 0.3] as const, [1.95, 3.15, 160] as const, '#e0e7ff'],
    [[1.18, 0.45, 0.55] as const, [3.35, 4.25, 128] as const, '#a5b4fc'],
  ] as const) {
    const rm = createRingMaterial(color)
    ringMats.push(rm)
    const ring = new THREE.Mesh(new THREE.RingGeometry(args[0], args[1], args[2]), rm)
    ring.rotation.set(rot[0], rot[1], rot[2])
    if (args[0] > 3) ring.scale.setScalar(0.94)
    planet.add(ring)
  }

  const pLight1 = new THREE.PointLight(0xf0f9ff, 3, 16)
  pLight1.position.set(3, 1.5, 4)
  const pLight2 = new THREE.PointLight(0xc4b5fd, 0.8, 14)
  pLight2.position.set(-4, -0.5, 2)
  planet.add(pLight1, pLight2)
  scene.add(planet)

  const asteroidCount = 64
  const asteroidGeo = new THREE.IcosahedronGeometry(1, 0)
  const asteroidMat = new THREE.MeshBasicMaterial({
    color: '#64748b',
    transparent: true,
    opacity: 0.35,
  })
  const asteroids = new THREE.InstancedMesh(asteroidGeo, asteroidMat, asteroidCount)
  const dummy = new THREE.Object3D()
  for (let i = 0; i < asteroidCount; i++) {
    const angle = (i / asteroidCount) * Math.PI * 2 + Math.random() * 0.2
    const radius = 6.2 + Math.random() * 1.2
    dummy.position.set(
      Math.cos(angle) * radius,
      (Math.random() - 0.5) * 0.25,
      Math.sin(angle) * radius,
    )
    dummy.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0)
    dummy.scale.setScalar(0.015 + Math.random() * 0.025)
    dummy.updateMatrix()
    asteroids.setMatrixAt(i, dummy.matrix)
  }
  asteroids.instanceMatrix.needsUpdate = true
  scene.add(asteroids)

  const cometMat = createCometMaterial()
  const comets: Comet[] = []
  const cometGroup = new THREE.Group()
  for (let i = 0; i < 5; i++) {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3))
    geo.setAttribute('aAlong', new THREE.BufferAttribute(new Float32Array([1, 0]), 1))
    const line = new THREE.Line(geo, cometMat.clone())
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
    })
  }
  scene.add(cometGroup)

  const camTarget = new THREE.Vector3(0, 0.12, 9.2)
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

    for (const { mat, points } of [farStars, nearStars]) {
      mat.uniforms.uTime.value = t
      mat.uniforms.uPixelRatio.value = renderer.getPixelRatio()
      points.rotation.y = t * 0.004
    }

    corona.scale.setScalar(14 + Math.sin(t * 0.8) * 0.6)
    galaxies.rotation.y = t * 0.01
    asteroids.rotation.y = t * 0.025
    dust.rotation.y = t * 0.006

    planetMat.uniforms.uTime.value = t
    ringMats.forEach((m) => {
      m.uniforms.uTime.value = t
    })
    planet.rotation.y = THREE.MathUtils.lerp(planet.rotation.y, mouse.x * 0.28 + t * 0.05, 0.025)
    planet.rotation.x = THREE.MathUtils.lerp(planet.rotation.x, mouse.y * 0.14, 0.025)

    camTarget.x = THREE.MathUtils.lerp(camTarget.x, mouse.x * 0.35, 0.02)
    camTarget.y = THREE.MathUtils.lerp(camTarget.y, mouse.y * 0.18 + 0.15, 0.02)
    camera.position.lerp(camTarget, 0.035)
    camera.lookAt(0, 0, 0)

    for (const s of comets) {
      if (!s.active && Math.random() < delta * 0.12) {
        s.active = true
        s.life = 0
        s.maxLife = 0.7 + Math.random() * 0.6
        const theta = Math.random() * Math.PI * 2
        const r = 10 + Math.random() * 5
        s.pos.set(Math.cos(theta) * r, 3 + Math.random() * 3, Math.sin(theta) * r)
        s.vel
          .set(-Math.cos(theta), -0.8, -Math.sin(theta))
          .normalize()
          .multiplyScalar(12 + Math.random() * 6)
        s.dir.copy(s.vel).normalize()
      }
      if (!s.active) {
        s.line.visible = false
        continue
      }
      s.life += delta
      if (s.life > s.maxLife) {
        s.active = false
        s.line.visible = false
        continue
      }
      s.pos.addScaledVector(s.vel, delta)
      s.line.visible = true
      const tailLen = 1.8 * (1 - s.life / s.maxLife)
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
      renderer.dispose()
      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh || obj instanceof THREE.Points || obj instanceof THREE.Line) {
          obj.geometry.dispose()
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
          mats.forEach((m) => m.dispose())
        }
      })
      galTex.dispose()
    },
  }
}
