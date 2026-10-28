// three ships ktx-parse without types; only the parts the SDF loader reads.
declare module "three/examples/jsm/libs/ktx-parse.module.js" {
  export interface KTX2Level {
    levelData: Uint8Array
    uncompressedByteLength: number
  }

  export interface KTX2Container {
    vkFormat: number
    typeSize: number
    pixelWidth: number
    pixelHeight: number
    pixelDepth: number
    layerCount: number
    faceCount: number
    supercompressionScheme: number
    levels: KTX2Level[]
    // Keys starting with "KTX" are decoded to strings; custom keys stay raw bytes (NUL included).
    keyValue: Record<string, string | Uint8Array>
  }

  export function read(data: Uint8Array): KTX2Container
}
