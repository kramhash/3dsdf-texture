"""Metadata shared by every target. Schema: docs/format.md.

The common part goes into the KTX2 `3dsdf.meta` key; the Godot `<name>.sdf.json`
sidecar is the common part plus what the atlas needs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..bake import BakeResult
from ..encode import ValueFormat, decode_params, tile_layout

FORMAT_VERSION = 1


def build_common(name: str, result: BakeResult, fmt: ValueFormat, band: float) -> dict[str, Any]:
    grid = result.grid
    scale, offset = decode_params(fmt, band)
    return {
        "version": FORMAT_VERSION,
        "bboxMin": grid.bbox_min.tolist(),
        "bboxMax": grid.bbox_max.tolist(),
        "voxelSize": grid.voxel_size,
        "units": "local",
        "axis": "y_up_gltf",
        "sign": "negative_inside",
        "decode": {"scale": scale, "offset": offset},
        "source": {
            "object": name,
            "triangles": result.triangle_count,
            "backend": result.backend.lower(),
        },
    }


def build_godot(common: dict[str, Any], dims: tuple[int, int, int], fmt: ValueFormat, image_name: str) -> dict[str, Any]:
    cols, rows = tile_layout(dims[2])
    return {
        **common,
        "dims": list(dims),
        "format": fmt,
        "layout": {"columns": cols, "rows": rows, "sliceOrder": "z_ascending_row_major", "row0": "y_min"},
        "files": {"godot": image_name},
    }


def write(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, indent=2) + "\n")
