"""Sidebar panel (View3D > N > SDF) and the bake operator."""

from __future__ import annotations

from pathlib import Path

import bpy

from .core.bake import BakeSettings
from .core.batch import BatchBake
from .core.export import ExportSettings
from .core.pipeline import BAKEABLE_TYPES, NameCollisionError


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
                ExportSettings(value_format=s.value_format, band_voxels=s.band_voxels, targets=frozenset(targets)),
                Path(bpy.path.abspath(s.output_dir)),
                lambda level, message: self.report({level}, message),
            )
        except NameCollisionError as e:
            self.report({"ERROR"}, str(e))
            return False
        return True

    def _finish(self, context) -> set[str]:
        level, message = self._batch.summary()
        self.report({level}, message)
        return {"CANCELLED"} if self._batch.cancelled else {"FINISHED"}

    def execute(self, context):
        # Scripted calls (bpy.ops without INVOKE) run to completion synchronously.
        if not self._start(context):
            return {"CANCELLED"}
        while not self._batch.advance(1.0):
            pass
        return self._finish(context)

    def invoke(self, context, event):
        if not self._start(context):
            return {"CANCELLED"}
        wm = context.window_manager
        wm.progress_begin(0, len(self._batch.objects))
        self._timer = wm.event_timer_add(0.01, window=context.window)
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
        col.prop(s, "target_godot")
        row = layout.row()
        unsaved = _unsaved_relative(s.output_dir)
        row.alert = unsaved
        row.prop(s, "output_dir")
        if unsaved:
            layout.label(text="Save the .blend or use an absolute path", icon="ERROR")

        layout.operator(SDFTEXTURE_OT_bake.bl_idname, icon="EXPORT")


classes = (SDFTEXTURE_PG_settings, SDFTEXTURE_OT_bake, SDFTEXTURE_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sdf_texture = bpy.props.PointerProperty(type=SDFTEXTURE_PG_settings)


def unregister():
    del bpy.types.Scene.sdf_texture
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
