import { useMemo } from "react"
import * as THREE from "three"
import type { SdfMeta } from "@/lib/sdf"

const vertexShader = /* glsl */ `
out vec3 vBox;
out vec3 vCamBox;

void main() {
  vBox = position;
  vCamBox = (inverse(modelMatrix) * vec4(cameraPosition, 1.0)).xyz;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

// Sphere-traces the SDF inside its bbox. The box mesh is centered on the bbox,
// so box-local + center = SDF local space (same as the glTF mesh's local space).
const fragmentShader = /* glsl */ `
precision highp float;
precision highp sampler3D;

uniform sampler3D uSdf;
uniform vec3 uBMin;
uniform vec3 uBMax;
uniform float uVoxel;
uniform float uDecodeScale;
uniform float uDecodeOffset;
uniform vec3 uColor;
uniform vec3 uLightDir;
uniform mat4 projectionMatrix;
uniform mat4 modelViewMatrix;
uniform mat4 modelMatrix;

in vec3 vBox;
in vec3 vCamBox;
out vec4 outColor;

float sdf(vec3 p) {
  return texture(uSdf, (p - uBMin) / (uBMax - uBMin)).r * uDecodeScale + uDecodeOffset;
}

vec3 sdfNormal(vec3 p) {
  vec2 e = vec2(uVoxel, 0.0);
  return normalize(vec3(
    sdf(p + e.xyy) - sdf(p - e.xyy),
    sdf(p + e.yxy) - sdf(p - e.yxy),
    sdf(p + e.yyx) - sdf(p - e.yyx)));
}

void main() {
  vec3 center = (uBMin + uBMax) * 0.5;
  vec3 ro = vCamBox + center;
  vec3 rd = normalize(vBox - vCamBox);

  vec3 inv = 1.0 / rd;
  vec3 t0 = (uBMin - ro) * inv;
  vec3 t1 = (uBMax - ro) * inv;
  float tNear = max(max(min(t0.x, t1.x), min(t0.y, t1.y)), min(t0.z, t1.z));
  float tFar = min(min(max(t0.x, t1.x), max(t0.y, t1.y)), max(t0.z, t1.z));

  float t = max(tNear, 0.0);
  bool hit = false;
  for (int i = 0; i < 256; i++) {
    if (t >= tFar) break;
    float d = sdf(ro + rd * t);
    if (d < uVoxel * 0.02) { hit = true; break; }
    t += max(d, uVoxel * 0.05);
  }
  if (!hit) discard;

  vec3 p = ro + rd * t;
  vec3 n = normalize(mat3(modelMatrix) * sdfNormal(p));
  float diffuse = max(dot(n, normalize(uLightDir)), 0.0);
  outColor = vec4(uColor * (0.35 + 0.75 * diffuse), 1.0);

  vec4 clip = projectionMatrix * modelViewMatrix * vec4(p - center, 1.0);
  gl_FragDepth = clip.z / clip.w * 0.5 + 0.5;
}
`

interface SdfVolumeProps {
  meta: SdfMeta
  texture: THREE.Data3DTexture
  lightDir: THREE.Vector3
}

export function SdfVolume({ meta, texture, lightDir }: SdfVolumeProps) {
  const size = useMemo(() => meta.bboxMax.clone().sub(meta.bboxMin), [meta])
  const center = useMemo(
    () => meta.bboxMax.clone().add(meta.bboxMin).multiplyScalar(0.5),
    [meta]
  )
  const uniforms = useMemo(
    () => ({
      uSdf: { value: texture },
      uBMin: { value: meta.bboxMin },
      uBMax: { value: meta.bboxMax },
      uVoxel: { value: meta.voxelSize },
      uDecodeScale: { value: meta.decodeScale },
      uDecodeOffset: { value: meta.decodeOffset },
      uColor: { value: new THREE.Color("#d98c59") },
      uLightDir: { value: lightDir },
    }),
    [meta, texture, lightDir]
  )

  return (
    <mesh position={center}>
      <boxGeometry args={[size.x, size.y, size.z]} />
      <shaderMaterial
        glslVersion={THREE.GLSL3}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        side={THREE.BackSide}
      />
    </mesh>
  )
}
