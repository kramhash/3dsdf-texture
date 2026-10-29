"""Godot target: slice atlas image plus a `.import` that selects the Texture3D importer.

r16f/r32f -> single-channel half/float EXR, r8 -> 8-bit grayscale PNG. A new
`.import` only carries [remap] and [params]; Godot fills in uid and cache paths on
first import. On re-export an existing `.import` keeps everything Godot wrote and
only gets its slice counts updated, so the resource uid survives.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..encode import tile
from .image_files import write_exr, write_png_gray8

IMAGE_SUFFIXES = (".exr", ".png")


def write(out_dir: Path, stem: str, values: np.ndarray) -> Path:
    """Write `<stem>.exr` or `<stem>.png` and its `.import`; return the image path.

    The other format's image from an earlier export is removed so Godot does not
    import a stale atlas next to the one the sidecar points at.
    """
    atlas, cols, rows = tile(values)
    suffix = ".exr" if values.dtype in (np.float16, np.float32) else ".png"
    for stale in IMAGE_SUFFIXES:
        if stale != suffix:
            for path in (out_dir / f"{stem}{stale}", out_dir / f"{stem}{stale}.import"):
                path.unlink(missing_ok=True)

    image_path = out_dir / f"{stem}{suffix}"
    if suffix == ".exr":
        write_exr(image_path, atlas)
    else:
        write_png_gray8(image_path, atlas)

    import_path = image_path.with_name(image_path.name + ".import")
    existing = import_path.read_text() if import_path.exists() else None
    import_path.write_text(_update_import_file(existing, cols, rows) if existing else _import_file(cols, rows))
    return image_path


def _update_import_file(text: str, cols: int, rows: int) -> str:
    """Rewrite the slice counts in place; fall back to a fresh file if either key is missing."""
    for key, value in (("horizontal", cols), ("vertical", rows)):
        text, n = re.subn(rf"^slices/{key}=.*$", f"slices/{key}={value}", text, flags=re.MULTILINE)
        if n != 1:
            return _import_file(cols, rows)
    return text


def _import_file(cols: int, rows: int) -> str:
    return (
        "[remap]\n\n"
        'importer="3d_texture"\n'
        'type="CompressedTexture3D"\n\n'
        "[params]\n\n"
        "compress/mode=0\n"
        "compress/high_quality=false\n"
        "compress/lossy_quality=0.7\n"
        "compress/hdr_compression=0\n"
        "compress/channel_pack=1\n"
        "mipmaps/generate=false\n"
        "mipmaps/limit=-1\n"
        f"slices/horizontal={cols}\n"
        f"slices/vertical={rows}\n"
    )
