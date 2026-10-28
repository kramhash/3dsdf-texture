"""GPU backend: brute-force distance and generalized winding number per voxel.

Every voxel walks every triangle, taking the minimum unsigned distance and
summing the signed solid angle. |winding| > 0.5 means inside, so globally
flipped normals still give the right sign. Triangles go to the shader as an
RGBA32F texture (3 texels per triangle).

The grid is split into tiles so one dispatch stays short (driver watchdogs
reset the GPU on long dispatches). Each tile writes its own R32F 3D image and
is read back right away: dispatch is asynchronous, and reading the image the
dispatch wrote is what waits for it, so progress reflects finished work.
"""

from __future__ import annotations

from collections.abc import Generator

import numpy as np

from .grid import Grid

TRIS_PER_ROW = 1024
# Upper bound on voxel x triangle pairs per dispatch, so one dispatch stays short.
WORK_PER_DISPATCH = 500_000_000
LOCAL_SIZE = 4

_COMPUTE_SRC = """
float dot2(vec3 v) { return dot(v, v); }

// Squared unsigned distance from p to triangle abc (Inigo Quilez).
float tri_dist2(vec3 p, vec3 a, vec3 b, vec3 c)
{
  vec3 ba = b - a; vec3 pa = p - a;
  vec3 cb = c - b; vec3 pb = p - b;
  vec3 ac = a - c; vec3 pc = p - c;
  vec3 nor = cross(ba, ac);
  bool outside = sign(dot(cross(ba, nor), pa)) +
                 sign(dot(cross(cb, nor), pb)) +
                 sign(dot(cross(ac, nor), pc)) < 2.0;
  if (outside) {
    return min(min(
      dot2(ba * clamp(dot(ba, pa) / dot2(ba), 0.0, 1.0) - pa),
      dot2(cb * clamp(dot(cb, pb) / dot2(cb), 0.0, 1.0) - pb)),
      dot2(ac * clamp(dot(ac, pc) / dot2(ac), 0.0, 1.0) - pc));
  }
  return dot(nor, pa) * dot(nor, pa) / dot2(nor);
}

// Signed solid angle of triangle abc seen from p (Van Oosterom & Strackee).
float solid_angle(vec3 p, vec3 a, vec3 b, vec3 c)
{
  vec3 x = a - p; vec3 y = b - p; vec3 z = c - p;
  float lx = length(x); float ly = length(y); float lz = length(z);
  float num = dot(x, cross(y, z));
  float den = lx * ly * lz + dot(x, y) * lz + dot(y, z) * lx + dot(z, x) * ly;
  if (num == 0.0 && den == 0.0) {
    return 0.0;
  }
  return 2.0 * atan(num, den);
}

void main()
{
  ivec3 local = ivec3(gl_GlobalInvocationID);
  if (any(greaterThanEqual(local, imageSize(sdf)))) {
    return;
  }
  vec3 p = origin + (vec3(local + tile_offset) + 0.5) * voxel_size;

  float best = 3.4e38;
  float winding = 0.0;
  for (int i = 0; i < tri_count; i++) {
    int col = (i % tris_per_row) * 3;
    int row = i / tris_per_row;
    vec3 a = texelFetch(tris, ivec2(col, row), 0).xyz;
    vec3 b = texelFetch(tris, ivec2(col + 1, row), 0).xyz;
    vec3 c = texelFetch(tris, ivec2(col + 2, row), 0).xyz;
    best = min(best, tri_dist2(p, a, b, c));
    winding += solid_angle(p, a, b, c);
  }
  winding /= 4.0 * 3.14159265358979;
  float d = sqrt(best);
  imageStore(sdf, local, vec4(abs(winding) > 0.5 ? -d : d));
}
"""

_shader = None


def ensure_context() -> None:
    """Create a GPU context when running headless; no-op inside the UI."""
    import bpy
    import gpu

    if bpy.app.background:
        gpu.init()


