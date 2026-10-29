"""KTX2 target: one 3D texture with the metadata in key/value data.

Layout is fixed by docs/format.md: R8_UNORM / R16_SFLOAT / R32_SFLOAT, one
level, x fastest, row 0 = y min, slice 0 = z min, level 0 optionally Zstandard
supercompressed. Written with struct so the extension needs no libktx; zstd
comes from the `zstandard` module bundled with Blender.
"""

from __future__ import annotations

import json
import struct
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

IDENTIFIER = b"\xabKTX 20\xbb\r\n\x1a\n"
META_KEY = "3dsdf.meta"
ORIENTATION = "ruo"  # rows go up (+y), slices come out of the screen (+z, right-handed Y-up)
_MANIFEST = Path(__file__).resolve().parents[2] / "blender_manifest.toml"
WRITER = f"3dsdf-texture {tomllib.loads(_MANIFEST.read_text())['version']}"

_HEADER_SIZE = 80
_SUPERCOMPRESSION_ZSTD = 2
# Written once per bake, so compress hard: level 19 costs ~0.2 s on a 2 MB level.
ZSTD_LEVEL = 19
_LEVEL_INDEX_SIZE = 24

# Khronos Data Format constants used by the single-sample basic descriptor.
_KHR_DF_MODEL_RGBSDA = 1
_KHR_DF_PRIMARIES_UNSPECIFIED = 0
_KHR_DF_TRANSFER_LINEAR = 1
_KHR_DF_SAMPLE_DATATYPE_SIGNED = 0x40
_KHR_DF_SAMPLE_DATATYPE_FLOAT = 0x80
_FLOAT_LOWER = 0xBF800000  # -1.0f
_FLOAT_UPPER = 0x3F800000  # 1.0f

# dtype -> (vkFormat, little-endian dtype)
_FORMATS: dict[np.dtype, tuple[int, str]] = {
    np.dtype(np.uint8): (9, "<u1"),  # VK_FORMAT_R8_UNORM
    np.dtype(np.float16): (76, "<f2"),  # VK_FORMAT_R16_SFLOAT
    np.dtype(np.float32): (100, "<f4"),  # VK_FORMAT_R32_SFLOAT
}


def write(path: Path, values: np.ndarray, meta: dict[str, Any], zstd: bool = False) -> None:
    """values: [z, y, x] array of uint8, float16 or float32."""
    if values.dtype not in _FORMATS:
        raise ValueError(f"no KTX2 format for dtype {values.dtype}")
    vk_format, le_dtype = _FORMATS[values.dtype]
    type_size = values.dtype.itemsize
    nz, ny, nx = values.shape
    raw = np.ascontiguousarray(values, dtype=le_dtype).tobytes()
    if zstd:
        import zstandard

        data, scheme = zstandard.ZstdCompressor(level=ZSTD_LEVEL).compress(raw), _SUPERCOMPRESSION_ZSTD
    else:
        data, scheme = raw, 0

    dfd = _dfd(values.dtype, type_size)
    kvd = _kvd(
        {
            META_KEY: json.dumps(meta, separators=(",", ":")),
            "KTXorientation": ORIENTATION,
            "KTXwriter": WRITER,
        }
    )
    dfd_offset = _HEADER_SIZE + _LEVEL_INDEX_SIZE
    kvd_offset = dfd_offset + len(dfd)
    # Level data starts on lcm(typeSize, 4), which is 4 for every format here.
    level_offset = _align(kvd_offset + len(kvd), 4)

    header = IDENTIFIER + struct.pack(
        "<9I", vk_format, type_size, nx, ny, nz, 0, 1, 1, scheme
    )  # layerCount 0, faceCount 1, levelCount 1
    header += struct.pack("<4I2Q", dfd_offset, len(dfd), kvd_offset, len(kvd), 0, 0)
    level_index = struct.pack("<3Q", level_offset, len(data), len(raw))
    padding = bytes(level_offset - (kvd_offset + len(kvd)))
    path.write_bytes(header + level_index + dfd + kvd + padding + data)


def _dfd(dtype: np.dtype, type_size: int) -> bytes:
    """dfdTotalSize followed by one basic descriptor block with a single red sample."""
    if dtype == np.uint8:
        channel_type = 0  # KHR_DF_CHANNEL_RGBSDA_RED, unsigned normalized
        lower, upper = 0, 255
    else:
        channel_type = _KHR_DF_SAMPLE_DATATYPE_FLOAT | _KHR_DF_SAMPLE_DATATYPE_SIGNED
        lower, upper = _FLOAT_LOWER, _FLOAT_UPPER
    block_size = 24 + 16
    block = struct.pack("<I", 0)  # vendorId 0 (Khronos), descriptorType 0 (basic)
    block += struct.pack("<HH", 2, block_size)  # versionNumber 2 (KDF 1.3)
    block += struct.pack(
        "<4B", _KHR_DF_MODEL_RGBSDA, _KHR_DF_PRIMARIES_UNSPECIFIED, _KHR_DF_TRANSFER_LINEAR, 0
    )
    block += bytes(4)  # texelBlockDimension 1x1x1x1, stored as value - 1
    block += struct.pack("<8B", type_size, 0, 0, 0, 0, 0, 0, 0)  # bytesPlane0..7
    block += struct.pack("<HBB", 0, type_size * 8 - 1, channel_type)  # bitOffset, bitLength - 1
    block += bytes(4)  # samplePosition
    block += struct.pack("<II", lower, upper)
    return struct.pack("<I", 4 + len(block)) + block


def _kvd(pairs: dict[str, str]) -> bytes:
    """Key/value pairs sorted by key, NUL-terminated, each padded to 4 bytes."""
    out = bytearray()
    for key in sorted(pairs):
        entry = key.encode() + b"\0" + pairs[key].encode() + b"\0"
        out += struct.pack("<I", len(entry)) + entry
        out += bytes(_align(len(entry), 4) - len(entry))
    return bytes(out)


def _align(n: int, a: int) -> int:
    return (n + a - 1) // a * a
