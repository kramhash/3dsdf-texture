"""Headless numeric tests. Run through tests/run.sh (blender -b --factory-startup).

Pass `-- --timing` to also time 128^3 and 256^3 bakes.
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "extension"))

from core import encode, gpu_backend  # noqa: E402
from core.bake import BakeSettings, bake, bake_steps  # noqa: E402
from core.batch import BatchBake  # noqa: E402
from core.export import ExportSettings, export  # noqa: E402
from core.mesh_extract import triangles_from_object  # noqa: E402
from core.pipeline import NameCollisionError, plan_outputs  # noqa: E402
from core.writers.image_files import read_exr, read_png_gray8  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# --- scene helpers -------------------------------------------------------------


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mesh_object(name: str, build) -> bpy.types.Object:
    """Create an object whose mesh is filled by build(bm)."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def tris_of(obj) -> np.ndarray:
    return triangles_from_object(obj, bpy.context.evaluated_depsgraph_get())


def sphere(bm, radius=1.0, segments=64, rings=32):
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)


def centers(grid) -> np.ndarray:
    zs, ys, xs = (grid.axis_centers(a) for a in (2, 1, 0))
    z, y, x = np.meshgrid(zs, ys, xs, indexing="ij")
    return np.stack([x, y, z], axis=-1)


# --- tests ---------------------------------------------------------------------


@test
def sphere_matches_analytic():
    reset_scene()
    obj = mesh_object("Sphere", sphere)
    tris = tris_of(obj)
    for backend in ("GPU", "CPU"):
        r = bake(tris, BakeSettings(resolution=48, padding=4, backend=backend))
        assert r.backend == backend
        expected = np.linalg.norm(centers(r.grid), axis=-1) - 1.0
        err = np.abs(r.distance - expected).max()
        assert err <= r.grid.voxel_size, f"{backend}: max err {err:.4f} > voxel {r.grid.voxel_size:.4f}"
        print(f"    {backend}: max err {err:.5f} (voxel {r.grid.voxel_size:.4f})")


@test
def box_exact_and_axis_converted():
    # Blender half extents (1, 0.5, 0.25) -> Y-up half extents (1, 0.25, 0.5).
    reset_scene()

    def build(bm):
        bmesh.ops.create_cube(bm, size=2.0)
        bmesh.ops.scale(bm, vec=(1.0, 0.5, 0.25), verts=bm.verts)

    tris = tris_of(mesh_object("Box", build))
    half = np.array([1.0, 0.25, 0.5])
    for backend in ("GPU", "CPU"):
        r = bake(tris, BakeSettings(resolution=40, padding=4, backend=backend))
        p = centers(r.grid)
        q = np.abs(p) - half
        expected = np.linalg.norm(np.maximum(q, 0.0), axis=-1) + np.minimum(q.max(axis=-1), 0.0)
        err = np.abs(r.distance - expected).max()
        assert err <= 1e-4, f"{backend}: box max err {err}"
        assert r.grid.dims[0] > r.grid.dims[2] > r.grid.dims[1], r.grid.dims


@test
def gpu_and_cpu_agree_on_torus():
    reset_scene()

    def build(bm):
        # Torus from a rotated circle, built by spinning.
        circ = bmesh.ops.create_circle(bm, cap_ends=False, segments=24, radius=0.3)
        bmesh.ops.translate(bm, vec=(1.0, 0.0, 0.0), verts=circ["verts"])
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=_rot_x90(), verts=circ["verts"])
        bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], cent=(0, 0, 0), axis=(0, 0, 1), angle=6.283185307, steps=48, use_merge=True)

    tris = tris_of(mesh_object("Torus", build))
    g = bake(tris, BakeSettings(resolution=48, backend="GPU"))
    c = bake(tris, BakeSettings(resolution=48, backend="CPU"))
    # Within a hair of the surface the sign is ill-conditioned (and the CPU rays are
    # jittered by ~0.02 voxel), so only compare voxels clearly off the surface.
    clear = np.abs(g.distance) > g.grid.voxel_size * 0.05
    sign_match = np.mean(np.sign(g.distance[clear]) == np.sign(c.distance[clear]))
    dist_diff = np.abs(np.abs(g.distance) - np.abs(c.distance)).max()
    print(f"    sign match {sign_match:.5f}, |d| diff {dist_diff:.2e}")
    assert sign_match >= 0.999, sign_match
    assert dist_diff <= g.grid.voxel_size * 0.1, dist_diff


