"""Tiny dependency-free PNG writer for before/after previews (COGs are used in real mode)."""
from __future__ import annotations

import struct
import zlib

import numpy as np


def _chunk(tag: bytes, data: bytes) -> bytes:
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].astype(np.uint8).tobytes() for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def ndvi_rgb(ndvi: np.ndarray, scale: int = 8) -> np.ndarray:
    t = np.clip((ndvi + 0.1) / 1.0, 0, 1)
    r = (200 * (1 - t) + 20 * t).astype(np.uint8)
    g = (150 * (1 - t) + 150 * t).astype(np.uint8)
    b = (110 * (1 - t) + 30 * t).astype(np.uint8)
    img = np.stack([r, g, b], axis=-1)
    return np.kron(img, np.ones((scale, scale, 1), dtype=np.uint8))
