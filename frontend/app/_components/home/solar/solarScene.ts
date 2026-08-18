/* ============================================================
   太阳系 · 3D 场景构建
   依赖：three（r0.184+）
   职责：建天体（太阳/行星/土星环/天王星薄环/小行星带/银河天球）/
        轨道线 / 地球昼夜 shader / 大气辉光
   所有纹理从 public/solar/textures/ 经 HTTP 加载（可缓存、不进 bundle）
   ============================================================ */

import * as THREE from 'three'
import { type PlanetData, PLANETS, orbitCurve } from './solarData'
import { type QualityPreset } from './quality'

/** 1 AU = SCENE_AU 个 three 单位 */
export const SCENE_AU = 100
/** 太阳观赏半径 */
export const SUN_VIEW_RADIUS = 12

/** 行星观赏半径（夸张但相互比例合理，便于辨识） */
export const VIEW_RADIUS: Record<string, number> = {
  mercury: 1.6, venus: 2.6, earth: 2.8, mars: 2.0,
  jupiter: 7.0, saturn: 6.2, uranus: 4.2, neptune: 4.0, pluto: 1.2,
}

/** 真实比例下的半径（以太阳真实半径 696340km 映射到 SUN_VIEW_RADIUS） */
const KM_PER_UNIT = 696340 / SUN_VIEW_RADIUS

export const TEX_DIR = '/solar/textures/'

export interface PlanetBuild {
  group: THREE.Group
  spin: THREE.Group
  mesh: THREE.Mesh
  radius: number
  planet: PlanetData
  moonPivot: THREE.Group | null
}

export interface SceneBuild {
  sun: THREE.Mesh
  planets: Record<string, PlanetBuild>
  orbitLines: Record<string, THREE.LineLoop>
  belt: THREE.InstancedMesh
  milkyway: THREE.Mesh
  /** 每帧需更新的材质（时间/光强等） */
  disposables: THREE.Material[]
}

function configureSurfaceTexture(tex: THREE.Texture): THREE.Texture {
  tex.minFilter = THREE.LinearMipmapLinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.generateMipmaps = true
  tex.colorSpace = THREE.SRGBColorSpace
  return tex
}

export function viewRadius(p: PlanetData): number {
  return VIEW_RADIUS[p.id] ?? 2
}
export function realRadius(p: PlanetData): number {
  return p.radiusKm / KM_PER_UNIT
}

/** 按主球体分段数等比缩放次要几何体（云层/月球/大气壳），并设下限防变形 */
function segFor(preset: QualityPreset, ratio: number, min = 24): number {
  return Math.max(min, Math.round(preset.sphereSegments * ratio))
}

/** —— 太阳：核心球 + 多层辉光 sprite + 点光源 —— */
function buildSun(texLoader: THREE.TextureLoader, preset: QualityPreset): THREE.Mesh {
  const seg = preset.sphereSegments
  const g = new THREE.SphereGeometry(SUN_VIEW_RADIUS, seg, seg)
  const m = new THREE.MeshBasicMaterial({
    map: configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_sun.jpg')),
  })
  const sun = new THREE.Mesh(g, m)
  sun.name = 'sun'

  // 程序化径向辉光贴在 sprite 上，叠加混合做出大气光晕
  function glowTex(stops: [number, string][]): THREE.CanvasTexture {
    const c = document.createElement('canvas')
    c.width = c.height = 256
    const ctx = c.getContext('2d')!
    const grd = ctx.createRadialGradient(128, 128, 0, 128, 128, 128)
    stops.forEach((s) => grd.addColorStop(s[0], s[1]))
    ctx.fillStyle = grd
    ctx.fillRect(0, 0, 256, 256)
    return new THREE.CanvasTexture(c)
  }
  const halo = glowTex([
    [0.0, 'rgba(255,240,200,0.95)'],
    [0.25, 'rgba(255,180,80,0.55)'],
    [0.5, 'rgba(255,120,40,0.20)'],
    [1.0, 'rgba(255,90,20,0)'],
  ])
  const spriteMat = new THREE.SpriteMaterial({
    map: halo, blending: THREE.AdditiveBlending,
    transparent: true, depthWrite: false,
  })
  const glow = new THREE.Sprite(spriteMat)
  glow.scale.set(SUN_VIEW_RADIUS * 8, SUN_VIEW_RADIUS * 8, 1)
  sun.add(glow)

  // 第二层更大更淡的光晕
  const glow2 = new THREE.Sprite(spriteMat.clone())
  glow2.material.opacity = 0.4
  glow2.scale.set(SUN_VIEW_RADIUS * 16, SUN_VIEW_RADIUS * 16, 1)
  sun.add(glow2)

  // 太阳点光源（照亮行星）
  const light = new THREE.PointLight(0xfff4e0, 3, 0, 0)
  sun.add(light)
  return sun
}

