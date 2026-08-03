"""Tests for the RAW565 full-color encoder (Task 7), ported from videopack.py.

These pin scripts/pack_beta.py's to_rgb565/rle_encode/rle_decode/build_raw565_sprite
against the numpy reference behaviour: no palette, no transparency, RGB565
texels, with optional per-row RLE kept only when it actually shrinks.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

import pack_beta


def _noise(w, h, seed=7):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), "RGB")


def _flat(w, h, color=(30, 200, 90)):
    return Image.new("RGB", (w, h), color)


def test_to_rgb565_size():
    texels = pack_beta.to_rgb565(_flat(64, 64), 64)
    assert len(texels) == 64 * 64 * 2


def test_rle_roundtrip_noise():
    img = _noise(120, 120)
    texels = pack_beta.to_rgb565(img, 120)
    payload = pack_beta.rle_encode(texels, 120, 120)
    assert pack_beta.rle_decode(payload, 120, 120) == texels


def test_rle_roundtrip_flat_compresses():
    texels = pack_beta.to_rgb565(_flat(240, 240), 240)
    payload = pack_beta.rle_encode(texels, 240, 240)
    assert pack_beta.rle_decode(payload, 240, 240) == texels
    assert len(payload) < len(texels) // 10   # flat color must compress hard


def test_build_raw565_sprite_picks_smaller_encoding():
    noisy = pack_beta.to_rgb565(_noise(32, 32), 32)
    blob = pack_beta.build_raw565_sprite(noisy, 32, 32, flags=pack_beta.OCT_FLAG_RAW565)
    hdr = pack_beta.parse_bmp_header(blob)
    assert hdr.compression == pack_beta.RAW565_PLAIN   # noise doesn't shrink under RLE
    flat = pack_beta.to_rgb565(_flat(32, 32), 32)
    blob = pack_beta.build_raw565_sprite(flat, 32, 32, flags=pack_beta.OCT_FLAG_RAW565)
    assert pack_beta.parse_bmp_header(blob).compression == pack_beta.RAW565_RLE


def test_rle_roundtrip_half_flat_half_noise():
    # left half of each row is flat (long runs), right half is noise (literals),
    # so every row forces the encoder to interleave a run token with literal
    # blocks -- this exercises the run/literal ordering within one row.
    w, h = 64, 40
    left = np.zeros((h, w // 2, 3), dtype=np.uint8)
    left[:, :] = (10, 20, 30)
    rng = np.random.default_rng(3)
    right = rng.integers(0, 255, (h, w // 2, 3), dtype=np.uint8)
    arr = np.concatenate([left, right], axis=1)
    img = Image.fromarray(arr, "RGB")

    texels = pack_beta.to_rgb565(img, (w, h))
    payload = pack_beta.rle_encode(texels, w, h)
    assert pack_beta.rle_decode(payload, w, h) == texels
