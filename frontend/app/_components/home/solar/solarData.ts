/* ============================================================
   太阳系 · 数据层
   轨道根数来源：NASA JPL —— Keplerian Elements for Approximate
   Positions of the Major Planets (J2000, 1800–2050 有效)
   a 半长轴(AU) · e 偏心率 · i 轨道倾角(°) · L 平黄经(°)
   varpi 近日点黄经(°) · Omega 升交点黄经(°)
   带 "Rate" 后缀的是每儒略世纪(36525 天)的变化率
   ============================================================ */

/** 1 天文单位 = 多少公里 */
export const AU_KM = 149597870.7
const DEG = Math.PI / 180

/** J2000 历元（2000-01-01 12:00 TT）对应的儒略日 */
export const J2000 = 2451545.0

/** 一对 [J2000 值, 每世纪变化率] */
export type OrbitalPair = readonly [number, number]

export interface PlanetData {
  id: string
  name: string
  en: string
  /** 颜色用于轨道线/标签 */
  color: number
  /** 贴图文件名（位于 public/solar/textures/） */
  texture: string
  /** 真实半径（公里），用于「真实比例」 */
  radiusKm: number
  /** 自转周期（小时），负值表示逆向自转 */
  rotationHours: number
  /** 自转轴倾角（°） */
  axialTilt: number
  /** 是否矮行星 */
  dwarf?: boolean
  /** 土星：true；天王星：'thin' */
  ring?: boolean | 'thin'
  a: OrbitalPair
  e: OrbitalPair
  i: OrbitalPair
  L: OrbitalPair
  varpi: OrbitalPair
  Omega: OrbitalPair
}

/** 八大行星 + 冥王星轨道根数 */
export const PLANETS: readonly PlanetData[] = [
  {
    id: 'mercury', name: '水星', en: 'Mercury',
    color: 0x9c8d7e, texture: '2k_mercury.jpg',
    radiusKm: 2439.7, rotationHours: 1407.6, axialTilt: 0.034,
    a: [0.38709927, 0.00000037], e: [0.20563593, 0.00001906],
    i: [7.00497902, -0.00594749], L: [252.25032350, 149472.67411175],
    varpi: [77.45779628, 0.16047689], Omega: [48.33076593, -0.12534081],
  },
  {
    id: 'venus', name: '金星', en: 'Venus',
    color: 0xd9b38c, texture: '2k_venus_atmosphere.jpg',
    radiusKm: 6051.8, rotationHours: -5832.5, axialTilt: 177.4,
    a: [0.72333566, 0.00000390], e: [0.00677672, -0.00004107],
    i: [3.39467605, -0.00078890], L: [181.97909950, 58517.81538729],
    varpi: [131.60246718, 0.00268329], Omega: [76.67984255, -0.27769418],
  },
  {
    id: 'earth', name: '地球', en: 'Earth',
    color: 0x4d7cb5, texture: '2k_earth_daymap.jpg',
    radiusKm: 6371.0, rotationHours: 23.93, axialTilt: 23.44,
    a: [1.00000261, 0.00000562], e: [0.01671123, -0.00004392],
    i: [-0.00001531, -0.01294668], L: [100.46457166, 35999.37244981],
    varpi: [102.93768193, 0.32327364], Omega: [0.0, 0.0],
  },
  {
    id: 'mars', name: '火星', en: 'Mars',
    color: 0xc1502a, texture: '2k_mars.jpg',
    radiusKm: 3389.5, rotationHours: 24.62, axialTilt: 25.19,
    a: [1.52371034, 0.00001847], e: [0.09339410, 0.00007882],
    i: [1.84969142, -0.00813131], L: [-4.55343205, 19140.30268499],
    varpi: [-23.94362959, 0.44441088], Omega: [49.55953891, -0.29257343],
  },
  {
    id: 'jupiter', name: '木星', en: 'Jupiter',
    color: 0xc7a87b, texture: '2k_jupiter.jpg',
    radiusKm: 69911, rotationHours: 9.93, axialTilt: 3.13,
    a: [5.20288700, -0.00011607], e: [0.04838624, -0.00013253],
    i: [1.30439695, -0.00183714], L: [34.39644051, 3034.74612775],
    varpi: [14.72847983, 0.21252668], Omega: [100.47390909, 0.20469106],
  },
  {
    id: 'saturn', name: '土星', en: 'Saturn',
    color: 0xd8c89a, texture: '2k_saturn.jpg', ring: true,
    radiusKm: 58232, rotationHours: 10.66, axialTilt: 26.73,
    a: [9.53667594, -0.00125060], e: [0.05386179, -0.00050991],
    i: [2.48599187, 0.00193609], L: [49.95442423, 1222.49362201],
    varpi: [92.59887831, -0.41897216], Omega: [113.66242448, -0.28867794],
  },
  {
    id: 'uranus', name: '天王星', en: 'Uranus',
    color: 0x9fd4de, texture: '2k_uranus.jpg', ring: 'thin',
    radiusKm: 25362, rotationHours: -17.24, axialTilt: 97.77,
    a: [19.18916464, -0.00196176], e: [0.04725744, -0.00004397],
    i: [0.77263783, -0.00242939], L: [313.23810451, 428.48202785],
    varpi: [170.95427630, 0.40805281], Omega: [74.01692503, 0.04240589],
  },
  {
    id: 'neptune', name: '海王星', en: 'Neptune',
    color: 0x3f66c4, texture: '2k_neptune.jpg',
    radiusKm: 24622, rotationHours: 16.11, axialTilt: 28.32,
    a: [30.06992276, 0.00026291], e: [0.00859048, 0.00005105],
    i: [1.77004347, 0.00035372], L: [-55.12002969, 218.45945325],
    varpi: [44.96476227, -0.32246464], Omega: [131.78422574, -0.00508664],
  },
  {
    id: 'pluto', name: '冥王星', en: 'Pluto', dwarf: true,
    color: 0xb8a088, texture: '2k_pluto.jpg',
    radiusKm: 1188, rotationHours: -153.3, axialTilt: 122.5,
    a: [39.48211675, -0.00031596], e: [0.24882730, 0.00005170],
    i: [17.14001206, 0.00004818], L: [238.92903833, 145.20780515],
    varpi: [224.06891629, -0.04062942], Omega: [110.30393684, -0.01183482],
  },
]

