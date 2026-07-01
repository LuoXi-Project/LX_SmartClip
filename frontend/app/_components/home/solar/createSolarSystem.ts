/* ============================================================
   太阳系 · 主程序
   职责：初始化渲染器/场景 → 加载纹理 → 建天体 →
        每帧推进时间（固定慢速）、更新位置、刷新相机。
   交互：点击星球 → 相机平滑聚焦并锁定跟随该天体（轨道追踪）；
        拖拽旋转视角、滚轮/捏合缩放。
   说明：移除了原 demo 的控制面板、信息卡、音乐、流星等，
        仅保留「点击星球跟随」与固定的慢速自转，作为首页壁纸欣赏。
   ============================================================ */

import * as THREE from 'three'
import {
  PLANETS,
  dateToJD,
  planetPosition,
} from './solarData'
import {
  buildSolarScene,
  realRadius,
  viewRadius,
  SCENE_AU,
  SUN_VIEW_RADIUS,
  type SceneBuild,
} from './solarScene'

export type SolarHandle = {
  dispose: () => void
}

/** 「被追踪星球」在屏幕上转一圈的目标时长（真实秒）。
 *  所有星球都按真实自转/公转比例运行，只是把整个时间轴统一放慢，
 *  让当前聚焦的那颗星球看起来恰好在约这个秒数内完成一圈自转，
 *  其余星球则按各自真实周期同比换算（木星仍比地球快、金星仍极慢且逆行）。 */
const TARGET_SPIN_PERIOD_SEC = 90

/** 太阳的自转周期（赤道，约 25 天）——用于聚焦太阳时换算时间轴 */
const SUN_ROTATION_HOURS = 25 * 24

/** 由「希望被追踪天体在 TARGET_SPIN_PERIOD_SEC 秒内转一圈」反推
 *  每「真实秒」应推进多少「模拟天」。所有星球共享这个时间轴。 */
function daysPerSecondFor(rotationHours: number): number {
  const periodDays = Math.abs(rotationHours) / 24
  return periodDays / TARGET_SPIN_PERIOD_SEC
}

/* ============================================================
   轨道相机（自研球坐标相机）
   左键拖拽旋转 / 滚轮缩放 / 惯性 / 平滑聚焦跟随
   不依赖 OrbitControls，因为要支持「锁定跟随某行星」这一特性
   ============================================================ */

interface CameraState {
  target: THREE.Vector3
  distance: number
  theta: number
  phi: number
  tTheta: number
  tPhi: number
  tDist: number
  tTarget: THREE.Vector3
  minDist: number
  maxDist: number
  follow: THREE.Object3D | null
  followRadius: number
  followOffset: number
  cinematic: boolean
  cineAge: number
}

