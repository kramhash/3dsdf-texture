# Changelog

The format is not frozen while the version is 0.x; format changes are marked **Format**.

## 0.1.0

First public release.

- Bake meshes, curves, text, surfaces and metaballs into 3D SDF textures (GPU generalized winding number, CPU fallback).
- **Format**: 3D KTX2 (`R8_UNORM` / `R16_SFLOAT` / `R32_SFLOAT`) with `3dsdf.meta`, `KTXorientation` and `KTXwriter` key/values, uncompressed by default or Zstandard-supercompressed (`supercompressionScheme = 2`) with *Zstd Compression* / `--zstd`; Godot slice atlas with a `.sdf.json` sidecar sharing the same camelCase schema. See [docs/format.md](docs/format.md).
- Modal bake with Esc to cancel; failing objects are skipped and reported by name.
- The panel shows the selection's triangle count before baking, replaces the bake button with a progress bar and time estimate while baking, and keeps the last result (with a button to open the output folder) until the next bake.
- Re-exporting the Godot target keeps an existing `.import` and only updates its slice counts, so the resource uid survives.
- Refuses file-name collisions, unsaved-relative output paths and r16f overflow.
- CLI at `scripts/bake_cli.py` (repository only).
- viewer-three (three.js) and godot-sample read the output; viewer-three decompresses Zstandard with `fzstd`.
