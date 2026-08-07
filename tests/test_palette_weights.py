"""Median cut must be weighted by pixel population, not by unique colour.

Measured on the reference corpus (Task 4 parity run): the ``eyes*`` bucket is
41 sprites sharing a 4-colour (2-bit) palette. The art is a white eye on a
solid black field, but every unique colour entered the cut with weight 1, so
14,400 black pixels counted exactly as much as one stray antialiased pixel —
black and white both fell out and the whole animation packed as three shades
of the background purple (premultiplied mean abs error 58/255 against the
source art, vs 1.9 for ``utils.exe``).

``median_cut`` has always taken ``(colour, weight)`` pairs; the callers just
passed 1. These tests pin the population weighting end to end.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from pack_codec import (
    build_config_palettes,
    extract_per_sprite_color_counts,
    extract_per_sprite_colors,
    median_cut,
)
from packtxt import parse_pack_txt_text


def _write(path: Path, arr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA").save(path)


def _solid(w: int, h: int, rgba) -> np.ndarray:
    a = np.zeros((h, w, 4), dtype=np.uint8)
    a[:, :] = rgba
    return a


# ── the primitive ───────────────────────────────────────────────────────────

def test_median_cut_already_honours_weights():
    """Not a new capability - the callers simply never used it."""
    dominant = (0, 0, 0, 31)
    speckles = [(200 + i, 200, 200, 31) for i in range(20)]
    weighted = [(dominant, 10000)] + [(c, 1) for c in speckles]
    out = median_cut(weighted, 2)
    assert any(c[0] <= 8 for c in out), out


# ── the extractor ───────────────────────────────────────────────────────────

def test_color_counts_are_pixel_counts(tmp_path: Path):
    img = np.zeros((4, 4, 4), dtype=np.uint8)
    img[:, :] = (0, 0, 0, 255)          # 16 px black
    img[0, 0] = (255, 255, 255, 255)    # 1 px white
    _write(tmp_path / "s.png", img)

    counts = extract_per_sprite_color_counts([str(tmp_path / "s.png")])["s"]
    assert sum(counts.values()) == 16
    assert max(counts.values()) == 15
    assert len(counts) == 2


def test_fully_transparent_pixels_are_not_counted(tmp_path: Path):
    img = np.zeros((4, 4, 4), dtype=np.uint8)   # alpha 0 everywhere
    img[0, 0] = (10, 20, 30, 255)
    _write(tmp_path / "s.png", img)

    counts = extract_per_sprite_color_counts([str(tmp_path / "s.png")])["s"]
    assert sum(counts.values()) == 1


def test_set_view_still_matches_the_counted_keys(tmp_path: Path):
    img = np.zeros((8, 8, 4), dtype=np.uint8)
    img[:, :] = (10, 20, 30, 255)
    img[0, :] = (200, 100, 50, 128)
    _write(tmp_path / "s.png", img)
    files = [str(tmp_path / "s.png")]

    assert set(extract_per_sprite_color_counts(files)["s"]) \
        == extract_per_sprite_colors(files)["s"]


# ── the corpus shape, reproduced in miniature ───────────────────────────────

_PACK_TXT = "exported\n\n4\neye*\n"


def test_a_dominant_flat_colour_survives_a_4_colour_bucket(tmp_path: Path):
    """The eyes bucket in miniature: one huge black field + speckle noise."""
    exported = tmp_path / "exported"
    _write(exported / "eye_bg.png", _solid(64, 64, (0, 0, 0, 255)))

    speckle = np.zeros((8, 8, 4), dtype=np.uint8)
    for i in range(8):
        for j in range(8):
            speckle[i, j] = (120 + i * 4, 110 + j * 4, 180, 255)
    _write(exported / "eye_noise.png", speckle)

    config = parse_pack_txt_text(_PACK_TXT)
    _assign, palettes, _unmatched = build_config_palettes(
        [str(p) for p in sorted(exported.glob("*.png"))], config)

    colors = palettes[0][0]
    assert len(colors) == 4
    darkest = min(colors[1:], key=lambda c: c[0] + c[1] + c[2])
    assert sum(darkest[:3]) <= 24, \
        f"the 4096-pixel black field did not survive the cut: {colors}"


def test_speckles_do_not_crowd_out_two_dominant_colours(tmp_path: Path):
    exported = tmp_path / "exported"
    _write(exported / "eye_black.png", _solid(40, 40, (0, 0, 0, 255)))
    _write(exported / "eye_white.png", _solid(40, 40, (255, 255, 255, 255)))

    speckle = np.zeros((10, 10, 4), dtype=np.uint8)
    for i in range(10):
        for j in range(10):
            speckle[i, j] = (100 + i, 100 + j, 100, 255)
    _write(exported / "eye_noise.png", speckle)

    config = parse_pack_txt_text(_PACK_TXT)
    _assign, palettes, _unmatched = build_config_palettes(
        [str(p) for p in sorted(exported.glob("*.png"))], config)

    colors = palettes[0][0][1:]
    assert any(sum(c[:3]) <= 24 for c in colors), colors
    assert any(sum(c[:3]) >= 720 for c in colors), colors


def test_small_palettes_are_unaffected_when_everything_fits(tmp_path: Path):
    """Under the budget there is no cut, so weighting cannot change anything."""
    exported = tmp_path / "exported"
    _write(exported / "eye_a.png", _solid(4, 4, (0, 0, 0, 255)))
    _write(exported / "eye_b.png", _solid(4, 4, (255, 255, 255, 255)))

    config = parse_pack_txt_text(_PACK_TXT)
    _assign, palettes, _unmatched = build_config_palettes(
        [str(p) for p in sorted(exported.glob("*.png"))], config)

    colors = palettes[0][0]
    assert colors[0] == (0, 0, 0, 0)
    assert {c[:3] for c in colors[1:]} >= {(0, 0, 0), (255, 255, 255)}