@test
def holed_sphere_keeps_sign():
    reset_scene()

    def build(bm):
        sphere(bm)
        bm.faces.ensure_lookup_table()
        # Punch a hole around the +X pole region.
        doomed = [f for f in bm.faces if f.calc_center_median().x > 0.95]
        bmesh.ops.delete(bm, geom=doomed, context="FACES")

    tris = tris_of(mesh_object("Holed", build))
    for backend, required in (("GPU", 1.0), ("CPU", 0.99)):
        r = bake(tris, BakeSettings(resolution=48, backend=backend))
        radius = np.linalg.norm(centers(r.grid), axis=-1)
        inside_ok = np.mean(r.distance[radius < 0.8] < 0)
        outside_ok = np.mean(r.distance[radius > 1.2] > 0)
        print(f"    {backend}: inside {inside_ok:.4f}, outside {outside_ok:.4f}")
        assert inside_ok >= required and outside_ok >= required, backend


@test
def overlapping_cubes_union():
    reset_scene()

    def build(bm):
        a = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.translate(bm, vec=(-0.3, 0, 0), verts=a["verts"])
        b = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.translate(bm, vec=(0.3, 0, 0), verts=b["verts"])

    tris = tris_of(mesh_object("Cubes", build))
    r = bake(tris, BakeSettings(resolution=48, backend="GPU"))
    p = centers(r.grid)
    # Union of two boxes (Y-up conversion leaves x alone and cubes are symmetric).
    qa = np.abs(p - [-0.3, 0, 0]) - 0.5
    qb = np.abs(p - [0.3, 0, 0]) - 0.5
    da = np.linalg.norm(np.maximum(qa, 0), axis=-1) + np.minimum(qa.max(-1), 0)
    db = np.linalg.norm(np.maximum(qb, 0), axis=-1) + np.minimum(qb.max(-1), 0)
    union = np.minimum(da, db)
    clear = np.abs(union) > r.grid.voxel_size
    assert np.all(np.sign(r.distance[clear]) == np.sign(union[clear]))


@test
def files_roundtrip():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", sphere))
    r = bake(tris, BakeSettings(resolution=36, backend="GPU"))
    nz, ny, nx = r.grid.shape
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for fmt, vk_format, dtype in (("r16f", 76, "<f2"), ("r32f", 100, "<f4"), ("r8", 9, "<u1")):
            sub = out / fmt
            export("Sphere", r, ExportSettings(value_format=fmt), sub)
            band = 8.0 * r.grid.voxel_size
            expected = encode.dequantize(encode.quantize(r.distance, fmt, band), fmt, band)

            # KTX2: header, key/value metadata, level 0.
            ktx = _read_ktx2(sub / "Sphere.sdf.ktx2")
            assert ktx["vkFormat"] == vk_format and ktx["typeSize"] == np.dtype(dtype).itemsize, fmt
            assert (ktx["pixelWidth"], ktx["pixelHeight"], ktx["pixelDepth"]) == (nx, ny, nz)
            assert (ktx["layerCount"], ktx["faceCount"], ktx["levelCount"], ktx["supercompressionScheme"]) == (0, 1, 1, 0)
            assert list(ktx["kv"]) == ["3dsdf.meta", "KTXorientation", "KTXwriter"], list(ktx["kv"])
            assert ktx["kv"]["KTXorientation"] == "ruo"
            common = json.loads(ktx["kv"]["3dsdf.meta"])
            assert common["version"] == 1 and common["units"] == "local" and common["sign"] == "negative_inside"
            assert np.allclose(common["bboxMin"], r.grid.bbox_min) and np.allclose(common["bboxMax"], r.grid.bbox_max)
            texels = np.frombuffer(ktx["level0"], dtype=dtype).reshape(nz, ny, nx)
            assert np.abs(encode.dequantize(texels, fmt, band) - expected).max() == 0.0

            # decode turns the sampled value (UNORM 0..1 for r8) back into distance.
            dec = common["decode"]
            sampled = texels.astype(np.float64) / 255.0 if fmt == "r8" else texels.astype(np.float64)
            assert np.abs(sampled * dec["scale"] + dec["offset"] - expected).max() <= 1e-5 * max(band, 1.0), fmt

            # Godot: the sidecar is the same common part plus the atlas fields.
            meta = json.loads((sub / "Sphere.sdf.json").read_text())
            assert {k: meta[k] for k in common} == common
            assert meta["dims"] == [nx, ny, nz] and meta["format"] == fmt
            image_path = sub / meta["files"]["godot"]
            atlas = read_png_gray8(image_path) if fmt == "r8" else read_exr(image_path)
            assert atlas.dtype == np.dtype(dtype), (fmt, atlas.dtype)
            lay = meta["layout"]
            assert atlas.shape == (lay["rows"] * ny, lay["columns"] * nx)
            slices = encode.untile(atlas, lay["columns"], lay["rows"], ny, nx)
            assert np.abs(encode.dequantize(slices, fmt, band) - expected).max() == 0.0
            assert (image_path.parent / (image_path.name + ".import")).exists()

            # r8: half of one 2*band/255 step, plus float slack.
            tol = {"r16f": 1e-3 * np.abs(r.distance).max(), "r32f": 1e-6, "r8": band / 255.0 * 1.0001}[fmt]
            clipped = np.clip(r.distance, -band, band) if fmt == "r8" else r.distance
            assert np.abs(expected - clipped).max() <= tol, fmt

        # A single target writes only its own files.
        export("Sphere", r, ExportSettings(targets=frozenset({"ktx2"})), out / "ktx2_only")
        assert sorted(p.name for p in (out / "ktx2_only").iterdir()) == ["Sphere.sdf.ktx2"]


