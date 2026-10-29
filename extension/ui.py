"""Sidebar panel (View3D > N > SDF) and the bake operator."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

from .core.bake import TRIANGLE_WARN_LIMIT, BakeSettings
from .core.batch import BatchBake
from .core.export import ExportSettings
from .core.pipeline import BAKEABLE_TYPES, NameCollisionError

# Without a modal tick for this long the panel stops showing a bake as running:
# the modal dies without cleanup when another .blend is opened.
LIVE_TIMEOUT = 5.0


@dataclass
class _Live:
    text: str
    factor: float
    updated: float


@dataclass(frozen=True)
class _Last:
    icon: str
    text: str
    warnings: int
    out_dir: str


# Session-only panel state, never saved into the .blend.
_live: _Live | None = None
_last: _Last | None = None


def _baking() -> bool:
    return _live is not None and time.monotonic() - _live.updated < LIVE_TIMEOUT


def _format_seconds(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


def _redraw_sidebars(context) -> None:
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "UI":
                        region.tag_redraw()


@persistent
def _clear_state(_filepath) -> None:
    global _live, _last
    _live = None
    _last = None


class SDFTEXTURE_PG_settings(bpy.types.PropertyGroup):
    resolution: bpy.props.IntProperty(
        name="Resolution",
        description="Voxels along the longest axis (padding included)",
        default=128,
        min=16,
        max=256,
        step=4,
    )
    padding: bpy.props.IntProperty(
        name="Padding",
        description="Empty voxels around the bounding box on each side",
        default=4,
        min=1,
        max=32,
    )
    backend: bpy.props.EnumProperty(
        name="Backend",
        items=[
            ("AUTO", "Auto", "GPU, falling back to CPU when unavailable"),
            ("GPU", "GPU", "Brute-force distance and winding number on the GPU"),
            ("CPU", "CPU", "BVH distance with a ray-parity vote for the sign"),
        ],
        default="AUTO",
    )
    value_format: bpy.props.EnumProperty(
        name="Format",
        items=[
            ("r16f", "Half Float", "Raw signed distance in local units"),
            ("r32f", "Float", "Raw signed distance in local units, full precision"),
            ("r8", "8-bit", "Distance clamped to +-band and normalized to 0..1"),
        ],
        default="r16f",
    )
    band_voxels: bpy.props.FloatProperty(
        name="Band (voxels)",
        description="8-bit only: clamp range on each side of the surface",
        default=8.0,
        min=0.5,
        max=128.0,
    )
    target_ktx2: bpy.props.BoolProperty(name="KTX2 (.ktx2)", default=True)
    ktx2_zstd: bpy.props.BoolProperty(
        name="Zstd Compression",
        description="Supercompress the KTX2 with Zstandard; readers must be able to decompress it",
        default=False,
    )
    target_godot: bpy.props.BoolProperty(name="Godot (slice atlas)", default=True)
    output_dir: bpy.props.StringProperty(
        name="Output", subtype="DIR_PATH", default="//sdf/", options={"PATH_SUPPORTS_BLEND_RELATIVE"}
    )


def _unsaved_relative(output_dir: str) -> bool:
    """`//` resolves against the .blend; unsaved, it would land in the process cwd."""
    return output_dir.startswith("//") and not bpy.data.filepath


class SDFTEXTURE_OT_bake(bpy.types.Operator):
    bl_idname = "sdf_texture.bake"
    bl_label = "Bake SDF Texture"
    bl_description = "Bake each selected object into its own 3D SDF texture (Esc cancels)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return any(o.type in BAKEABLE_TYPES for o in context.selected_objects)

    def _start(self, context) -> bool:
        s = context.scene.sdf_texture
        targets = {t for t, on in (("ktx2", s.target_ktx2), ("godot", s.target_godot)) if on}
        if not targets:
            self.report({"ERROR"}, "Choose at least one target")
            return False
        if _unsaved_relative(s.output_dir):
            self.report({"ERROR"}, "Save the .blend first, or set an absolute output folder")
            return False

        selected = context.selected_objects
        skipped = [o.name for o in selected if o.type not in BAKEABLE_TYPES]
        if skipped:
            self.report({"WARNING"}, f"Skipped objects without geometry: {', '.join(skipped)}")
        try:
            self._batch = BatchBake(
                [o for o in selected if o.type in BAKEABLE_TYPES],
                context.evaluated_depsgraph_get,
                BakeSettings(resolution=s.resolution, padding=s.padding, backend=s.backend),
                ExportSettings(
                    value_format=s.value_format,
                    band_voxels=s.band_voxels,
                    targets=frozenset(targets),
                    ktx2_zstd=s.ktx2_zstd,
                ),
                Path(bpy.path.abspath(s.output_dir)),
                lambda level, message: self.report({level}, message),
            )
        except NameCollisionError as e:
            self.report({"ERROR"}, str(e))
            return False
        return True

    def _update_live(self) -> None:
        global _live
        batch = self._batch
        eta = batch.eta()
        left = f"{_format_seconds(eta)} left" if eta is not None else "estimating"
        _live = _Live(
            text=f"{batch.current_name} {batch.index + 1}/{len(batch.objects)} · {left}",
            factor=batch.progress / max(1, len(batch.objects)),
            updated=time.monotonic(),
        )

    def _finish(self, context) -> set[str]:
        global _live, _last
        batch = self._batch
        level, message = batch.summary()
        self.report({level}, message)

        baked, total = len(batch.baked), len(batch.objects)
        if batch.cancelled:
            icon, text = "CANCEL", f"Cancelled: {baked}/{total} baked"
        elif batch.failed:
            icon, text = "ERROR", f"{baked}/{total} baked, {len(batch.failed)} failed"
        else:
            icon, text = "CHECKMARK", f"{baked}/{total} baked"
        _live = None
        _last = _Last(icon, f"{text} · {_format_seconds(batch.elapsed)}", batch.warning_count, str(batch.out_dir))
        _redraw_sidebars(context)
        return {"CANCELLED"} if batch.cancelled else {"FINISHED"}

    def execute(self, context):
        # Scripted calls (bpy.ops without INVOKE) run to completion synchronously.
        if not self._start(context):
            return {"CANCELLED"}
        while not self._batch.advance(1.0):
            pass
        return self._finish(context)

    def invoke(self, context, event):
        global _last
        if not self._start(context):
            return {"CANCELLED"}
        _last = None  # the previous result would read as this bake's
        wm = context.window_manager
        wm.progress_begin(0, len(self._batch.objects))
        self._timer = wm.event_timer_add(0.01, window=context.window)
        self._update_live()
        _redraw_sidebars(context)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        batch = self._batch
        if event.type == "ESC":
            batch.cancel()
        elif event.type == "TIMER":
            batch.advance(0.05)
            context.window_manager.progress_update(batch.progress)
            if not batch.done:
                position = f"{batch.index + 1}/{len(batch.objects)}"
                context.workspace.status_text_set(
                    f"Baking SDF {position} {batch.current_name}: {batch.fraction:.0%}  (Esc to cancel)"
                )
                self._update_live()
                _redraw_sidebars(context)
        if not batch.done:
            return {"PASS_THROUGH"}

        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        context.workspace.status_text_set(None)
        return self._finish(context)


class SDFTEXTURE_PT_panel(bpy.types.Panel):
    bl_label = "SDF Texture"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SDF"

    def draw(self, context):
        s = context.scene.sdf_texture
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column()
        col.prop(s, "resolution")
        col.prop(s, "padding")
        col.prop(s, "backend")

        col = layout.column()
        col.prop(s, "value_format")
        sub = col.column()
        sub.active = s.value_format == "r8"
        sub.prop(s, "band_voxels")

        col = layout.column(heading="Targets")
        col.prop(s, "target_ktx2")
        sub = col.column()
        sub.active = s.target_ktx2
        sub.prop(s, "ktx2_zstd")
        col.prop(s, "target_godot")
        row = layout.row()
        unsaved = _unsaved_relative(s.output_dir)
        row.alert = unsaved
        row.prop(s, "output_dir")
        if unsaved:
            layout.label(text="Save the .blend or use an absolute path", icon="ERROR")

        _draw_triangles(layout, context)

        if _baking():
            layout.progress(factor=_live.factor, type="BAR", text=_live.text)
            layout.label(text="Esc to cancel", icon="INFO")
        else:
            layout.operator(SDFTEXTURE_OT_bake.bl_idname, icon="EXPORT")

        if _last is not None:
            box = layout.box()
            box.label(text=_last.text, icon=_last.icon)
            if _last.warnings:
                box.label(text=f"{_last.warnings} warning(s), see the Info log", icon="ERROR")
            box.operator("wm.path_open", text="Open Output Folder", icon="FILE_FOLDER").filepath = _last.out_dir


def _draw_triangles(layout, context) -> None:
    """Triangle count of the selection, so a slow bake is visible before it starts."""
    depsgraph = context.view_layer.depsgraph
    total = 0
    uncounted = 0
    heavy = []
    for obj in context.selected_objects:
        if obj.type == "MESH":
            count = len(obj.evaluated_get(depsgraph).data.loop_triangles)
            total += count
            if count > TRIANGLE_WARN_LIMIT:
                heavy.append((obj.name, count))
        elif obj.type in BAKEABLE_TYPES:
            uncounted += 1
    if not total and not uncounted:
        return

    col = layout.column(align=True)
    text = f"Triangles: {total:,}"
    if uncounted:
        text += f" (+{uncounted} non-mesh not counted)"
    col.label(text=text, icon="MESH_DATA")
    for name, count in heavy:
        # Kept short to fit the sidebar; the bake report carries the Decimate hint.
        col.label(text=f"{name}: {count:,}, slow bake", icon="ERROR")


classes = (SDFTEXTURE_PG_settings, SDFTEXTURE_OT_bake, SDFTEXTURE_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sdf_texture = bpy.props.PointerProperty(type=SDFTEXTURE_PG_settings)
    bpy.app.handlers.load_post.append(_clear_state)


def unregister():
    if _clear_state in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_clear_state)
    del bpy.types.Scene.sdf_texture
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
