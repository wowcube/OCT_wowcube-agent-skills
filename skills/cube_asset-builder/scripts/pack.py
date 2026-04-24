#!/usr/bin/env python3
"""
WowCube Packed Sprite Encoder
=============================

Packs RGBA PNG sprites into the WowCube packed format (single-pixel-high
PNG strips with embedded header, scanline trims, and bit-packed RLE data).

Two operating modes:

  1. Re-pack (default): reads existing packed/ sprites for header metadata
     (pivot, flags, palette index, etc.) and re-encodes pixel data from
     the exported/ folder.  Use this after editing exported PNGs.

  2. Standalone: packs exported PNGs from scratch, generating headers and
     building a new palette.

Packed sprite format:
  - 48-byte header (octBmp_t without PackerSizes)
  - Scanline trim array (H bytes, aligned to multiple of 4)
  - Bit-packed texel stream (palette symbol + RLE length code)

Usage:
  python pack.py                                    # re-pack all (reuse existing palette)
  python pack.py exported/coin.png                  # re-pack one file
  python pack.py --build-palette                    # auto-build palette (try 16 colors first)
  python pack.py --build-palette --max-colors 64    # limit palette size
  python pack.py --build-palette --target-colors 16 # force exact palette size
"""

from __future__ import annotations

import argparse
import csv
import heapq
import math
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)

