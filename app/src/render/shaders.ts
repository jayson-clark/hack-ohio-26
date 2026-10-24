// The projection shader: what the projector emits, computed per pixel in map
// coordinates. The projector window draws it on a flat quad; the virtual table
// drapes it over the terrain mesh (DRAPED), lit as white PLA would be.
//
// Colors here are display (sRGB) values written straight to the framebuffer.

export const MAX_TOKENS = 32;

export const vertexShader = /* glsl */ `
varying vec2 vUv;
varying vec3 vWorldPos;
#ifdef DRAPED
varying vec3 vNormal;
#endif

void main() {
  vUv = uv;
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
#ifdef DRAPED
  vNormal = normalize(mat3(modelMatrix) * normal);
#endif
  gl_Position = projectionMatrix * viewMatrix * wp;
}
`;

export const fragmentShader = /* glsl */ `
precision highp float;

#define MAX_TOKENS ${MAX_TOKENS}

varying vec2 vUv;          // (col / width, row / height), row 0 = north
varying vec3 vWorldPos;

uniform sampler2D uHeight; // elevation normalized to 0..1
uniform sampler2D uLabels; // static overlay: towns and names
uniform sampler2D uRoutes; // evacuation routes, redrawn per routes message
uniform float uShowRoutes;
uniform sampler2D uFire;   // r = burning, g = burned (linear filtered masks),
                           // b, a = forecast P(burned) at the first two horizons
uniform vec2 uGrid;        // map size in cells
uniform float uCellM;      // cell size in meters
uniform float uElevMin;
uniform float uElevRange;
uniform float uTime;
uniform float uHasFire;
uniform vec4 uLayers;      // tint, contours, labels, grid (0 or 1)

uniform vec4 uTokens[MAX_TOKENS]; // x, y (cells), type index, selected
uniform int uTokenCount;
uniform vec3 uTokenColors[4];
uniform float uHalo;
uniform float uCrewReach; // cells: a crew's reach (hello.crew_radius)
uniform float uRing;

#ifdef DRAPED
varying vec3 vNormal;
uniform vec3 uProjector;   // projector position, world mm
uniform float uAmbient;    // room light under the canopy
uniform vec2 uTiles;       // print tile grid, for seams
#endif

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * noise(p);
    p *= 2.03;
    a *= 0.5;
  }
  return v;
}

// Hypsometric tint, muted so fire reads as the brightest thing on the table.
vec3 hypso(float t) {
  vec3 c0 = vec3(0.11, 0.24, 0.23);
  vec3 c1 = vec3(0.24, 0.36, 0.23);
  vec3 c2 = vec3(0.45, 0.44, 0.28);
  vec3 c3 = vec3(0.62, 0.54, 0.41);
  vec3 c4 = vec3(0.86, 0.83, 0.76);
  if (t < 0.25) return mix(c0, c1, t / 0.25);
  if (t < 0.5) return mix(c1, c2, (t - 0.25) / 0.25);
  if (t < 0.78) return mix(c2, c3, (t - 0.5) / 0.28);
  return mix(c3, c4, (t - 0.78) / 0.22);
}

// Anti-aliased iso-lines of v at every integer, about widthPx pixels wide.
float isoLine(float v, float widthPx) {
  float d = abs(fract(v - 0.5) - 0.5) / max(fwidth(v), 1e-5);
  return 1.0 - smoothstep(widthPx * 0.5, widthPx * 0.5 + 1.0, d);
}

vec3 terrain(vec2 uv, vec2 cell) {
  float h = texture2D(uHeight, uv).r;
  vec2 texel = 1.0 / uGrid;
  float hl = texture2D(uHeight, uv - vec2(texel.x, 0.0)).r;
  float hr = texture2D(uHeight, uv + vec2(texel.x, 0.0)).r;
  float hn = texture2D(uHeight, uv - vec2(0.0, texel.y)).r;
  float hs = texture2D(uHeight, uv + vec2(0.0, texel.y)).r;

  // Hillshade, sun from the north-west. Axes: east, south, up.
  float k = uElevRange / (2.0 * uCellM) * 2.5;
  vec3 n = normalize(vec3(-(hr - hl) * k, -(hs - hn) * k, 1.0));
  vec3 sun = normalize(vec3(-0.54, -0.54, 0.64));
  float shade = clamp(dot(n, sun), 0.0, 1.0);

  vec3 base = mix(vec3(0.42), hypso(h), uLayers.x);
  vec3 col = base * (0.42 + 0.78 * shade);

  // Contours: minor every 50 m, major every 250 m.
  float elev = uElevMin + h * uElevRange;
  float minor = isoLine(elev / 50.0, 1.0);
  float major = isoLine(elev / 250.0, 1.6);
  col = mix(col, col * 1.45 + 0.04, minor * 0.35 * uLayers.y);
  col = mix(col, vec3(0.93, 0.9, 0.82), major * 0.55 * uLayers.y);

  // Reference grid every 32 cells.
  float g = max(isoLine(cell.x / 32.0, 1.0), isoLine(cell.y / 32.0, 1.0));
  col = mix(col, vec3(0.55, 0.75, 0.95), g * 0.22 * uLayers.w);
  return col;
}

vec3 fire(vec3 col, vec2 uv, vec2 cell) {
  vec4 f = texture2D(uFire, uv);
  float t = uTime;

  // Forecast ghost on unburned ground: further horizon in yellow, nearer in orange on top.
  float unburned = 1.0 - clamp(f.r + f.g, 0.0, 1.0);
  col = mix(col, vec3(0.98, 0.82, 0.31), f.a * 0.3 * unburned);
  col = mix(col, vec3(1.0, 0.47, 0.16), f.b * 0.55 * unburned);

  // Burned ground: dark char with a few glowing embers.
  float burned = smoothstep(0.3, 0.6, f.g + (noise(cell * 0.3) - 0.5) * 0.3);
  col = mix(col, col * 0.12 + vec3(0.05, 0.035, 0.03), burned);
  float ember = smoothstep(0.78, 0.86, noise(cell * 1.1)) * (0.5 + 0.5 * sin(t * 2.5 + hash(floor(cell * 1.1)) * 6.28));
  col += vec3(1.0, 0.32, 0.06) * ember * burned * 0.55;

  // Active flame front, with flicker and a soft glow ahead of it.
  float flick = fbm(cell * 0.16 + vec2(0.0, -t * 0.9));
  float edge = fbm(cell * 0.18 + vec2(t * 0.05, 0.0));
  float burning = smoothstep(0.3, 0.6, f.r + (edge - 0.5) * 0.45);
  vec3 flame = mix(vec3(0.92, 0.2, 0.03), vec3(1.0, 0.8, 0.35), smoothstep(0.35, 0.75, flick));
  col = mix(col, flame * (1.0 + 0.35 * flick), burning);
  float glow = smoothstep(0.02, 0.45, f.r) * (1.0 - burning);
  col += vec3(1.0, 0.36, 0.08) * glow * (0.3 + 0.15 * flick);
  return col;
}

vec3 tokens(vec3 col, vec2 cell) {
  for (int i = 0; i < MAX_TOKENS; i++) {
    if (i >= uTokenCount) break;
    vec4 tk = uTokens[i];
    float d = distance(cell, tk.xy);
    float aa = max(fwidth(d), 1e-4);
    vec3 tc = uTokenColors[int(tk.z)];
    // A crew's reach (#98), so it's visible what it holds. Its full-strength
    // core (60%) sits under the white halo, so mark the outer edge instead: a
    // faint tint fading out like its suppression, and a dashed ring at the
    // full radius, dashed like the recommendation rings that use the same
    // radius. Type 0 is crew (TOKEN_TYPES).
    if (tk.z < 0.5) {
      float core = 0.6 * uCrewReach;
      float reach = clamp((uCrewReach - d) / (uCrewReach - core), 0.0, 1.0);
      col = mix(col, tc, 0.18 * reach);
      vec2 rel = cell - tk.xy;
      float dash = step(0.0, sin(atan(rel.y, rel.x) * 18.0));
      col = mix(col, tc, (1.0 - smoothstep(0.3, 0.3 + aa * 1.5, abs(d - uCrewReach))) * dash * 0.9);
    }
    // Colored ring for the type, white disc under the marker.
    col = mix(col, tc, 1.0 - smoothstep(uRing - aa, uRing + aa, d));
    col = mix(col, vec3(1.0), 1.0 - smoothstep(uHalo - aa, uHalo + aa, d));
    if (tk.w > 0.5) {
      float r = uRing + 2.5 + 1.2 * sin(uTime * 5.0);
      col = mix(col, vec3(1.0), (1.0 - smoothstep(0.35, 0.35 + aa * 1.5, abs(d - r))) * 0.9);
    }
  }
  return col;
}

void main() {
  vec2 cell = vUv * uGrid;
  vec3 col = terrain(vUv, cell);
  if (uHasFire > 0.5) col = fire(col, vUv, cell);
  // Routes pulse gently so they read as live guidance, not map ink.
  vec4 rt = texture2D(uRoutes, vUv);
  col = mix(col, rt.rgb, rt.a * uShowRoutes * (0.82 + 0.18 * sin(uTime * 3.0)));
  vec4 lab = texture2D(uLabels, vUv);
  col = mix(col, lab.rgb, lab.a * uLayers.z);
  col = tokens(col, cell);

#ifdef DRAPED
  // Projected light on matte white PLA, plus a little room light.
  vec3 n = normalize(vNormal);
  float lambert = max(dot(n, normalize(uProjector - vWorldPos)), 0.0);
  vec2 tile = vUv * uTiles;
  vec2 td = abs(fract(tile + 0.5) - 0.5) / max(fwidth(tile), vec2(1e-5));
  float seam = 1.0 - clamp(min(td.x, td.y) - 0.5, 0.0, 1.0);
  vec3 albedo = vec3(0.92) * (1.0 - seam * 0.4);
  col = albedo * (col * (0.15 + 0.95 * lambert) + uAmbient * (0.55 + 0.45 * n.y));
#endif

  gl_FragColor = vec4(col, 1.0);
}
`;