def _get_shader():
    global _shader
    if _shader is None:
        import gpu

        info = gpu.types.GPUShaderCreateInfo()
        info.image(0, "R32F", "FLOAT_3D", "sdf", qualifiers={"WRITE"})
        info.sampler(0, "FLOAT_2D", "tris")
        info.push_constant("VEC3", "origin")
        info.push_constant("FLOAT", "voxel_size")
        info.push_constant("INT", "tri_count")
        info.push_constant("INT", "tris_per_row")
        info.push_constant("IVEC3", "tile_offset")
        info.local_group_size(LOCAL_SIZE, LOCAL_SIZE, LOCAL_SIZE)
        info.compute_source(_COMPUTE_SRC)
        _shader = gpu.shader.create_from_info(info)
    return _shader


def _triangle_texture(tris: np.ndarray):
    import gpu

    count = len(tris)
    rows = max(1, -(-count // TRIS_PER_ROW))
    texels = np.zeros((rows, TRIS_PER_ROW * 3, 4), dtype=np.float32)
    flat = texels.reshape(-1, 4)
    flat[: count * 3, :3] = tris.reshape(-1, 3)
    buf = gpu.types.Buffer("FLOAT", texels.size, texels.ravel())
    return gpu.types.GPUTexture((TRIS_PER_ROW * 3, rows), format="RGBA32F", data=buf)


def tile_size(dims: tuple[int, int, int], tri_count: int, work_limit: int = WORK_PER_DISPATCH) -> tuple[int, int, int]:
    """Largest (tx, ty, tz) with tx * ty * tz * tri_count <= work_limit.

    Splits z first, then y, then x; sizes stay multiples of LOCAL_SIZE (dims are
    already aligned) and never go below one work group.
    """
    nx, ny, nz = dims
    budget = max(LOCAL_SIZE**3, work_limit // max(1, tri_count))

    def fit(n: int, area: int) -> int:
        return max(LOCAL_SIZE, min(n, budget // area // LOCAL_SIZE * LOCAL_SIZE))

    if nx * ny * LOCAL_SIZE <= budget:
        return nx, ny, fit(nz, nx * ny)
    if nx * LOCAL_SIZE * LOCAL_SIZE <= budget:
        return nx, fit(ny, nx * LOCAL_SIZE), LOCAL_SIZE
    return fit(nx, LOCAL_SIZE * LOCAL_SIZE), LOCAL_SIZE, LOCAL_SIZE


def compute_steps(
    tris: np.ndarray, grid: Grid, work_limit: int = WORK_PER_DISPATCH
) -> Generator[float, None, np.ndarray]:
    """Yield progress after each finished tile; return the distance field.

    State is rebound per tile because the UI may draw (and bind other shaders)
    between steps.
    """
    import gpu

    ensure_context()
    shader = _get_shader()
    tri_tex = _triangle_texture(tris)
    nx, ny, nz = grid.dims
    tx, ty, tz = tile_size(grid.dims, len(tris), work_limit)
    tiles = [(x0, y0, z0) for z0 in range(0, nz, tz) for y0 in range(0, ny, ty) for x0 in range(0, nx, tx)]

    distance = np.empty(grid.shape, dtype=np.float32)
    for done, (x0, y0, z0) in enumerate(tiles, start=1):
        sx, sy, sz = min(tx, nx - x0), min(ty, ny - y0), min(tz, nz - z0)
        out = gpu.types.GPUTexture((sx, sy, sz), format="R32F")
        shader.bind()
        shader.image("sdf", out)
        shader.uniform_sampler("tris", tri_tex)
        shader.uniform_float("origin", grid.origin)
        shader.uniform_float("voxel_size", grid.voxel_size)
        shader.uniform_int("tri_count", len(tris))
        shader.uniform_int("tris_per_row", TRIS_PER_ROW)
        shader.uniform_int("tile_offset", (x0, y0, z0))
        gpu.compute.dispatch(shader, -(-sx // LOCAL_SIZE), -(-sy // LOCAL_SIZE), -(-sz // LOCAL_SIZE))
        block = np.frombuffer(out.read(), dtype=np.float32).reshape(sz, sy, sx)
        distance[z0 : z0 + sz, y0 : y0 + sy, x0 : x0 + sx] = block
        yield done / len(tiles)
    return distance
