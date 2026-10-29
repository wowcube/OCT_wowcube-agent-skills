"""RAW565 sprites must carry utils.exe-style on-screen pivots.

A regular (x2 upscaled) sprite of authored width w is centred at w - 0.5 on
screen; a fullsize (1:1) sprite at (w - 1) / 2. The generic (w - 1) / 2 for a
regular full-color sprite shifted it by half its size (a real game showed
2xGAP black bars across all 24 screens until fix_pivots.py patched the pack).
"""
from __future__ import annotations

import struct

from pack_beta import OCT_FLAG_FULLSIZE, build_raw565_sprite


def _pivot(blob: bytes) -> tuple[float, float]:
    return struct.unpack_from("<ff", blob, 4)


def test_regular_full_color_sprite_pivot_is_on_screen_centre():
    w, h = 120, 60
    blob = build_raw565_sprite(b"\x00\x00" * w * h, w, h, flags=0)
    assert _pivot(blob) == (w - 0.5, h - 0.5)


def test_fullsize_full_color_sprite_pivot_is_native_centre():
    w, h = 240, 240
    blob = build_raw565_sprite(b"\x00\x00" * w * h, w, h, flags=OCT_FLAG_FULLSIZE)
    assert _pivot(blob) == ((w - 1) / 2, (h - 1) / 2)