function createOrbitCamera(
  camera: THREE.PerspectiveCamera,
  domElement: HTMLCanvasElement,
) {
  const state: CameraState = {
    target: new THREE.Vector3(0, 0, 0),
    distance: 600,
    theta: Math.PI * 0.25,
    phi: Math.PI * 0.32,
    tTheta: Math.PI * 0.25, tPhi: Math.PI * 0.32, tDist: 600,
    tTarget: new THREE.Vector3(0, 0, 0),
    minDist: 18, maxDist: 50000,
    follow: null, followRadius: 0, followOffset: 30,
    cinematic: false, cineAge: 0,
  }

  let dragging = false, lastX = 0, lastY = 0
  let vTheta = 0, vPhi = 0

  // 跟随行星时允许抵近到表面附近；自由视角仍用全局 minDist
  function distLimits() {
    if (state.follow && state.followRadius > 0) {
      return { min: Math.max(state.followRadius * 1.08, 2), max: state.maxDist }
    }
    return { min: state.minDist, max: state.maxDist }
  }
  function clampDist(d: number): number {
    const { min, max } = distLimits()
    return Math.max(min, Math.min(max, d))
  }

  // —— 操控区域限制 ——
  // 画布只在视口「中央带」内响应缩放/旋转（拖拽与滚轮），
  // 两侧边缘（各约 20% 宽）放行滚轮与触摸滑动，便于上下滚动页面。
  // 指针起手时记录是否在中央带，整段手势期间保持该判定。
  let inZone = true
  function isControlZone(clientX: number): boolean {
    const x = clientX - domElement.getBoundingClientRect().left
    const w = domElement.clientWidth
    return x >= w * 0.2 && x <= w * 0.8
  }

  function onDown(e: PointerEvent) {
    inZone = isControlZone(e.clientX)
    if (!inZone) return // 边缘起手：交给页面（不抢拖拽）
    dragging = true
    lastX = e.clientX; lastY = e.clientY
    vTheta = vPhi = 0
    state.cinematic = false
    domElement.style.cursor = 'grabbing'
  }
  function onMove(e: PointerEvent) {
    if (!dragging) return
    const dx = e.clientX - lastX, dy = e.clientY - lastY
    lastX = e.clientX; lastY = e.clientY
    const k = 0.005
    state.tTheta -= dx * k
    state.tPhi -= dy * k
    state.tPhi = Math.max(0.05, Math.min(Math.PI - 0.05, state.tPhi))
    vTheta = -dx * k; vPhi = -dy * k
  }
  function onUp() {
    dragging = false
    if (inZone) domElement.style.cursor = 'grab'
  }

  function onWheel(e: WheelEvent) {
    // 边缘区域：放行页面滚动
    if (!isControlZone(e.clientX)) return
    e.preventDefault()
    const f = Math.pow(0.92, -e.deltaY * 0.025)
    state.tDist = clampDist(state.tDist * f)
  }

  // 触屏：单指旋转 / 双指捏合缩放
  let pinchDist = 0
  function touchStart(e: TouchEvent) {
    if (e.touches.length === 1) {
      // 单指起手在边缘则不抢手势，留给页面滚动
      inZone = isControlZone(e.touches[0].clientX)
      if (!inZone) return
      dragging = true
      lastX = e.touches[0].clientX; lastY = e.touches[0].clientY
      vTheta = vPhi = 0
    } else if (e.touches.length === 2) {
      // 双指：至少一指在中央带才接管（捏合缩放）
      const a = isControlZone(e.touches[0].clientX)
      const b = isControlZone(e.touches[1].clientX)
      inZone = a || b
      if (!inZone) return
      dragging = false
      pinchDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      )
    }
  }
  function touchMove(e: TouchEvent) {
    if (!inZone) return // 边缘：不阻止默认行为，交给页面
    e.preventDefault()
    if (e.touches.length === 1 && dragging) {
      const dx = e.touches[0].clientX - lastX, dy = e.touches[0].clientY - lastY
      lastX = e.touches[0].clientX; lastY = e.touches[0].clientY
      const k = 0.006
      state.tTheta -= dx * k; state.tPhi -= dy * k
      state.tPhi = Math.max(0.05, Math.min(Math.PI - 0.05, state.tPhi))
      vTheta = -dx * k; vPhi = -dy * k
    } else if (e.touches.length === 2) {
      const d = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      )
      if (pinchDist) {
        const ratio = pinchDist / d
        state.tDist = clampDist(state.tDist * Math.pow(ratio, 1.6))
      }
      pinchDist = d
    }
  }
  function touchEnd() { dragging = false; pinchDist = 0 }

  function onHover(e: PointerEvent) {
    if (dragging) return
    domElement.style.cursor = isControlZone(e.clientX) ? 'grab' : 'default'
  }

  domElement.addEventListener('pointerdown', onDown)
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  domElement.addEventListener('pointermove', onHover)
  domElement.addEventListener('wheel', onWheel, { passive: false })
  domElement.addEventListener('touchstart', touchStart, { passive: false })
  domElement.addEventListener('touchmove', touchMove, { passive: false })
  domElement.addEventListener('touchend', touchEnd)
  domElement.style.cursor = 'default'

  // 聚焦某个 group：平滑过渡到合适的观察距离
  function focusOn(group: THREE.Object3D, radius: number) {
    const same = state.follow === group
    state.follow = group
    state.followRadius = radius
    state.followOffset = Math.max(radius * 4.5, 14)
    if (!same) state.tDist = clampDist(state.followOffset)
  }
  function focusSun() {
    state.follow = null
    state.followRadius = 0
    state.tTarget.set(0, 0, 0)
    state.tDist = 600
  }
  function freeFly() {
    state.follow = null
    state.followRadius = 0
    state.cinematic = false
  }

  function update() {
    // 跟随目标位置
    if (state.follow) state.follow.getWorldPosition(state.tTarget)
    // 惯性（未拖拽时继续滑动并衰减）
    if (!dragging) {
      state.tTheta += vTheta
      state.tPhi += vPhi
      state.tPhi = Math.max(0.05, Math.min(Math.PI - 0.05, state.tPhi))
      vTheta *= 0.93; vPhi *= 0.93
      if (Math.abs(vTheta) < 1e-5) vTheta = 0
      if (Math.abs(vPhi) < 1e-5) vPhi = 0
    }
    // 阻尼插值
    const lerp = 0.12
    state.theta += (state.tTheta - state.theta) * lerp
    state.phi += (state.tPhi - state.phi) * lerp
    state.distance += (state.tDist - state.distance) * lerp
    state.target.lerp(state.tTarget, lerp)

    // 球坐标 → 笛卡尔
    const sinP = Math.sin(state.phi)
    camera.position.set(
      state.target.x + state.distance * sinP * Math.sin(state.theta),
      state.target.y + state.distance * Math.cos(state.phi),
      state.target.z + state.distance * sinP * Math.cos(state.theta),
    )
    camera.lookAt(state.target)
  }

  function dispose() {
    domElement.removeEventListener('pointerdown', onDown)
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    domElement.removeEventListener('pointermove', onHover)
    domElement.removeEventListener('wheel', onWheel)
    domElement.removeEventListener('touchstart', touchStart)
    domElement.removeEventListener('touchmove', touchMove)
    domElement.removeEventListener('touchend', touchEnd)
  }

  return { state, update, focusOn, focusSun, freeFly, dispose }
}

