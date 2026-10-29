import * as THREE from "three"
import { read } from "three/examples/jsm/libs/ktx-parse.module.js"

// Mirrors docs/format.md (version 1).
export type SdfFormat = "r8" | "r16f" | "r32f"

const META_KEY = "3dsdf.meta"
const SCHEME_NONE = 0
const SCHEME_ZSTD = 2

/** Decompress one zstd frame into `size` bytes. Injected so this module needs no decoder. */
export type ZstdDecoder = (bytes: Uint8Array, size: number) => Uint8Array

const VK_FORMATS: Record<
  number,
  { format: SdfFormat; type: THREE.TextureDataType }
> = {
  9: { format: "r8", type: THREE.UnsignedByteType }, // R8_UNORM
  76: { format: "r16f", type: THREE.HalfFloatType }, // R16_SFLOAT
  100: { format: "r32f", type: THREE.FloatType }, // R32_SFLOAT
}

export interface SdfMeta {
  version: number
  dims: [number, number, number]
  format: SdfFormat
  voxelSize: number
  bboxMin: THREE.Vector3
  bboxMax: THREE.Vector3
  // distance = sampled value * decodeScale + decodeOffset
  decodeScale: number
  decodeOffset: number
  objectName: string
  triangles: number
  backend: string
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

function numberTriple(v: unknown, field: string): [number, number, number] {
  if (
    Array.isArray(v) &&
    v.length === 3 &&
    v.every((n) => typeof n === "number")
  ) {
    return [v[0], v[1], v[2]]
  }
  throw new Error(`${META_KEY}: ${field} must be 3 numbers`)
}

/** Validate the `3dsdf.meta` JSON; dims and format come from the KTX2 header. */
export function parseSdfMeta(
  raw: unknown,
  dims: [number, number, number],
  format: SdfFormat
): SdfMeta {
  if (!isRecord(raw)) throw new Error(`${META_KEY}: not an object`)
  if (raw.version !== 1)
    throw new Error(`${META_KEY}: unsupported version ${String(raw.version)}`)
  if (raw.axis !== "y_up_gltf")
    throw new Error(`${META_KEY}: unsupported axis ${String(raw.axis)}`)
  if (raw.sign !== "negative_inside")
    throw new Error(`${META_KEY}: unsupported sign ${String(raw.sign)}`)
  if (typeof raw.voxelSize !== "number")
    throw new Error(`${META_KEY}: voxelSize missing`)
  const decode = raw.decode
  if (
    !isRecord(decode) ||
    typeof decode.scale !== "number" ||
    typeof decode.offset !== "number"
  ) {
    throw new Error(`${META_KEY}: decode must be { scale, offset }`)
  }
  const source = raw.source
  if (!isRecord(source)) throw new Error(`${META_KEY}: no source`)

  return {
    version: raw.version,
    dims,
    format,
    voxelSize: raw.voxelSize,
    bboxMin: new THREE.Vector3(...numberTriple(raw.bboxMin, "bboxMin")),
    bboxMax: new THREE.Vector3(...numberTriple(raw.bboxMax, "bboxMax")),
    decodeScale: decode.scale,
    decodeOffset: decode.offset,
    objectName: String(source.object),
    triangles: Number(source.triangles),
    backend: String(source.backend),
  }
}

/** Fetch `<name>.sdf.ktx2` into a linearly filtered Data3DTexture. */
export async function loadSdf(
  url: string,
  options: { zstd?: ZstdDecoder } = {}
): Promise<{ meta: SdfMeta; texture: THREE.Data3DTexture }> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
  const container = read(new Uint8Array(await res.arrayBuffer()))

  const vk = VK_FORMATS[container.vkFormat]
  if (!vk) throw new Error(`${url}: unsupported vkFormat ${container.vkFormat}`)
  const scheme = container.supercompressionScheme
  if (scheme !== SCHEME_NONE && scheme !== SCHEME_ZSTD) {
    throw new Error(
      `${url}: supercompressionScheme ${scheme} (must be 0 or 2)`
    )
  }
  if (container.pixelDepth === 0)
    throw new Error(`${url}: pixelDepth is 0 (not a 3D texture)`)
  const rawMeta = container.keyValue[META_KEY]
  if (rawMeta === undefined) throw new Error(`${url}: no ${META_KEY} key/value`)
  const metaText =
    typeof rawMeta === "string"
      ? rawMeta
      : new TextDecoder().decode(rawMeta).replace(/\0$/, "")

  const dims: [number, number, number] = [
    container.pixelWidth,
    container.pixelHeight,
    container.pixelDepth,
  ]
  const meta = parseSdfMeta(JSON.parse(metaText), dims, vk.format)

  const level = container.levels[0]
  let bytes: Uint8Array
  if (scheme === SCHEME_ZSTD) {
    if (!options.zstd)
      throw new Error(`${url}: zstd-compressed (scheme 2) but no zstd decoder was given`)
    bytes = options.zstd(level.levelData, level.uncompressedByteLength)
    if (bytes.byteLength !== level.uncompressedByteLength)
      throw new Error(
        `${url}: zstd level decoded to ${bytes.byteLength} bytes, expected ${level.uncompressedByteLength}`
      )
    // A decoder may return a view into a larger buffer; the typed arrays below need offset 0.
    if (bytes.byteOffset !== 0 || bytes.buffer.byteLength !== bytes.byteLength) bytes = bytes.slice()
  } else {
    // levelData is a view into the file; copy so the typed array starts on an aligned offset.
    bytes = level.levelData.slice()
  }
  const data =
    vk.format === "r8"
      ? bytes
      : vk.format === "r16f"
        ? new Uint16Array(bytes.buffer)
        : new Float32Array(bytes.buffer)
  const [nx, ny, nz] = dims
  if (data.length !== nx * ny * nz)
    throw new Error(
      `${url}: expected ${nx * ny * nz} voxels, got ${data.length}`
    )

  // Level 0 is x fastest, then y, then z: exactly width/height/depth order.
  const texture = new THREE.Data3DTexture(data, nx, ny, nz)
  texture.format = THREE.RedFormat
  texture.type = vk.type
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.wrapS = texture.wrapT = texture.wrapR = THREE.ClampToEdgeWrapping
  texture.unpackAlignment = 1
  texture.needsUpdate = true
  return { meta, texture }
}