/* ============================================================
   轨道解算
   实现 JPL 文档的算法：由开普勒根数求某时刻的日心黄道坐标
   1) 按时间线性外推 6 个根数
   2) 解开普勒方程 M = E - e*sinE（牛顿迭代）
   3) 在轨道平面内求位置，再三次旋转到 J2000 黄道系
   ============================================================ */

/** 公历日期 → 儒略日 */
export function dateToJD(date: Date): number {
  return date.getTime() / 86400000 + 2440587.5
}

/** 把角度规整到 [-180,180]，提升迭代稳定性 */
function wrapDeg(d: number): number {
  d = d % 360
  if (d > 180) d -= 360
  if (d < -180) d += 360
  return d
}

/** 解开普勒方程，返回偏近点角 E(弧度) */
function solveKepler(M: number, e: number): number {
  const Mr = M * DEG
  let E = Mr + e * Math.sin(Mr) // 初值
  for (let k = 0; k < 8; k++) {
    const dM = Mr - (E - e * Math.sin(E))
    const dE = dM / (1 - e * Math.cos(E))
    E += dE
    if (Math.abs(dE) < 1e-9) break
  }
  return E
}

export interface OrbitPosition {
  x: number
  y: number
  z: number
  a: number
  e: number
}

/**
 * 计算某行星在给定儒略日的日心黄道坐标（单位 AU）
 * 返回 {x,y,z}，采用 J2000 黄道系：x 指向春分点，z 指向黄北极
 * 已映射为 Three.js 的 y-up：场景 X=日心x，场景 Z=-日心y，场景 Y=日心z
 */
export function planetPosition(p: PlanetData, jd: number): OrbitPosition {
  const T = (jd - J2000) / 36525 // 儒略世纪数
  const a = p.a[0] + p.a[1] * T
  const e = p.e[0] + p.e[1] * T
  const i = (p.i[0] + p.i[1] * T) * DEG
  const L = p.L[0] + p.L[1] * T
  const varpi = p.varpi[0] + p.varpi[1] * T
  const Omega = p.Omega[0] + p.Omega[1] * T

  const omega = (varpi - Omega) * DEG // 近日点幅角
  const M = wrapDeg(L - varpi) // 平近点角
  const E = solveKepler(M, e)

  // 轨道平面内坐标（x' 指向近日点）
  const xp = a * (Math.cos(E) - e)
  const yp = a * Math.sqrt(1 - e * e) * Math.sin(E)

  // 三次旋转：近日点幅角 ω → 倾角 i → 升交点黄经 Ω
  const cosO = Math.cos(Omega * DEG), sinO = Math.sin(Omega * DEG)
  const cosw = Math.cos(omega), sinw = Math.sin(omega)
  const cosi = Math.cos(i), sini = Math.sin(i)

  const x = (cosO * cosw - sinO * sinw * cosi) * xp +
    (-cosO * sinw - sinO * cosw * cosi) * yp
  const y = (sinO * cosw + cosO * sinw * cosi) * xp +
    (-sinO * sinw + cosO * cosw * cosi) * yp
  const z = (sinw * sini) * xp + (cosw * sini) * yp

  return { x, y: z, z: -y, a, e }
}

/** 采样整条轨道（一个完整周期），用于画轨道线。返回点数组(AU) */
export function orbitCurve(p: PlanetData, jd: number, segments = 256): OrbitPosition[] {
  const T = (jd - J2000) / 36525
  const a = p.a[0] + p.a[1] * T
  const e = p.e[0] + p.e[1] * T
  const i = (p.i[0] + p.i[1] * T) * DEG
  const varpi = p.varpi[0] + p.varpi[1] * T
  const Omega = p.Omega[0] + p.Omega[1] * T
  const omega = (varpi - Omega) * DEG

  const cosO = Math.cos(Omega * DEG), sinO = Math.sin(Omega * DEG)
  const cosw = Math.cos(omega), sinw = Math.sin(omega)
  const cosi = Math.cos(i), sini = Math.sin(i)

  const pts: OrbitPosition[] = []
  for (let s = 0; s <= segments; s++) {
    const E = (s / segments) * Math.PI * 2 // 沿偏近点角均匀取点
    const xp = a * (Math.cos(E) - e)
    const yp = a * Math.sqrt(1 - e * e) * Math.sin(E)
    const x = (cosO * cosw - sinO * sinw * cosi) * xp +
      (-cosO * sinw - sinO * cosw * cosi) * yp
    const y = (sinO * cosw + cosO * sinw * cosi) * xp +
      (-sinO * sinw + cosO * cosw * cosi) * yp
    const z = (sinw * sini) * xp + (cosw * sini) * yp
    pts.push({ x, y: z, z: -y, a, e })
  }
  return pts
}
