# Output format (canonical)

This is the canonical definition of the files 3dsdf-texture writes. The readers — viewer-three, godot-sample and frapx (`@frapx/glsl-sdf-volume`) — all follow it. To change the format, change this document first, then update the readers.

**Stability:** while the extension is 0.x the format is not frozen. The metadata `version` stays `1` and its contents may still change; every change is listed in [CHANGELOG.md](../CHANGELOG.md). Version 1 is frozen at extension 1.0. After that, an incompatible change bumps both the format `version` and the extension's major version.

This document is licensed under MIT ([LICENSE](LICENSE)), so readers may copy from it freely.

## Files

| Target | Files | Use |
|---|---|---|
| `ktx2` | `<name>.sdf.ktx2` | Web (three.js, frapx). Self-contained; the metadata is in the key/value data |
| `godot` | `<name>.sdf.json`, `<name>.sdf.exr` / `.png`, `.import` | Slice atlas for Godot 4's Texture3D importer |

Godot cannot load non-2D KTX files (`modules/ktx/texture_loader_ktx.cpp` rejects them), so the Godot target stays an atlas.

## Value formats

| `format` | Stored value | Back to distance (`decode`) |
|---|---|---|
| `r8` | `clamp(d / band, -1, 1) * 0.5 + 0.5`, rounded to 0..255 | `{ scale: 2 * band, offset: -band }` |
| `r16f` | distance as half float | `{ scale: 1, offset: 0 }` |
| `r32f` | distance as float | `{ scale: 1, offset: 0 }` |

- Distance is `d = v * scale + offset`, where `v` is the sampled value (0..1 for r8, which samples as UNORM). Shaders need no per-format branch.
- `band = band_voxels * voxelSize`; `band_voxels` defaults to 8.
- r16f is only usable when the field fits in half range (|d| ≤ 65504). If it does not, or if the voxel size drops below the smallest normal half (6.1e-5), the writer refuses and suggests r32f. Half precision is relative, so within range the step near the surface stays around 1/1000 of a voxel.

## KTX2 (`<name>.sdf.ktx2`)

- KTX 2.0, `sgdByteLength = 0`, and `supercompressionScheme` is one of:
  - `0`: uncompressed (the default).
  - `2` (Zstandard, opt-in with *Zstd Compression* / `--zstd`): level 0 is one zstd frame. Its level index has `byteLength` = compressed size and `uncompressedByteLength` = the uncompressed level size; the header, DFD and key/value data are not compressed. It pays off mainly for `r8` (about 30% of the uncompressed size, against about 75% for `r16f` and 90% for `r32f`).
- `vkFormat` / `typeSize` is one of:

  | `vkFormat` | Format | `typeSize` | `format` |
  |---|---|---|---|
  | 9 | `R8_UNORM` | 1 | `r8` |
  | 76 | `R16_SFLOAT` | 2 | `r16f` |
  | 100 | `R32_SFLOAT` | 4 | `r32f` |

- `pixelWidth`, `pixelHeight`, `pixelDepth` hold nx, ny, nz (all ≥ 1).
- The other header values are `layerCount = 0`, `faceCount = 1`, `levelCount = 1`.
- The DFD is a basic descriptor with one sample (RED), 44 bytes in total: model RGBSDA, primaries UNSPECIFIED, transfer LINEAR. Readers need not interpret it.
- Level 0 starts on a 4-byte boundary and, once decompressed, is laid out as:
  - x fastest,
  - then y, row 0 being y min,
  - then z, slice 0 being z min.
- Key/value data holds three keys, sorted by code point, with UTF-8 values terminated by NUL; each pair is padded to 4 bytes.

  | Key | Value |
  |---|---|
  | `3dsdf.meta` | the common metadata below as one-line JSON |
  | `KTXorientation` | `ruo` (rows increase toward +y, slices toward +z; in right-handed Y-up, +z points toward the viewer) |
  | `KTXwriter` | `3dsdf-texture <version>` |

- Files pass `ktx validate` (KTX-Software 4.4.2). The only warning is `warning-7010` (custom key present), unavoidable with `3dsdf.meta`.

## Metadata

### Common part (in both `3dsdf.meta` and `.sdf.json`)

```json
{
  "version": 1,
  "bboxMin": [-1.414, -1.076, -0.906],
  "bboxMax": [1.414, 1.045, 0.950],
  "voxelSize": 0.0221,
  "units": "local",
  "axis": "y_up_gltf",
  "sign": "negative_inside",
  "decode": { "scale": 1, "offset": 0 },
  "source": { "object": "Suzanne", "triangles": 3936, "backend": "gpu" }
}
```

- `bboxMin` / `bboxMax` are the outer faces of the voxel grid. Voxel i's center is at `bboxMin + (i + 0.5) * voxelSize`. Voxels are cubic.
- `units: "local"`: coordinates are the source object's local units.
- `axis: "y_up_gltf"`: Blender's Z-up converted to glTF's Y-up.
- `sign: "negative_inside"`: distances inside the surface are negative.
- `source` is informational; readers need not interpret it.
- `source.object` is the Blender object name, unchanged (`Suzanne.001` and non-ASCII names included). File names replace `[^\w.-]` with `_`, so they may differ from it.
- To match a glb node, pass the name through your loader's naming rule: three.js `PropertyBinding.sanitizeNodeName()`, Godot `String.validate_node_name()` (e.g. `Suzanne.001 x` becomes `Suzanne001_x` in three and `Suzanne_001 x` in Godot).

### Added only to Godot's `.sdf.json`

```json
{
  "dims": [128, 96, 84],
  "format": "r16f",
  "layout": { "columns": 12, "rows": 7, "sliceOrder": "z_ascending_row_major", "row0": "y_min" },
  "files": { "godot": "Suzanne.sdf.exr" }
}
```

- Images: `r16f` is a single-channel half EXR, `r32f` a single-channel float EXR, `r8` an 8-bit grayscale PNG.
- Slice k sits in tile (row `k // columns`, column `k % columns`), with `columns * rows == dims[2]` because Godot's importer derives the depth from `columns * rows`.
- In KTX2, `dims` and `format` come from the header and are not repeated in the key/value data.

## Reader errors

Readers fail with an error naming the offending field when:

- `3dsdf.meta` `version` is not 1,
- `vkFormat` is not one of the three above,
- `supercompressionScheme` is neither 0 nor 2,
- `supercompressionScheme` is 2 and the reader has no Zstandard decoder, or the decoded level is not `uncompressedByteLength` bytes,
- `pixelDepth` is 0,
- `3dsdf.meta` is missing.
