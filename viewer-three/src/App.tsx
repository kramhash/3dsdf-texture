import { OrbitControls } from "@react-three/drei"
import { Canvas } from "@react-three/fiber"
import { Suspense, useCallback, useEffect, useState } from "react"
import * as THREE from "three"
import { Scene, type ViewMode } from "@/components/Scene"
import { useSdf } from "@/hooks/useSdf"

// URL params: ?sdf=/sdf/Suzanne.r16f.sdf.ktx2&glb=/sdf/suzanne.glb&mode=sdf|mesh|both
const params = new URLSearchParams(window.location.search)
const SDF_URL = params.get("sdf") ?? "/sdf/Suzanne.r16f.sdf.ktx2"
const GLB_URL = params.get("glb") ?? "/sdf/suzanne.glb"
const MODES: ViewMode[] = ["sdf", "mesh", "both"]

function initialMode(): ViewMode {
  const m = params.get("mode")
  return MODES.find((x) => x === m) ?? "both"
}

export default function App() {
  const sdf = useSdf(SDF_URL)
  const [mode, setMode] = useState<ViewMode>(initialMode)
  const [ready, setReady] = useState(false)
  const handleReady = useCallback(() => setReady(true), [])
  // r32f needs OES_texture_float_linear for linear filtering; without it the
  // texture is incomplete and samples as 0, so fall back to nearest.
  const [floatLinear, setFloatLinear] = useState<boolean | null>(null)
  const nearest = sdf.status === "ready" && sdf.meta.format === "r32f" && floatLinear === false

  useEffect(() => {
    if (sdf.status !== "ready") return
    const filter = nearest ? THREE.NearestFilter : THREE.LinearFilter
    sdf.texture.minFilter = filter
    sdf.texture.magFilter = filter
    sdf.texture.needsUpdate = true
  }, [sdf, nearest])

  return (
    <div
      className="relative h-dvh w-full bg-[#1a1a1f] text-sm text-neutral-200"
      data-ready={ready}
    >
      {sdf.status === "ready" && (
        <Canvas
          camera={{ position: [1.3, 0.6, 3.6], fov: 45 }}
          gl={{ antialias: true }}
          onCreated={({ gl }) => setFloatLinear(gl.extensions.has("OES_texture_float_linear"))}
        >
          <color attach="background" args={["#1a1a1f"]} />
          <Suspense fallback={null}>
            <Scene
              glbUrl={GLB_URL}
              meta={sdf.meta}
              texture={sdf.texture}
              mode={mode}
              onReady={handleReady}
            />
          </Suspense>
          <OrbitControls makeDefault target={[0, 0, 0]} />
        </Canvas>
      )}

      <div className="absolute top-3 left-3 flex flex-col gap-2" data-hud>
        <div className="flex gap-1">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`rounded px-3 py-1 ${m === mode ? "bg-neutral-200 text-neutral-900" : "bg-neutral-800 hover:bg-neutral-700"}`}
            >
              {m}
            </button>
          ))}
        </div>
        {sdf.status === "loading" && <p>loading…</p>}
        {sdf.status === "error" && (
          <p className="text-red-400">{sdf.message}</p>
        )}
        {sdf.status === "ready" && (
          <p className="font-mono text-xs text-neutral-400">
            {sdf.meta.objectName} {sdf.meta.dims.join("×")} {sdf.meta.format} ·{" "}
            {sdf.meta.triangles} tris · {sdf.meta.backend}
            {nearest && <span className="text-amber-400"> · r32f: nearest</span>}
          </p>
        )}
      </div>
    </div>
  )
}
