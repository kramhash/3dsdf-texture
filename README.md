# 3dsdf-texture

A Blender 5.2 extension that bakes meshes into 3D signed distance field textures, written for the SDF volume feature of [frapx](https://github.com/kramhash/frapx) and also readable from three.js and Godot 4.

[日本語](README.ja.md)

- Bakes each selected mesh, curve, text, surface or metaball (modifiers applied) in its local space, converted to glTF's Y-up so it lines up with an exported glb.
- GPU (generalized winding number) or CPU fallback; the GPU sign stays correct on open meshes.
- Writes an uncompressed 3D KTX2 (R8 / R16F / R32F) with its metadata inside, plus a slice atlas for Godot.

## Install

Download `sdf_texture-<version>.zip` from [Releases](https://github.com/kramhash/3dsdf-texture/releases) and drag it into Blender, or use *Preferences → Get Extensions → Install from Disk*. Requires Blender 5.2 or later. Updates are manual: install the newer zip over the old one.

## Usage

**UI**: 3D Viewport → N panel → *SDF*. Pick resolution, format and targets, then *Bake SDF Texture*.

- Baking runs in the background with progress in the status bar; Esc cancels and keeps the objects already finished.
- An object that fails is reported by name and the rest keep baking. Types without geometry are skipped with a warning.
- The default output `//sdf/` is relative to the .blend, so save the file first or choose an absolute folder.
- Selections whose file names would collide (`Cube 1` / `Cube_1`, `Cube` / `cube`) are refused before baking. Existing files are overwritten.

**CLI** (from a clone of this repository; exits 1 if any object failed):

```sh
blender -b scene.blend --python scripts/bake_cli.py -- --out out/ \
  [--input model.glb] [--objects A B] [--resolution 128] [--padding 4] \
  [--format r16f|r32f|r8] [--band-voxels 8] [--targets ktx2,godot] [--backend AUTO|GPU|CPU]
```

## Output

| Target | Files |
|---|---|
| `ktx2` | `<name>.sdf.ktx2` — metadata in the `3dsdf.meta` key/value entry |
| `godot` | `<name>.sdf.json`, `<name>.sdf.exr` or `.png` (slice atlas), `.import` (Texture3D import settings) |

Distances are negative inside. The full layout, metadata schema and decode rule are in [docs/format.md](docs/format.md).

## Readers

- **frapx**: `@frapx/glsl-sdf-volume` (planned for fx-canvas 1.1).
- **three.js**: [viewer-three](viewer-three/) reads the KTX2 with three's bundled `ktx-parse` into a `Data3DTexture` and sphere-traces it (`pnpm dev`, `?sdf=...&glb=...&mode=sdf|mesh|both`).
- **Godot 4**: [godot-sample](godot-sample/) imports the atlas as a `Texture3D` and ray-marches it (keys 1/2/3 switch views).

## Development

- `tests/run.sh [--timing]` — headless numeric tests (GPU tests need a GPU; developed on Apple Silicon / Metal).
- `samples/build.sh` — bakes the Suzanne sample into the viewer and the Godot sample.
- `scripts/release.sh <version> [--publish]` — release checks and the GitHub release.

## License

| Path | License |
|---|---|
| `extension/`, `tests/` | GPL-3.0-or-later ([LICENSE](LICENSE)) — required for Blender add-ons |
| `docs/`, `viewer-three/`, `godot-sample/`, `samples/`, `scripts/` | MIT (each directory's `LICENSE`) — so readers can reuse the format spec and sample code freely |

## Roadmap

1.0 freezes format version 1. It ships when:

1. frapx `@frapx/glsl-sdf-volume` reads these KTX2 files and its `examples/vite-sdf-volume` runs, and
2. the tool has been used for at least one real project.

Until then (0.x) the format may still change; see [CHANGELOG.md](CHANGELOG.md). The extension is distributed through GitHub Releases only; a listing on extensions.blender.org will be considered if there is outside demand.