@test
def bbox_matches_gltf_export():
    reset_scene()

    def build(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.translate(bm, vec=(0.5, 2.0, 0.25), verts=bm.verts)
        bmesh.ops.scale(bm, vec=(1.0, 3.0, 0.5), verts=bm.verts)

    obj = mesh_object("Asym", build)
    tris = tris_of(obj)
    with tempfile.TemporaryDirectory() as tmp:
        glb = Path(tmp) / "asym.glb"
        bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB")
        gmin, gmax = _glb_position_bounds(glb)
    pts = tris.reshape(-1, 3)
    assert np.allclose(pts.min(0), gmin, atol=1e-5), (pts.min(0), gmin)
    assert np.allclose(pts.max(0), gmax, atol=1e-5), (pts.max(0), gmax)


@test
def progress_steps_match_bake():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", lambda bm: sphere(bm, segments=24, rings=12)))
    for backend in ("GPU", "CPU"):
        settings = BakeSettings(resolution=24, backend=backend)
        steps = bake_steps(tris, settings)
        fractions = []
        while True:
            try:
                fractions.append(next(steps))
            except StopIteration as stop:
                result = stop.value
                break
        # The GPU may finish this small grid in a single tile; the CPU steps per slice.
        assert fractions == sorted(fractions) and fractions[-1] == 1.0, (backend, fractions[:3])
        assert backend == "GPU" or len(fractions) > 1, fractions
        assert np.array_equal(result.distance, bake(tris, settings).distance), backend


@test
def gpu_tiles_match_single_dispatch():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", lambda bm: sphere(bm, segments=24, rings=12)))
    grid = bake(tris, BakeSettings(resolution=32, backend="GPU")).grid
    whole = bake(tris, BakeSettings(resolution=32, backend="GPU")).distance
    for limit in (len(tris) * 32 * 8 * 4, len(tris) * 8 * 4 * 4, 1):  # split z, then y, then x
        size = gpu_backend.tile_size(grid.dims, len(tris), limit)
        steps = gpu_backend.compute_steps(tris, grid, work_limit=limit)
        count = 0
        while True:
            try:
                next(steps)
                count += 1
            except StopIteration as stop:
                tiled = stop.value
                break
        print(f"    limit {limit}: tile {size}, {count} dispatches")
        assert count > 1
        assert np.array_equal(tiled, whole), size


@test
def file_names_and_collisions():
    assert plan_outputs(["Suzanne.001", "\u732b", "a b"]) == {"Suzanne.001": "Suzanne.001", "\u732b": "\u732b", "a b": "a_b"}
    for names in (["Cube 1", "Cube_1"], ["Cube", "cube"]):
        try:
            plan_outputs(names)
        except NameCollisionError as e:
            assert all(repr(n) in str(e) for n in names), str(e)
        else:
            raise AssertionError(f"no collision for {names}")

    # The metadata keeps the Blender name; only the file stem is sanitized.
    reset_scene()
    obj = mesh_object("Suzanne.001 x", lambda bm: sphere(bm, segments=12, rings=6))
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch([obj], Path(tmp), BakeSettings(resolution=16))
        batch.advance(60.0)
        meta = json.loads((Path(tmp) / "Suzanne.001_x.sdf.json").read_text())
        assert meta["source"]["object"] == "Suzanne.001 x", meta["source"]


@test
def format_switch_removes_stale_atlas():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6)))
    r = bake(tris, BakeSettings(resolution=16))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        export("Sphere", r, ExportSettings(value_format="r16f"), out)
        assert (out / "Sphere.sdf.exr").exists()
        export("Sphere", r, ExportSettings(value_format="r8"), out)
        names = sorted(p.name for p in out.iterdir())
        assert names == ["Sphere.sdf.json", "Sphere.sdf.ktx2", "Sphere.sdf.png", "Sphere.sdf.png.import"], names


