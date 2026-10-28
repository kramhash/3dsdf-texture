"""CPU fallback: BVHTree distances with a ray-parity vote for the sign.

The sign gets 7 votes per voxel: inside/outside parity from rays along +x, -x,
+y, -y, +z, -z, plus the side of the nearest face. Rays run along whole grid
lines so each line costs one batch of ray casts instead of one per voxel.
This is weaker than the GPU winding number on meshes with holes, but a single
hole only spoils the votes of rays that pass through it.
"""

from __future__ import annotations

from collections.abc import Generator

import numpy as np

from .grid import Grid

# Small irrational-ish offsets keep grid lines off mesh edges and face planes.
_JITTER = (0.01371, 0.02913)


def compute_steps(tris: np.ndarray, grid: Grid) -> Generator[float, None, np.ndarray]:
    """Yield progress after each z slice and each row of ray lines; return the distance field."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    verts = tris.reshape(-1, 3).astype(np.float64)
    polys = np.arange(len(verts), dtype=np.int64).reshape(-1, 3)
    bvh = BVHTree.FromPolygons(verts.tolist(), polys.tolist(), all_triangles=True, epsilon=0.0)

    nz, ny, nx = grid.shape
    xs, ys, zs = (grid.axis_centers(a) for a in range(3))

    distance = np.empty(grid.shape, dtype=np.float32)
    votes = np.zeros(grid.shape, dtype=np.int8)

    # Nearest-face distance and the normal vote.
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                p = Vector((xs[i], ys[j], zs[k]))
                loc, normal, _index, dist = bvh.find_nearest(p)
                distance[k, j, i] = dist
                if (p - loc).dot(normal) < 0.0:
                    votes[k, j, i] += 1
        yield 0.5 * (k + 1) / nz

    # Parity votes along each axis.
    centers = (xs, ys, zs)
    step = grid.voxel_size * 1e-4
    far = float(np.max(grid.bbox_max - grid.bbox_min)) * 4.0
    for axis in range(3):
        b, c = [a for a in range(3) if a != axis]
        start_coord = grid.bbox_min[axis] - grid.voxel_size
        line_coords = centers[axis]
        direction = Vector(tuple(1.0 if a == axis else 0.0 for a in range(3)))
        for jb, cb in enumerate(centers[b]):
            for jc, cc in enumerate(centers[c]):
                origin = [0.0, 0.0, 0.0]
                origin[axis] = start_coord
                origin[b] = cb + grid.voxel_size * _JITTER[0]
                origin[c] = cc + grid.voxel_size * _JITTER[1]
                hits = _all_hits(bvh, Vector(origin), direction, axis, far, step)
                before = np.searchsorted(np.asarray(hits), line_coords) if hits else np.zeros(len(line_coords), int)
                after = len(hits) - before
                line_votes = (before & 1) + (after & 1)
                _add_line(votes, axis, b, c, jb, jc, line_votes)
            yield 0.5 + 0.5 * (axis + (jb + 1) / len(centers[b])) / 3

    inside = votes >= 4
    distance[inside] *= -1.0
    return distance


def _all_hits(bvh, origin, direction, axis: int, far: float, step: float) -> list[float]:
    hits: list[float] = []
    start = origin.copy()
    remaining = far
    while remaining > 0.0:
        loc, _normal, _index, dist = bvh.ray_cast(start, direction, remaining)
        if loc is None:
            break
        hits.append(loc[axis])
        start = loc + direction * step
        remaining -= dist + step
    return hits


def _add_line(votes: np.ndarray, axis: int, b: int, c: int, jb: int, jc: int, line_votes: np.ndarray) -> None:
    # votes is indexed [z, y, x]; map axis numbers (x=0, y=1, z=2) to array dims.
    index: list[slice | int] = [slice(None)] * 3
    index[2 - b] = jb
    index[2 - c] = jc
    votes[tuple(index)] += line_votes.astype(np.int8)
