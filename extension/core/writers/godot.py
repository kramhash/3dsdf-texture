"""Godot target: slice atlas image plus a `.import` that selects the Texture3D importer.

r16f/r32f -> single-channel half/float EXR, r8 -> 8-bit grayscale PNG. The `.import`
file only carries [remap] and [params]; Godot fills in uid and cache paths on
first import.
"""

from __future__ import annotations

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

    image_path.with_name(image_path.name + ".import").write_text(_import_file(cols, rows))
    return image_path


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
