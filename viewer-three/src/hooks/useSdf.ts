import { decompress } from "fzstd"
import { useEffect, useState } from "react"
import type * as THREE from "three"
import { loadSdf, type SdfMeta, type ZstdDecoder } from "@/lib/sdf"

const zstd: ZstdDecoder = (bytes, size) => decompress(bytes, new Uint8Array(size))

export type SdfState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; meta: SdfMeta; texture: THREE.Data3DTexture }

export function useSdf(url: string): SdfState {
  const [state, setState] = useState<SdfState>({ status: "loading" })

  useEffect(() => {
    let cancelled = false
    let texture: THREE.Data3DTexture | null = null
    setState({ status: "loading" })
    loadSdf(url, { zstd }).then(
      (loaded) => {
        texture = loaded.texture
        if (cancelled) {
          texture.dispose()
          return
        }
        setState({ status: "ready", ...loaded })
      },
      (err: unknown) => {
        if (!cancelled)
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          })
      }
    )
    return () => {
      cancelled = true
      texture?.dispose()
    }
  }, [url])

  return state
}
