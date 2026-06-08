#!/usr/bin/env python3
"""
WowCube Packed Sprite Encoder — codec module
============================================

Pure encoding primitives split out of pack.py:

  * Color helpers (RGB565 + A5 quantisation, palette-color encode/decode).
  * EncoderPalette and the median-cut auto-palette builder.
  * Multi-palette grouping (cluster_sprites_grouped, build_grouped_palettes).
  * Palette I/O (save_palette_png / load_palette_for_encoding).
  * BitWriter and the RLE scanline encoder (encode_scanline).
  * 48-byte octBmp_t header build/parse helpers (build_header, read_existing_header,
    compute_*_pivot, compute_default_pivot).
  * The single-sprite packer (pack_sprite) and blob_to_packed_png wrapper.

Contains no PSD/FNT I/O — see pack_psd.py for those.
"""

from __future__ import annotations

import heapq
import math
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
    B_MAX, BYTES_PER_RGBA,
    DEFAULT_OFFSET_BITNESS, DEFAULT_QUALITY_THRESHOLD, G_MAX,
    HDR_OFF_COMPRESSION, HDR_OFF_NUM_PIXELS, HDR_OFF_PIDX, HDR_OFF_WIDTH,
    HEADER_SIZE, MEDIAN_CUT_CHANNEL_WEIGHTS,
    PACKED_COLOR_MASK, PAL_DESCRIPTOR_SIZE, PAL_MAX_PALETTES,
    PAL_MAX_TOTAL_COLORS, PAL_TRANSPARENT_IDX, PALETTE_SIZES_TRIED,
    PALETTE_SPRITE_NAME, PALETTE_TIERS_USABLE, PIVOT_HALFPIX,
    PIVOT_LOCAL_OFFSET, PIVOT_MODE, PIVOT_SCALE, PivotMode,
    PLACEHOLDER_SPRITE_NAME, PRESPLIT_MASK,
    R_MAX, RGB565_MASK, RLE_ENCODE, RLE_MAX_RUN, SpriteFlag, WORD_BITS,
)


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

def compute_atlas_pivot(atlas_x: int, atlas_y: int) -> tuple[float, float]:
    """Pivot value in the utils.exe convention:
        pivot = -(atlas_xy * PIVOT_SCALE + PIVOT_HALFPIX)
    where atlas_xy is the sprite's top-left position on the PSD canvas.
    Used when PIVOT_MODE == PivotMode.ATLAS."""
    return (
        -(atlas_x * PIVOT_SCALE + PIVOT_HALFPIX),
        -(atlas_y * PIVOT_SCALE + PIVOT_HALFPIX),
    )


def compute_legacy_local_pivot(w: int, h: int) -> tuple[float, float]:
    """Pivot value in the legacy psd.exe convention:
        pivot = (w - PIVOT_LOCAL_OFFSET, h - PIVOT_LOCAL_OFFSET)
    Local sprite coordinates pointing at the bottom-right pixel center.
    Matches the byte-exact layout of packed_old/. Used when
    PIVOT_MODE == PivotMode.LEGACY."""
    return (
        float(w) - PIVOT_LOCAL_OFFSET,
        float(h) - PIVOT_LOCAL_OFFSET,
    )


def compute_default_pivot(w: int, h: int,
                          atlas_x: int | None,
                          atlas_y: int | None) -> tuple[float, float]:
    """Dispatch to the active pivot encoding selected by PIVOT_MODE."""
    if PIVOT_MODE == PivotMode.LEGACY:
        return compute_legacy_local_pivot(w, h)
    if atlas_x is None or atlas_y is None:
        raise ValueError(
            "ATLAS pivot mode requires atlas_x and atlas_y for the sprite.")
    return compute_atlas_pivot(atlas_x, atlas_y)


def build_header(w: int, h: int, symbol_bitness: int, offset_bitness: int,
                 pidx: int, flags: int,
                 atlas_x: int | None = None, atlas_y: int | None = None,
                 pivot_x: float | None = None, pivot_y: float | None = None,
                 num_pixels: int = 0, tags: int = 0, number: int = 0,
                 group: int = 0, sprite_type: int = 0, seq: int = 0, rate: int = 1,
                 bx: float = 0.0, by: float = 0.0,
                 bw: float = 0.0, bh: float = 0.0) -> bytes:
    """Build a 48-byte octBmp_t header (without PackerSizes).

    Pivot is selected by config.PIVOT_MODE:
      - PivotMode.LEGACY  -> (w - PIVOT_LOCAL_OFFSET, h - PIVOT_LOCAL_OFFSET)
      - PivotMode.ATLAS   -> -(atlas_xy * PIVOT_SCALE + PIVOT_HALFPIX)
    Callers may also pass pivot_x/pivot_y explicitly to bypass both modes
    (used for the reserved 0.png placeholder and advanced test cases).
    """
    if pivot_x is None or pivot_y is None:
        cpx, cpy = compute_default_pivot(w, h, atlas_x, atlas_y)
        if pivot_x is None: pivot_x = cpx
        if pivot_y is None: pivot_y = cpy

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
    """Read the HEADER_SIZE-byte header from an existing packed sprite.

    Old packs written before HEADER_SIZE was bumped to 52 produced 48-byte
    headers. Returning None for those forces a fresh header rebuild on repack
    instead of silently mixing layouts.
    """
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
    atlas_x: int | None = None,
    atlas_y: int | None = None,
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
            atlas_x=atlas_x, atlas_y=atlas_y,
            pivot_x=pivot_x, pivot_y=pivot_y,
        )

    # ── Vectorised pixel quantisation ──────────────────────────────────
    indices_2d = palette.quantize_image(pixels)
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
    struct.pack_into('<I', header_mut, HDR_OFF_NUM_PIXELS, len(texel_data))
    return bytes(header_mut) + bytes(trims) + texel_data


def blob_to_packed_png(blob: bytes) -> Image.Image:
    """Wrap a raw binary blob in a 1×W RGBA PNG (the packed format container)."""
    blob = pad_to_multiple(blob, BYTES_PER_RGBA)
    width = len(blob) // BYTES_PER_RGBA
    return Image.frombytes('RGBA', (width, 1), blob)
