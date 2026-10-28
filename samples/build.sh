#!/usr/bin/env bash
# Build the sample asset (Suzanne + Subdivision, open mesh with intersecting eyes)
# and bake it through the CLI into the viewer and Godot sample projects.
set -euo pipefail
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
cd "$(dirname "$0")/.."
"$BLENDER" -b --factory-startup --python-exit-code 1 --python-expr '
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_monkey_add()
obj = bpy.context.object
obj.modifiers.new("Subdiv", "SUBSURF").levels = 1
bpy.ops.object.shade_smooth()
bpy.ops.export_scene.gltf(filepath="samples/suzanne.glb", export_format="GLB", use_selection=True, export_apply=True)
'
for fmt in r16f r32f r8; do
  "$BLENDER" -b --factory-startup --python-exit-code 1 --python scripts/bake_cli.py -- \
    --input samples/suzanne.glb --out "samples/out/$fmt" --format "$fmt"
done
mkdir -p godot-sample/sdf
mkdir -p viewer-three/public/sdf
cp samples/suzanne.glb viewer-three/public/sdf/
for fmt in r16f r32f r8; do
  cp "samples/out/$fmt/Suzanne.sdf.ktx2" "viewer-three/public/sdf/Suzanne.$fmt.sdf.ktx2"
done
cp samples/suzanne.glb godot-sample/sdf/
cp samples/out/r16f/Suzanne.sdf.{exr,exr.import,json} godot-sample/sdf/