/** —— 地球昼夜 shader：白天用日图、夜面用夜景灯光图 —— */
function earthMaterial(texLoader: THREE.TextureLoader): THREE.ShaderMaterial {
  const day = configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_earth_daymap.jpg'))
  const night = configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_earth_nightmap.jpg'))
  return new THREE.ShaderMaterial({
    uniforms: {
      dayTex: { value: day },
      nightTex: { value: night },
      sunDir: { value: new THREE.Vector3(1, 0, 0) },
    },
    vertexShader: `
      varying vec2 vUv; varying vec3 vNormal;
      void main(){
        vUv = uv;
        vNormal = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
      }`,
    fragmentShader: `
      uniform sampler2D dayTex; uniform sampler2D nightTex;
      uniform vec3 sunDir; varying vec2 vUv; varying vec3 vNormal;
      void main(){
        float d = dot(normalize(vNormal), normalize(sunDir));
        float t = smoothstep(-0.15, 0.25, d);   // 晨昏线柔化
        vec3 day = texture2D(dayTex, vUv).rgb;
        vec3 night = texture2D(nightTex, vUv).rgb * 1.4;
        gl_FragColor = vec4(mix(night, day, t), 1.0);
      }`,
  })
}

/** —— 大气辉光：背面 additive 球壳，做出边缘光 —— */
function atmosphere(radius: number, color: number | string, scale = 1.025, segments = 48): THREE.Mesh {
  const g = new THREE.SphereGeometry(radius * scale, segments, segments)
  const m = new THREE.ShaderMaterial({
    uniforms: { glowColor: { value: new THREE.Color(color) } },
    vertexShader: `
      varying float vI;
      void main(){
        vec3 n = normalize(mat3(modelMatrix)*normal);
        vec3 v = normalize(cameraPosition - (modelMatrix*vec4(position,1.0)).xyz);
        vI = pow(1.0 - abs(dot(n, v)), 2.5);
        gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0);
      }`,
    fragmentShader: `
      uniform vec3 glowColor; varying float vI;
      void main(){ gl_FragColor = vec4(glowColor, vI*0.9); }`,
    blending: THREE.AdditiveBlending,
    side: THREE.BackSide, transparent: true, depthWrite: false,
  })
  return new THREE.Mesh(g, m)
}

/** 土星环：环面几何 + alpha 贴图，重映射 UV 让纹理沿半径分布 */
function buildSaturnRing(planetR: number, texLoader: THREE.TextureLoader): THREE.Mesh {
  const inner = planetR * 1.25, outer = planetR * 2.3
  const geo = new THREE.RingGeometry(inner, outer, 128, 1)
  // 重写 UV：u 沿半径方向(0→1)，让条带纹理正确贴
  const pos = geo.attributes.position
  const uv = geo.attributes.uv
  const v3 = new THREE.Vector3()
  for (let i = 0; i < pos.count; i++) {
    v3.fromBufferAttribute(pos, i)
    const radius = v3.length()
    const u = (radius - inner) / (outer - inner)
    uv.setXY(i, u, 1)
  }
  const tex = configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_saturn_ring_alpha.png'))
  const mat = new THREE.MeshBasicMaterial({
    map: tex, alphaMap: tex, transparent: true,
    side: THREE.DoubleSide, opacity: 0.95, depthWrite: false,
  })
  const ring = new THREE.Mesh(geo, mat)
  ring.rotation.x = Math.PI / 2 // 放平到赤道面
  return ring
}