@test
def reexport_keeps_godot_import_uid():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6)))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        export("Sphere", bake(tris, BakeSettings(resolution=16)), ExportSettings(), out)
        import_path = out / "Sphere.sdf.exr.import"
        # What Godot writes back on first import.
        text = import_path.read_text().replace("[remap]\n", '[remap]\n\nuid="uid://bkeep"\npath="res://.godot/x"\n', 1)
        import_path.write_text(text)
        export("Sphere", bake(tris, BakeSettings(resolution=32)), ExportSettings(), out)
        meta = json.loads((out / "Sphere.sdf.json").read_text())
        updated = import_path.read_text()
        assert 'uid="uid://bkeep"' in updated and 'path="res://.godot/x"' in updated, updated
        assert f"slices/horizontal={meta['layout']['columns']}\n" in updated, updated
        assert f"slices/vertical={meta['layout']['rows']}\n" in updated, updated


@test
def r16f_overflow_is_refused():
    reset_scene()

    def build(bm):
        bmesh.ops.create_cube(bm, size=2.0)
        bmesh.ops.scale(bm, vec=(1e5, 1e5, 1e5), verts=bm.verts)

    obj = mesh_object("Huge", build)
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch([obj], Path(tmp), BakeSettings(resolution=16), ExportSettings(value_format="r16f"))
        batch.advance(60.0)
        assert batch.failed == ["Huge"], batch.failed
        assert any("r32f" in m for level, m in batch.messages if level == "ERROR"), batch.messages
        assert not any(Path(tmp).iterdir())
        batch = _batch([obj], Path(tmp), BakeSettings(resolution=16), ExportSettings(value_format="r32f"))
        batch.advance(60.0)
        assert not batch.failed, batch.messages


@test
def curve_bakes_and_failures_are_skipped():
    reset_scene()
    bpy.ops.curve.primitive_bezier_circle_add(radius=1.0)
    curve = bpy.context.object
    curve.data.bevel_depth = 0.25
    curve.data.fill_mode = "FULL"
    empty = mesh_object("NoFaces", lambda bm: bm.verts.new((0, 0, 0)))
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch([empty, curve], Path(tmp), BakeSettings(resolution=32))
        batch.advance(60.0)
        assert batch.failed == ["NoFaces"], batch.messages
        assert [r.name for r in batch.baked] == [curve.name]
        assert batch.summary()[0] == "ERROR" and "1/2 baked" in batch.summary()[1], batch.summary()
        assert any(m.startswith("NoFaces: ") for level, m in batch.messages if level == "ERROR"), batch.messages
        # The bevelled circle is a closed torus-like tube: its inside is negative.
        assert batch.baked[0].result.distance.min() < 0.0


@test
def cancel_writes_nothing_for_the_current_object():
    reset_scene()
    a = mesh_object("A", lambda bm: sphere(bm, segments=12, rings=6))
    b = mesh_object("B", lambda bm: sphere(bm, segments=12, rings=6))
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch([a, b], Path(tmp), BakeSettings(resolution=24, backend="CPU"))
        batch.advance(0.0)  # one step into A
        assert batch.index == 0 and 0.0 < batch.fraction < 1.0
        batch.cancel()
        assert batch.done and batch.summary() == ("WARNING", "Cancelled: 0/2 baked")
        assert not any(Path(tmp).iterdir())


