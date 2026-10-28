"""Write a bake result to disk for each requested target."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from . import encode
from .bake import BakeResult
from .writers import godot, ktx2, meta

Target = Literal["ktx2", "godot"]


@dataclass(frozen=True)
class ExportSettings:
    value_format: encode.ValueFormat = "r16f"
    band_voxels: float = 8.0  # r8 only: clamp range in voxels on each side of the surface
    targets: frozenset[Target] = field(default_factory=lambda: frozenset({"ktx2", "godot"}))


def export(
    name: str, result: BakeResult, settings: ExportSettings, out_dir: Path, object_name: str | None = None
) -> list[Path]:
    """name is the file stem; object_name (default: name) goes into the metadata unchanged."""
    if settings.value_format == "r16f":
        encode.check_r16f(result.distance, result.grid.voxel_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    band = settings.band_voxels * result.grid.voxel_size
    values = encode.quantize(result.distance, settings.value_format, band)
    common = meta.build_common(object_name or name, result, settings.value_format, band)

    written: list[Path] = []
    stem = f"{name}.sdf"
    if "ktx2" in settings.targets:
        path = out_dir / f"{stem}.ktx2"
        ktx2.write(path, values, common)
        written.append(path)
    if "godot" in settings.targets:
        image_path = godot.write(out_dir, stem, values)
        meta_path = out_dir / f"{stem}.json"
        meta.write(meta_path, meta.build_godot(common, result.grid.dims, settings.value_format, image_path.name))
        written += [image_path, meta_path]
    return written
