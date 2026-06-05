import * as THREE from 'three'

export const NOISE_GLSL = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
    i.z + vec4(0.0, i1.z, i2.z, 1.0))
    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.z;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}

float fbm(vec3 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * snoise(p);
    p = p * 2.1 + vec3(17.0, 9.0, 23.0);
    a *= 0.48;
  }
  return v;
}

float hash31(vec3 p) {
  return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

vec3 hash33(vec3 p) {
  p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
           dot(p, vec3(269.5, 183.3, 246.1)),
           dot(p, vec3(113.5, 271.9, 124.6)));
  return fract(sin(p) * 43758.5453);
}

vec3 galaxyStars(vec3 dir, float milkyMask) {
  vec3 stars = vec3(0.0);
  for (int layer = 0; layer < 4; layer++) {
    float scale = 180.0 + float(layer) * 320.0;
    vec3 p = dir * scale;
    vec3 cell = floor(p);
    vec3 f = fract(p);
    float h = hash31(cell);
    if (h > 0.55 - float(layer) * 0.08) {
      vec3 rnd = hash33(cell);
      float d = length(f - rnd);
      float core = exp(-d * d * (60.0 + float(layer) * 20.0));
      float bright = smoothstep(0.82, 1.0, h);
      vec3 tint = mix(vec3(0.85, 0.9, 1.0), vec3(1.0, 0.92, 0.75), rnd.x);
      stars += tint * core * (0.2 + bright * 0.9) * milkyMask * 0.55;
    }
  }
  return stars;
}
`

/** 深空天空盒 — 华丽星云 + 银河带 */
export function createNebulaMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uMouse: { value: new THREE.Vector2(0, 0) },
    },
    vertexShader: /* glsl */ `
      varying vec3 vWorldPos;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorldPos = world.xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      uniform vec2 uMouse;
      varying vec3 vWorldPos;
      ${NOISE_GLSL}
      void main() {
        vec3 dir = normalize(vWorldPos);
        float t = uTime * 0.022;
        vec3 p = dir * 2.2 + vec3(t * 0.06, t * 0.03, 0.0);

        float band = fbm(p * 1.3 + vec3(1.0, 3.0, 5.0));
        float wisps = fbm(p * 2.6 + vec3(4.0, 1.0, 2.0));
        float filaments = fbm(p * 4.5 + vec3(t * 0.1, 2.0, 8.0));

        vec3 galAxis = normalize(vec3(0.12, 0.88, 0.32));
        float galLat = abs(dot(dir, galAxis));
        float milkyCore = exp(-galLat * galLat * 55.0);
        float milkyBand = exp(-galLat * galLat * 8.0);
        float milkyHaze = exp(-galLat * galLat * 2.5);
        float milkyNoise = fbm(dir * 5.5 + vec3(t * 0.015, 0.0, 0.0));
        float milkyFilament = fbm(dir * 11.0 + vec3(3.0, t * 0.02, 7.0));
        float milky = milkyBand * (0.5 + milkyNoise * 0.5);

        vec3 voidCol = vec3(0.002, 0.003, 0.012);
        vec3 indigo = vec3(0.06, 0.03, 0.18);
        vec3 violet = vec3(0.18, 0.05, 0.32);
        vec3 cyan = vec3(0.02, 0.22, 0.42);
        vec3 magenta = vec3(0.28, 0.06, 0.22);
        vec3 gold = vec3(0.35, 0.22, 0.06);

        vec3 col = mix(voidCol, indigo, smoothstep(0.2, 0.6, band) * 0.7);
        col = mix(col, violet, smoothstep(0.45, 0.72, wisps) * 0.55);
        col = mix(col, cyan, smoothstep(0.5, 0.75, filaments) * 0.45);
        col = mix(col, magenta, smoothstep(0.55, 0.8, band * wisps) * 0.35);
        col += gold * pow(smoothstep(0.6, 0.85, filaments), 2.0) * 0.18;

        vec3 milkyGlow = mix(vec3(0.15, 0.18, 0.35), vec3(0.35, 0.25, 0.55), milkyFilament);
        milkyGlow = mix(milkyGlow, vec3(0.5, 0.55, 0.85), milkyCore);
        col += milkyGlow * milkyHaze * 0.22;
        col += vec3(0.2, 0.25, 0.45) * milky * 0.42;
        col += vec3(0.45, 0.5, 0.75) * milkyCore * 0.28;
        col += vec3(0.6, 0.65, 0.95) * milkyCore * milkyFilament * 0.15;

        col += galaxyStars(dir, milkyBand + milkyCore * 1.2);

        float mouse = dot(normalize(dir.xy + 0.001), normalize(uMouse + 0.001)) * 0.5 + 0.5;
        col += mix(vec3(0.04, 0.1, 0.25), vec3(0.2, 0.08, 0.3), mouse) * 0.12;

        float pin = pow(max(snoise(dir * 13.0), 0.0), 20.0);
        col += vec3(0.95, 0.97, 1.0) * pin * 1.6;
        float bright = pow(max(snoise(dir * 8.0 + 3.0), 0.0), 8.0);
        col += vec3(0.7, 0.85, 1.0) * bright * 0.22;

        col = pow(col, vec3(0.94));
        gl_FragColor = vec4(col, 1.0);
      }
    `,
    side: THREE.BackSide,
    depthWrite: false,
  })
}

/** 月表 — 陨石坑 + 地球反射蓝辉 */
export function createMoonSurfaceMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uEarthGlow: { value: 0.6 },
    },
    vertexShader: /* glsl */ `
      uniform float uTime;
      varying vec2 vUv;
      varying vec3 vNormal;
      varying float vCrater;
      varying float vDist;
      ${NOISE_GLSL}
      void main() {
        vUv = uv;
        vec3 pos = position;
        float macro = fbm(vec3(uv * 3.5, 0.0)) * 0.55;
        float micro = fbm(vec3(uv * 18.0, 2.0)) * 0.18;
        float crater = fbm(vec3(uv * 9.0, 4.0));
        float rim = smoothstep(0.48, 0.52, crater) * (1.0 - smoothstep(0.52, 0.58, crater));
        float h = macro + micro - rim * 0.35;
        pos.y += h * 0.75;
        vCrater = crater;
        vDist = length(pos.xz);
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      uniform float uEarthGlow;
      varying vec2 vUv;
      varying vec3 vNormal;
      varying float vCrater;
      varying float vDist;
      ${NOISE_GLSL}
      void main() {
        float fine = fbm(vec3(vUv * 40.0, 1.0));
        float crater = smoothstep(0.42, 0.55, vCrater);
        vec3 regolith = vec3(0.44, 0.43, 0.41);
        vec3 shadow = vec3(0.12, 0.11, 0.1);
        vec3 highlight = vec3(0.65, 0.64, 0.62);
        vec3 col = mix(regolith, shadow, crater * 0.72);
        col = mix(col, highlight, fine * 0.2);

        vec3 sunDir = normalize(vec3(0.35, 0.12, -0.92));
        float sunDiff = max(dot(vNormal, sunDir), 0.0);
        col *= 0.15 + sunDiff * 0.85;

        float horizon = smoothstep(0.0, 0.5, vUv.y);
        float earthLight = exp(-vDist * 0.04) * horizon * uEarthGlow;
        col += vec3(0.15, 0.35, 0.65) * earthLight * 0.55;
        col += vec3(0.4, 0.6, 0.95) * pow(earthLight, 2.0) * 0.35;

        float fresnel = pow(1.0 - max(dot(vNormal, vec3(0.0, 1.0, 0.0)), 0.0), 3.0);
        col += vec3(0.5, 0.7, 1.0) * fresnel * earthLight * 0.25;

        gl_FragColor = vec4(col, 1.0);
      }
    `,
  })
}

/** 地球 — 华丽大陆/云层/晨昏线/城市灯光/极光 */
export function createEarthMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uSunDir: { value: new THREE.Vector3(0.6, 0.2, 0.75).normalize() },
    },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vWorldPos;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorldPos = world.xyz;
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      uniform vec3 uSunDir;
      varying vec3 vNormal;
      varying vec3 vWorldPos;
      ${NOISE_GLSL}
      void main() {
        vec3 n = normalize(vNormal);
        float lon = atan(n.z, n.x);
        float lat = asin(clamp(n.y, -1.0, 1.0));
        vec2 uv = vec2(lon / 6.28318 + 0.5, lat / 3.14159 + 0.5);

        float continent = fbm(vec3(uv * 3.2, 0.2));
        float detail = fbm(vec3(uv * 9.0, 1.5));
        float landMask = smoothstep(0.36, 0.5, continent + detail * 0.28);

        vec3 deepOcean = vec3(0.01, 0.06, 0.22);
        vec3 shallowOcean = vec3(0.05, 0.22, 0.48);
        vec3 landLow = vec3(0.1, 0.35, 0.12);
        vec3 landHigh = vec3(0.45, 0.38, 0.2);
        vec3 snow = vec3(0.95, 0.97, 1.0);

        vec3 ocean = mix(deepOcean, shallowOcean, fbm(vec3(uv * 6.0, 3.0)) * 0.5 + 0.5);
        vec3 land = mix(landLow, landHigh, fbm(vec3(uv * 7.0, 2.0)) * 0.5 + 0.5);
        land = mix(land, snow, smoothstep(0.62, 0.8, lat + fbm(vec3(uv * 5.0, 4.0)) * 0.15));
        vec3 base = mix(ocean, land, landMask);

        float clouds = smoothstep(0.48, 0.65, fbm(vec3(uv * 5.5 + uTime * 0.004, 5.0)));
        float cloudDetail = fbm(vec3(uv * 12.0 + uTime * 0.002, 7.0));
        base = mix(base, vec3(0.95, 0.97, 1.0), clouds * (0.5 + cloudDetail * 0.2));

        float diff = max(dot(n, uSunDir), 0.0);
        float night = 1.0 - smoothstep(-0.08, 0.18, diff);

        float cities = fbm(vec3(uv * 28.0, 6.0));
        float cityDetail = fbm(vec3(uv * 55.0, 8.0));
        float cityLights = landMask * night * smoothstep(0.5, 0.68, cities) * (0.6 + cityDetail * 0.4);
        base += vec3(1.0, 0.8, 0.4) * cityLights * 1.1;
        base += vec3(0.4, 0.7, 1.0) * cityLights * cityDetail * 0.4;

        float auroraLat = abs(lat);
        float aurora = night * exp(-auroraLat * auroraLat * 8.0) * smoothstep(0.4, 0.7, fbm(vec3(uv * 4.0 + uTime * 0.05, 9.0)));
        base += mix(vec3(0.1, 0.8, 0.5), vec3(0.5, 0.2, 0.9), fbm(vec3(uv * 3.0, uTime * 0.03))) * aurora * 0.7;

        vec3 col = base * (0.06 + diff * 1.1);
        float spec = pow(max(dot(reflect(-uSunDir, n), normalize(cameraPosition - vWorldPos)), 0.0), 48.0);
        col += vec3(0.7, 0.9, 1.0) * spec * 0.45 * (1.0 - landMask * 0.4);

        float terminator = smoothstep(-0.02, 0.14, diff);
        vec3 termGlow = mix(vec3(0.0), vec3(1.0, 0.55, 0.15), smoothstep(0.0, 0.08, diff) * (1.0 - smoothstep(0.08, 0.18, diff)));
        col = mix(col * 0.2, col, terminator);
        col += termGlow * 0.35;

        col = pow(col, vec3(0.92));
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  })
}

export function createStarMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
    },
    vertexShader: /* glsl */ `
      attribute float aSize;
      attribute float aPhase;
      attribute float aBright;
      attribute vec3 aColor;
      varying vec3 vColor;
      varying float vTwinkle;
      varying float vBright;
      uniform float uTime;
      uniform float uPixelRatio;
      void main() {
        vColor = aColor;
        vBright = aBright;
        vTwinkle = 0.7 + 0.3 * sin(uTime * (1.8 + aPhase * 0.4) + aPhase);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = aSize * uPixelRatio * (260.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      varying vec3 vColor;
      varying float vTwinkle;
      varying float vBright;
      void main() {
        vec2 uv = gl_PointCoord - 0.5;
        float d = length(uv);
        if (d > 0.5) discard;
        float core = exp(-d * d * 32.0);
        float halo = exp(-d * d * 5.5) * 0.18;
        float glow = exp(-d * d * 2.2) * 0.05;
        float spike = exp(-abs(uv.x) * 26.0) * exp(-abs(uv.y) * 6.0);
        spike += exp(-abs(uv.y) * 26.0) * exp(-abs(uv.x) * 6.0);
        spike *= vBright * 0.28;
        float alpha = (core + halo + glow + spike) * vTwinkle * 0.75;
        vec3 col = vColor * (0.75 + core * 0.5 + halo * 0.15 + spike * 0.3);
        gl_FragColor = vec4(col, alpha);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
}

export function createAtmosphereMaterial(color: string, intensity: number, pulse = false) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uIntensity: { value: intensity },
      uTime: { value: 0 },
      uSunDir: { value: new THREE.Vector3(0.55, 0.18, 0.8).normalize() },
    },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vViewDir = normalize(cameraPosition - world.xyz);
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform float uIntensity;
      uniform float uTime;
      uniform vec3 uSunDir;
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        float fresnel = pow(1.0 - max(dot(vNormal, vViewDir), 0.0), 3.2);
        float rim = smoothstep(0.08, 1.0, fresnel);
        float sunSide = max(dot(vNormal, uSunDir), 0.0);
        float sunRim = pow(sunSide, 1.5) * fresnel;
        float pulse = ${pulse ? '0.85 + 0.15 * sin(uTime * 0.8)' : '1.0'};
        vec3 col = uColor + vec3(1.0, 0.6, 0.2) * sunRim * 0.5;
        float alpha = (rim + sunRim * 0.6) * uIntensity * pulse;
        gl_FragColor = vec4(col, alpha);
      }
    `,
    transparent: true,
    depthWrite: false,
    side: THREE.BackSide,
    blending: THREE.AdditiveBlending,
  })
}

/** 流星尾迹 */
export function createCometMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color('#bfdbfe') },
      uTime: { value: 0 },
    },
    vertexShader: /* glsl */ `
      attribute float aAlong;
      varying float vAlong;
      void main() {
        vAlong = aAlong;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform float uTime;
      varying float vAlong;
      void main() {
        float head = smoothstep(0.0, 0.12, vAlong);
        float tail = 1.0 - smoothstep(0.5, 1.0, vAlong);
        float alpha = head * tail;
        vec3 col = mix(uColor, vec3(1.0, 0.9, 0.7), head);
        gl_FragColor = vec4(col, alpha * 0.95);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
}

export function createPlanetMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying vec3 vWorldPos;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorldPos = world.xyz;
        vNormal = normalize(normalMatrix * normal);
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      varying vec3 vNormal;
      varying vec3 vWorldPos;
      ${NOISE_GLSL}
      void main() {
        vec3 n = normalize(vNormal);
        float bump = fbm(n * 4.0 + uTime * 0.015) * 0.5 + 0.5;
        vec3 deep = vec3(0.01, 0.05, 0.14);
        vec3 sea = vec3(0.04, 0.18, 0.38);
        vec3 ice = vec3(0.75, 0.88, 1.0);
        vec3 base = mix(deep, sea, smoothstep(0.4, 0.58, bump));
        base = mix(base, ice, smoothstep(0.72, 0.9, bump) * 0.55);
        vec3 lightDir = normalize(vec3(0.55, 0.25, 1.0));
        float diff = max(dot(n, lightDir), 0.0);
        float spec = pow(max(dot(reflect(-lightDir, n), normalize(-vWorldPos)), 0.0), 48.0);
        vec3 col = base * (0.22 + diff * 0.78);
        col += vec3(0.7, 0.9, 1.0) * spec * 0.35;
        col = pow(col, vec3(0.95));
        gl_FragColor = vec4(col, 1.0);
      }
    `,
  })
}

export function createRingMaterial(color: string) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uColor: { value: new THREE.Color(color) },
    },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      varying vec3 vViewDir;
      void main() {
        vUv = uv;
        vec4 world = modelMatrix * vec4(position, 1.0);
        vViewDir = normalize(cameraPosition - world.xyz);
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: /* glsl */ `
      uniform float uTime;
      uniform vec3 uColor;
      varying vec2 vUv;
      varying vec3 vViewDir;
      ${NOISE_GLSL}
      void main() {
        float r = vUv.y;
        float edge = smoothstep(0.05, 0.18, r) * (1.0 - smoothstep(0.82, 0.96, r));
        float sparkle = fbm(vec3(vUv.x * 24.0, r * 6.0, uTime * 0.08));
        float alpha = edge * (0.18 + sparkle * 0.22);
        float fresnel = pow(1.0 - abs(dot(normalize(vViewDir), vec3(0.0, 1.0, 0.0))), 3.0);
        vec3 col = mix(uColor, vec3(1.0), fresnel * 0.45 + sparkle * 0.15);
        gl_FragColor = vec4(col, alpha);
      }
    `,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  })
}