/** 天王星等的程序化薄环 */
function buildThinRing(inner: number, outer: number, color: number): THREE.Mesh {
  const geo = new THREE.RingGeometry(inner, outer, 96, 1)
  const mat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: 0.35,
    side: THREE.DoubleSide, depthWrite: false,
  })
  const ring = new THREE.Mesh(geo, mat)
  ring.rotation.x = Math.PI / 2
  return ring
}

/** 标准纹理行星：phong 材质 + 可选大气 */
function buildPlanet(p: PlanetData, texLoader: THREE.TextureLoader, preset: QualityPreset): PlanetBuild {
  const r = viewRadius(p)
  const group = new THREE.Group() // 公转锚点（位置由主循环更新）
  const spin = new THREE.Group() // 自转锚点
  group.add(spin)

  let mesh: THREE.Mesh
  let moonPivot: THREE.Group | null = null

  if (p.id === 'earth') {
    // 地球用昼夜 shader
    mesh = new THREE.Mesh(
      new THREE.SphereGeometry(r, preset.sphereSegments, preset.sphereSegments),
      earthMaterial(texLoader),
    )
    spin.add(mesh)
    // 云层
    const clouds = new THREE.Mesh(
      new THREE.SphereGeometry(r * 1.012, segFor(preset, 0.75, 32), segFor(preset, 0.75, 32)),
      new THREE.MeshPhongMaterial({
        map: configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_earth_clouds.jpg')),
        transparent: true, opacity: 0.55, depthWrite: false,
      }),
    )
    spin.add(clouds)
    mesh.userData.clouds = clouds
    // 大气辉光
    spin.add(atmosphere(r, 0x6ab7ff, 1.03, segFor(preset, 0.375)))

    // 月球：独立公转 pivot（不随地球自转/轴倾，挂在 group 上）
    moonPivot = new THREE.Group()
    const moonR = r * 0.27 // 月球约为地球的 0.273
    const moon = new THREE.Mesh(
      new THREE.SphereGeometry(moonR, segFor(preset, 0.5), segFor(preset, 0.5)),
      new THREE.MeshPhongMaterial({
        map: configureSurfaceTexture(texLoader.load(TEX_DIR + '2k_moon.jpg')),
        shininess: 2,
      }),
    )
    moon.position.set(r * 2.6, 0, 0) // 夸张轨道半径，便于看清
    moonPivot.add(moon)
    moonPivot.rotation.x = (5.14 * Math.PI) / 180 // 白道相对黄道 5.14°
    group.add(moonPivot)
  } else {
    const mat = new THREE.MeshPhongMaterial({
      map: configureSurfaceTexture(texLoader.load(TEX_DIR + p.texture)),
      shininess: 8,
    })
    // 气态巨行星给一点自发光，暗部不死黑
    if (['jupiter', 'saturn', 'uranus', 'neptune'].includes(p.id)) {
      mat.emissive = new THREE.Color(p.color)
      mat.emissiveIntensity = 0.05
    }
    mesh = new THREE.Mesh(
      new THREE.SphereGeometry(r, preset.sphereSegments, preset.sphereSegments),
      mat,
    )
    spin.add(mesh)
    // 金星厚大气辉光
    if (p.id === 'venus') spin.add(atmosphere(r, 0xffd9a0, 1.04, segFor(preset, 0.375)))
  }

  // 轴倾角（绕 z 轴倾斜自转轴）
  spin.rotation.z = ((p.axialTilt || 0) * Math.PI) / 180

  // 土星环
  if (p.ring === true) spin.add(buildSaturnRing(r, texLoader))
  // 天王星薄环（竖直，因为它躺着转）
  if (p.ring === 'thin') spin.add(buildThinRing(r * 1.6, r * 1.9, 0x88aabb))

  return { group, spin, mesh, radius: r, planet: p, moonPivot }
}

