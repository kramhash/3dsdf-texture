"""Quantize distances and lay slices out as a 2D tile atlas."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

ValueFormat = Literal["r8", "r16f", "r32f"]


def quantize(distance: np.ndarray, fmt: ValueFormat, band: float) -> np.ndarray:
    """r16f/r32f: raw distance. r8: clamp to +-band, map to 0..255 (128 ~ surface)."""
    if fmt == "r16f":
        return distance.astype(np.float16)
    if fmt == "r32f":
        return distance.astype(np.float32)
    if fmt == "r8":
        normalized = np.clip(distance / band, -1.0, 1.0) * 0.5 + 0.5
        return np.round(normalized * 255.0).astype(np.uint8)
    raise ValueError(f"unknown value format {fmt!r}")


HALF_MAX = 65504.0
HALF_MIN_NORMAL = 6.103515625e-05


def check_r16f(distance: np.ndarray, voxel_size: float) -> None:
    """Refuse fields that half floats cannot hold.

    Half precision is relative, so near the surface it is always ~1/1000 voxel;
    it only breaks when distances overflow or the voxel drops into subnormals.
    """
    peak = float(np.abs(distance).max())
    if peak > HALF_MAX:
        raise ValueError(f"r16f overflows: distances reach {peak:.6g} (max {HALF_MAX:g}); use r32f")
    if voxel_size < HALF_MIN_NORMAL:
        raise ValueError(f"r16f loses precision: voxel size {voxel_size:.3g} is below {HALF_MIN_NORMAL:.3g}; use r32f")


def dequantize(values: np.ndarray, fmt: ValueFormat, band: float) -> np.ndarray:
    if fmt in ("r16f", "r32f"):
        return values.astype(np.float32)
    if fmt == "r8":
        return (values.astype(np.float32) / 255.0 * 2.0 - 1.0) * band
    raise ValueError(f"unknown value format {fmt!r}")


def decode_params(fmt: ValueFormat, band: float) -> tuple[float, float]:
    """(scale, offset) such that distance = v * scale + offset, v being the sampled texel.

    r8 samples as UNORM, so v is already 0..1 there.
    """
    if fmt == "r8":
        return 2.0 * band, -band
    return 1.0, 0.0


def tile_layout(depth: int) -> tuple[int, int]:
    """(columns, rows) with columns * rows == depth, as square as possible.

    Godot's Texture3D importer derives the depth from columns * rows, so the
    grid must divide exactly; empty filler slices would change the depth.
    """
    rows = 1
    for r in range(1, math.isqrt(depth) + 1):
        if depth % r == 0:
            rows = r
    return depth // rows, rows


def tile(field: np.ndarray) -> tuple[np.ndarray, int, int]:
    """Arrange [z, y, x] slices into an atlas, slice k at (row k // cols, col k % cols).

    Image row 0 is the top row and holds y index 0 (bbox min), matching how
    Godot and Three.js map the first data row to v = 0.
    """
    nz, ny, nx = field.shape
    cols, rows = tile_layout(nz)
    atlas = field.reshape(rows, cols, ny, nx).transpose(0, 2, 1, 3).reshape(rows * ny, cols * nx)
    return np.ascontiguousarray(atlas), cols, rows


def untile(atlas: np.ndarray, cols: int, rows: int, ny: int, nx: int) -> np.ndarray:
    return atlas.reshape(rows, ny, cols, nx).transpose(0, 2, 1, 3).reshape(rows * cols, ny, nx)
