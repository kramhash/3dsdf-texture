"""Minimal single-channel PNG and OpenEXR writers/readers.

Written by hand instead of through bpy.types.Image so values pass through
without color management and the row order is exactly what we lay out.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

# --- PNG (8-bit grayscale) ---------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png_gray8(path: Path, image: np.ndarray) -> None:
    h, w = image.shape
    raw = np.zeros((h, w + 1), dtype=np.uint8)  # leading filter byte 0 per row
    raw[:, 1:] = image
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    data = _PNG_SIG + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw.tobytes(), 9))
    data += _png_chunk(b"IEND", b"")
    path.write_bytes(data)


def read_png_gray8(path: Path) -> np.ndarray:
    data = path.read_bytes()
    pos = len(_PNG_SIG)
    w = h = 0
    idat = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, w + 1)
    if raw[:, 0].any():
        raise ValueError("only unfiltered rows are supported")
    return raw[:, 1:].copy()


# --- OpenEXR (one HALF or FLOAT channel "R", no compression, scanline) ---------

_EXR_MAGIC = 20000630
_EXR_PIXEL_TYPES = {np.dtype(np.float16): (1, "<f2"), np.dtype(np.float32): (2, "<f4")}
_EXR_DTYPES = {code: le for code, le in _EXR_PIXEL_TYPES.values()}


def _attr(name: str, type_name: str, payload: bytes) -> bytes:
    return name.encode() + b"\0" + type_name.encode() + b"\0" + struct.pack("<i", len(payload)) + payload


def write_exr(path: Path, image: np.ndarray, channel: str = "R") -> None:
    """float16 image -> HALF channel, float32 -> FLOAT channel."""
    pixel_type, le_dtype = _EXR_PIXEL_TYPES[image.dtype]
    h, w = image.shape
    chlist = channel.encode() + b"\0" + struct.pack("<iB3xii", pixel_type, 0, 1, 1) + b"\0"
    box = struct.pack("<iiii", 0, 0, w - 1, h - 1)
    header = struct.pack("<ii", _EXR_MAGIC, 2)
    header += _attr("channels", "chlist", chlist)
    header += _attr("compression", "compression", b"\0")
    header += _attr("dataWindow", "box2i", box)
    header += _attr("displayWindow", "box2i", box)
    header += _attr("lineOrder", "lineOrder", b"\0")
    header += _attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
    header += _attr("screenWindowCenter", "v2f", struct.pack("<ff", 0.0, 0.0))
    header += _attr("screenWindowWidth", "float", struct.pack("<f", 1.0))
    header += b"\0"

    rows = image.astype(le_dtype)
    line_bytes = w * rows.itemsize
    block = 8 + line_bytes
    first = len(header) + 8 * h
    offsets = struct.pack(f"<{h}Q", *(first + y * block for y in range(h)))
    body = bytearray()
    for y in range(h):
        body += struct.pack("<ii", y, line_bytes)
        body += rows[y].tobytes()
    path.write_bytes(header + offsets + bytes(body))


def read_exr(path: Path) -> np.ndarray:
    """Reader for files written by write_exr (single channel, uncompressed)."""
    data = path.read_bytes()
    pos = 8
    w = h = 0
    dtype = "<f2"
    while data[pos] != 0:
        name_end = data.index(b"\0", pos)
        name = data[pos:name_end].decode()
        type_end = data.index(b"\0", name_end + 1)
        (size,) = struct.unpack("<i", data[type_end + 1 : type_end + 5])
        payload = data[type_end + 5 : type_end + 5 + size]
        if name == "dataWindow":
            x0, y0, x1, y1 = struct.unpack("<iiii", payload)
            w, h = x1 - x0 + 1, y1 - y0 + 1
        elif name == "channels":
            (pixel_type,) = struct.unpack("<i", payload[payload.index(b"\0") + 1 :][:4])
            dtype = _EXR_DTYPES[pixel_type]
        pos = type_end + 5 + size
    pos += 1
    offsets = struct.unpack(f"<{h}Q", data[pos : pos + 8 * h])
    out = np.empty((h, w), dtype=dtype)
    for y, off in enumerate(offsets):
        out[y] = np.frombuffer(data, dtype=dtype, count=w, offset=off + 8)
    return out
