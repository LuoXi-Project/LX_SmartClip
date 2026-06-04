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
`

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
        float t = uTime * 0.028;
        vec3 p = dir * 1.6 + vec3(t * 0.12, t * 0.06, 0.0);
        float band = fbm(p * 1.1);
        float wisps = fbm(p * 2.4 + vec3(2.0, 5.0, 1.0));
        float aurora = smoothstep(0.52, 0.78, band) * smoothstep(0.35, 0.65, wisps);
        vec3 voidCol = vec3(0.002, 0.006, 0.018);
        vec3 indigo = vec3(0.08, 0.05, 0.22);
        vec3 cyan = vec3(0.04, 0.28, 0.42);
        vec3 ice = vec3(0.55, 0.75, 0.95);
        vec3 col = mix(voidCol, indigo, smoothstep(0.25, 0.55, band) * 0.55);
        col = mix(col, cyan, aurora * 0.7);
        col += ice * pow(aurora, 2.5) * 0.18;
        float mouse = dot(normalize(dir.xy + 0.001), normalize(uMouse + 0.001)) * 0.5 + 0.5;
        col += vec3(0.04, 0.12, 0.22) * mouse * 0.08;
        float pin = pow(max(snoise(dir * 12.0), 0.0), 18.0);
        col += vec3(0.92, 0.96, 1.0) * pin * 2.2;
        col = pow(col, vec3(0.92));
        col = mix(col, voidCol, 0.08);
        gl_FragColor = vec4(col, 1.0);
      }
    `,
    side: THREE.BackSide,
    depthWrite: false,
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
      attribute vec3 aColor;
      varying vec3 vColor;
      varying float vTwinkle;
      uniform float uTime;
      uniform float uPixelRatio;
      void main() {
        vColor = aColor;
        vTwinkle = 0.82 + 0.18 * sin(uTime * 1.2 + aPhase);
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = aSize * uPixelRatio * (220.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      varying vec3 vColor;
      varying float vTwinkle;
      void main() {
        vec2 uv = gl_PointCoord - 0.5;
        float d = length(uv);
        if (d > 0.5) discard;
        float core = exp(-d * d * 40.0);
        float halo = exp(-d * d * 8.0) * 0.12;
        float alpha = (core + halo) * vTwinkle;
        vec3 col = vColor * (0.85 + core * 0.35);
        gl_FragColor = vec4(col, alpha);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
}

export function createAtmosphereMaterial(color: string, intensity: number) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uIntensity: { value: intensity },
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
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        float fresnel = pow(1.0 - max(dot(vNormal, vViewDir), 0.0), 4.0);
        float rim = smoothstep(0.15, 1.0, fresnel);
        gl_FragColor = vec4(uColor, rim * uIntensity);
      }
    `,
    transparent: true,
    depthWrite: false,
    side: THREE.BackSide,
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

export function createCometMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uColor: { value: new THREE.Color('#e0f2fe') } },
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
      varying float vAlong;
      void main() {
        float alpha = smoothstep(0.0, 0.15, vAlong) * (1.0 - smoothstep(0.7, 1.0, vAlong));
        gl_FragColor = vec4(uColor, alpha * 0.85);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
}
