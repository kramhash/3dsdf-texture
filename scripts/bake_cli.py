"""Headless entry point.

    blender -b [scene.blend] --python scripts/bake_cli.py -- --out DIR [options]

Bakes every object with geometry (mesh, curve, text, surface, metaball) in the
opened .blend (or a .glb/.gltf given with --input) unless --objects narrows the
list. A failing object is reported and skipped; the exit code is then 1.

Runs from a clone of the repository; it is not part of the extension zip.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

# Repository-side tool: import the extension's bpy-free core straight from the checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extension"))

from core.bake import BakeSettings  # noqa: E402
from core.batch import BatchBake  # noqa: E402
from core.export import ExportSettings  # noqa: E402
from core.pipeline import BAKEABLE_TYPES, NameCollisionError  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="sdf_texture", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, type=Path, help="output directory")
    p.add_argument("--input", type=Path, help=".glb/.gltf to import into an empty scene")
    p.add_argument("--objects", nargs="+", help="object names (default: all meshes)")
    p.add_argument("--resolution", type=int, default=128)
    p.add_argument("--padding", type=int, default=4)
    p.add_argument("--backend", choices=["AUTO", "GPU", "CPU"], default="AUTO")
    p.add_argument("--format", choices=["r16f", "r32f", "r8"], default="r16f")
    p.add_argument("--band-voxels", type=float, default=8.0)
    p.add_argument("--targets", default="ktx2,godot", help="comma separated: ktx2,godot")
    p.add_argument("--zstd", action="store_true", help="Zstandard-supercompress the KTX2 level data")
    return p.parse_args(argv)


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parse_args(argv)

    if args.input:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(args.input))

    candidates = [o for o in bpy.context.scene.objects if o.type in BAKEABLE_TYPES]
    if args.objects:
        by_name = {o.name: o for o in candidates}
        missing = [n for n in args.objects if n not in by_name]
        if missing:
            print(f"error: no objects with geometry named {missing}", file=sys.stderr)
            return 2
        candidates = [by_name[n] for n in args.objects]
    if not candidates:
        print("error: no objects to bake", file=sys.stderr)
        return 2

    targets = frozenset(t.strip() for t in args.targets.split(",") if t.strip())
    unknown = targets - {"ktx2", "godot"}
    if unknown or not targets:
        print(f"error: bad --targets {args.targets!r}", file=sys.stderr)
        return 2

    def report(level: str, message: str) -> None:
        if level == "INFO":
            print(message)
        else:
            print(f"{level.lower()}: {message}", file=sys.stderr)

    try:
        batch = BatchBake(
            candidates,
            bpy.context.evaluated_depsgraph_get,
            BakeSettings(resolution=args.resolution, padding=args.padding, backend=args.backend),
            ExportSettings(value_format=args.format, band_voxels=args.band_voxels, targets=targets, ktx2_zstd=args.zstd),
            args.out,
            report,
        )
    except NameCollisionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    while not batch.advance(1.0):
        pass
    level, message = batch.summary()
    report(level, message)
    return 1 if batch.failed else 0


sys.exit(main())