/* ============================================================
   主程序
   ============================================================ */

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

export function createSolarSystem(canvas: HTMLCanvasElement): SolarHandle | null {
  const renderer = createRenderer(canvas)
  if (!renderer) return null

  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75))
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200000)
  scene.add(new THREE.AmbientLight(0x404048, 0.35))

  const texLoader = new THREE.TextureLoader()
  const build: SceneBuild = buildSolarScene(texLoader)

  scene.add(build.milkyway)
  scene.add(build.sun)
  scene.add(build.belt)
  Object.values(build.planets).forEach((p) => scene.add(p.group))
  Object.values(build.orbitLines).forEach((l) => scene.add(l))

  // 相机控制
  const camCtrl = createOrbitCamera(camera, canvas)

  // 拾取
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()

  // 时间轴：跟随哪颗星就以它为基准换算「天/秒」，使它在屏幕上转一圈 ≈ TARGET_SPIN_PERIOD_SEC 秒。
  // 所有星球共享同一时间轴，因此各自相对速度始终是真实的比例。
  let daysPerSecond = daysPerSecondFor(24) // 默认以地球（约 24h 自转）为基准

  // 仅当点击发生在画布上且未发生明显拖动时，才视为「点击星球」
  let downX = 0, downY = 0, isDown = false
  function onDownPick(e: PointerEvent) {
    isDown = true; downX = e.clientX; downY = e.clientY
  }
  function onUpPick(e: PointerEvent) {
    if (!isDown) return
    isDown = false
    if (Math.hypot(e.clientX - downX, e.clientY - downY) > 5) return // 拖拽，忽略
    onClick(e)
  }
  // 共享临时向量（避免每帧分配）
  const _worldPos = new THREE.Vector3()
  const _screen = new THREE.Vector3()

  /** 把一个世界坐标投影到画布像素坐标，返回是否在相机前方及像素位置 */
  function projectToPixel(obj: THREE.Object3D, w: number, h: number) {
    obj.getWorldPosition(_worldPos)
    _screen.copy(_worldPos).project(camera)
    const behind = _screen.z > 1
    const x = (_screen.x * 0.5 + 0.5) * w
    const y = (-_screen.y * 0.5 + 0.5) * h
    return { behind, x, y, dist: camera.position.distanceTo(_worldPos) }
  }

  function onClick(e: PointerEvent) {
    const rect = canvas.getBoundingClientRect()
    const px = e.clientX - rect.left
    const py = e.clientY - rect.top
    pointer.x = (px / rect.width) * 2 - 1
    pointer.y = -(py / rect.height) * 2 + 1
    raycaster.setFromCamera(pointer, camera)

    const meshes: THREE.Object3D[] = []
    Object.values(build.planets).forEach((p) => meshes.push(p.mesh))
    meshes.push(build.sun)

    // ① 精确命中：射线直接打到星体表面
    const hits = raycaster.intersectObjects(meshes, false)
    if (hits.length) {
      const obj = hits[0].object
      if (obj === build.sun) {
        focusSun()
        return
      }
      const planetBuild = Object.values(build.planets).find((p) => p.mesh === obj)
      if (planetBuild) {
        focusPlanet(planetBuild.planet.id)
        return
      }
    }

    // ② 容差命中：点击落在星体附近（屏幕距离阈值），就视作选中最近的那颗。
    //    星球在缩小的背景下点击区域很小，这里把每颗星按其在屏幕上的视半径
    //    放宽 ~2.2 倍作为可点击圆盘，命中最近者。
    let bestId: string | null = null
    let bestScore = Infinity
    const w = rect.width, h = rect.height
    // 太阳
    {
      const proj = projectToPixel(build.sun, w, h)
      if (!proj.behind) {
        // 屏幕视半径（像素）≈ radius(世界) / dist * (h/2 / tan(fov/2))
        const apparent = (SUN_VIEW_RADIUS / proj.dist) * (h / 2 / Math.tan((camera.fov * Math.PI) / 360))
        const threshold = Math.max(apparent * 2.2, 26)
        const d = Math.hypot(proj.x - px, proj.y - py)
        if (d < threshold && d < bestScore) {
          bestScore = d
          bestId = 'sun'
        }
      }
    }
    Object.values(build.planets).forEach((p) => {
      const proj = projectToPixel(p.group, w, h)
      if (proj.behind) return
      const apparent = (p.radius / proj.dist) * (h / 2 / Math.tan((camera.fov * Math.PI) / 360))
      const threshold = Math.max(apparent * 2.2, 26)
      const d = Math.hypot(proj.x - px, proj.y - py)
      if (d < threshold && d < bestScore) {
        bestScore = d
        bestId = p.planet.id
      }
    })
    if (bestId === 'sun') focusSun()
    else if (bestId) focusPlanet(bestId)
  }

  function focusPlanet(id: string) {
    const p = build.planets[id]
    if (!p) return
    camCtrl.focusOn(p.group, p.radius)
    highlightOrbit(id)
    // 以这颗星的真实自转周期为基准重算时间轴：它在屏幕上 ≈ TARGET_SPIN_PERIOD_SEC 秒一圈
    daysPerSecond = daysPerSecondFor(p.planet.rotationHours)
  }
  function focusSun() {
    camCtrl.focusSun()
    highlightOrbit(null)
    daysPerSecond = daysPerSecondFor(SUN_ROTATION_HOURS)
  }
  function highlightOrbit(id: string | null) {
    Object.entries(build.orbitLines).forEach(([k, line]) => {
      const mat = line.material as THREE.LineBasicMaterial
      mat.opacity = id === null ? 0.35 : k === id ? 0.85 : 0.12
    })
  }

  canvas.addEventListener('pointerdown', onDownPick)
  canvas.addEventListener('pointerup', onUpPick)

  // 自适应尺寸
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

  // 模拟时间（从当前日期起，按固定慢速推进）
  let simDate = new Date()
  const clock = new THREE.Clock()
  let raf = 0

  function updateBodies(jd: number, dt: number, deltaDays: number) {
    // 行星位置 + 自转
    PLANETS.forEach((p) => {
      const built = build.planets[p.id]
      const pos = planetPosition(p, jd)
      built.group.position.set(pos.x * SCENE_AU, pos.y * SCENE_AU, pos.z * SCENE_AU)

      // 自转
      const dir = p.rotationHours < 0 ? -1 : 1
      const spd = (2 * Math.PI) / (Math.abs(p.rotationHours) / 24) // 弧度/模拟天
      built.spin.rotation.y += dir * spd * deltaDays * dt

      // 地球昼夜 shader 的太阳方向：太阳在原点，指向太阳 = normalize(-行星位置)
      if (p.id === 'earth') {
        const mat = built.mesh.material as THREE.ShaderMaterial
        if (mat.uniforms) {
          mat.uniforms.sunDir.value.copy(built.group.position).multiplyScalar(-1).normalize()
        }
        const clouds = (built.mesh.userData.clouds as THREE.Mesh) || null
        if (clouds) clouds.rotation.y += 0.02 * deltaDays * dt
      }

      // 月球公转（约 27.3 天一圈）
      if (built.moonPivot) {
        const moonSpd = (2 * Math.PI) / 27.32 // 弧度/模拟天
        built.moonPivot.rotation.y += moonSpd * deltaDays * dt
      }
    })

    // 太阳自转
    build.sun.rotation.y += (0.1 * deltaDays * dt) / 25
  }

  const animate = () => {
    raf = requestAnimationFrame(animate)
    const dt = Math.min(clock.getDelta(), 0.1)

    // 推进模拟时间：时间轴随「当前追踪的天体」自适应（真实比例不变）
    simDate = new Date(simDate.getTime() + daysPerSecond * dt * 86400000)
    const jd = dateToJD(simDate)

    updateBodies(jd, dt, daysPerSecond)
    camCtrl.update()
    renderer.render(scene, camera)
  }
  animate()

  // 默认追踪地球：相机锁定跟随地球，时间轴以地球自转（≈24h）为基准换算
  focusPlanet('earth')

  // 保留 realRadius/viewRadius 引用，避免 tree-shaking 误删（未来若开启「真实比例」可复用）
  void realRadius
  void viewRadius

  return {
    dispose() {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('pointerdown', onDownPick)
      canvas.removeEventListener('pointerup', onUpPick)
      camCtrl.dispose()

      renderer.forceContextLoss()
      renderer.dispose()
      scene.traverse((obj) => {
        if (obj instanceof THREE.Mesh || obj instanceof THREE.Points || obj instanceof THREE.Line) {
          obj.geometry.dispose()
          const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
          mats.forEach((m) => m.dispose())
        }
        if (obj instanceof THREE.Sprite) obj.material.dispose()
      })
      build.disposables.forEach((m) => m.dispose())
    },
  }
}
