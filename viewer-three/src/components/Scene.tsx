import { useGLTF } from "@react-three/drei"
import { createPortal, useThree } from "@react-three/fiber"
import { useEffect, useMemo } from "react"
import * as THREE from "three"
import { SdfVolume } from "@/components/SdfVolume"
import type { SdfMeta } from "@/lib/sdf"

export type ViewMode = "sdf" | "mesh" | "both"

interface SceneProps {
  glbUrl: string
  meta: SdfMeta
  texture: THREE.Data3DTexture
  mode: ViewMode
  onReady: () => void
}

const LIGHT_DIR = new THREE.Vector3(0.43, 0.5, 0.75)

export function Scene({ glbUrl, meta, texture, mode, onReady }: SceneProps) {
  const gltf = useGLTF(glbUrl)
  const invalidate = useThree((s) => s.invalidate)

  // The SDF is in the source mesh's local space, so the volume is parented to that mesh.
  // source.object is the Blender name; GLTFLoader sanitizes node names the same way.
  const target = useMemo(() => {
    const nodeName = THREE.PropertyBinding.sanitizeNodeName(meta.objectName)
    const found = gltf.scene.getObjectByName(nodeName)
    if (!found) throw new Error(`glb has no object named ${meta.objectName} (node ${nodeName})`)
    return found
  }, [gltf, meta.objectName])

  // Plain white material so the mesh and the SDF are easy to tell apart.
  const meshMaterial = useMemo(() => new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 }), [])
  useEffect(() => () => meshMaterial.dispose(), [meshMaterial])

  useEffect(() => {
    if (target instanceof THREE.Mesh) {
      target.material = meshMaterial
      meshMaterial.visible = mode !== "sdf"
    }
    invalidate()
    const id = requestAnimationFrame(() => requestAnimationFrame(onReady))
    return () => cancelAnimationFrame(id)
  }, [mode, target, meshMaterial, invalidate, onReady])

  return (
    <>
      <primitive object={gltf.scene} />
      {mode !== "mesh" &&
        createPortal(
          <group>
            <SdfVolume meta={meta} texture={texture} lightDir={LIGHT_DIR} />
          </group>,
          target,
        )}
      <ambientLight intensity={0.6} />
      <directionalLight position={LIGHT_DIR.clone().multiplyScalar(4)} intensity={2.2} />
    </>
  )
}