/** 小行星带：InstancedMesh，2.1–3.3 AU 之间随机散布 */
function buildAsteroidBelt(count: number): THREE.InstancedMesh {
  const geo = new THREE.DodecahedronGeometry(0.18, 0)
  const mat = new THREE.MeshStandardMaterial({
    color: 0x8a7d6b, roughness: 0.95, metalness: 0.0,
    emissive: 0x2a2018, emissiveIntensity: 0.3,
  })
  const mesh = new THREE.InstancedMesh(geo, mat, count)
  const dummy = new THREE.Object3D()
  // 用确定性伪随机（避免每次刷新跳变）
  let seed = 1337
  const rnd = () => {
    seed = (seed * 16807) % 2147483647
    return seed / 2147483647
  }
  for (let i = 0; i < count; i++) {
    const au = 2.1 + rnd() * 1.2
    const ang = rnd() * Math.PI * 2
    const rad = au * SCENE_AU
    const yJ = (rnd() - 0.5) * 0.12 * SCENE_AU // 轻微厚度
    dummy.position.set(Math.cos(ang) * rad, yJ, Math.sin(ang) * rad)
    const s = 0.4 + rnd() * 1.6
    dummy.scale.set(s, s, s)
    dummy.rotation.set(rnd() * 6, rnd() * 6, rnd() * 6)
    dummy.updateMatrix()
    mesh.setMatrixAt(i, dummy.matrix)
  }
  mesh.userData.isBelt = true
  return mesh
}

/** 银河天球：真实全景贴图，背面渲染做星空背景 */
function buildMilkyWay(texLoader: THREE.TextureLoader): THREE.Mesh {
  const geo = new THREE.SphereGeometry(60000, 64, 64)
  const tex = configureSurfaceTexture(texLoader.load(TEX_DIR + '8k_stars_milky_way.jpg'))
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    side: THREE.BackSide,
    depthWrite: false,
  })
  const sky = new THREE.Mesh(geo, mat)
  sky.rotation.x = (60 * Math.PI) / 180
  return sky
}

/** 轨道线：用解算出的一圈点画 LineLoop */
function buildOrbitLine(p: PlanetData, jd: number): THREE.LineLoop {
  const pts = orbitCurve(p, jd, 360)
  const arr = new Float32Array(pts.length * 3)
  pts.forEach((pt, i) => {
    arr[i * 3] = pt.x * SCENE_AU
    arr[i * 3 + 1] = pt.y * SCENE_AU
    arr[i * 3 + 2] = pt.z * SCENE_AU
  })
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(arr, 3))
  const mat = new THREE.LineBasicMaterial({
    color: p.color, transparent: true, opacity: 0.35,
  })
  const line = new THREE.LineLoop(geo, mat)
  line.userData.planetId = p.id
  return line
}

/** 构建整个太阳系场景对象（不含相机控制/光照环境），画质规格由 preset 决定 */
export function buildSolarScene(texLoader: THREE.TextureLoader, preset: QualityPreset): SceneBuild {
  const sun = buildSun(texLoader, preset)
  const belt = buildAsteroidBelt(preset.beltCount)
  const milkyway = buildMilkyWay(texLoader)

  const planets: Record<string, PlanetBuild> = {}
  const orbitLines: Record<string, THREE.LineLoop> = {}
  const jd = new Date().getTime() / 86400000 + 2440587.5
  PLANETS.forEach((p) => {
    const built = buildPlanet(p, texLoader, preset)
    planets[p.id] = built
    orbitLines[p.id] = buildOrbitLine(p, jd)
  })

  return { sun, planets, orbitLines, belt, milkyway, disposables: [] }
}
