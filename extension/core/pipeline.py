"""One object in, files out. Shared by the UI operator and the CLI."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .bake import TRIANGLE_WARN_LIMIT, BakeResult, BakeSettings, Steps, bake_steps
from .export import ExportSettings, export
from .mesh_extract import triangles_from_object

# Object types whose evaluated geometry converts to a mesh with to_mesh().
BAKEABLE_TYPES = frozenset({"MESH", "CURVE", "FONT", "SURFACE", "META"})


class NameCollisionError(ValueError):
    pass


@dataclass(frozen=True)
class ObjectReport:
    name: str  # Blender object name
    file_stem: str
    result: BakeResult
    files: list[Path]
    warnings: list[str]


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("._") or "object"


def plan_outputs(names: Iterable[str]) -> dict[str, str]:
    """Map object names to file stems; raise if two would write the same files.

    Stems are compared case-insensitively because the default macOS and Windows
    file systems are.
    """
    owners: dict[str, str] = {}
    clashes: list[str] = []
    stems: dict[str, str] = {}
    for name in names:
        stem = safe_name(name)
        other = owners.setdefault(stem.casefold(), name)
        if other != name:
            clashes.append(f"{other!r} and {name!r} both write {stem}.sdf.*")
        stems[name] = stem
    if clashes:
        raise NameCollisionError("; ".join(clashes) + ". Rename one of them.")
    return stems


def bake_object_steps(
    obj,
    depsgraph,
    bake_settings: BakeSettings,
    export_settings: ExportSettings,
    out_dir: Path,
    file_stem: str | None = None,
    on_fallback: Callable[[str], None] | None = None,
) -> Steps[ObjectReport]:
    """Bake and export one object. Errors are re-raised prefixed with the object name.

    Files are written only after the bake finishes, so closing the generator
    early leaves nothing half written. When on_fallback is given it receives the
    GPU error as it happens instead of a warning in the report.
    """
    try:
        tris = triangles_from_object(obj, depsgraph)
        warnings: list[str] = []
        if len(tris) > TRIANGLE_WARN_LIMIT:
            warnings.append(
                f"{obj.name}: {len(tris)} triangles exceeds {TRIANGLE_WARN_LIMIT}; "
                "the GPU bake gets slow, consider a Decimate modifier"
            )
        result = yield from bake_steps(tris, bake_settings, on_fallback)
        if result.fallback_reason and on_fallback is None:
            warnings.append(
                f"{obj.name}: GPU unavailable ({result.fallback_reason}), "
                "used the CPU fallback (weaker sign on open meshes)"
            )
        stem = file_stem or safe_name(obj.name)
        files = export(stem, result, export_settings, out_dir, object_name=obj.name)
    except GeneratorExit:
        raise
    except Exception as e:
        raise RuntimeError(f"{obj.name}: {e}") from e
    return ObjectReport(obj.name, stem, result, files, warnings)
