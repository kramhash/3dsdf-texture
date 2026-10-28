# Changelog

The format is not frozen while the version is 0.x; format changes are marked **Format**.

## 0.1.0

First public release.

- Bake meshes, curves, text, surfaces and metaballs into 3D SDF textures (GPU generalized winding number, CPU fallback).
- **Format**: uncompressed 3D KTX2 (`R8_UNORM` / `R16_SFLOAT` / `R32_SFLOAT`) with `3dsdf.meta`, `KTXorientation` and `KTXwriter` key/values; Godot slice atlas with a `.sdf.json` sidecar sharing the same camelCase schema. See [docs/format.md](docs/format.md).
- Modal bake with progress and Esc to cancel; failing objects are skipped and reported by name.
- Refuses file-name collisions, unsaved-relative output paths and r16f overflow.
- CLI at `scripts/bake_cli.py` (repository only).
