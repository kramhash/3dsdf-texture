"""Turn Blender mesh data into a flat triangle array in the glTF Y-up frame.

Only duck-typed mesh / object access is used here, so this module does not import bpy.
"""

from __future__ import annotations

import numpy as np


def to_y_up(points: np.ndarray) -> np.ndarray:
    """Blender Z-up (x, y, z) -> glTF Y-up (x, z, -y), same as the glTF exporter."""
    return np.stack([points[..., 0], points[..., 2], -points[..., 1]], axis=-1)


def triangles_from_mesh(mesh) -> np.ndarray:
    """Return a (T, 3, 3) float32 array of triangle corners in Y-up local space."""
    mesh.calc_loop_triangles()
    nv = len(mesh.vertices)
    nt = len(mesh.loop_triangles)
    if nt == 0:
        return np.zeros((0, 3, 3), dtype=np.float32)

    co = np.empty(nv * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    idx = np.empty(nt * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", idx)

    verts = to_y_up(co.reshape(-1, 3))
    return np.ascontiguousarray(verts[idx.reshape(-1, 3)], dtype=np.float32)


def triangles_from_object(obj, depsgraph) -> np.ndarray:
    """Triangles of the evaluated (modifiers applied) mesh, in object-local space."""
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        return triangles_from_mesh(mesh)
    finally:
        obj_eval.to_mesh_clear()
