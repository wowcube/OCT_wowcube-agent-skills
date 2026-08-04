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


def test_rle_roundtrip_wide_noise_row_splits_literals():
    # a row of 300 noisy texels exceeds MAX_LITERAL (128) per control byte,
    # so this exercises the literal-block-split branch in rle_blocks.
    w, h = 300, 4
    img = _noise(w, h, seed=11)
    texels = pack_beta.to_rgb565(img, (w, h))
    payload = pack_beta.rle_encode(texels, w, h)
    assert pack_beta.rle_decode(payload, w, h) == texels


def _gradient(w, h):
    """Photo-like smooth gradient: the banding-prone worst case for 565."""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    arr[:, :, 1] = np.linspace(255, 0, w, dtype=np.uint8)[None, :]
    arr[:, :, 2] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    return Image.fromarray(arr, "RGB")


# ── rounding: nearest 565 level, not the truncated one ──────────────────────

def test_to_rgb565_rounds_to_nearest_level():
    # one row holding every 8-bit value: each channel must land on the level
    # whose reconstruction is nearest (round(v * levels / 255)), never the floor
    ramp = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
    texels = np.frombuffer(
        pack_beta.to_rgb565(Image.fromarray(ramp, "RGB"), (256, 1)), dtype="<u2")
    for v in range(256):
        t = int(texels[v])
        assert (t >> 11) & 0x1F == round(v * 31 / 255), f"r5 for {v}"
        assert (t >> 5) & 0x3F == round(v * 63 / 255), f"g6 for {v}"
        assert t & 0x1F == round(v * 31 / 255), f"b5 for {v}"


def test_to_rgb565_not_truncation():
    # 200 >> 3 == 25 (the old truncation), but level 24 reconstructs to ~197
    # vs level 25 -> ~206, so the NEAREST level for 200 is 24; green likewise
    # 200 >> 2 == 50 vs nearest 49
    texels = np.frombuffer(
        pack_beta.to_rgb565(_flat(4, 4, (200, 200, 200)), 4), dtype="<u2")
    t = int(texels[0])
    assert (t >> 11) & 0x1F == 24
    assert (t >> 5) & 0x3F == 49
    assert t & 0x1F == 24


# ── optional Floyd-Steinberg dithering ───────────────────────────────────────

def test_dither_roundtrips_rle_bit_exact():
    # dithering happens BEFORE encoding, so RLE must stay lossless on the
    # dithered texels — full 240x240, the real full-screen case
    texels = pack_beta.to_rgb565(_gradient(240, 240), (240, 240), dither=True)
    assert len(texels) == 240 * 240 * 2
    payload = pack_beta.rle_encode(texels, 240, 240)
    assert pack_beta.rle_decode(payload, 240, 240) == texels


def test_dither_differs_from_undithered():
    img = _gradient(64, 64)
    assert pack_beta.to_rgb565(img, (64, 64), dither=True) != \
        pack_beta.to_rgb565(img, (64, 64))


def test_dither_on_lattice_colors_is_noop():
    # pure white/black sit exactly on the 565 lattice: no error to diffuse,
    # so dithering must not perturb them
    for color, word in (((255, 255, 255), b"\xff\xff"), ((0, 0, 0), b"\x00\x00")):
        texels = pack_beta.to_rgb565(_flat(16, 16, color), 16, dither=True)
        assert texels == word * (16 * 16)


def test_dither_preserves_mean_brightness():
    # error diffusion trades banding for noise but must not shift the mean:
    # reconstruct the red channel and compare against the source ramp mean
    img = _gradient(120, 120)
    texels = np.frombuffer(
        pack_beta.to_rgb565(img, (120, 120), dither=True), dtype="<u2")
    r_rec = ((texels >> 11) & 0x1F).astype(np.float64) * (255.0 / 31.0)
    src_mean = np.asarray(img, dtype=np.float64)[:, :, 0].mean()
    assert abs(r_rec.mean() - src_mean) < 1.0


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