from config import (
    A_MAX, ALPHA5_MASK, ALPHA5_SHIFT,
    B_MAX, BMFONT_BLOCK_CHARS, BMFONT_BLOCK_PAGES, BMFONT_CHAR_SIZE,
    BMFONT_FIRST_PRINTABLE, BMFONT_MAGIC, BMFONT_VERSION,
    BYTES_PER_RGBA,
    COMPR1_LEN_DECODE_MASK, DEFAULT_ASSET_NAME, DEFAULT_LAYER_MARK,
    DEFAULT_OFFSET_BITNESS, DEFAULT_PALETTE_FILENAME,
    DEFAULT_QUALITY_THRESHOLD, G_MAX,
    HDR_OFF_COMPRESSION, HDR_OFF_FLAGS, HDR_OFF_HEIGHT, HDR_OFF_NUM_PIXELS,
    HDR_OFF_PIDX, HDR_OFF_PIVOT_X, HDR_OFF_PIVOT_Y, HDR_OFF_WIDTH,
    HEADER_SIZE, MAP_FILENAME_PREFIX, MEDIAN_CUT_CHANNEL_WEIGHTS,
    NUMBER_FIELD_MASK, OCT_PLACE_RATE_DEFAULT,
    PACKED_COLOR_MASK, PAL_DESCRIPTOR_SIZE, PAL_MAX_PALETTES,
    PAL_MAX_TOTAL_COLORS, PAL_TRANSPARENT_IDX, PALETTE_SIZES_TRIED,
    PALETTE_SPRITE_NAME, PALETTE_TIERS_USABLE, PIVOT_HALFPIX, PIVOT_SCALE,
    PLACEHOLDER_SPRITE_NAME, PLACEHOLDER_SPRITE_PIVOT,
    PSL_CENTER_X_OFFSET, PSL_CENTER_Y_OFFSET, PSL_GROUP_OFFSET,
    PSL_GROUP_SIZE, PSL_HEADER_SIZE, PSL_LAYERMARK_OFFSET,
    PSL_NAME_OFFSET, PSL_NAME_SIZE, PSL_NUMBER_OFFSET, PSL_RATE_OFFSET,
    PSL_RATE_SIZE, PSL_RECORD_SIZE, PSL_RESERVED_1, PSL_RESERVED_2,
    PSL_SIDE_OFFSET, PSL_TYPE_ASSET, PSL_TYPE_MAP, PSL_TYPE_OFFSET,
    PSL_TYPE_SIZE, PSL_XYWH_OFFSET, PlaceFlag, PRESPLIT_MASK,
    R_MAX, RGB565_MASK, RLE_ENCODE, RLE_MAX_RUN, SpriteFlag, WORD_BITS,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-compiled regular expressions (hot paths use these)
# ─────────────────────────────────────────────────────────────────────────────

# Metadata stop chars:
#  — _META_STOPS_VALUE: used inside [^...] when extracting a value for a
#    given suffix, so we stop before the next suffix begins. Must include
#    all possible suffix markers ($, %, &, #, !, =).
#  — _META_STOPS_BASE: used by parse_layer_metadata's base split
#    (matches the original regex `[%&#$!]`).
#  — _META_STOPS_PNG: used by normalize_layer_name's png_name split
#    (matches the original behaviour which stripped only `%&=!`).
_META_STOPS_VALUE = r'%&=$#!'
_META_STOPS_BASE  = r'%&#$!'
_META_STOPS_PNG   = r'%&=!'

_RE_META_OBJ     = re.compile(rf'\$([^{_META_STOPS_VALUE}]+)')
_RE_META_TYPE    = re.compile(rf'%([^{_META_STOPS_VALUE}]+)')
_RE_META_GROUP   = re.compile(rf'&([^{_META_STOPS_VALUE}]+)')
_RE_META_TAG     = re.compile(rf'#([^{_META_STOPS_VALUE}]+)')
_RE_META_SPLIT_BASE = re.compile(rf'[{_META_STOPS_BASE}]')
_RE_META_SPLIT_PNG  = re.compile(rf'[{_META_STOPS_PNG}]')
_RE_META_CSV_SPL    = re.compile(r'([%&=!])')
_RE_RATE_SUFFIX  = re.compile(r'!rate(\d+)', re.I)
_RE_RATE_INLINE  = re.compile(r'rate(\d+)', re.I)
_RE_SPRITE_NUM   = re.compile(r'=([0-9]+)')
_RE_SEQ_FRAME    = re.compile(r'^(.+?)_(\d{2,})$')


def _norm(s: str) -> str:
    """Normalize a free-form string to a lowercase snake-case identifier."""
    return s.lower().replace('-', '_').replace(' ', '_')


# ─────────────────────────────────────────────────────────────────────────────
# Color helpers
# ─────────────────────────────────────────────────────────────────────────────

def rgba_to_rgb565(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to 16-bit RGB565."""
    return (((r >> 3) & R_MAX) << 11) | (((g >> 2) & G_MAX) << 5) | ((b >> 3) & B_MAX)


def rgb565_to_presplit(rgb565: int) -> int:
    """Convert RGB565 to pre-split 0x07e0f81f format for fast blending."""
    return (rgb565 | (rgb565 << 16)) & PRESPLIT_MASK


def encode_palette_color(r: int, g: int, b: int, a: int, has_alpha: bool) -> int:
    """Encode RGBA8888 into the uint32 storage format used in pal.png.

    Unifies the formerly duplicated rgba_to_palette_color /
    palette_color_to_uint32 helpers.
    """
    rgb565 = rgba_to_rgb565(r, g, b)
    if not has_alpha:
        return rgb565
    alpha5 = (a >> 3) & ALPHA5_MASK
    return (alpha5 << ALPHA5_SHIFT) | rgb565_to_presplit(rgb565)


def decode_palette_color(c32: int, has_alpha: bool) -> tuple[int, int, int, int]:
    """Inverse of encode_palette_color — returns (r8, g8, b8, a8)."""
    if has_alpha:
        alpha5 = (c32 >> ALPHA5_SHIFT) & ALPHA5_MASK
        alpha8 = (alpha5 << 3) | (alpha5 >> 2)
        packed = c32 & PACKED_COLOR_MASK
        rgb565 = (packed | (packed >> 16)) & RGB565_MASK
    else:
        rgb565 = c32 & RGB565_MASK
        alpha8 = 255
    r5 = (rgb565 >> 11) & R_MAX
    g6 = (rgb565 >> 5) & G_MAX
    b5 = rgb565 & B_MAX
    return (
        (r5 << 3) | (r5 >> 2),
        (g6 << 2) | (g6 >> 4),
        (b5 << 3) | (b5 >> 2),
        alpha8,
    )


def quantize_565_a5(r8: int, g8: int, b8: int, a8: int) -> tuple[int, int, int, int]:
    """Quantize RGBA8888 to (r5, g6, b5, a5) tuple."""
    return ((r8 >> 3) & R_MAX, (g8 >> 2) & G_MAX,
            (b8 >> 3) & B_MAX, (a8 >> 3) & A_MAX)


def expand_565_a5(r5: int, g6: int, b5: int, a5: int) -> tuple[int, int, int, int]:
    """Expand (r5, g6, b5, a5) back to RGBA8888."""
    return (
        (r5 << 3) | (r5 >> 2),
        (g6 << 2) | (g6 >> 4),
        (b5 << 3) | (b5 >> 2),
        (a5 << 3) | (a5 >> 2),
    )


def symbol_bitness_for_size(palette_size: int) -> int:
    """Minimum number of bits required to encode ``palette_size`` indices."""
    if palette_size <= 1:
        return 1
    return max(1, math.ceil(math.log2(palette_size)))


def pad_to_multiple(data: bytes | bytearray, alignment: int) -> bytes:
    """Pad ``data`` with NULs so its length is a multiple of ``alignment``."""
    remainder = len(data) % alignment
    if remainder == 0:
        return bytes(data)
    return bytes(data) + b'\x00' * (alignment - remainder)


# ─────────────────────────────────────────────────────────────────────────────
# Palette
# ─────────────────────────────────────────────────────────────────────────────

class EncoderPalette:
    """Palette for encoding: maps RGBA colors to palette indices.

    The hot path ``find_nearest_batch`` uses a fully vectorised numpy
    argmin, which is orders of magnitude faster than the per-pixel Python
    loop the original version relied on.
    """

    __slots__ = ('colors', 'has_alpha', '_cache', '_colors_arr', '_nz_idx')

    def __init__(self, colors_rgba: list[tuple[int, int, int, int]],
                 has_alpha: bool = True) -> None:
        self.colors = colors_rgba
        self.has_alpha = has_alpha
        self._cache: dict[tuple[int, int, int, int], int] = {}

        # Pre-compute numpy view of non-transparent palette entries. Index
        # 0 is the transparent slot (skipped during nearest search).
        arr = np.asarray(colors_rgba, dtype=np.int32)
        self._colors_arr = arr
        # Indices we actually search over. If palette has just index 0
        # fall back to a single-entry fake to avoid empty argmin.
        self._nz_idx = np.arange(1, len(colors_rgba), dtype=np.int32) \
            if len(colors_rgba) > 1 else np.array([0], dtype=np.int32)

    # ── Scalar lookup (kept for backward compatibility) ────────────────
    def find_nearest(self, r: int, g: int, b: int, a: int) -> int:
        if a == 0:
            return PAL_TRANSPARENT_IDX
        key = (r, g, b, a)
        hit = self._cache.get(key)
        if hit is not None:
            return hit

        target = np.array([r, g, b, a], dtype=np.int32)
        diffs = self._colors_arr[self._nz_idx] - target
        dists = (diffs * diffs).sum(axis=1)
        best = int(self._nz_idx[int(dists.argmin())])
        self._cache[key] = best
        return best

    # ── Batch lookup: full image quantisation in one shot ──────────────
    def quantize_image(self, pixels: np.ndarray) -> np.ndarray:
        """Quantize an H×W×4 RGBA image into an H×W index array.

        Transparent pixels (a == 0) collapse to index 0 regardless of RGB.
        """
        h, w = pixels.shape[:2]
        flat = pixels.reshape(-1, 4).astype(np.int32)

        out = np.zeros(flat.shape[0], dtype=np.int32)
        opaque_mask = flat[:, 3] != 0

        if opaque_mask.any():
            opaque = flat[opaque_mask]
            # Distance to every non-transparent palette entry
            pal = self._colors_arr[self._nz_idx]        # (P, 4)
            diffs = opaque[:, None, :] - pal[None, :, :]  # (N, P, 4)
            dists = (diffs * diffs).sum(axis=2)         # (N, P)
            nearest_local = dists.argmin(axis=1)        # (N,)
            out[opaque_mask] = self._nz_idx[nearest_local]
        return out.reshape(h, w)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-palette construction (median cut)
# ─────────────────────────────────────────────────────────────────────────────

def collect_sprite_colors(file_list: Iterable[str]) -> dict[tuple[int, int, int, int], int]:
    """Scan exported PNGs and collect all non-transparent color counts.

    Returns dict ``(r8, g8, b8, a8) -> pixel_count``.
    Fully vectorised via numpy.unique for speed.
    """
    counts: dict[tuple[int, int, int, int], int] = {}
    for fpath in file_list:
        path = Path(fpath)
        if path.stem in (PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME) \
                or path.suffix.lower() != '.png':
            continue
        try:
            pixels = np.asarray(Image.open(fpath).convert('RGBA')).reshape(-1, 4)
        except Exception:
            continue

        opaque = pixels[pixels[:, 3] > 0]
        if opaque.size == 0:
            continue

        # Pack each RGBA into a single uint32 key for fast np.unique
        keys = (opaque[:, 0].astype(np.uint32) << 24) \
             | (opaque[:, 1].astype(np.uint32) << 16) \
             | (opaque[:, 2].astype(np.uint32) << 8) \
             |  opaque[:, 3].astype(np.uint32)
        unique, cnts = np.unique(keys, return_counts=True)

        for k, c in zip(unique.tolist(), cnts.tolist()):
            tup = ((k >> 24) & 0xFF, (k >> 16) & 0xFF,
                   (k >> 8) & 0xFF, k & 0xFF)
            counts[tup] = counts.get(tup, 0) + int(c)
    return counts


def unique_quantized_colors(color_counts: dict[tuple[int, int, int, int], int]
                            ) -> list[tuple[tuple[int, int, int, int], int]]:
    """Aggregate color counts by (r5, g6, b5, a5) buckets."""
    quantized: dict[tuple[int, int, int, int], int] = {}
    for (r8, g8, b8, a8), count in color_counts.items():
        q = quantize_565_a5(r8, g8, b8, a8)
        quantized[q] = quantized.get(q, 0) + count
    return list(quantized.items())


class MedianCutBox:
    """A box of colors for median-cut quantization."""

    __slots__ = ('items', 'total_weight', 'ranges')

    _MAX_CHANNELS = (R_MAX, G_MAX, B_MAX, A_MAX)

    def __init__(self, colors_weights: list[tuple[tuple[int, int, int, int], int]]) -> None:
        self.items = colors_weights
        self.total_weight = sum(w for _, w in colors_weights)
        self._compute_ranges()

    def _compute_ranges(self) -> None:
        if not self.items:
            self.ranges = [(0, 0)] * 4
            return
        # Vector op — much faster than 4 Python comprehensions
        arr = np.asarray([c for c, _ in self.items], dtype=np.int16)
        mins = arr.min(axis=0)
        maxs = arr.max(axis=0)
        self.ranges = list(zip(mins.tolist(), maxs.tolist()))

    @property
    def max_range_channel(self) -> int:
        """Channel index with the widest weighted range."""
        best_ch = 0
        best_span = -1.0
        for ch, (lo, hi) in enumerate(self.ranges):
            span = (hi - lo) * MEDIAN_CUT_CHANNEL_WEIGHTS[ch]
            if span > best_span:
                best_span = span
                best_ch = ch
        return best_ch

    @property
    def can_split(self) -> bool:
        return len(self.items) >= 2 and any(hi > lo for lo, hi in self.ranges)

    def split(self) -> tuple['MedianCutBox', 'MedianCutBox']:
        """Split box at median along the widest channel."""
        ch = self.max_range_channel
        self.items.sort(key=lambda x: x[0][ch])

        half = self.total_weight / 2
        cumulative = 0
        split_idx = 1
        for i, (_, w) in enumerate(self.items):
            cumulative += w
            if cumulative >= half and i > 0:
                split_idx = i
                break
        if split_idx == 0:
            split_idx = 1

        return (MedianCutBox(self.items[:split_idx]),
                MedianCutBox(self.items[split_idx:]))

    def representative(self) -> tuple[int, int, int, int]:
        """Weighted average color of the box, quantized to (r5, g6, b5, a5)."""
        if not self.items:
            return (0, 0, 0, 0)
        # Vectorised weighted average
        arr = np.asarray([c for c, _ in self.items], dtype=np.float64)
        w = np.asarray([w for _, w in self.items], dtype=np.float64)
        avg = (arr * w[:, None]).sum(axis=0) / self.total_weight
        clamped = np.clip(np.round(avg), 0, self._MAX_CHANNELS).astype(int)
        return (int(clamped[0]), int(clamped[1]),
                int(clamped[2]), int(clamped[3]))


def median_cut(quantized_colors_weights: list[tuple[tuple[int, int, int, int], int]],
               target_count: int) -> list[tuple[int, int, int, int]]:
    """Reduce colors to target_count using median-cut quantization."""
    if len(quantized_colors_weights) <= target_count:
        return [c for c, _ in quantized_colors_weights]

    initial = MedianCutBox(quantized_colors_weights)
    heap: list[tuple[int, int, MedianCutBox]] = [(-initial.total_weight, 0, initial)]
    frozen: list[MedianCutBox] = []
    box_id = 1

    while len(heap) + len(frozen) < target_count and heap:
        _, _, box = heapq.heappop(heap)
        if not box.can_split:
            frozen.append(box)
            continue
        b1, b2 = box.split()
        for b in (b1, b2):
            if b.can_split:
                heapq.heappush(heap, (-b.total_weight, box_id, b))
                box_id += 1
            else:
                frozen.append(b)

    result = [b.representative() for b in frozen]
    result += [item[2].representative() for item in heap]
    return result[:target_count]


def measure_palette_quality(
    color_counts: dict[tuple[int, int, int, int], int],
    palette_rgba: list[tuple[int, int, int, int]],
) -> tuple[float, int, float]:
    """Return (mean_error, max_error, pct_exact) in RGB888 space."""
    if not color_counts:
        return 0.0, 0, 100.0

    pal = EncoderPalette(palette_rgba, has_alpha=True)
    total_pixels = 0
    total_error = 0.0
    max_error = 0
    exact_count = 0

    for (r, g, b, a), count in color_counts.items():
        if a == 0:
            continue
        idx = pal.find_nearest(r, g, b, a)
        pr, pg, pb, pa = pal.colors[idx]
        err = max(abs(r - pr), abs(g - pg), abs(b - pb), abs(a - pa))
        if err == 0:
            exact_count += count
        total_error += err * count
        if err > max_error:
            max_error = err
        total_pixels += count

    if total_pixels == 0:
        return 0.0, 0, 100.0
    return (total_error / total_pixels,
            max_error,
            100.0 * exact_count / total_pixels)


def _pad_palette_to_size(palette_rgba: list[tuple[int, int, int, int]],
                         size: int) -> list[tuple[int, int, int, int]]:
    """Pad palette with transparent entries until it has ``size`` colors."""
    if len(palette_rgba) < size:
        palette_rgba = palette_rgba + [(0, 0, 0, 0)] * (size - len(palette_rgba))
    return palette_rgba


def build_auto_palette(
    file_list: list[str],
    max_colors: int = 256,
    target_colors: int | None = None,
    quality_threshold: int = DEFAULT_QUALITY_THRESHOLD,
) -> tuple[EncoderPalette, int, int, list[tuple[int, int, int, int]]]:
    """Build a single palette from sprites. See module docstring for behaviour."""
    print("  Scanning sprites for color analysis...")
    color_counts = collect_sprite_colors(file_list)
    total_unique = len(color_counts)
    total_pixels = sum(color_counts.values())
    print(f"  Found {total_unique} unique RGBA colors across {total_pixels:,} opaque pixels")

    quant_colors = unique_quantized_colors(color_counts)
    unique_q = len(quant_colors)
    print(f"  After RGB565+A5 quantization: {unique_q} unique colors")

    if target_colors is not None:
        sizes_to_try: list[int] = [target_colors]
    else:
        sizes_to_try = [s for s in PALETTE_SIZES_TRIED if s <= max_colors] \
                        or [max_colors]

    best_pal = best_colors = None
    best_size = best_sym = 0

    for pal_size in sizes_to_try:
        usable = pal_size - 1
        print(f"\n  Trying palette size {pal_size} ({usable} usable colors)...")

        if unique_q <= usable:
            pal_q = [c for c, _ in quant_colors]
            print(f"    All {unique_q} quantized colors fit, no reduction needed")
        else:
            pal_q = median_cut(quant_colors, usable)
            print(f"    Median-cut reduced {unique_q} -> {len(pal_q)} colors")

        palette_rgba = [(0, 0, 0, 0)] + [expand_565_a5(*q) for q in pal_q]
        palette_rgba = _pad_palette_to_size(palette_rgba, pal_size)

        sym_bits = symbol_bitness_for_size(pal_size)
        mean_err, max_err, pct_exact = measure_palette_quality(color_counts, palette_rgba)
        print(f"    Quality: mean_err={mean_err:.2f}, max_err={max_err}, exact={pct_exact:.1f}%")

        best_pal = EncoderPalette(palette_rgba, has_alpha=True)
        best_size = pal_size
        best_sym = sym_bits
        best_colors = palette_rgba

        if target_colors is not None:
            break
        if mean_err <= quality_threshold:
            print(f"    -> Accepted! Mean error {mean_err:.2f} <= threshold {quality_threshold}")
            break
        print(f"    -> Mean error {mean_err:.2f} > threshold {quality_threshold}, trying larger...")

    print(f"\n  Final palette: {best_size} colors, {best_sym}-bit symbols")
    return best_pal, best_size, best_sym, best_colors


# ─────────────────────────────────────────────────────────────────────────────
# Multi-palette grouping
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PaletteGroup:
    """A group of sprites sharing one palette."""

    sprite_names: list[str] = field(default_factory=list)
    colors: set[tuple[int, int, int, int]] = field(default_factory=set)

    @property
    def num_unique(self) -> int:
        return len(self.colors)

    def add(self, name: str, colors: set[tuple[int, int, int, int]]) -> None:
        self.sprite_names.append(name)
        self.colors |= colors


def snap_color(r5: int, g6: int, b5: int, a5: int,
               tolerance: int) -> tuple[int, int, int, int]:
    """Snap a quantized color to a coarser grid to merge similar colors."""
    if tolerance <= 0:
        return (r5, g6, b5, a5)
    step = 2 * tolerance
    return (
        min(((r5 + tolerance) // step) * step, R_MAX),
        min(((g6 + tolerance) // step) * step, G_MAX),
        min(((b5 + tolerance) // step) * step, B_MAX),
        min(((a5 + tolerance) // step) * step, A_MAX),
    )


def extract_per_sprite_colors(
    file_list: Iterable[str],
    color_tolerance: int = 0,
) -> dict[str, set[tuple[int, int, int, int]]]:
    """Return the set of quantized colors each sprite uses.

    Vectorised via numpy.unique so large sheets process in milliseconds.
    """
    result: dict[str, set[tuple[int, int, int, int]]] = {}

    for fpath in file_list:
        path = Path(fpath)
        name = path.stem
        if name in (PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME) \
                or path.suffix.lower() != '.png':
            continue
        try:
            pixels = np.asarray(Image.open(fpath).convert('RGBA')).reshape(-1, 4)
        except Exception:
            result[name] = set()
            continue

        opaque = pixels[pixels[:, 3] > 0]
        if opaque.size == 0:
            result[name] = set()
            continue

        # Vectorised RGB565+A5 quantisation
        r5 = (opaque[:, 0] >> 3) & R_MAX
        g6 = (opaque[:, 1] >> 2) & G_MAX
        b5 = (opaque[:, 2] >> 3) & B_MAX
        a5 = (opaque[:, 3] >> 3) & A_MAX

        # Encode into a single uint32 key so np.unique can dedup fast
        keys = (r5.astype(np.uint32) << 24) | (g6.astype(np.uint32) << 16) \
             | (b5.astype(np.uint32) << 8)  |  a5.astype(np.uint32)
        unique = np.unique(keys)

        colors: set[tuple[int, int, int, int]] = set()
        for k in unique.tolist():
            tup = ((k >> 24) & 0xFF, (k >> 16) & 0xFF,
                   (k >> 8) & 0xFF, k & 0xFF)
            if color_tolerance > 0:
                tup = snap_color(*tup, color_tolerance)
            colors.add(tup)
        result[name] = colors
    return result


def _pick_tier(tiers: list[int], need: int) -> int:
    """Smallest tier that fits ``need`` colors; falls back to largest."""
    return next((t for t in tiers if t >= need), tiers[-1])


def _merge_smallest_groups(groups: list[tuple[PaletteGroup, int]],
                           tiers: list[int]) -> list[tuple[PaletteGroup, int]]:
    """Merge the two groups with the fewest unique colors into one."""
    groups.sort(key=lambda x: x[0].num_unique)
    g1, _ = groups.pop(0)
    g2, _ = groups.pop(0)
    merged = PaletteGroup()
    merged.sprite_names = g1.sprite_names + g2.sprite_names
    merged.colors = g1.colors | g2.colors
    groups.append((merged, _pick_tier(tiers, merged.num_unique)))
    return groups


def cluster_sprites_grouped(
    sprite_colors: dict[str, set[tuple[int, int, int, int]]],
    max_colors: int = 256,
    pre_reduce: int | None = None,
) -> list[tuple[PaletteGroup, int]]:
    """Cluster sprites into palette groups, preferring small palettes.

    Phase 0: pre-reduce oversized sprites via median-cut.
    Phase 1: greedy grouping at the smallest viable tier per group.
    Phase 2: shrink each group's tier to the actual minimum.
    Phase 3: merge until we fit engine limits (PAL_MAX_PALETTES, PAL_MAX_TOTAL_COLORS).
    """
    max_usable = min(max_colors - 1, max(PALETTE_TIERS_USABLE))
    tiers = [t for t in PALETTE_TIERS_USABLE if t <= max_usable] or [max_usable]

    if pre_reduce is None:
        pre_reduce = max_usable // 2
    pre_reduce = min(pre_reduce, max_usable)

    # Phase 0: pre-reduce large sprites
    reduced: dict[str, set[tuple[int, int, int, int]]] = {}
    reduced_count = 0
    for name, colors in sprite_colors.items():
        if len(colors) > pre_reduce:
            weighted = [(c, 1) for c in colors]
            reduced[name] = set(median_cut(weighted, pre_reduce))
            reduced_count += 1
        else:
            reduced[name] = colors
    if reduced_count:
        print(f"  Pre-reduced {reduced_count} sprites to <={pre_reduce} colors via median-cut")

    # Phase 1: greedy grouping — small sprites first (fonts, icons cluster nicely)
    sorted_sprites = sorted(reduced.items(), key=lambda x: len(x[1]))
    groups: list[tuple[PaletteGroup, int]] = []

    for name, colors in sorted_sprites:
        n = len(colors)
        if n == 0:
            if groups:
                groups[0][0].add(name, colors)
            else:
                g = PaletteGroup()
                g.add(name, colors)
                groups.append((g, tiers[0]))
            continue

        sprite_tier = _pick_tier(tiers, n)

        # Try to reuse an existing group without bumping its tier
        best_idx = None
        best_new = math.inf
        for i, (group, cur_tier) in enumerate(groups):
            combined = len(group.colors | colors)
            if combined <= cur_tier:
                new_colors = combined - group.num_unique
                if new_colors < best_new:
                    best_new = new_colors
                    best_idx = i

        if best_idx is not None:
            groups[best_idx][0].add(name, colors)
        else:
            g = PaletteGroup()
            g.add(name, colors)
            groups.append((g, sprite_tier))

    # Phase 2: shrink tiers
    groups = [(g, _pick_tier(tiers, g.num_unique)) for g, _ in groups]

    # Phase 3: merge if we bust engine limits
    def _total_colors(grps: list[tuple[PaletteGroup, int]]) -> int:
        return sum(t + 1 for _, t in grps)

    while len(groups) > PAL_MAX_PALETTES:
        groups = _merge_smallest_groups(groups, tiers)
    while _total_colors(groups) > PAL_MAX_TOTAL_COLORS and len(groups) > 1:
        groups = _merge_smallest_groups(groups, tiers)

    total_c = _total_colors(groups)
    if total_c > PAL_MAX_TOTAL_COLORS:
        print(f"  WARNING: {total_c} total palette colors exceeds engine limit of "
              f"{PAL_MAX_TOTAL_COLORS}!")

    groups.sort(key=lambda x: (x[1], -len(x[0].sprite_names)))
    return groups


def build_grouped_palettes(
    file_list: list[str],
    max_colors: int = 256,
    quality_threshold: int = DEFAULT_QUALITY_THRESHOLD,
    pre_reduce: int | None = None,
    color_tolerance: int = 0,
) -> tuple[dict[str, tuple[int, EncoderPalette, int]],
           list[tuple[list[tuple[int, int, int, int]], int]]]:
    """Build multiple palettes grouped by color similarity.

    Returns:
      sprite_assignments: dict name -> (pidx, EncoderPalette, symbol_bitness)
      all_palette_data:   list of (palette_colors_rgba, symbol_bitness)
    """
    print("  Scanning sprites for per-sprite color analysis...")
    if color_tolerance > 0:
        print(f"  Color tolerance: {color_tolerance} "
              f"(merging similar colors in 565 space)")
    sprite_colors = extract_per_sprite_colors(file_list, color_tolerance=color_tolerance)

    total_sprites = len(sprite_colors)
    total_unique = len(set().union(*sprite_colors.values())) if sprite_colors else 0
    print(f"  {total_sprites} sprites, {total_unique} unique quantized colors total")

    if sprite_colors:
        sizes = [len(c) for c in sprite_colors.values()]
        print(f"  Per-sprite unique colors: min={min(sizes)}, max={max(sizes)}")

    print(f"\n  Clustering into palette groups (max {max_colors} colors per group)...")
    groups = cluster_sprites_grouped(sprite_colors, max_colors, pre_reduce=pre_reduce)

    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] = {}
    all_palette_data: list[tuple[list[tuple[int, int, int, int]], int]] = []

    print(f"  Created {len(groups)} palette group(s):\n")

    for pidx, (group, tier) in enumerate(groups):
        pal_size = tier + 1
        sym_bits = symbol_bitness_for_size(pal_size)

        unique_colors = list(group.colors)
        if len(unique_colors) <= tier:
            pal_q = unique_colors
        else:
            weighted = [(c, 1) for c in unique_colors]
            pal_q = median_cut(weighted, tier)

        palette_rgba = [(0, 0, 0, 0)] + [expand_565_a5(*q) for q in pal_q]
        palette_rgba = _pad_palette_to_size(palette_rgba, pal_size)

        encoder_pal = EncoderPalette(palette_rgba, has_alpha=True)
        all_palette_data.append((palette_rgba, sym_bits))

        for name in group.sprite_names:
            sprite_assignments[name] = (pidx, encoder_pal, sym_bits)

        print(f"    [{pidx}] {pal_size} colors ({sym_bits}-bit), "
              f"{len(group.sprite_names)} sprites, {group.num_unique} unique colors")

    return sprite_assignments, all_palette_data


# ─────────────────────────────────────────────────────────────────────────────
# Palette I/O (pal.png)
# ─────────────────────────────────────────────────────────────────────────────

def save_palette_png(
    palette_colors_rgba: list[tuple[int, int, int, int]]
                        | list[list[tuple[int, int, int, int]]],
    output_path: str,
    has_alpha: bool = True,
) -> None:
    """Serialise one or more palettes into the WowCube pal.png container."""
    # Normalise to list-of-lists
    if palette_colors_rgba and isinstance(palette_colors_rgba[0], tuple):
        palette_list: list[list[tuple[int, int, int, int]]] = [palette_colors_rgba]  # type: ignore[list-item]
    else:
        palette_list = palette_colors_rgba  # type: ignore[assignment]

    num_palettes = len(palette_list)
    flags = int(SpriteFlag.ALPHA) if has_alpha else 0

    data = bytearray()
    data.extend(struct.pack('<I', num_palettes))

    # octPal_t descriptors (12 bytes each)
    cbi_offset = 0
    for pal_id, pal_colors in enumerate(palette_list):
        k = len(pal_colors) - 1
        blend = 0
        anims = 0
        data.append(pal_id & 0xFF)
        data.append(blend & 0xFF)
        data.append(k & 0xFF)
        data.append(anims & 0xFF)
        data.extend(struct.pack('<I', flags))
        data.extend(struct.pack('<i', cbi_offset))
        cbi_offset += len(pal_colors)

    # Color payload
    for pal_colors in palette_list:
        for (r8, g8, b8, a8) in pal_colors:
            data.extend(struct.pack('<I', encode_palette_color(r8, g8, b8, a8, has_alpha)))

    blob = pad_to_multiple(data, BYTES_PER_RGBA)
    width = len(blob) // BYTES_PER_RGBA
    Image.frombytes('RGBA', (width, 1), blob).save(output_path)

    sizes = [len(p) for p in palette_list]
    print(f"  Saved {num_palettes} palette(s) ({sizes}) to {output_path}")


def load_palette_for_encoding(pal_png_path: str) -> tuple[dict[int, EncoderPalette], bytes]:
    """Load pal.png and return EncoderPalette objects keyed by palette index."""
    img = Image.open(pal_png_path)
    raw = img.tobytes()

    num_palettes = struct.unpack_from('<I', raw, 0)[0]
    off = 4
    pal_descriptors: list[tuple[int, int, int, int, int, int]] = []

    for _ in range(num_palettes):
        pal_id = raw[off]
        blend  = raw[off + 1]
        k      = raw[off + 2]
        anims  = raw[off + 3]
        flags  = struct.unpack_from('<I', raw, off + 4)[0]
        cbi    = struct.unpack_from('<i', raw, off + 8)[0]
        pal_descriptors.append((pal_id, blend, k, anims, flags, cbi))
        off += PAL_DESCRIPTOR_SIZE

    colors_offset = off
    num_color_words = (len(raw) - colors_offset) // BYTES_PER_RGBA
    all_colors_raw = list(struct.unpack_from(f'<{num_color_words}I', raw, colors_offset))

    palettes: dict[int, EncoderPalette] = {}
    for pidx, (_pal_id, _blend, k, _anims, flags, cbi) in enumerate(pal_descriptors):
        has_alpha = bool(flags & SpriteFlag.ALPHA)
        num_colors = k + 1
        colors_raw = all_colors_raw[cbi:cbi + num_colors]

        # Index 0 is always transparent; raw[0] is therefore skipped.
        colors_rgba = [(0, 0, 0, 0)]
        colors_rgba.extend(decode_palette_color(c32, has_alpha) for c32 in colors_raw[1:])
        colors_rgba = _pad_palette_to_size(colors_rgba, num_colors)

        palettes[pidx] = EncoderPalette(colors_rgba, has_alpha)

    return palettes, raw


# ─────────────────────────────────────────────────────────────────────────────
# Bitstream writer and RLE scanline encoder
# ─────────────────────────────────────────────────────────────────────────────

class BitWriter:
    """Bit-level writer producing the decoder-compatible bitstream format."""

    __slots__ = ('buffer', 'current_word', 'bits_in_word')

    _WORD_MASK = (1 << WORD_BITS) - 1

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.current_word = 0
        self.bits_in_word = 0

    def write_bits(self, value: int, num_bits: int) -> None:
        """Write the low ``num_bits`` bits of ``value``."""
        value &= (1 << num_bits) - 1
        self.current_word |= value << self.bits_in_word
        self.bits_in_word += num_bits

        while self.bits_in_word >= WORD_BITS:
            self.buffer.extend(struct.pack('<I', self.current_word & self._WORD_MASK))
            self.current_word >>= WORD_BITS
            self.bits_in_word -= WORD_BITS

    def flush(self) -> None:
        """Flush remaining bits, padding with zeros to byte boundary."""
        if self.bits_in_word > 0:
            num_bytes = (self.bits_in_word + 7) // 8
            for _ in range(num_bytes):
                self.buffer.append(self.current_word & 0xFF)
                self.current_word >>= 8
            self.bits_in_word = 0
            self.current_word = 0

    def get_bytes(self) -> bytes:
        self.flush()
        return bytes(self.buffer)


def encode_scanline(indices: list[int] | np.ndarray, symbol_bitness: int) -> bytes:
    """Encode a scanline of palette indices into a bit-packed RLE stream."""
    writer = BitWriter()
    if isinstance(indices, np.ndarray):
        indices = indices.tolist()

    i, n = 0, len(indices)
    while i < n:
        symbol = indices[i]
        run = 1
        while i + run < n and indices[i + run] == symbol and run < RLE_MAX_RUN:
            run += 1

        writer.write_bits(symbol, symbol_bitness)
        rle_bits, rle_nbits = RLE_ENCODE[run]
        writer.write_bits(rle_bits, rle_nbits)

        i += run

    return writer.get_bytes()


# ─────────────────────────────────────────────────────────────────────────────
# Sprite header building / parsing
# ─────────────────────────────────────────────────────────────────────────────

def build_header(w: int, h: int, symbol_bitness: int, offset_bitness: int,
                 pidx: int, flags: int,
                 pivot_x: float | None = None, pivot_y: float | None = None,
                 num_pixels: int = 0, tags: int = 0, number: int = 0,
                 group: int = 0, sprite_type: int = 0, seq: int = 0, rate: int = 1,
                 bx: float = 0.0, by: float = 0.0,
                 bw: float = 0.0, bh: float = 0.0) -> bytes:
    """Build a 48-byte octBmp_t header (without PackerSizes)."""
    if pivot_x is None:
        pivot_x = w - PIVOT_HALFPIX
    if pivot_y is None:
        pivot_y = h - PIVOT_HALFPIX

    compression = (offset_bitness << 8) | symbol_bitness

    header = b''.join((
        struct.pack('<I',    num_pixels),
        struct.pack('<ff',   pivot_x, pivot_y),
        struct.pack('<ffff', bx, by, bw, bh),
        struct.pack('<I',    tags),
        struct.pack('<I',    compression),
        struct.pack('<hh',   w, h),
        struct.pack('<h',    number),
        struct.pack('<BB',   group, sprite_type),
        struct.pack('<BB',   flags, pidx),
        struct.pack('<bb',   seq, rate),
    ))

    assert len(header) == HEADER_SIZE
    return header


def read_existing_header(packed_png_path: str) -> bytes | None:
    """Read the 48-byte header from an existing packed sprite."""
    try:
        raw = Image.open(packed_png_path).tobytes()
    except Exception:
        return None
    return raw[:HEADER_SIZE] if len(raw) >= HEADER_SIZE else None


# ─────────────────────────────────────────────────────────────────────────────
# Single sprite packer
# ─────────────────────────────────────────────────────────────────────────────

def pack_sprite(
    exported_png_path: str,
    palette: EncoderPalette,
    header_bytes: bytes | None = None,
    pidx: int = 0,
    flags: int = int(SpriteFlag.ALPHA),
    symbol_bitness: int = 8,
    offset_bitness: int = DEFAULT_OFFSET_BITNESS,
    symbol_bitness_override: int | None = None,
    pivot_x: float | None = None,
    pivot_y: float | None = None,
) -> bytes | None:
    """Pack an exported RGBA PNG into the WowCube packed format.

    Pixel quantisation is fully vectorised via ``EncoderPalette.quantize_image``
    — the previous per-pixel Python loop was the dominant bottleneck on
    full-sheet packs.
    """
    img = Image.open(exported_png_path).convert('RGBA')
    pixels = np.asarray(img)
    h, w = pixels.shape[:2]

    if header_bytes:
        header = bytearray(header_bytes)
        old_w, old_h = struct.unpack_from('<hh', header, HDR_OFF_WIDTH)
        if old_w != w or old_h != h:
            struct.pack_into('<hh', header, HDR_OFF_WIDTH, w, h)

        compression = struct.unpack_from('<I', header, HDR_OFF_COMPRESSION)[0]
        symbol_bitness = compression & 0xFF
        offset_bitness = (compression >> 8) & 0xFF

        if symbol_bitness_override is not None:
            symbol_bitness = symbol_bitness_override
            compression = (offset_bitness << 8) | symbol_bitness
            struct.pack_into('<I', header, HDR_OFF_COMPRESSION, compression)
            header[HDR_OFF_PIDX] = pidx
        header = bytes(header)
    else:
        header = build_header(
            w, h, symbol_bitness, offset_bitness, pidx, flags,
            pivot_x=pivot_x, pivot_y=pivot_y,
        )

    # ── Vectorised pixel quantisation ──────────────────────────────────
    indices_2d = palette.quantize_image(pixels)
    num_opaque = int((pixels[:, :, 3] != 0).sum())

    # ── Encode each scanline ───────────────────────────────────────────
    encoded_lines = [encode_scanline(indices_2d[y].tolist(), symbol_bitness)
                     for y in range(h)]

    # ── Scanline trim array (byte length of each encoded line) ─────────
    trims = bytearray(len(lb) & 0xFF for lb in encoded_lines)
    trims_padded_size = ((h + 3) // 4) * 4
    if len(trims) < trims_padded_size:
        trims.extend(b'\x00' * (trims_padded_size - len(trims)))

    texel_data = b''.join(encoded_lines)

    # Patch num_pixels into header
    header_mut = bytearray(header)
    struct.pack_into('<I', header_mut, HDR_OFF_NUM_PIXELS, num_opaque)
    return bytes(header_mut) + bytes(trims) + texel_data


def blob_to_packed_png(blob: bytes) -> Image.Image:
    """Wrap a raw binary blob in a 1×W RGBA PNG (the packed format container)."""
    blob = pad_to_multiple(blob, BYTES_PER_RGBA)
    width = len(blob) // BYTES_PER_RGBA
    return Image.frombytes('RGBA', (width, 1), blob)


# ─────────────────────────────────────────────────────────────────────────────
# PSD layer name parsing
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LayerName:
    """Parsed PSD layer name (with %type / &group / #tag / =num / !rate suffixes)."""
    base: str
    png_name: str
    obj_name: str
    type_name: str
    group_name: str
    tag_name: str
    rate: int | None
    sprite_number: int
    marker_number: int | None

    @property
    def is_marker(self) -> bool:
        return self.base.startswith('=')

    @classmethod
    def parse(cls, name: str) -> 'LayerName':
        obj_name = _first_group(_RE_META_OBJ,   name)
        type_name = _first_group(_RE_META_TYPE,  name)
        group_name = _first_group(_RE_META_GROUP, name)
        tag_name = _first_group(_RE_META_TAG,   name)

        # Base: everything before the first metadata separator (matches
        # the original parse_layer_metadata split on [%&#$!]).
        base = _RE_META_SPLIT_BASE.split(name, 1)[0]
        # Strip "=value" if still in base (e.g. "n_0=5" → "n_0")
        base = base.split('=', 1)[0]

        m = _RE_RATE_SUFFIX.search(name)
        rate = int(m.group(1)) if m else None

        marker_num: int | None = None
        sprite_num = 0
        if name.startswith('='):
            try:
                marker_num = int(name[1:])
            except ValueError:
                marker_num = None
        else:
            m = _RE_SPRITE_NUM.search(name)
            if m:
                try:
                    sprite_num = int(m.group(1))
                except ValueError:
                    sprite_num = 0

        # png_name uses a narrower split (%&=!) that matches the original
        # normalize_layer_name — it deliberately preserves $ and # chars
        # in the filename stem if they appear before a metadata suffix.
        png_stem = _RE_META_SPLIT_PNG.split(name, 1)[0]
        png_name = _norm(png_stem)

        return cls(
            base=base,
            png_name=png_name,
            obj_name=_norm(obj_name),
            type_name=_norm(type_name),
            group_name=_norm(group_name),
            tag_name=_norm(tag_name),
            rate=rate,
            sprite_number=sprite_num,
            marker_number=marker_num,
        )


def _first_group(pat: re.Pattern[str], text: str) -> str:
    m = pat.search(text)
    return m.group(1) if m else ''


# Backward-compatible wrappers for external callers -------------------------
def normalize_layer_name(name: str) -> str:
    return LayerName.parse(name).png_name


def parse_layer_metadata(name: str) -> tuple[str, str, str, str, str]:
    ln = LayerName.parse(name)
    return ln.base, ln.obj_name, ln.type_name, ln.group_name, ln.tag_name


def parse_layer_rate(name: str) -> int | None:
    return LayerName.parse(name).rate


def parse_marker_number(name: str) -> int | None:
    return LayerName.parse(name).marker_number


def parse_sprite_number(name: str) -> int:
    return LayerName.parse(name).sprite_number


# ─────────────────────────────────────────────────────────────────────────────
# PSD export (pure Python via psd-tools)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PivotMarker:
    """A single pivot marker extracted from the ~pivot PSD layer."""
    cx: float
    cy: float
    rect: tuple[int, int, int, int]  # (min_x, min_y, max_x, max_y)


@dataclass
class SpriteRecord:
    """Record stored in CSV/PSL per PSD layer."""
    id: int
    name: str
    group_id: int
    kind: int
    bmp: str
    x: int
    y: int
    w: int
    h: int
    pivot_x: float | None
    pivot_y: float | None
    layer_mark: int
    side: int
    side_cx: int
    side_cy: int
    png_name: str
    is_marker: bool
    marker_number: int
    sprite_number: int
    type_name: str
    group_name: str
    rate: int


def nearest_side(x: int, y: int, w: int, h: int,
                 side_centers: dict[int, tuple[int, int]]) -> int:
    """Return the ~sideN id whose marker is closest to the layer center."""
    cx, cy = x + w / 2.0, y + h / 2.0
    best_side, best_dist = -1, math.inf
    for sn, (sx, sy) in side_centers.items():
        d = math.hypot(cx - sx, cy - sy)
        if d < best_dist:
            best_dist, best_side = d, sn
    return best_side


def _rects_intersect(r1: tuple[int, int, int, int],
                     r2: tuple[int, int, int, int]) -> bool:
    return r1[0] <= r2[2] and r1[2] >= r2[0] and r1[1] <= r2[3] and r1[3] >= r2[1]


def _extract_pivot_markers(layer) -> list[PivotMarker]:  # noqa: ANN001 — psd_tools layer
    """Extract pivot markers from a ~pivot PSD layer.

    Uses a numpy-based connected-components detector (4-connected flood fill
    on a boolean mask) rather than Python-level set iteration.
    """
    pimg = layer.composite()
    if pimg is None:
        return []

    arr = np.asarray(pimg.convert('RGBA'))
    alpha = arr[:, :, 3]
    ph, pw = alpha.shape
    if ph == 0 or pw == 0:
        return []

    mask = alpha > 0
    if not mask.any():
        return []

    # Connected components via iterative flood fill on a labels grid
    labels = np.zeros((ph, pw), dtype=np.int32)
    next_label = 0
    # Pre-flatten pixel coordinates for efficient iteration
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if labels[y0, x0] != 0:
            continue
        next_label += 1
        stack = [(y0, x0)]
        labels[y0, x0] = next_label
        while stack:
            y, x = stack.pop()
            # 4-connected neighbours
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < ph and 0 <= nx < pw and mask[ny, nx] and labels[ny, nx] == 0:
                    labels[ny, nx] = next_label
                    stack.append((ny, nx))

    markers: list[PivotMarker] = []
    for lbl in range(1, next_label + 1):
        comp_ys, comp_xs = np.where(labels == lbl)
        if comp_xs.size == 0:
            continue
        min_x = int(comp_xs.min()) + layer.left
        max_x = int(comp_xs.max()) + layer.left
        min_y = int(comp_ys.min()) + layer.top
        max_y = int(comp_ys.max()) + layer.top
        # Center = bounding-box center (matches utils.exe)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        markers.append(PivotMarker(cx, cy, (min_x, min_y, max_x, max_y)))

    return markers


def _write_records_csv(csv_path: str, records: list[SpriteRecord]) -> None:
    with open(csv_path, 'w', newline='') as f:
        f.write('int Id,str Name,int GroupId,int Kind,str Bmp,int X,int Y,'
                'int W,int H,int LayerMark,float PivotX,float PivotY\n')
        for r in records:
            pvx = f'{r.pivot_x:.2f}' if r.pivot_x is not None else ''
            pvy = f'{r.pivot_y:.2f}' if r.pivot_y is not None else ''
            f.write(f'{r.id},"{r.name}",{r.group_id},{r.kind},"{r.bmp}",'
                    f'{r.x},{r.y},{r.w},{r.h},{r.layer_mark},{pvx},{pvy}\n')


def _write_records_psl(psl_path: str, records: list[SpriteRecord], psl_type: int) -> None:
    with open(psl_path, 'wb') as f:
        f.write(struct.pack('<4I', psl_type, 0, 0, len(records)))
        for r in records:
            rec_buf = bytearray(PSL_RECORD_SIZE)

            psl_name = '' if r.is_marker else r.png_name
            name_bytes = psl_name.encode('ascii', errors='replace')[:PSL_NAME_SIZE - 1]
            rec_buf[:len(name_bytes)] = name_bytes

            struct.pack_into('<4i', rec_buf, PSL_XYWH_OFFSET, r.x, r.y, r.w, r.h)
            struct.pack_into('<i',  rec_buf, PSL_LAYERMARK_OFFSET, r.layer_mark)
            struct.pack_into('<4I', rec_buf, PSL_SIDE_OFFSET,
                             r.side if r.side >= 0 else 0,
                             r.side_cx, r.side_cy, 1)
            struct.pack_into('<I',  rec_buf, PSL_RESERVED_2, 1)

            if r.rate:
                rate_str = f'rate{r.rate}'.encode('ascii')[:PSL_RATE_SIZE - 1]
                rec_buf[PSL_RATE_OFFSET:PSL_RATE_OFFSET + len(rate_str)] = rate_str

            gname = r.group_name.encode('ascii', errors='replace')[:PSL_GROUP_SIZE - 1]
            rec_buf[PSL_GROUP_OFFSET:PSL_GROUP_OFFSET + len(gname)] = gname

            tname = r.type_name.encode('ascii', errors='replace')[:PSL_TYPE_SIZE - 1]
            rec_buf[PSL_TYPE_OFFSET:PSL_TYPE_OFFSET + len(tname)] = tname

            num_val = r.marker_number if r.is_marker else r.sprite_number
            struct.pack_into('<I', rec_buf, PSL_NUMBER_OFFSET, num_val & 0xFFFFFFFF)

            f.write(rec_buf)


def export_psd_file_python(psd_path: str, exported_dir: str,
                            is_map: bool = False
                            ) -> tuple[list[SpriteRecord], dict[str, int], dict[str, int]]:
    """Export a single PSD file using psd-tools (pure Python)."""
    try:
        from psd_tools import PSDImage
    except ImportError:
        print("Error: psd-tools not installed. Run: pip install psd-tools")
        sys.exit(1)

    psd = PSDImage.open(psd_path)
    stem = Path(psd_path).stem

    # Pass 1: collect ~sideN centers and ~pivot markers
    side_centers: dict[int, tuple[int, int]] = {}
    pivot_markers: list[PivotMarker] = []
    for layer in psd:
        if layer.name.startswith('~side'):
            try:
                sn = int(layer.name[5:])
                side_centers[sn] = (layer.left, layer.top)
            except ValueError:
                pass
        elif layer.name == '~pivot':
            try:
                pivot_markers = _extract_pivot_markers(layer)
                if pivot_markers:
                    print(f"    Found {len(pivot_markers)} pivot marker(s) in ~pivot layer")
            except Exception as e:
                print(f"    WARNING: failed to read ~pivot layer: {e}")

    types_seen: dict[str, int] = {}
    groups_seen: dict[str, int] = {}
    records: list[SpriteRecord] = []
    custom_pivots: list[tuple[str, int, int, float, float]] = []
    layer_id = 1

    for layer in psd:
        name = layer.name
        if name.startswith('~') or not layer.is_visible():
            continue
        if not name.isascii():
            print(f"    WARNING: non-ASCII layer name '{name}' in {psd_path}, skipping")
            continue

        x, y = layer.left, layer.top
        w, h = layer.width, layer.height
        parsed = LayerName.parse(name)

        # Type/group index assignment
        if parsed.type_name and parsed.type_name not in types_seen:
            types_seen[parsed.type_name] = len(types_seen) + 1
        if parsed.group_name and parsed.group_name not in groups_seen:
            groups_seen[parsed.group_name] = len(groups_seen) + 1
        kind = types_seen.get(parsed.type_name, 0)
        group_id = groups_seen.get(parsed.group_name, 0)

        # Nearest side (for maps)
        side, side_cx, side_cy = -1, 0, 0
        if side_centers:
            side = nearest_side(x, y, w, h, side_centers)
            if side in side_centers:
                side_cx, side_cy = side_centers[side]

        # Custom pivot lookup
        sprite_pvx, sprite_pvy = _find_sprite_pivot(
            pivot_markers, x, y, w, h)
        if sprite_pvx is not None:
            custom_pivots.append((parsed.png_name, w, h, sprite_pvx, sprite_pvy))

        records.append(SpriteRecord(
            id=layer_id,
            name=name,
            group_id=group_id,
            kind=kind,
            bmp='',
            x=x, y=y, w=w, h=h,
            pivot_x=sprite_pvx,
            pivot_y=sprite_pvy,
            layer_mark=DEFAULT_LAYER_MARK,
            side=side,
            side_cx=side_cx, side_cy=side_cy,
            png_name=parsed.png_name,
            is_marker=parsed.is_marker,
            marker_number=parsed.marker_number or 0,
            sprite_number=parsed.sprite_number,
            type_name=parsed.type_name,
            group_name=parsed.group_name,
            rate=parsed.rate or 0,
        ))
        layer_id += 1

        # Export PNG (skip markers, zero-size, already-exported names)
        if not parsed.is_marker and w > 0 and h > 0:
            out_png = os.path.join(exported_dir, f"{parsed.png_name}.png")
            if not os.path.exists(out_png):
                try:
                    img = layer.composite()
                    if img is not None:
                        img.convert('RGBA').save(out_png)
                except Exception as e:
                    print(f"    WARNING: failed to composite '{name}': {e}")

    if custom_pivots:
        _write_pivot_log(exported_dir, stem, custom_pivots)

    _write_records_csv(os.path.join(exported_dir, f"{stem}.csv"), records)
    psl_type = PSL_TYPE_MAP if is_map else PSL_TYPE_ASSET
    _write_records_psl(os.path.join(exported_dir, f"{stem}.psl"), records, psl_type)

    return records, types_seen, groups_seen


def _find_sprite_pivot(pivot_markers: list[PivotMarker],
                       x: int, y: int, w: int, h: int
                       ) -> tuple[float | None, float | None]:
    """Find the closest pivot marker whose rect intersects this sprite's bbox."""
    if not pivot_markers or w <= 0 or h <= 0:
        return None, None

    sprite_rect = (x, y, x + w - 1, y + h - 1)
    sprite_cx = x + w / 2.0
    sprite_cy = y + h / 2.0
    best_dist = math.inf
    best_px = best_py = None

    for m in pivot_markers:
        if _rects_intersect(sprite_rect, m.rect):
            d = math.hypot(m.cx - sprite_cx, m.cy - sprite_cy)
            if d < best_dist:
                best_dist, best_px, best_py = d, m.cx, m.cy

    if best_px is None:
        return None, None

    # utils.exe stores pivot = pixel_offset * PIVOT_SCALE + PIVOT_HALFPIX
    pixel_offset_x = best_px - x
    pixel_offset_y = best_py - y
    return (pixel_offset_x * PIVOT_SCALE + PIVOT_HALFPIX,
            pixel_offset_y * PIVOT_SCALE + PIVOT_HALFPIX)


def _write_pivot_log(exported_dir: str, stem: str,
                     custom_pivots: list[tuple[str, int, int, float, float]]) -> None:
    pivot_log = os.path.join(exported_dir, f"{stem}_pivots.log")
    with open(pivot_log, 'w') as f:
        f.write(f"Custom pivots for {stem} ({len(custom_pivots)} sprites)\n")
        f.write(f"{'Sprite':<30s} {'Size':>10s} {'Pivot':>16s} "
                f"{'Center':>16s} {'Offset':>16s}\n")
        f.write('-' * 100 + '\n')
        for pname, pw, ph, pvx, pvy in custom_pivots:
            cx, cy = pw / 2.0, ph / 2.0
            dx, dy = pvx - cx, pvy - cy
            f.write(f"{pname:<30s} {pw:>4d}x{ph:<4d} "
                    f"({pvx:>6.1f},{pvy:>6.1f}) "
                    f"({cx:>6.1f},{cy:>6.1f}) "
                    f"({dx:>+6.1f},{dy:>+6.1f})\n")
    print(f"    {len(custom_pivots)} sprites with custom pivots (see {pivot_log})")


# ─────────────────────────────────────────────────────────────────────────────
# Font (BMFont) export
# ─────────────────────────────────────────────────────────────────────────────

def export_font_python(fnt_path: str, exported_dir: str) -> int | None:
    """Export a BMFont binary (.fnt + atlas PNG) into individual glyph PNGs."""
    fnt_dir = str(Path(fnt_path).parent)
    font_stem = Path(fnt_path).stem

    with open(fnt_path, 'rb') as f:
        magic = f.read(3)
        if magic != BMFONT_MAGIC:
            print(f"    WARNING: not a BMFont file: {fnt_path}")
            return None
        version = struct.unpack('B', f.read(1))[0]
        if version != BMFONT_VERSION:
            print(f"    WARNING: unsupported BMFont version {version}")
            return None

        pages: list[str] = []
        chars: list[dict] = []

        while True:
            block_header = f.read(5)
            if len(block_header) < 5:
                break
            block_type, block_size = struct.unpack('<BI', block_header)
            block_data = f.read(block_size)
            if len(block_data) < block_size:
                break

            if block_type == BMFONT_BLOCK_PAGES:
                parts = block_data.rstrip(b'\x00').split(b'\x00')
                pages = [p.decode('ascii', errors='replace') for p in parts if p]
            elif block_type == BMFONT_BLOCK_CHARS:
                n_chars = block_size // BMFONT_CHAR_SIZE
                for i in range(n_chars):
                    off = i * BMFONT_CHAR_SIZE
                    char_id, cx, cy, cw, ch, xoff, yoff, xadv, page, _chnl = \
                        struct.unpack_from('<IHHHHhhhBB', block_data, off)
                    chars.append({
                        'id': char_id, 'x': cx, 'y': cy,
                        'w': cw, 'h': ch,
                        'xoff': xoff, 'yoff': yoff,
                        'xadvance': xadv, 'page': page,
                    })

    if not pages:
        print(f"    WARNING: no atlas pages in {fnt_path}")
        return 0

    atlases: dict[int, Image.Image] = {}
    for i, page_file in enumerate(pages):
        atlas_path = os.path.join(fnt_dir, page_file)
        if os.path.isfile(atlas_path):
            atlases[i] = Image.open(atlas_path).convert('RGBA')
        else:
            print(f"    WARNING: atlas not found: {atlas_path}")

    exported_count = 0
    for ch in chars:
        if ch['w'] == 0 or ch['h'] == 0 or ch['id'] < BMFONT_FIRST_PRINTABLE:
            continue
        atlas = atlases.get(ch['page'])
        if atlas is None:
            continue
        glyph = atlas.crop((ch['x'], ch['y'],
                            ch['x'] + ch['w'], ch['y'] + ch['h']))
        glyph.save(os.path.join(exported_dir, f"{font_stem}_{ch['id']:05d}.png"))
        exported_count += 1

    # Lightweight PSL for font (no side data)
    psl_path = os.path.join(exported_dir, f"{font_stem}.psl")
    with open(psl_path, 'wb') as f:
        f.write(struct.pack('<4I', PSL_TYPE_ASSET, 0, 0, len(chars)))
        for ch in chars:
            rec_buf = bytearray(PSL_RECORD_SIZE)
            name = f"{font_stem}_{ch['id']:05d}"
            name_bytes = name.encode('ascii', errors='replace')[:PSL_NAME_SIZE - 1]
            rec_buf[:len(name_bytes)] = name_bytes
            struct.pack_into('<4I', rec_buf, PSL_XYWH_OFFSET,
                             ch['x'], ch['y'], ch['w'], ch['h'])
            struct.pack_into('<i', rec_buf, PSL_LAYERMARK_OFFSET, DEFAULT_LAYER_MARK)
            struct.pack_into('<I', rec_buf, PSL_RESERVED_1, 1)
            f.write(rec_buf)

    print(f"    {exported_count} glyphs exported")
    return exported_count


def export_all_python(art_dir: str, exported_dir: str,
                      map_filter=None,
                      asset_names: set[str] | None = None,
                      ) -> tuple[list[str], list[str]]:
    """Export all PSD and FNT files using psd-tools."""
    if asset_names is None:
        asset_names = {DEFAULT_ASSET_NAME}

    # Recreate and clean the exported directory
    os.makedirs(exported_dir, exist_ok=True)
    for pattern in ('*.png', '*.psl', '*.csv', '*.log'):
        for f in Path(exported_dir).glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass

    # Copy 0.png placeholder
    zero_png = os.path.join(art_dir, f'{PLACEHOLDER_SPRITE_NAME}.png')
    if os.path.isfile(zero_png):
        shutil.copy2(zero_png, os.path.join(exported_dir, f'{PLACEHOLDER_SPRITE_NAME}.png'))

    asset_names_out: list[str] = []
    map_names_exported: list[str] = []

    # Fonts
    fonts_dir = os.path.join(art_dir, 'fonts')
    if os.path.isdir(fonts_dir):
        for fnt in sorted(Path(fonts_dir).glob('*.fnt')):
            print(f"  Export font: {fnt.name}")
            export_font_python(str(fnt), exported_dir)

    # PSDs
    for psd in sorted(Path(art_dir).glob('*.psd')):
        name = psd.stem
        if map_filter is None:
            is_map = name not in asset_names
        elif map_filter == 'all':
            is_map = name not in asset_names
        elif isinstance(map_filter, list):
            is_map = name in map_filter
        else:
            is_map = name not in asset_names

        label = 'map' if is_map else 'assets'
        print(f"  Export {label}: {psd.name}")

        records, types, groups = export_psd_file_python(
            str(psd), exported_dir, is_map=is_map)
        print(f"    {len(records)} layers, {len(types)} types, {len(groups)} groups")

        (map_names_exported if is_map else asset_names_out).append(name)

    n_png = len(list(Path(exported_dir).glob('*.png')))
    n_csv = len(list(Path(exported_dir).glob('*.csv')))
    n_psl = len(list(Path(exported_dir).glob('*.psl')))
    print(f"\n  Exported: {n_png} PNGs, {n_csv} CSVs, {n_psl} PSLs")
    if len(asset_names_out) > 1:
        print(f"  Assets: {', '.join(asset_names_out)}")

    return asset_names_out, map_names_exported


def export_psd(art_dir: str, exported_dir: str,
               map_filter=None, asset_names: set[str] | None = None
               ) -> tuple[list[str], list[str]]:
    """Wrapper: export PSD/FNT into exported_dir using psd-tools."""
    return export_all_python(art_dir, exported_dir, map_filter, asset_names)


# ─────────────────────────────────────────────────────────────────────────────
# Map (PSL/CSV) packing
# ─────────────────────────────────────────────────────────────────────────────

def _bytes_to_str_at(rec: bytes, off: int, size: int) -> str:
    """Read a null-terminated ASCII string from a fixed-size buffer slot."""
    end = rec.find(0, off, off + size)
    if end < 0:
        end = off + size
    return rec[off:end].decode('ascii', errors='replace')


def parse_psl(psl_path: str) -> tuple[int, list[dict]]:
    """Parse a PSL binary map file.  Returns (psl_type, list_of_records)."""
    with open(psl_path, 'rb') as f:
        data = f.read()

    psl_type, _z1, _z2, record_count = struct.unpack_from('<4I', data, 0)

    records = []
    for i in range(record_count):
        base = PSL_HEADER_SIZE + i * PSL_RECORD_SIZE
        rec = data[base:base + PSL_RECORD_SIZE]

        name = _bytes_to_str_at(rec, PSL_NAME_OFFSET, PSL_NAME_SIZE)
        x, y, w, h = struct.unpack_from('<4i', rec, PSL_XYWH_OFFSET)
        layer_mark = struct.unpack_from('<i', rec, PSL_LAYERMARK_OFFSET)[0]
        side = struct.unpack_from('<I', rec, PSL_SIDE_OFFSET)[0]
        center_x = struct.unpack_from('<I', rec, PSL_CENTER_X_OFFSET)[0]
        center_y = struct.unpack_from('<I', rec, PSL_CENTER_Y_OFFSET)[0]

        group_name = _bytes_to_str_at(rec, PSL_GROUP_OFFSET, PSL_GROUP_SIZE)
        type_name  = _bytes_to_str_at(rec, PSL_TYPE_OFFSET,  PSL_TYPE_SIZE)
        number = struct.unpack_from('<I', rec, PSL_NUMBER_OFFSET)[0]

        rate_str = _bytes_to_str_at(rec, PSL_RATE_OFFSET, PSL_RATE_SIZE)
        rate_val = 0
        if rate_str.startswith('rate'):
            try:
                rate_val = int(rate_str[4:])
            except ValueError:
                rate_val = 0

        records.append({
            'name': name,
            'x': x, 'y': y, 'w': w, 'h': h,
            'layer_mark': layer_mark,
            'side': side,
            'center_x': center_x, 'center_y': center_y,
            'group_name': group_name,
            'type_name': type_name,
            'number': number,
            'rate': rate_val,
        })

    return psl_type, records


def parse_map_csv(csv_path: str) -> list[dict]:
    """Parse a map CSV file into per-layer dicts with metadata annotations."""
    records = []
    with open(csv_path, 'r') as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header

        for row in reader:
            if len(row) < 10:
                continue

            raw_name = row[1]
            x, y = int(row[5]), int(row[6])
            w, h = int(row[7]), int(row[8])

            type_name = group_name = ''
            number = rate = 0

            parts = _RE_META_CSV_SPL.split(raw_name)
            base_name = parts[0]

            i = 1
            while i < len(parts) - 1:
                marker = parts[i]
                value = parts[i + 1]
                if marker == '%':
                    type_name = value.lower()
                elif marker == '&':
                    group_name = value.lower()
                elif marker == '=':
                    try:
                        number = int(value)
                    except ValueError:
                        pass
                elif marker == '!':
                    m = _RE_RATE_INLINE.match(value)
                    if m:
                        rate = int(m.group(1))
                i += 2

            records.append({
                'csv_id': int(row[0]),
                'raw_name': raw_name,
                'sprite_name': _norm(base_name),
                'base_name': base_name,
                'type_name': type_name,
                'group_name': group_name,
                'number': number,
                'rate': rate,
                'x': x, 'y': y, 'w': w, 'h': h,
                'layer_mark': int(row[9]),
                'bmp_name': row[4],
                'group_id': int(row[2]),
                'kind': int(row[3]),
            })

    return records


def build_bmp_name_index(packed_dir: str, exported_dir: str
                         ) -> tuple[dict[str, int], list[str]]:
    """Build alphabetically-sorted BMP name → index mapping from packed sprites."""
    names: set[str] = set()

    if os.path.isdir(packed_dir):
        for f in Path(packed_dir).glob('*.png'):
            if f.stem != PLACEHOLDER_SPRITE_NAME:
                names.add(f.stem)

    if os.path.isdir(exported_dir):
        for f in Path(exported_dir).glob('*.png'):
            stem = f.stem
            if stem != PLACEHOLDER_SPRITE_NAME and not stem.endswith('.csv'):
                names.add(stem)

    names.add(PALETTE_SPRITE_NAME)

    # Map-typed PSLs contribute their stem to the sprite index namespace
    if os.path.isdir(exported_dir):
        for f in Path(exported_dir).glob('*.psl'):
            try:
                with open(f, 'rb') as fh:
                    psl_type = struct.unpack('<I', fh.read(4))[0]
            except Exception:
                continue
            if psl_type != PSL_TYPE_MAP:
                continue
            stem = f.stem
            if stem.startswith(MAP_FILENAME_PREFIX):
                stem = stem[len(MAP_FILENAME_PREFIX):]
            if stem and stem not in (PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME):
                names.add(stem)

    sorted_names = sorted(names)
    name_to_idx = {name: idx + 1 for idx, name in enumerate(sorted_names)}
    return name_to_idx, sorted_names


def build_metadata_maps(exported_dir: str
                        ) -> tuple[dict[str, int], dict[str, int],
                                   dict[str, int], dict[str, int]]:
    """Scan CSVs and collect $names / %types / &groups / #tags index maps."""
    names: set[str] = set()
    types: set[str] = set()
    groups: set[str] = set()
    tags: set[str] = set()

    for csv_path in sorted(Path(exported_dir).glob('*.csv')):
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            try:
                next(reader)
            except StopIteration:
                continue
            for row in reader:
                if len(row) < 2:
                    continue
                parsed = LayerName.parse(row[1])
                if parsed.obj_name:
                    names.add(parsed.obj_name)
                if parsed.type_name:
                    types.add(parsed.type_name)
                if parsed.group_name:
                    groups.add(parsed.group_name)
                if parsed.tag_name:
                    tags.add(parsed.tag_name)

    def _to_index_map(s: set[str]) -> dict[str, int]:
        return {n: i + 1 for i, n in enumerate(sorted(s))}

    return _to_index_map(names), _to_index_map(types), \
           _to_index_map(groups), _to_index_map(tags)


def _load_packed_pivots(packed_dir: str
                        ) -> dict[str, tuple[float, float, int, int]]:
    """Read stored pivots and packed sizes from every sprite in packed_dir."""
    pivots: dict[str, tuple[float, float, int, int]] = {}
    if not os.path.isdir(packed_dir):
        return pivots
    for f in Path(packed_dir).glob('*.png'):
        if f.stem == PALETTE_SPRITE_NAME:
            continue
        try:
            raw = Image.open(f).tobytes()
            if len(raw) < HEADER_SIZE:
                continue
            px = struct.unpack_from('<f', raw, HDR_OFF_PIVOT_X)[0]
            py = struct.unpack_from('<f', raw, HDR_OFF_PIVOT_Y)[0]
            pw = struct.unpack_from('<h', raw, HDR_OFF_WIDTH)[0]
            ph = struct.unpack_from('<h', raw, HDR_OFF_HEIGHT)[0]
            pivots[f.stem] = (px, py, pw, ph)
        except Exception:
            pass
    return pivots


def _pack_octplace(x: float, y: float, w: int, h: int, bmp_idx: int,
                   number: int, flags: int, side: int, rate: int,
                   name_byte: int, group_idx: int, parent: int,
                   type_idx: int) -> bytes:
    """Pack a single octPlace_t (28 bytes)."""
    return b''.join((
        struct.pack('<ff', x, y),
        struct.pack('<I',  0),                              # Tags
        struct.pack('<hh', w & NUMBER_FIELD_MASK, h & NUMBER_FIELD_MASK),
        struct.pack('<h',  bmp_idx),
        struct.pack('<h',  number & NUMBER_FIELD_MASK),
        struct.pack('<H',  flags),
        struct.pack('<b',  side if side < 128 else -1),
        struct.pack('<b',  rate & 0xFF),
        struct.pack('<B',  name_byte),
        struct.pack('<B',  group_idx),
        struct.pack('<B',  parent),
        struct.pack('<B',  type_idx),
    ))


def psl_to_octplace(records: list[dict],
                    bmp_index: dict[str, int],
                    type_map: dict[str, int],
                    group_map: dict[str, int],
                    packed_pivots: dict[str, tuple[float, float, int, int]] | None = None
                    ) -> bytes:
    """Convert parsed PSL records to an octPlace_t binary blob (map payload)."""
    if packed_pivots is None:
        packed_pivots = {}

    places: list[bytes] = []
    for rec in records:
        name = rec.get('name', rec.get('sprite_name', ''))
        x_psd, y_psd = rec['x'], rec['y']
        w, h = rec['w'], rec['h']
        sid = rec.get('side', 0)
        cx, cy = rec.get('center_x', 0), rec.get('center_y', 0)
        type_name = rec.get('type_name', '')
        group_name = rec.get('group_name', '')
        number = rec.get('number', 0)
        rate = rec.get('rate', 0)

        is_layer_marker = (not name and w <= 1 and h <= 1)
        bmp_idx = bmp_index.get(name, 0) if name else 0

        stored_pvx = stored_pvy = 0.0
        if name and name in packed_pivots:
            stored_pvx, stored_pvy, _, _ = packed_pivots[name]

        # Position formula matching utils.exe exactly
        local_x = 2.0 * (x_psd - cx) + stored_pvx
        local_y = -2.0 * (y_psd - cy) - stored_pvy
        if local_x < 0:
            local_x -= 1
        if local_y > 0:
            local_y += 1

        type_idx = type_map.get(type_name, 0) if type_name else 0
        group_idx = group_map.get(group_name, 0) if group_name else 0

        # Animation start flag: name ends with "_00" or explicit !rate suffix
        flags = 0
        if name and name.endswith('_00'):
            flags |= int(PlaceFlag.LOOPED)
        if rate > 0:
            flags |= int(PlaceFlag.LOOPED)

        rate_out = rate if rate > 0 else OCT_PLACE_RATE_DEFAULT

        if is_layer_marker:
            bmp_idx = type_idx = group_idx = 0
            flags = 0
            rate_out = OCT_PLACE_RATE_DEFAULT

        places.append(_pack_octplace(
            local_x, local_y, w, h, bmp_idx, number,
            flags, sid, rate_out, 0, group_idx, 0, type_idx,
        ))

    return struct.pack('<ii', 1, len(places)) + b''.join(places)


def csv_to_octplace(csv_records: list[dict],
                    bmp_index: dict[str, int],
                    type_map: dict[str, int],
                    group_map: dict[str, int]) -> bytes:
    """Convert parsed CSV records to an octPlace_t blob (map payload, no sides)."""
    places: list[bytes] = []
    name_counter = 1

    for rec in csv_records:
        raw_name = rec['raw_name']
        sprite_name = rec['sprite_name']
        x, y = rec['x'], rec['y']
        w, h = rec['w'], rec['h']

        # "=N" layer marker: BmpIdx=0, Name=0, Number=layer
        if raw_name.startswith('=') and not sprite_name:
            try:
                layer_num = int(raw_name[1:])
            except ValueError:
                layer_num = 0
            # hand-rolled packing kept to match original byte layout
            place_data = struct.pack('<ff', float(x), float(y))
            place_data += struct.pack('<I', 0)
            place_data += struct.pack('<hh', w, h)
            place_data += struct.pack('<hh', 0, layer_num)
            place_data += struct.pack('<H', 0)
            place_data += struct.pack('<bb', -1, 0)
            place_data += struct.pack('<BBBB', 0, 0, 0, 0)
            places.append(place_data)
            continue

        bmp_idx  = bmp_index.get(sprite_name, 0)
        type_idx = type_map.get(rec['type_name'], 0) if rec['type_name'] else 0
        group_idx = group_map.get(rec['group_name'], 0) if rec['group_name'] else 0

        places.append(_pack_octplace(
            float(x), float(y), w, h, bmp_idx, rec['number'],
            0, -1, rec['rate'], name_counter & 0xFF, group_idx, 0, type_idx,
        ))
        name_counter += 1

    return struct.pack('<ii', 1, len(places)) + b''.join(places)


def pack_maps(exported_dir: str, packed_dir: str, output_dir: str,
              map_filter=None, asset_names: set[str] | None = None
              ) -> tuple[list[str], dict[str, int], list[str],
                         dict[str, int], dict[str, int],
                         dict[str, int], dict[str, int]]:
    """Pack map files (PSL or CSV) into pseudo-sprite PNGs."""
    bmp_index, sorted_names = build_bmp_name_index(packed_dir, exported_dir)
    name_map, type_map, group_map, tag_map = build_metadata_maps(exported_dir)

    pivot_src = output_dir if os.path.isdir(output_dir) and any(
        Path(output_dir).glob('*.png')) else packed_dir
    packed_pivots = _load_packed_pivots(pivot_src)

    print(f"  BMP index: {len(bmp_index)} sprites")
    print(f"  Packed pivots: {len(packed_pivots)} sprites (from {pivot_src})")
    print(f"  Names: {name_map}")
    print(f"  Types: {type_map}")
    print(f"  Groups: {group_map}")
    print(f"  Tags: {tag_map}")

    psl_files = {p.stem: p for p in sorted(Path(exported_dir).glob('*.psl'))}
    csv_files = {p.stem: p for p in sorted(Path(exported_dir).glob('*.csv'))}
    all_map_candidates = sorted(set(psl_files.keys()) | set(csv_files.keys()))

    explicit_set = set(map_filter) if isinstance(map_filter, list) else None
    skip_assets = asset_names if asset_names else {DEFAULT_ASSET_NAME}
    map_names: list[str] = []

    for map_name in all_map_candidates:
        has_psl = map_name in psl_files
        has_csv = map_name in csv_files

        if explicit_set is not None:
            if map_name not in explicit_set:
                continue
        elif map_filter != 'all':
            if map_name.startswith('font') or map_name in skip_assets:
                continue

        if has_psl:
            print(f"\n  Map: {map_name} (from PSL)")
            psl_type, records = parse_psl(str(psl_files[map_name]))
            print(f"    PSL type={psl_type}, {len(records)} records")

            if explicit_set is None and map_filter != 'all' and psl_type != PSL_TYPE_MAP:
                print(f"    Skipping (not a map PSL, type={psl_type})")
                continue
            blob = psl_to_octplace(records, bmp_index, type_map, group_map,
                                   packed_pivots=packed_pivots)
        elif has_csv:
            print(f"\n  Map: {map_name} (from CSV, no side conversion)")
            csv_records = parse_map_csv(str(csv_files[map_name]))
            print(f"    CSV: {len(csv_records)} records")
            if not csv_records:
                print("    Skipping (empty CSV)")
                continue
            blob = csv_to_octplace(csv_records, bmp_index, type_map, group_map)
        else:
            continue

        clean_name = map_name[len(MAP_FILENAME_PREFIX):] \
            if map_name.startswith(MAP_FILENAME_PREFIX) else map_name

        packed_img = blob_to_packed_png(blob)
        out_path = os.path.join(output_dir, f"{clean_name}.png")
        packed_img.save(out_path)

        version = struct.unpack_from('<i', blob, 0)[0]
        count = struct.unpack_from('<i', blob, 4)[0]
        print(f"    Packed: version={version}, {count} places, {len(blob)} bytes -> {out_path}")

        verify_img = Image.open(out_path)
        verify_raw = verify_img.tobytes()
        w_verify = verify_img.size[0]
        dims_val = w_verify | (verify_img.size[1] << 16)
        print(f"    On-disk verify: {verify_img.size}, "
              f"dimensions_word={dims_val} (0x{dims_val:08x}), "
              f"blob match={verify_raw == blob}")

        map_names.append(clean_name)

    return map_names, bmp_index, sorted_names, name_map, type_map, group_map, tag_map


# ─────────────────────────────────────────────────────────────────────────────
# app_ids.h generator
# ─────────────────────────────────────────────────────────────────────────────

def _emit_index_block(lines: list[str], prefix: str, label: str,
                      idx_map: dict[str, int]) -> None:
    """Append a '// label\\n const uint8_t PREFIX_X = N;\\n ...' block to lines."""
    lines.append(f'//{label}\n')
    for name, idx in sorted(idx_map.items(), key=lambda x: x[1]):
        lines.append(f'const uint8_t {prefix}_{name} = {idx};\n')
    last = (max(idx_map.values()) + 1) if idx_map else 1
    if idx_map or prefix != 'TAG':
        lines.append(f'const uint8_t {prefix}_last = {last};\n')
    lines.append('\n')


def generate_app_ids_h(sorted_sprite_names: list[str],
                       map_names: list[str],
                       name_map: dict[str, int],
                       type_map: dict[str, int],
                       group_map: dict[str, int],
                       tag_map: dict[str, int],
                       output_path: str,
                       exported_dir: str) -> dict[str, int]:
    """Generate app_ids.h (BMP/MAP enums and NAME_/TYPE_/GROUP_/TAG_ constants)."""
    map_name_set = set(map_names)

    # Merge sprites (without map-named entries) and maps into one sorted list
    all_entries: list[tuple[str, str]] = []
    for name in sorted_sprite_names:
        if name in map_name_set:
            continue
        all_entries.append(('bmp', name))
    for name in map_names:
        all_entries.append(('map', name))
    all_entries.sort(key=lambda e: e[1])

    # Pre-scan animation sequences
    seq_groups_raw: dict[str, list[tuple[str, int]]] = {}
    for kind, name in all_entries:
        if kind != 'bmp':
            continue
        m = _RE_SEQ_FRAME.match(name)
        if m:
            seq_groups_raw.setdefault(m.group(1), []).append((name, int(m.group(2))))

    # Only sequences that include frame 0 get base/end aliases
    seq_groups = {base: sorted(members, key=lambda x: x[1])
                  for base, members in seq_groups_raw.items()
                  if any(num == 0 for _, num in members)}

    lines = ['enum BMP { BMP_none = 0, \nBMP_0 = 0, \n']
    map_lines = ['enum MAP { MAP_none = 0, \n']

    idx = 1
    seq_first_idx: dict[str, int] = {}
    assigned: dict[str, int] = {}

    for kind, name in all_entries:
        if kind == 'map':
            map_lines.append(f'MAP_{name} = {idx}, \n')
            assigned[name] = idx
        else:
            lines.append(f'BMP_{name} = {idx}, \n')
            assigned[name] = idx

            m = _RE_SEQ_FRAME.match(name)
            if m:
                base = m.group(1)
                seq_num = int(m.group(2))
                group = seq_groups.get(base)
                if group:
                    if group[0][1] == seq_num:
                        seq_first_idx[base] = idx
                    if group[-1][1] == seq_num:
                        first = seq_first_idx.get(base, idx)
                        lines.append(f'BMP_{base} = {first}, \n')
                        lines.append(f'BMP_{base}_end = {idx}, \n')
        idx += 1

    lines.append('BMP_last};\n\n')
    map_lines.append('MAP_last};\n\n')

    out_parts: list[str] = []
    out_parts.extend(lines)
    out_parts.extend(map_lines)
    out_parts.append('typedef enum BMP BMP;\ntypedef enum MAP MAP;\n\n')

    _emit_index_block(out_parts, 'NAME',  '$names',  name_map)
    _emit_index_block(out_parts, 'TYPE',  '%types',  type_map)
    _emit_index_block(out_parts, 'GROUP', '&groups', group_map)
    _emit_index_block(out_parts, 'TAG',   '#tags',   tag_map)

    with open(output_path, 'w') as f:
        f.write(''.join(out_parts))

    print(f"\n  Generated {output_path}")
    print(f"    {len(sorted_sprite_names)} sprites, {len(map_names)} maps")
    print(f"    {len(name_map)} names, {len(type_map)} types, "
          f"{len(group_map)} groups, {len(tag_map)} tags")
    return assigned


# ─────────────────────────────────────────────────────────────────────────────
# Entry point — phases
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WowCube Packed Sprite Encoder")
    p.add_argument('files', nargs='*',
                   help='Exported PNGs to pack (default: all from exported/)')
    p.add_argument('--exported-dir', default='exported')
    p.add_argument('--packed-dir',   default='packed')
    p.add_argument('--output-dir',   default='packed_new')
    p.add_argument('--pal', default=None,
                   help='Path to pal.png (default: packed/pal.png)')
    p.add_argument('--no-reuse-headers', action='store_true')
    p.add_argument('--build-palette', action='store_true')
    p.add_argument('--max-colors', type=int, default=256)
    p.add_argument('--single-palette', action='store_true')
    p.add_argument('--target-colors', type=int, default=None)
    p.add_argument('--quality-threshold', type=int, default=DEFAULT_QUALITY_THRESHOLD)
    p.add_argument('--pre-reduce', type=int, default=None)
    p.add_argument('--color-tolerance', type=int, default=0)
    p.add_argument('--export', action='store_true')
    p.add_argument('--art-dir', default='.')
    p.add_argument('--assets', default=None)
    p.add_argument('--build-maps', action='store_true')
    p.add_argument('--map-filter', default=None)
    p.add_argument('--build-ids', action='store_true')
    p.add_argument('--ids-output', default=None)
    return p


def _resolve_asset_names(args: argparse.Namespace) -> set[str]:
    if args.assets is not None:
        return {n.strip() for n in args.assets.split(',') if n.strip()}
    asset_psds = sorted(Path(args.art_dir).glob('*assets*.psd'))
    if asset_psds:
        result = {p.stem for p in asset_psds}
        print(f"  Auto-detected assets: {', '.join(sorted(result))}")
        return result
    return {DEFAULT_ASSET_NAME}


def _resolve_map_filter(args: argparse.Namespace) -> None:
    if args.map_filter is not None:
        return
    map_psds = sorted(Path(args.art_dir).glob(f'{MAP_FILENAME_PREFIX}*.psd'))
    if map_psds:
        args.map_filter = ','.join(p.stem for p in map_psds)
        print(f"  Auto-detected maps: {args.map_filter}")


def _phase_export(args: argparse.Namespace, asset_names_set: set[str]) -> None:
    if not args.export:
        return
    print("=== Exporting PSD/FNT layers (psd-tools) ===")
    mf = args.map_filter
    if mf is None or mf == 'auto':
        export_map_filter = None
    elif mf == 'all':
        export_map_filter = 'all'
    else:
        export_map_filter = [n.strip() for n in mf.split(',') if n.strip()]

    export_psd(
        art_dir=args.art_dir,
        exported_dir=args.exported_dir,
        map_filter=export_map_filter,
        asset_names=asset_names_set,
    )
    print()


def _phase_palette(args: argparse.Namespace, files: list[Path]
                   ) -> tuple[dict[str, tuple[int, EncoderPalette, int]] | None,
                              dict[int, EncoderPalette],
                              bool]:
    """Resolve palette.  Returns (sprite_assignments, palettes, has_palette)."""
    palettes: dict[int, EncoderPalette] = {}
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None = None

    pal_path = args.pal or os.path.join(args.packed_dir, DEFAULT_PALETTE_FILENAME)
    has_palette = args.build_palette or os.path.exists(pal_path)

    if not has_palette and (args.build_maps or args.build_ids):
        print("No palette found, skipping sprite packing (maps/ids only).")
        return None, palettes, False

    if args.build_palette:
        file_strs = [str(f) for f in files]

        if args.single_palette or args.target_colors:
            print("=== Auto-building single palette ===")
            auto_pal, _, auto_sym, auto_colors = build_auto_palette(
                file_strs,
                max_colors=args.max_colors,
                target_colors=args.target_colors,
                quality_threshold=args.quality_threshold,
            )
            pal_out = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
            save_palette_png(auto_colors, pal_out, has_alpha=True)
            palettes = {1: auto_pal}
            sprite_assignments = {
                f.stem: (1, auto_pal, auto_sym)
                for f in files
                if f.stem not in (PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME)
                and f.suffix.lower() == '.png'
            }
            print()
        else:
            print("=== Auto-building grouped palettes ===")
            sprite_assignments, all_palette_data = build_grouped_palettes(
                file_strs,
                max_colors=args.max_colors,
                quality_threshold=args.quality_threshold,
                pre_reduce=args.pre_reduce,
                color_tolerance=args.color_tolerance,
            )
            pal_out = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
            save_palette_png([colors for colors, _ in all_palette_data],
                             pal_out, has_alpha=True)
            palettes = {
                i + 1: EncoderPalette(colors, has_alpha=True)
                for i, (colors, _sym) in enumerate(all_palette_data)
            }
            print()
        return sprite_assignments, palettes, True

    # Load existing palette
    if not os.path.exists(pal_path):
        print(f"Error: palette not found: {pal_path}")
        print("  Use --build-palette to auto-generate one.")
        sys.exit(1)

    print(f"Loading palette from {pal_path}...")
    palettes, _raw = load_palette_for_encoding(pal_path)
    print(f"  Loaded {len(palettes)} palette(s)")
    for pidx, pal in palettes.items():
        print(f"    [{pidx}] {len(pal.colors)} colors, alpha={pal.has_alpha}")

    pal_dst = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
    if os.path.abspath(pal_path) != os.path.abspath(pal_dst):
        shutil.copy2(pal_path, pal_dst)
        print(f"  Copied pal.png to {args.output_dir}/")

    return None, palettes, True


def _load_sprite_pivots_from_csvs(exported_dir: str
                                  ) -> dict[str, tuple[float, float]]:
    """Map png_name → (pivot_x, pivot_y) extracted from every CSV."""
    sprite_pivots: dict[str, tuple[float, float]] = {}
    for csv_file in sorted(Path(exported_dir).glob('*.csv')):
        try:
            with open(csv_file, 'r') as f:
                reader = csv.reader(f)
                header_row = next(reader, None)
                if header_row is None:
                    continue
                col_names = [c.split()[-1] if ' ' in c else c for c in header_row]
                if 'PivotX' not in col_names or 'PivotY' not in col_names:
                    continue
                px_idx = col_names.index('PivotX')
                py_idx = col_names.index('PivotY')
                name_idx = col_names.index('Name')
                for row in reader:
                    if len(row) <= max(px_idx, py_idx, name_idx):
                        continue
                    raw_name = row[name_idx].strip('"')
                    try:
                        pvx = float(row[px_idx])
                        pvy = float(row[py_idx])
                    except (ValueError, IndexError):
                        continue
                    sprite_pivots[normalize_layer_name(raw_name)] = (pvx, pvy)
        except Exception:
            pass
    return sprite_pivots


def _compute_map_skip_set(args: argparse.Namespace,
                          asset_names_set: set[str]) -> set[str]:
    """Sprite names that must be skipped because they are packed as maps."""
    if not (args.build_maps or args.build_ids):
        return set()

    mf = args.map_filter or ''
    psl_cands = {p.stem for p in Path(args.exported_dir).glob('*.psl')}
    csv_cands = {p.stem for p in Path(args.exported_dir).glob('*.csv')}
    all_cands = psl_cands | csv_cands

    if ',' in mf:
        skip = {n.strip() for n in mf.split(',') if n.strip()}
    elif mf == 'all':
        skip = all_cands
    else:
        skip = {n for n in all_cands
                if not n.startswith('font') and n not in asset_names_set}

    if skip:
        print(f"  Map names (will skip in sprite packing): "
              f"{', '.join(sorted(skip))}")
    return skip


def _phase_pack_sprites(
    args: argparse.Namespace,
    files: list[Path],
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None,
    palettes: dict[int, EncoderPalette],
    map_skip_names: set[str],
    sprite_pivots: dict[str, tuple[float, float]],
    has_palette: bool,
) -> None:
    ok = skip = err = 0
    total_orig = total_packed = 0

    if not has_palette and not args.build_palette:
        return  # nothing to pack

    for fpath in files:
        name = fpath.stem
        if name == PALETTE_SPRITE_NAME or name.endswith('.csv') or name.endswith('.psl'):
            skip += 1
            continue
        if name in map_skip_names:
            print(f"  [SKIP] {name}.png (map, will be packed by pack_maps)")
            skip += 1
            continue
        if fpath.suffix.lower() != '.png':
            skip += 1
            continue

        try:
            existing_packed = os.path.join(args.packed_dir, f"{name}.png")
            header_bytes = None
            if not args.no_reuse_headers and os.path.exists(existing_packed):
                header_bytes = read_existing_header(existing_packed)

            sym_override = None
            if sprite_assignments and name in sprite_assignments:
                pidx, palette, sym_override = sprite_assignments[name]
            elif header_bytes:
                pidx = header_bytes[HDR_OFF_PIDX]
                palette = palettes.get(pidx, next(iter(palettes.values())))
            else:
                pidx = 1 if 'font' in name else 0
                palette = palettes.get(pidx, next(iter(palettes.values())))

            pvx, pvy = sprite_pivots.get(name, (None, None))
            if name == PLACEHOLDER_SPRITE_NAME:
                pvx, pvy = PLACEHOLDER_SPRITE_PIVOT

            blob = pack_sprite(
                str(fpath), palette,
                header_bytes=header_bytes,
                pidx=pidx,
                symbol_bitness_override=sym_override,
                pivot_x=pvx,
                pivot_y=pvy,
            )
            if blob is None:
                skip += 1
                continue

            packed_img = blob_to_packed_png(blob)
            out_path = os.path.join(args.output_dir, f"{name}.png")
            packed_img.save(out_path)

            compression = struct.unpack_from('<I', blob, HDR_OFF_COMPRESSION)[0]
            sym_bits = compression & 0xFF
            w, h_val = struct.unpack_from('<hh', blob, HDR_OFF_WIDTH)

            total_orig += len(Image.open(fpath).tobytes())
            total_packed += len(blob)

            mode = "reuse" if header_bytes else "new"
            print(f"  [OK] {name}.png ({w}x{h_val}, sym={sym_bits}bit, "
                  f"pal={pidx}, {len(blob)}B, header={mode})")
            ok += 1

        except Exception as e:
            import traceback
            print(f"  [ERR] {name}: {e}")
            traceback.print_exc()
            err += 1

    print(f"\nDone: {ok} packed, {skip} skipped, {err} errors")
    if total_orig > 0:
        ratio = total_packed / total_orig
        print(f"  Raw RGBA: {total_orig:,} bytes -> Packed: {total_packed:,} bytes "
              f"(ratio {ratio:.3f}x, saved {100*(1-ratio):.1f}%)")


def _phase_pack_maps(args: argparse.Namespace,
                     asset_names_set: set[str]) -> None:
    if not (args.build_maps or args.build_ids):
        return

    print("\n=== Building maps and/or app_ids.h ===")
    mf = args.map_filter
    if mf is None or mf == 'auto':
        map_filter_val = None
    elif mf == 'all':
        map_filter_val = 'all'
    else:
        map_filter_val = [n.strip() for n in mf.split(',') if n.strip()]

    (map_names, _bmp_index, sorted_names, name_map,
     type_map, group_map, tag_map) = pack_maps(
        args.exported_dir, args.packed_dir, args.output_dir,
        map_filter=map_filter_val,
        asset_names=asset_names_set,
    )
    print(f"\n  Maps packed: {len(map_names)} ({', '.join(map_names)})")

    if args.build_ids:
        ids_path = args.ids_output or 'app_ids.h'
        ids_dir = os.path.dirname(ids_path)
        if ids_dir:
            os.makedirs(ids_dir, exist_ok=True)
        generate_app_ids_h(
            sorted_names, map_names,
            name_map, type_map, group_map, tag_map,
            ids_path, args.exported_dir,
        )


def main() -> None:
    args = _build_arg_parser().parse_args()
    asset_names_set = _resolve_asset_names(args)
    _resolve_map_filter(args)

    _phase_export(args, asset_names_set)

    files = [Path(f) for f in args.files] if args.files \
            else sorted(Path(args.exported_dir).glob('*.png'))
    os.makedirs(args.output_dir, exist_ok=True)

    sprite_assignments, palettes, has_palette = _phase_palette(args, files)

    # Copy 0.png placeholder into exported/ if missing
    zero_art = os.path.join(args.art_dir, f'{PLACEHOLDER_SPRITE_NAME}.png')
    zero_exp = os.path.join(args.exported_dir, f'{PLACEHOLDER_SPRITE_NAME}.png')
    if os.path.isfile(zero_art) and not os.path.isfile(zero_exp):
        os.makedirs(args.exported_dir, exist_ok=True)
        shutil.copy2(zero_art, zero_exp)
        print(f"  Copied 0.png from {args.art_dir}/ to {args.exported_dir}/")

    map_skip_names = _compute_map_skip_set(args, asset_names_set)
    sprite_pivots = _load_sprite_pivots_from_csvs(args.exported_dir)
    if sprite_pivots:
        print(f"  Loaded pivot data for {len(sprite_pivots)} sprites from CSVs")

    _phase_pack_sprites(
        args, files, sprite_assignments, palettes,
        map_skip_names, sprite_pivots, has_palette,
    )

    _phase_pack_maps(args, asset_names_set)

    if sprite_pivots:
        custom = [(n, px, py) for n, (px, py) in sprite_pivots.items()
                  if px is not None]
        if custom:
            print(f"\n=== Custom pivots ({len(custom)} sprites) ===")
            for name, px, py in sorted(custom):
                print(f"  {name:<30s} pivot=({px:.1f}, {py:.1f})")


if __name__ == '__main__':
    main()