@test
def ktx2_zstd_matches_uncompressed():
    reset_scene()
    tris = tris_of(mesh_object("Sphere", sphere))
    r = bake(tris, BakeSettings(resolution=36, backend="GPU"))
    with tempfile.TemporaryDirectory() as tmp:
        for fmt in ("r8", "r16f"):
            plain_dir, zstd_dir = Path(tmp) / fmt / "plain", Path(tmp) / fmt / "zstd"
            export("Sphere", r, ExportSettings(value_format=fmt, targets=frozenset({"ktx2"})), plain_dir)
            export("Sphere", r, ExportSettings(value_format=fmt, targets=frozenset({"ktx2"}), ktx2_zstd=True), zstd_dir)
            plain = _read_ktx2(plain_dir / "Sphere.sdf.ktx2")
            packed = _read_ktx2(zstd_dir / "Sphere.sdf.ktx2")
            assert plain["supercompressionScheme"] == 0 and packed["supercompressionScheme"] == 2, fmt
            assert packed["levelByteLength"] < len(packed["level0"]), (fmt, packed["levelByteLength"])
            assert packed["level0"] == plain["level0"], fmt
            assert packed["kv"] == plain["kv"], fmt
            assert ({k: v for k, v in packed.items() if k not in ("supercompressionScheme", "levelByteLength", "level0", "kv")}
                    == {k: v for k, v in plain.items() if k not in ("supercompressionScheme", "levelByteLength", "level0", "kv")}), fmt


@test
def eta_waits_for_progress_then_extrapolates():
    reset_scene()
    obj = mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6))
    with tempfile.TemporaryDirectory() as tmp:
        batch = _batch([obj], Path(tmp), BakeSettings(resolution=24, backend="CPU"))
        assert batch.eta() is None
        batch.advance(0.0)
        assert 0.0 < batch.fraction < 1.0
        batch.started -= 10.0  # pretend the first step took long enough to estimate from
        eta = batch.eta()
        assert eta is not None and eta > 0.0, eta
        assert abs(eta - batch.elapsed * (1.0 - batch.fraction) / batch.fraction) < 0.1, eta


@test
def warnings_are_counted():
    from core import pipeline

    reset_scene()
    obj = mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6))
    limit = pipeline.TRIANGLE_WARN_LIMIT
    pipeline.TRIANGLE_WARN_LIMIT = 10
    try:
        with tempfile.TemporaryDirectory() as tmp:
            batch = _batch([obj], Path(tmp), BakeSettings(resolution=16))
            batch.advance(60.0)
    finally:
        pipeline.TRIANGLE_WARN_LIMIT = limit
    assert batch.warning_count == 1, batch.messages
    assert [m for level, m in batch.messages if level == "WARNING"][0].startswith("Sphere: "), batch.messages
    assert batch.summary()[0] == "INFO", batch.summary()


@test
def operator_leaves_last_result_for_the_panel():
    reset_scene()
    sys.path.insert(0, str(ROOT))
    import extension
    from extension import ui

    extension.register()
    try:
        obj = mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6))
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        s = bpy.context.scene.sdf_texture
        with tempfile.TemporaryDirectory() as tmp:
            s.output_dir = tmp + "/"
            s.resolution = 16
            assert bpy.ops.sdf_texture.bake() == {"FINISHED"}
            assert ui._last is not None and ui._last.text.startswith("1/1 baked · "), ui._last
            assert ui._last.icon == "CHECKMARK" and ui._last.out_dir == tmp, ui._last
            assert not ui._baking()
        # A stale live state (modal gone without cleanup) stops counting as a running bake.
        ui._live = ui._Live("x", 0.5, time.monotonic() - ui.LIVE_TIMEOUT - 1.0)
        assert not ui._baking()
        ui._live = ui._Live("x", 0.5, time.monotonic())
        assert ui._baking()
        ui._clear_state(None)
        assert ui._live is None and ui._last is None
    finally:
        extension.unregister()


