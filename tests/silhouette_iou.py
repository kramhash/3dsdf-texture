"""Silhouette IoU of two screenshots taken from the same camera on a flat background.

    blender -b --factory-startup --python tests/silhouette_iou.py -- sdf.png mesh.png [--min 0.97]

A pixel belongs to the silhouette when it differs from the top-left background
pixel. Exits 1 when the IoU is below --min.
"""

from __future__ import annotations

import argparse
import sys

import bpy
import numpy as np


def mask(path: str) -> np.ndarray:
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(h, w, 4)[..., :3]
    bg = rgb[-1, 0]  # Blender rows are bottom-up; [-1, 0] is the top-left pixel
    return np.abs(rgb - bg).max(axis=-1) > 0.02


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    p = argparse.ArgumentParser()
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--min", type=float, default=0.97)
    args = p.parse_args(argv)
    a, b = mask(args.a), mask(args.b)
    iou = float((a & b).sum() / max(1, (a | b).sum()))
    print(f"silhouette IoU {iou:.4f} (pixels {a.sum()} vs {b.sum()})")
    return 0 if iou >= args.min else 1


sys.exit(main())
