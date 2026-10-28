"""Voxel grid definition shared by the backends and writers.

All coordinates are object-local and already converted to the glTF Y-up frame.
Arrays sampled on a grid are indexed [z, y, x] so that x varies fastest in memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Each axis is rounded up to a multiple of this so GPU work groups tile evenly
# and the slice count factors into a reasonable tile layout.
DIM_ALIGN = 4


@dataclass(frozen=True)
class Grid:
    dims: tuple[int, int, int]  # (nx, ny, nz)
    voxel_size: float
    origin: tuple[float, float, float]  # bbox min corner

    @property
    def shape(self) -> tuple[int, int, int]:
        """numpy shape of a sampled field: (nz, ny, nx)."""
        nx, ny, nz = self.dims
        return (nz, ny, nx)

    @property
    def bbox_min(self) -> np.ndarray:
        return np.asarray(self.origin, dtype=np.float64)

    @property
    def bbox_max(self) -> np.ndarray:
        return self.bbox_min + np.asarray(self.dims, dtype=np.float64) * self.voxel_size

    def axis_centers(self, axis: int) -> np.ndarray:
        """Voxel-center coordinates along one axis (0=x, 1=y, 2=z)."""
        n = self.dims[axis]
        return self.origin[axis] + (np.arange(n, dtype=np.float64) + 0.5) * self.voxel_size


def fit_grid(vmin: np.ndarray, vmax: np.ndarray, resolution: int, padding: int) -> Grid:
    """Fit a cubic-voxel grid around a bbox.

    The longest bbox edge plus `padding` voxels on each side spans `resolution`
    voxels; the other axes use the same voxel size and stay centered.
    """
    inner = resolution - 2 * padding
    if inner < 1:
        raise ValueError(f"resolution {resolution} leaves no room inside padding {padding}")

    vmin = np.asarray(vmin, dtype=np.float64)
    vmax = np.asarray(vmax, dtype=np.float64)
    extent = vmax - vmin
    longest = float(extent.max())
    if longest <= 0.0:
        raise ValueError("mesh has an empty bounding box")

    voxel = longest / inner
    dims = []
    for e in extent:
        n = math.ceil(e / voxel - 1e-9) + 2 * padding
        n = max(DIM_ALIGN, math.ceil(n / DIM_ALIGN) * DIM_ALIGN)
        dims.append(n)

    center = (vmin + vmax) * 0.5
    origin = center - np.asarray(dims, dtype=np.float64) * voxel * 0.5
    return Grid(dims=(dims[0], dims[1], dims[2]), voxel_size=voxel, origin=tuple(float(v) for v in origin))