@test
def operator_refuses_unsaved_relative_output():
    reset_scene()
    sys.path.insert(0, str(ROOT))
    import extension

    extension.register()
    try:
        obj = mesh_object("Sphere", lambda bm: sphere(bm, segments=12, rings=6))
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        s = bpy.context.scene.sdf_texture
        s.output_dir = "//sdf/"
        try:
            bpy.ops.sdf_texture.bake()
        except RuntimeError as e:
            assert "Save the .blend" in str(e), str(e)
        else:
            raise AssertionError("bake ran with an unsaved relative output")
        with tempfile.TemporaryDirectory() as tmp:
            s.output_dir = tmp + "/"
            s.resolution = 16
            assert bpy.ops.sdf_texture.bake() == {"FINISHED"}
            assert (Path(tmp) / "Sphere.sdf.ktx2").exists()
    finally:
        extension.unregister()


def timing():
    reset_scene()
    obj = mesh_object("Dense", lambda bm: sphere(bm, segments=96, rings=56))
    tris = tris_of(obj)
    print(f"  timing with {len(tris)} triangles")
    for res in (128, 256):
        t0 = time.perf_counter()
        bake(tris, BakeSettings(resolution=res, backend="GPU"))
        print(f"    GPU {res}: {time.perf_counter() - t0:.2f}s")
    t0 = time.perf_counter()
    bake(tris, BakeSettings(resolution=128, backend="CPU"))
    print(f"    CPU 128: {time.perf_counter() - t0:.2f}s")


# --- utilities -----------------------------------------------------------------


def _rot_x90():
    from mathutils import Matrix

    return Matrix.Rotation(1.5707963267948966, 3, "X")


def _batch(objects, out: Path, bake_settings: BakeSettings, export_settings: ExportSettings | None = None) -> BatchBake:
    """BatchBake that records its reports in `.messages`."""
    messages: list[tuple[str, str]] = []
    batch = BatchBake(
        objects,
        bpy.context.evaluated_depsgraph_get,
        bake_settings,
        export_settings or ExportSettings(),
        out,
        lambda level, message: messages.append((level, message)),
    )
    batch.messages = messages
    return batch


def _read_ktx2(path: Path) -> dict:
    """Independent KTX2 reader (spec layout, not the writer's code)."""
    data = path.read_bytes()
    assert data[:12] == b"\xabKTX 20\xbb\r\n\x1a\n", "bad identifier"
    names = ("vkFormat", "typeSize", "pixelWidth", "pixelHeight", "pixelDepth", "layerCount", "faceCount", "levelCount", "supercompressionScheme")
    out = dict(zip(names, struct.unpack_from("<9I", data, 12), strict=True))
    dfd_off, dfd_len, kvd_off, kvd_len, sgd_off, sgd_len = struct.unpack_from("<4I2Q", data, 48)
    assert (sgd_off, sgd_len) == (0, 0)
    assert struct.unpack_from("<I", data, dfd_off)[0] == dfd_len
    kv = {}
    pos, end = kvd_off, kvd_off + kvd_len
    while pos < end:
        (n,) = struct.unpack_from("<I", data, pos)
        entry = data[pos + 4 : pos + 4 + n]
        key, value = entry.split(b"\0", 1)
        assert value.endswith(b"\0"), key
        kv[key.decode()] = value[:-1].decode()
        pos += 4 + (n + 3) // 4 * 4
    out["kv"] = kv
    level_off, level_len, level_ulen = struct.unpack_from("<3Q", data, 80)
    assert level_off % 4 == 0 and level_off + level_len == len(data)
    level0 = data[level_off : level_off + level_len]
    out["levelByteLength"] = level_len
    if out["supercompressionScheme"] == 2:
        import zstandard

        level0 = zstandard.ZstdDecompressor().decompress(level0, max_output_size=level_ulen)
    else:
        assert out["supercompressionScheme"] == 0 and level_len == level_ulen
    assert len(level0) == level_ulen
    out["level0"] = level0
    return out


def _glb_position_bounds(path: Path):
    data = path.read_bytes()
    (json_len,) = struct.unpack("<I", data[12:16])
    doc = json.loads(data[20 : 20 + json_len])
    acc = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    return np.array(acc["min"]), np.array(acc["max"])


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    failed = 0
    for fn in TESTS:
        print(f"[test] {fn.__name__}")
        try:
            fn()
            print("  ok")
        except Exception:
            failed += 1
            traceback.print_exc()
            print("  FAILED")
    if "--timing" in argv:
        timing()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


sys.exit(main())
