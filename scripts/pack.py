#!/usr/bin/env python3
"""
WowCube Packed Sprite Encoder
==============================
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

import struct
import sys
import os
import math
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)


# ── Constants from oct_consts.h ──────────────────────────────────────────────

COMPR1_LEN_DECODE_MASK = 127

# Sprite flags
OCT_FLAG_ALPHA    = 1 << 0
OCT_FLAG_FULLSIZE = 1 << 1
OCT_FLAG_ADDITIVE = 1 << 2
OCT_FLAG_BG       = 1 << 3

HEADER_SIZE = 48


# ── RLE encoding table ──────────────────────────────────────────────────────
# Reverse lookup: run_length -> (bit_pattern, num_bits)
# Built from COMPR1_LEN_DECODE / COMPR1_LEN_CONSUME tables in oct_consts.h

RLE_ENCODE = {
     1: (0x00, 1),
     2: (0x05, 3),
     3: (0x03, 4),
     4: (0x0b, 4),
     5: (0x07, 5),
     6: (0x17, 5),
     7: (0x0f, 7),
     8: (0x4f, 7),
     9: (0x2f, 7),
    10: (0x6f, 7),
    11: (0x1f, 7),
    12: (0x5f, 7),
    13: (0x3f, 7),
    14: (0x7f, 7),
    15: (0x01, 3),
}


# ── Color conversion helpers ─────────────────────────────────────────────────

def rgba_to_rgb565(r, g, b):
    """Convert 8-bit RGB to 16-bit RGB565."""
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    return (r5 << 11) | (g6 << 5) | b5


def rgb565_to_presplit(rgb565):
    """Convert RGB565 to pre-split 0x07e0f81f format for fast blending."""
    return (rgb565 | (rgb565 << 16)) & 0x07e0f81f


def rgba_to_palette_color(r, g, b, a, has_alpha):
    """Convert RGBA8888 to the palette's uint32 storage format."""
    rgb565 = rgba_to_rgb565(r, g, b)
    if has_alpha:
        alpha5 = (a >> 3) & 0x1F
        presplit = rgb565_to_presplit(rgb565)
        return (alpha5 << 27) | presplit
    else:
        return rgb565


def color_distance_sq(r1, g1, b1, a1, r2, g2, b2, a2):
    """Squared Euclidean distance in RGBA space (alpha-weighted)."""
    dr = int(r1) - int(r2)
    dg = int(g1) - int(g2)
    db = int(b1) - int(b2)
    da = int(a1) - int(a2)
    return dr*dr + dg*dg + db*db + da*da


# ── Palette ──────────────────────────────────────────────────────────────────

class EncoderPalette:
    """Palette for encoding: maps RGBA colors to palette indices."""

    def __init__(self, colors_rgba, has_alpha=True):
        """
        colors_rgba: list of (r8, g8, b8, a8) tuples, index 0 = transparent.
        """
        self.colors = colors_rgba
        self.has_alpha = has_alpha
        # Build a cache for fast lookup
        self._cache = {}

    def find_nearest(self, r, g, b, a):
        """Find the palette index closest to the given RGBA color.
        Returns 0 for fully transparent pixels."""
        if a == 0:
            return 0

        key = (r, g, b, a)
        if key in self._cache:
            return self._cache[key]

        best_idx = 1
        best_dist = float('inf')

        for i in range(1, len(self.colors)):
            cr, cg, cb, ca = self.colors[i]
            d = color_distance_sq(r, g, b, a, cr, cg, cb, ca)
            if d < best_dist:
                best_dist = d
                best_idx = i
                if d == 0:
                    break

        self._cache[key] = best_idx
        return best_idx


# ── Auto-palette: color collection & median-cut quantization ─────────────

def symbol_bitness_for_size(palette_size):
    """Return the minimum number of bits to encode palette_size indices."""
    if palette_size <= 1:
        return 1
    return max(1, math.ceil(math.log2(palette_size)))


def collect_sprite_colors(file_list):
    """Scan exported PNGs and collect all non-transparent colors.
    Returns dict: (r8, g8, b8, a8) -> pixel_count."""
    color_counts = {}
    for fpath in file_list:
        name = Path(fpath).stem
        if name in ('pal', '0') or Path(fpath).suffix.lower() != '.png':
            continue
        try:
            img = Image.open(fpath).convert('RGBA')
            pixels = np.array(img).reshape(-1, 4)
            for r, g, b, a in pixels:
                if a == 0:
                    continue
                key = (int(r), int(g), int(b), int(a))
                color_counts[key] = color_counts.get(key, 0) + 1
        except Exception:
            pass
    return color_counts


def rgba_to_565_a5(r8, g8, b8, a8):
    """Quantize RGBA8888 to (r5, g6, b5, a5) tuple."""
    return ((r8 >> 3) & 0x1F, (g8 >> 2) & 0x3F, (b8 >> 3) & 0x1F, (a8 >> 3) & 0x1F)


def expand_565_a5(r5, g6, b5, a5):
    """Expand (r5, g6, b5, a5) back to RGBA8888."""
    r8 = (r5 << 3) | (r5 >> 2)
    g8 = (g6 << 2) | (g6 >> 4)
    b8 = (b5 << 3) | (b5 >> 2)
    a8 = (a5 << 3) | (a5 >> 2)
    return (r8, g8, b8, a8)


def unique_quantized_colors(color_counts):
    """Convert color_counts to unique quantized (r5,g6,b5,a5) colors with weights.
    Returns list of ((r5,g6,b5,a5), weight)."""
    quantized = {}
    for (r8, g8, b8, a8), count in color_counts.items():
        q = rgba_to_565_a5(r8, g8, b8, a8)
        quantized[q] = quantized.get(q, 0) + count
    return list(quantized.items())


class MedianCutBox:
    """A box of colors for median-cut quantization."""

    def __init__(self, colors_weights):
        """colors_weights: list of ((r5, g6, b5, a5), weight)."""
        self.items = colors_weights
        self.total_weight = sum(w for _, w in colors_weights)
        self._compute_ranges()

    def _compute_ranges(self):
        """Compute min/max per channel."""
        if not self.items:
            self.ranges = [(0, 0)] * 4
            return
        cols = [c for c, _ in self.items]
        self.ranges = []
        for ch in range(4):
            vals = [c[ch] for c in cols]
            self.ranges.append((min(vals), max(vals)))

    @property
    def max_range_channel(self):
        """Channel index with the largest range (weighted by bit significance)."""
        # Weight channels by their bit range to break ties meaningfully
        # R: 0-31, G: 0-63, B: 0-31, A: 0-31
        weights = [2.0, 1.0, 2.0, 2.0]  # normalize G range
        best_ch = 0
        best_span = -1
        for ch in range(4):
            span = (self.ranges[ch][1] - self.ranges[ch][0]) * weights[ch]
            if span > best_span:
                best_span = span
                best_ch = ch
        return best_ch

    @property
    def can_split(self):
        return len(self.items) >= 2 and any(hi > lo for lo, hi in self.ranges)

    def split(self):
        """Split box at median along the widest channel. Returns two boxes."""
        ch = self.max_range_channel
        self.items.sort(key=lambda x: x[0][ch])

        # Find split point closest to half the total weight
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

        return MedianCutBox(self.items[:split_idx]), MedianCutBox(self.items[split_idx:])

    def representative(self):
        """Weighted average color of the box, quantized to (r5,g6,b5,a5)."""
        if not self.items:
            return (0, 0, 0, 0)
        avg = [0.0] * 4
        for (c, w) in self.items:
            for ch in range(4):
                avg[ch] += c[ch] * w
        tw = self.total_weight
        # Clamp to valid ranges: R 0-31, G 0-63, B 0-31, A 0-31
        maxvals = [31, 63, 31, 31]
        result = tuple(min(maxvals[ch], max(0, round(avg[ch] / tw))) for ch in range(4))
        return result


def median_cut(quantized_colors_weights, target_count):
    """Reduce colors to target_count using median-cut.
    quantized_colors_weights: list of ((r5,g6,b5,a5), weight).
    Returns list of (r5, g6, b5, a5) representative colors."""
    if len(quantized_colors_weights) <= target_count:
        return [c for c, _ in quantized_colors_weights]

    import heapq

    # Splittable boxes in a max-heap (by -total_weight)
    initial_box = MedianCutBox(quantized_colors_weights)
    heap = [(-initial_box.total_weight, 0, initial_box)]
    box_id = 1
    # Frozen boxes that can't be split further
    frozen = []

    while len(heap) + len(frozen) < target_count and heap:
        neg_w, _, box = heapq.heappop(heap)
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

    # Collect representatives from all boxes
    result = [b.representative() for b in frozen]
    result += [item[2].representative() for item in heap]
    return result[:target_count]


def measure_palette_quality(color_counts, palette_rgba):
    """Measure how well palette matches the original colors.
    Returns (mean_error, max_error, pct_exact) in RGB888 space."""
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
        max_error = max(max_error, err)
        total_pixels += count

    if total_pixels == 0:
        return 0, 0, 100.0

    mean_err = total_error / total_pixels
    pct_exact = 100.0 * exact_count / total_pixels
    return mean_err, max_error, pct_exact


def build_auto_palette(file_list, max_colors=256, target_colors=None,
                       quality_threshold=8):
    """
    Automatically build a palette from exported sprites.

    If target_colors is set, build exactly that size palette.
    Otherwise, try sizes 16, 32, 64, 128, 256 (up to max_colors) and
    pick the smallest one where max per-pixel error <= quality_threshold.

    Returns (EncoderPalette, palette_size, symbol_bitness, palette_colors_rgba).
    """
    print("  Scanning sprites for color analysis...")
    color_counts = collect_sprite_colors(file_list)
    total_unique = len(color_counts)
    total_pixels = sum(color_counts.values())
    print(f"  Found {total_unique} unique RGBA colors across {total_pixels:,} opaque pixels")

    # Quantize to RGB565+A5
    quant_colors = unique_quantized_colors(color_counts)
    unique_q = len(quant_colors)
    print(f"  After RGB565+A5 quantization: {unique_q} unique colors")

    # Determine sizes to try
    if target_colors is not None:
        sizes_to_try = [target_colors]
    else:
        # Standard sizes: palette index 0 is transparent, so usable = size-1
        all_sizes = [16, 32, 64, 128, 256]
        sizes_to_try = [s for s in all_sizes if s <= max_colors]
        if not sizes_to_try:
            sizes_to_try = [max_colors]

    best_pal = None
    best_size = None
    best_sym = None
    best_colors = None

    for pal_size in sizes_to_try:
        usable = pal_size - 1  # index 0 = transparent
        print(f"\n  Trying palette size {pal_size} ({usable} usable colors)...")

        if unique_q <= usable:
            # All quantized colors fit — no need to reduce
            pal_q = [c for c, _ in quant_colors]
            print(f"    All {unique_q} quantized colors fit, no reduction needed")
        else:
            # Median-cut quantization
            pal_q = median_cut(quant_colors, usable)
            print(f"    Median-cut reduced {unique_q} -> {len(pal_q)} colors")

        # Build RGBA8888 palette from quantized colors
        # Index 0 = transparent
        palette_rgba = [(0, 0, 0, 0)]
        for (r5, g6, b5, a5) in pal_q:
            palette_rgba.append(expand_565_a5(r5, g6, b5, a5))

        # Pad to pal_size
        while len(palette_rgba) < pal_size:
            palette_rgba.append((0, 0, 0, 0))

        sym_bits = symbol_bitness_for_size(pal_size)

        # Measure quality
        mean_err, max_err, pct_exact = measure_palette_quality(color_counts, palette_rgba)
        print(f"    Quality: mean_err={mean_err:.2f}, max_err={max_err}, exact={pct_exact:.1f}%")

        encoder_pal = EncoderPalette(palette_rgba, has_alpha=True)
        best_pal = encoder_pal
        best_size = pal_size
        best_sym = sym_bits
        best_colors = palette_rgba

        if target_colors is not None:
            # User forced this size, use it
            break

        if mean_err <= quality_threshold:
            print(f"    -> Accepted! Mean error {mean_err:.2f} <= threshold {quality_threshold}")
            break
        else:
            print(f"    -> Mean error {mean_err:.2f} > threshold {quality_threshold}, trying larger...")

    print(f"\n  Final palette: {best_size} colors, {best_sym}-bit symbols")
    return best_pal, best_size, best_sym, best_colors


# ── Multi-palette grouping ───────────────────────────────────────────────

PALETTE_TIERS = [15, 31, 63, 127, 255]  # usable colors per tier (index 0 = transparent)


class PaletteGroup:
    """A group of sprites sharing one palette."""

    def __init__(self):
        self.sprite_names = []
        self.colors = set()  # unique (r5, g6, b5, a5) quantized colors

    @property
    def num_unique(self):
        return len(self.colors)

    def can_add_within(self, new_colors, limit):
        """Can we add new_colors and stay within limit unique colors?"""
        return len(self.colors | new_colors) <= limit

    def overlap(self, new_colors):
        """Number of shared colors with new_colors."""
        return len(self.colors & new_colors)

    def add(self, name, colors):
        self.sprite_names.append(name)
        self.colors |= colors


def snap_color(r5, g6, b5, a5, tolerance):
    """Snap a quantized color to a coarser grid to merge similar colors.
    tolerance=0: no snapping (exact). tolerance=1: ±1 in 565 space. etc."""
    if tolerance <= 0:
        return (r5, g6, b5, a5)
    t = tolerance
    # Snap each channel to nearest multiple of (2*t), keeping within range
    r5 = min(((r5 + t) // (2 * t)) * (2 * t), 31)
    g6 = min(((g6 + t) // (2 * t)) * (2 * t), 63)
    b5 = min(((b5 + t) // (2 * t)) * (2 * t), 31)
    a5 = min(((a5 + t) // (2 * t)) * (2 * t), 31)
    return (r5, g6, b5, a5)


def extract_per_sprite_colors(file_list, color_tolerance=0):
    """Extract unique quantized colors for each sprite.
    color_tolerance: merge colors within this distance in 565 space (0=exact).
    Returns dict: sprite_name -> set of (r5, g6, b5, a5)."""
    result = {}
    for fpath in file_list:
        name = Path(fpath).stem
        if name in ('pal', '0') or Path(fpath).suffix.lower() != '.png':
            continue
        try:
            img = Image.open(fpath).convert('RGBA')
            pixels = np.array(img).reshape(-1, 4)
            colors = set()
            for r, g, b, a in pixels:
                if a == 0:
                    continue
                c = rgba_to_565_a5(int(r), int(g), int(b), int(a))
                if color_tolerance > 0:
                    c = snap_color(*c, color_tolerance)
                colors.add(c)
            result[name] = colors
        except Exception:
            result[name] = set()
    return result


def cluster_sprites_grouped(sprite_colors, max_colors=256, pre_reduce=None):
    """
    Group sprites by color similarity, preferring the smallest possible palette
    per group (even at the cost of more groups).

    Algorithm:
      Phase 0: Pre-reduce sprites with >pre_reduce colors via median-cut.
      Phase 1: Greedy grouping — sort ascending by color count, assign each
               sprite to a group ONLY if it fits without increasing the tier.
               Otherwise create a new group at the minimum tier for that sprite.
      Phase 2: Shrink each group's tier to the minimum that fits.
      Phase 3: If >254 groups (pidx uint8 limit), merge most similar pairs.

    Returns: list of (PaletteGroup, tier_usable_colors)
    """
    max_usable = min(max_colors - 1, 255)
    tiers = [t for t in PALETTE_TIERS if t <= max_usable]
    if not tiers:
        tiers = [max_usable]

    # Pre-reduction limit: default to half of max tier for good groupability
    if pre_reduce is None:
        pre_reduce = max_usable // 2
    pre_reduce = min(pre_reduce, max_usable)

    # Phase 0: pre-reduce large sprites so they can share groups
    reduced = {}
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

    # Phase 1: greedy grouping — prefer smallest palettes
    # Sort ascending by color count so small sprites (fonts, icons) group first
    sorted_sprites = sorted(reduced.items(), key=lambda x: len(x[1]))
    groups = []  # list of (PaletteGroup, current_tier)

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

        # Determine minimum tier this sprite needs on its own
        sprite_tier = next((t for t in tiers if t >= n), tiers[-1])

        # Try to fit into an existing group WITHOUT increasing its tier
        best_idx = None
        best_new_colors = float('inf')

        for i, (group, cur_tier) in enumerate(groups):
            combined = len(group.colors | colors)
            # Only consider if combined colors still fit in the group's current tier
            if combined <= cur_tier:
                new_colors = combined - group.num_unique
                if new_colors < best_new_colors:
                    best_new_colors = new_colors
                    best_idx = i

        if best_idx is not None:
            # Fits without tier increase — add to this group
            groups[best_idx][0].add(name, colors)
        else:
            # No group can absorb without tier increase — create new group
            g = PaletteGroup()
            g.add(name, colors)
            groups.append((g, sprite_tier))

    # Phase 2: shrink tiers to actual minimum
    for i, (group, _) in enumerate(groups):
        actual = group.num_unique
        tier = next((t for t in tiers if t >= actual), tiers[-1])
        groups[i] = (group, tier)

    # Phase 3: merge excess groups to respect engine limits
    # OCT_PALS_CAP = 64, OctPalsData = 16*256 = 4096 total color entries
    MAX_PALETTES = 63       # leave slot 0 for engine use
    MAX_TOTAL_COLORS = 4096

    def _total_colors(grps):
        return sum(t + 1 for _, t in grps)

    # 3a: merge if too many groups
    while len(groups) > MAX_PALETTES:
        groups.sort(key=lambda x: x[0].num_unique)
        g1, _ = groups.pop(0)
        g2, _ = groups.pop(0)
        merged = PaletteGroup()
        merged.sprite_names = g1.sprite_names + g2.sprite_names
        merged.colors = g1.colors | g2.colors
        tier = next((t for t in tiers if t >= merged.num_unique), tiers[-1])
        groups.append((merged, tier))

    # 3b: merge if total color entries exceed OctPalsData capacity
    while _total_colors(groups) > MAX_TOTAL_COLORS and len(groups) > 1:
        groups.sort(key=lambda x: x[0].num_unique)
        g1, _ = groups.pop(0)
        g2, _ = groups.pop(0)
        merged = PaletteGroup()
        merged.sprite_names = g1.sprite_names + g2.sprite_names
        merged.colors = g1.colors | g2.colors
        tier = next((t for t in tiers if t >= merged.num_unique), tiers[-1])
        groups.append((merged, tier))

    total_c = _total_colors(groups)
    if total_c > MAX_TOTAL_COLORS:
        print(f"  WARNING: {total_c} total palette colors exceeds engine limit of {MAX_TOTAL_COLORS}!")

    groups.sort(key=lambda x: (x[1], -len(x[0].sprite_names)))
    return groups


def build_grouped_palettes(file_list, max_colors=256, quality_threshold=8,
                           pre_reduce=None, color_tolerance=0):
    """
    Build multiple palettes grouped by color similarity.

    Returns:
        sprite_assignments: dict name -> (pidx, EncoderPalette, symbol_bitness)
        all_palette_data: list of (palette_colors_rgba, symbol_bitness) for pal.png
    """
    print("  Scanning sprites for per-sprite color analysis...")
    if color_tolerance > 0:
        print(f"  Color tolerance: {color_tolerance} (merging similar colors in 565 space)")
    sprite_colors = extract_per_sprite_colors(file_list, color_tolerance=color_tolerance)
    total_sprites = len(sprite_colors)

    # Report statistics
    color_counts = {}
    for name, colors in sprite_colors.items():
        count = len(colors)
        if count not in color_counts:
            color_counts[count] = 0
        color_counts[count] += 1

    total_unique = len(set().union(*sprite_colors.values())) if sprite_colors else 0
    print(f"  {total_sprites} sprites, {total_unique} unique quantized colors total")

    max_per_sprite = max((len(c) for c in sprite_colors.values()), default=0)
    min_per_sprite = min((len(c) for c in sprite_colors.values()), default=0)
    print(f"  Per-sprite unique colors: min={min_per_sprite}, max={max_per_sprite}")

    # Filter tiers to max_colors
    tiers = [t for t in PALETTE_TIERS if t + 1 <= max_colors]
    if not tiers:
        tiers = [max_colors - 1]

    print(f"\n  Clustering into palette groups (max {max_colors} colors per group)...")
    groups = cluster_sprites_grouped(sprite_colors, max_colors, pre_reduce=pre_reduce)

    # Build palette for each group
    sprite_assignments = {}
    all_palette_data = []

    print(f"  Created {len(groups)} palette group(s):\n")

    for gi, (group, tier) in enumerate(groups):
        pidx = gi  # 0-based (matches OctPals[] array index)
        pal_size = tier + 1  # e.g. tier=15 -> 16 colors
        sym_bits = symbol_bitness_for_size(pal_size)

        # Collect all unique colors in the group
        unique_colors = list(group.colors)

        if len(unique_colors) <= tier:
            # All colors fit — use them directly
            pal_q = unique_colors
        else:
            # Need median-cut (group has >tier unique colors after merging)
            weighted = [(c, 1) for c in unique_colors]
            pal_q = median_cut(weighted, tier)

        # Build RGBA8888 palette
        palette_rgba = [(0, 0, 0, 0)]  # index 0 = transparent
        for (r5, g6, b5, a5) in pal_q:
            palette_rgba.append(expand_565_a5(r5, g6, b5, a5))

        # Pad to pal_size
        while len(palette_rgba) < pal_size:
            palette_rgba.append((0, 0, 0, 0))

        encoder_pal = EncoderPalette(palette_rgba, has_alpha=True)
        all_palette_data.append((palette_rgba, sym_bits))

        # Assign all sprites in this group
        for name in group.sprite_names:
            sprite_assignments[name] = (pidx, encoder_pal, sym_bits)

        print(f"    [{pidx}] {pal_size} colors ({sym_bits}-bit), "
              f"{len(group.sprite_names)} sprites, "
              f"{group.num_unique} unique colors")

    return sprite_assignments, all_palette_data


def palette_color_to_uint32(r8, g8, b8, a8, has_alpha=True):
    """Convert RGBA8888 to the uint32 storage format used in pal.png."""
    rgb565 = rgba_to_rgb565(r8, g8, b8)
    if has_alpha:
        alpha5 = (a8 >> 3) & 0x1F
        presplit = rgb565_to_presplit(rgb565)
        return (alpha5 << 27) | presplit
    else:
        return rgb565


def save_palette_png(palette_colors_rgba, output_path, has_alpha=True):
    """
    Save palette as pal.png in WowCube format.

    palette_colors_rgba: either a single list of (r8,g8,b8,a8) tuples,
                         or a list of such lists for multiple palettes.
    """
    # Normalize: if first element is a tuple, wrap in a list
    if palette_colors_rgba and isinstance(palette_colors_rgba[0], tuple):
        palette_list = [palette_colors_rgba]
    else:
        palette_list = palette_colors_rgba

    num_palettes = len(palette_list)
    flags = OCT_FLAG_ALPHA if has_alpha else 0

    data = bytearray()
    data.extend(struct.pack('<I', num_palettes))

    # Compute ColorsBufferIndex offsets
    cbi_offset = 0
    descriptors = []
    for i, pal_colors in enumerate(palette_list):
        pal_size = len(pal_colors)
        k = pal_size - 1
        descriptors.append((i, 0, k, 0, flags, cbi_offset))
        cbi_offset += pal_size

    # Write octPal_t descriptors (12 bytes each)
    for (pal_id, blend, k, anims, fl, cbi) in descriptors:
        data.append(pal_id & 0xFF)
        data.append(blend & 0xFF)
        data.append(k & 0xFF)
        data.append(anims & 0xFF)
        data.extend(struct.pack('<I', fl))
        data.extend(struct.pack('<i', cbi))

    # Write all color data
    total_colors = 0
    for pal_colors in palette_list:
        for (r8, g8, b8, a8) in pal_colors:
            c32 = palette_color_to_uint32(r8, g8, b8, a8, has_alpha)
            data.extend(struct.pack('<I', c32))
            total_colors += 1

    # Wrap in RGBA PNG
    blob = bytes(data)
    while len(blob) % 4 != 0:
        blob += b'\x00'
    width = len(blob) // 4
    img = Image.frombytes('RGBA', (width, 1), blob)
    img.save(output_path)
    sizes = [len(p) for p in palette_list]
    print(f"  Saved {num_palettes} palette(s) ({sizes}) to {output_path}")


def load_palette_for_encoding(pal_png_path):
    """Load existing pal.png and return EncoderPalette objects keyed by pidx."""
    img = Image.open(pal_png_path)
    raw = img.tobytes()

    num_palettes = struct.unpack_from('<I', raw, 0)[0]

    off = 4
    pal_descriptors = []
    for i in range(num_palettes):
        pal_id = raw[off]
        blend  = raw[off + 1]
        k      = raw[off + 2]
        anims  = raw[off + 3]
        flags  = struct.unpack_from('<I', raw, off + 4)[0]
        cbi    = struct.unpack_from('<i', raw, off + 8)[0]
        pal_descriptors.append((pal_id, blend, k, anims, flags, cbi))
        off += 12

    colors_offset = off
    num_color_words = (len(raw) - colors_offset) // 4
    all_colors_raw = list(struct.unpack_from(f'<{num_color_words}I', raw, colors_offset))

    palettes = {}
    for i, (pal_id, blend, k, anims, flags, cbi) in enumerate(pal_descriptors):
        has_alpha = bool(flags & OCT_FLAG_ALPHA)
        num_colors = k + 1
        colors_raw = all_colors_raw[cbi:cbi + num_colors]

        # Decode raw uint32 colors to RGBA8888
        colors_rgba = [(0, 0, 0, 0)]  # index 0 = transparent
        for c32 in colors_raw[1:]:  # skip index 0 in raw palette
            if has_alpha:
                alpha5 = (c32 >> 27) & 0x1F
                alpha8 = (alpha5 << 3) | (alpha5 >> 2)
                packed = c32 & 0x07FFFFFF
                rgb565 = (packed | (packed >> 16)) & 0xFFFF
            else:
                rgb565 = c32 & 0xFFFF
                alpha8 = 255

            r5 = (rgb565 >> 11) & 0x1F
            g6 = (rgb565 >> 5) & 0x3F
            b5 = rgb565 & 0x1F
            r8 = (r5 << 3) | (r5 >> 2)
            g8 = (g6 << 2) | (g6 >> 4)
            b8 = (b5 << 3) | (b5 >> 2)
            colors_rgba.append((r8, g8, b8, alpha8))

        # Pad to full size (index 0 already prepended)
        while len(colors_rgba) < num_colors:
            colors_rgba.append((0, 0, 0, 0))

        pidx = i  # 0-based (matches OctPals[] array index)
        palettes[pidx] = EncoderPalette(colors_rgba, has_alpha)

    return palettes, raw  # return raw for copying pal.png as-is


# ── Bitstream writer ─────────────────────────────────────────────────────────

class BitWriter:
    """Bit-level writer producing the same bitstream format as the decoder expects."""

    def __init__(self):
        self.buffer = bytearray()
        self.current_word = 0
        self.bits_in_word = 0

    def write_bits(self, value, num_bits):
        """Write `num_bits` least-significant bits of `value`."""
        value &= (1 << num_bits) - 1
        self.current_word |= value << self.bits_in_word
        self.bits_in_word += num_bits

        # Flush complete 32-bit words
        while self.bits_in_word >= 32:
            self.buffer.extend(struct.pack('<I', self.current_word & 0xFFFFFFFF))
            self.current_word >>= 32
            self.bits_in_word -= 32

    def flush(self):
        """Flush remaining bits, padding with zeros to byte boundary."""
        if self.bits_in_word > 0:
            # Pad to full bytes
            num_bytes = (self.bits_in_word + 7) // 8
            for i in range(num_bytes):
                self.buffer.append(self.current_word & 0xFF)
                self.current_word >>= 8
            self.bits_in_word = 0
            self.current_word = 0

    def get_bytes(self):
        """Return the written data as bytes."""
        self.flush()
        return bytes(self.buffer)


def encode_scanline(indices, symbol_bitness):
    """
    Encode a scanline of palette indices into a bit-packed RLE stream.

    Returns the encoded bytes for this scanline.
    """
    writer = BitWriter()
    i = 0
    n = len(indices)

    while i < n:
        symbol = indices[i]

        # Count run length (how many consecutive identical symbols)
        run = 1
        while i + run < n and indices[i + run] == symbol and run < 15:
            run += 1

        # Write symbol
        writer.write_bits(symbol, symbol_bitness)

        # Write RLE code for this run length
        rle_bits, rle_nbits = RLE_ENCODE[run]
        writer.write_bits(rle_bits, rle_nbits)

        i += run

    return writer.get_bytes()


# ── Header builder ───────────────────────────────────────────────────────────

def build_header(w, h, symbol_bitness, offset_bitness, pidx, flags,
                 pivot_x=None, pivot_y=None, num_pixels=0,
                 tags=0, number=0, group=0, sprite_type=0, seq=0, rate=1,
                 bx=0.0, by=0.0, bw=0.0, bh=0.0):
    """Build a 48-byte octBmp_t header (without PackerSizes)."""
    if pivot_x is None:
        pivot_x = w - 0.5
    if pivot_y is None:
        pivot_y = h - 0.5

    compression = (offset_bitness << 8) | symbol_bitness

    header = struct.pack('<I',     num_pixels)
    header += struct.pack('<ff',   pivot_x, pivot_y)
    header += struct.pack('<ffff', bx, by, bw, bh)
    header += struct.pack('<I',    tags)
    header += struct.pack('<I',    compression)
    header += struct.pack('<hh',   w, h)
    header += struct.pack('<h',    number)
    header += struct.pack('<BB',   group, sprite_type)
    header += struct.pack('<BB',   flags, pidx)
    header += struct.pack('<bb',   seq, rate)

    assert len(header) == HEADER_SIZE
    return header


def read_existing_header(packed_png_path):
    """Read header from an existing packed sprite. Returns raw 48 bytes or None."""
    try:
        img = Image.open(packed_png_path)
        raw = img.tobytes()
        if len(raw) >= HEADER_SIZE:
            return raw[:HEADER_SIZE]
    except Exception:
        pass
    return None


# ── Single sprite packer ─────────────────────────────────────────────────────

def pack_sprite(exported_png_path, palette, header_bytes=None,
                pidx=0, flags=OCT_FLAG_ALPHA, symbol_bitness=8,
                offset_bitness=5, symbol_bitness_override=None,
                pivot_x=None, pivot_y=None):
    """
    Pack an exported RGBA PNG into the packed format.

    If header_bytes is provided (from existing packed sprite), reuse it.
    Otherwise, generate a new header from the given parameters.

    Returns packed binary data as bytes, or None on error.
    """
    img = Image.open(exported_png_path).convert('RGBA')
    pixels = np.array(img)
    h, w = pixels.shape[:2]

    if header_bytes:
        # Reuse existing header but potentially update W/H if they changed
        header = bytearray(header_bytes)
        old_w, old_h = struct.unpack_from('<hh', header, 36)
        if old_w != w or old_h != h:
            # Update dimensions in header
            struct.pack_into('<hh', header, 36, w, h)
        # Read symbol_bitness from existing header
        compression = struct.unpack_from('<I', header, 32)[0]
        symbol_bitness = compression & 0xFF
        offset_bitness = (compression >> 8) & 0xFF
        pidx_from_header = header[45]
        # Apply symbol_bitness override if building new palette
        if symbol_bitness_override is not None:
            symbol_bitness = symbol_bitness_override
            compression = (offset_bitness << 8) | symbol_bitness
            struct.pack_into('<I', header, 32, compression)
            # Update pidx to 1 (new palette)
            header[45] = pidx
        header = bytes(header)
    else:
        header = build_header(
            w, h, symbol_bitness, offset_bitness, pidx, flags,
            pivot_x=pivot_x, pivot_y=pivot_y,
        )
        pidx_from_header = pidx

    # Quantize pixels to palette indices
    indices_2d = np.zeros((h, w), dtype=int)
    num_opaque = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[y, x]
            if a == 0:
                indices_2d[y, x] = 0
            else:
                indices_2d[y, x] = palette.find_nearest(int(r), int(g), int(b), int(a))
                num_opaque += 1

    # Encode each scanline
    encoded_lines = []
    for y in range(h):
        line_indices = indices_2d[y].tolist()
        line_bytes = encode_scanline(line_indices, symbol_bitness)
        encoded_lines.append(line_bytes)

    # Build scanline trim array (byte length of each encoded line)
    trims = bytearray()
    for lb in encoded_lines:
        trims.append(len(lb) & 0xFF)

    # Pad trims to multiple of 4
    trims_padded_size = ((h + 3) // 4) * 4
    while len(trims) < trims_padded_size:
        trims.append(0)

    # Concatenate texel data
    texel_data = b''.join(encoded_lines)

    # Update num_pixels in header
    header = bytearray(header)
    struct.pack_into('<I', header, 0, num_opaque)
    header = bytes(header)

    # Assemble final blob
    blob = header + bytes(trims) + texel_data
    return blob


def blob_to_packed_png(blob):
    """Convert a raw binary blob to a 1xW RGBA PNG (packed format container)."""
    # Pad to multiple of 4 bytes (RGBA pixel = 4 bytes)
    while len(blob) % 4 != 0:
        blob = blob + b'\x00'

    width = len(blob) // 4
    img = Image.frombytes('RGBA', (width, 1), blob)
    return img


# ── PSD/FNT export (Python fallback via psd-tools + BMFont parser) ──────────


def normalize_layer_name(name):
    """
    Normalize a PSD layer name to a filesystem-safe PNG name.
    Matches WowCube PSD naming conventions: lowercase, hyphens → underscores,
    spaces → underscores.
    Strips =value, %type, and &group suffixes.

    Examples:
      "BG-S2-1"                → "bg_s2_1"
      "Correct Code&correct"   → "correct_code"
      "n_0=5%Numbers"          → "n_0"
      "MainGear_00&game"       → "maingear_00"
    """
    # Strip &group (may appear before or after %type)
    base = name.split('&')[0]
    # Strip %type
    base = base.split('%')[0]
    # Strip =value (e.g. "n_0=5" → "n_0")
    base = base.split('=')[0]
    # Strip !rate (e.g. "Twist_00!rate10" → "Twist_00")
    base = base.split('!')[0]
    # Lowercase, hyphens and spaces → underscores
    return base.lower().replace('-', '_').replace(' ', '_')


def parse_layer_metadata(name):
    """
    Parse PSD layer name metadata.
    Format: BaseName=value%type&group#tag!rate  (any order of suffixes)

    Returns (base_name, obj_name, type_name, group_name, tag_name).
    """
    import re
    obj_name = ''
    type_name = ''
    group_name = ''
    tag_name = ''

    def norm(s):
        return s.lower().replace('-', '_').replace(' ', '_')

    # Extract $name from anywhere in the string
    m = re.search(r'\$([^%&=$#!]+)', name)
    if m:
        obj_name = m.group(1)

    # Extract %type from anywhere in the string
    m = re.search(r'%([^%&=$#!]+)', name)
    if m:
        type_name = m.group(1)

    # Extract &group from anywhere in the string
    m = re.search(r'&([^%&=$#!]+)', name)
    if m:
        group_name = m.group(1)

    # Extract #tag from anywhere in the string
    m = re.search(r'#([^%&=$#!]+)', name)
    if m:
        tag_name = m.group(1)

    # Base name: everything before the first special char (%&#$=!) that's a suffix
    base = re.split(r'[%&#$!]', name)[0]
    # Strip =value from base (e.g. "n_0=5" → "n_0")
    base = base.split('=')[0] if '=' in base else base

    return base, norm(obj_name), norm(type_name), norm(group_name), norm(tag_name)


def parse_layer_rate(name):
    """Extract animation rate from '!rateN' suffix. Returns int or None."""
    import re
    m = re.search(r'!rate(\d+)', name, re.I)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def parse_marker_number(name):
    """Extract layer-marker number from '=N' name. Returns int or None."""
    if not name.startswith('='):
        return None
    try:
        return int(name[1:])
    except ValueError:
        return None


def parse_sprite_number(name):
    """Extract =N value from a sprite name (e.g. 'n_0=5%numbers' -> 5).
    Only applies to named sprites, not '=N' layer markers. Returns int or 0."""
    if name.startswith('='):
        return 0  # layer marker, handled separately
    import re
    m = re.search(r'=([0-9]+)', name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def nearest_side(x, y, w, h, side_centers):
    """Find the nearest ~sideN center to the layer's center point."""
    cx, cy = x + w / 2.0, y + h / 2.0
    best_side, best_dist = -1, float('inf')
    for sn, (sx, sy) in side_centers.items():
        d = math.hypot(cx - sx, cy - sy)
        if d < best_dist:
            best_dist, best_side = d, sn
    return best_side


def _extract_pivot_markers(layer):
    """
    Extract pivot markers from a ~pivot PSD layer.

    Pivot markers can be: single pixels (1x1), small dots (2x2),
    lines, crosses (two intersecting lines), or L-shapes.

    Returns list of (center_x, center_y, rect) where rect is
    (min_x, min_y, max_x, max_y) used for intersection testing.
    """
    pimg = layer.composite()
    if pimg is None:
        return []

    parr = np.array(pimg.convert('RGBA'))
    alpha = parr[:, :, 3]
    ph, pw = alpha.shape
    if ph == 0 or pw == 0:
        return []

    # Get all non-transparent pixels in absolute coordinates
    pys, pxs = np.where(alpha > 0)
    if len(pxs) == 0:
        return []

    abs_pixels = set()
    for i in range(len(pxs)):
        abs_pixels.add((layer.left + int(pxs[i]), layer.top + int(pys[i])))

    # Find connected components via flood-fill (4-connected)
    remaining = set(abs_pixels)
    components = []
    while remaining:
        seed = next(iter(remaining))
        component = set()
        stack = [seed]
        while stack:
            pt = stack.pop()
            if pt in remaining:
                remaining.discard(pt)
                component.add(pt)
                x, y = pt
                for nx, ny in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]:
                    if (nx, ny) in remaining:
                        stack.append((nx, ny))
        components.append(component)

    markers = []
    for comp in components:
        if not comp:
            continue

        xs = [x for x, y in comp]
        ys = [y for x, y in comp]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        comp_w = max_x - min_x + 1
        comp_h = max_y - min_y + 1

        # Pivot center = bounding box center of the entire component.
        # This matches utils.exe behavior for:
        #   - dots (1x1, 2x2, 3x3): bbox center = dot center
        #   - single lines: bbox center = line midpoint
        #   - crosses / L-shapes: bbox center = midpoint of the line span,
        #     NOT the intersection pixel (which may be offset by 0.5px
        #     when line widths and component extents don't align)
        cx = (min_x + max_x) / 2.0
        cy = (min_y + max_y) / 2.0
        rect = (min_x, min_y, max_x, max_y)
        markers.append((cx, cy, rect))

    return markers


def _rects_intersect(r1, r2):
    """Check if two rects (min_x, min_y, max_x, max_y) overlap."""
    return r1[0] <= r2[2] and r1[2] >= r2[0] and r1[1] <= r2[3] and r1[3] >= r2[1]


def export_psd_file_python(psd_path, exported_dir, is_map=False):
    """
    Export a single PSD file using psd-tools (pure Python).

    Produces:
      - One PNG per non-special layer (RGBA, cropped to layer bounds)
      - One CSV with layer metadata (positions, types, groups)
      - One PSL binary for map PSD files (with side centers)

    Returns list of (png_name, layer_info) tuples.
    """
    try:
        from psd_tools import PSDImage
    except ImportError:
        print("Error: psd-tools not installed. Run: pip install psd-tools")
        sys.exit(1)

    psd = PSDImage.open(psd_path)
    stem = Path(psd_path).stem
    records = []

    # Collect ~sideN centers and ~pivot markers
    side_centers = {}
    # Each pivot marker: (center_x, center_y, rect)
    # rect = (min_x, min_y, max_x, max_y) for intersection testing with sprites
    pivot_markers = []
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

    # Track types and groups for index assignment
    types_seen = {}   # type_name -> index
    groups_seen = {}  # group_name -> index

    # Walk layers in PSD order (top to bottom = file order)
    layer_id_counter = 1
    current_side_marker = -1
    _custom_pivots = []  # collect sprites with non-default pivots for logging

    for layer in psd:
        name = layer.name

        # Skip meta layers (background, borders, pivot, side markers)
        if name.startswith('~'):
            continue

        # Skip hidden (invisible) layers
        if not layer.is_visible():
            continue

        # Warn and skip layers with non-ASCII names (e.g. Cyrillic)
        if not name.isascii():
            print(f"    WARNING: non-ASCII layer name '{name}' in {psd_path}, skipping")
            continue

        x, y = layer.left, layer.top
        w, h = layer.width, layer.height
        layer_mark = -16777216  # 0xFF000000 — default value

        # Parse =N layer-markers: include in CSV/PSL but don't export PNG.
        # The engine treats these as "set layer = Number for subsequent sprites".
        is_marker = name.startswith('=')
        marker_number = parse_marker_number(name) if is_marker else None

        # Parse metadata (type, group, tag, rate) and the optional =N value
        # embedded in a named sprite (e.g. "n_0=5%numbers" -> number=5).
        base_raw, obj_name, type_name, group_name, tag_name = parse_layer_metadata(name)
        layer_rate = parse_layer_rate(name)
        sprite_number = parse_sprite_number(name) if not is_marker else 0
        png_name = normalize_layer_name(name)

        # Assign type/group indices
        kind = 0
        group_id = 0
        if type_name and type_name not in types_seen:
            types_seen[type_name] = len(types_seen) + 1
        if group_name and group_name not in groups_seen:
            groups_seen[group_name] = len(groups_seen) + 1
        if type_name:
            kind = types_seen[type_name]
        if group_name:
            group_id = groups_seen[group_name]

        # Determine side (for maps)
        side = -1
        side_cx, side_cy = 0, 0
        if side_centers:
            side = nearest_side(x, y, w, h, side_centers)
            if side in side_centers:
                side_cx, side_cy = side_centers[side]

        # Find pivot marker whose rect intersects this sprite's bbox.
        # Pivot = offset from sprite's top-left to the pivot center.
        # If no custom pivot found, leave as None — pack_sprite will use
        # the utils.exe default (W-0.5, H-0.5).
        sprite_pivot_x = None
        sprite_pivot_y = None
        if pivot_markers and w > 0 and h > 0:
            sprite_rect = (x, y, x + w - 1, y + h - 1)
            best_dist = float('inf')
            best_px, best_py = None, None
            sprite_cx = x + w / 2.0
            sprite_cy = y + h / 2.0
            for pcx, pcy, prect in pivot_markers:
                if _rects_intersect(sprite_rect, prect):
                    d = math.hypot(pcx - sprite_cx, pcy - sprite_cy)
                    if d < best_dist:
                        best_dist = d
                        best_px, best_py = pcx, pcy
            if best_px is not None:
                # Pixel offset from sprite top-left to pivot marker
                pixel_offset_x = best_px - x
                pixel_offset_y = best_py - y
                # Utils.exe stores pivot pre-multiplied by 2x zoom + half-pixel:
                #   stored_pivot = pixel_offset * 2 + 0.5
                sprite_pivot_x = pixel_offset_x * 2 + 0.5
                sprite_pivot_y = pixel_offset_y * 2 + 0.5
                _custom_pivots.append((png_name, w, h, sprite_pivot_x, sprite_pivot_y))

        # Build record
        rec = {
            'id': layer_id_counter,
            'name': name,  # raw layer name with all metadata (%type, &group, #tag, !rate)
            'group_id': group_id,
            'kind': kind,
            'bmp': '',
            'x': x, 'y': y, 'w': w, 'h': h,
            'pivot_x': sprite_pivot_x,
            'pivot_y': sprite_pivot_y,
            'layer_mark': layer_mark,
            'side': side,
            'side_cx': side_cx, 'side_cy': side_cy,
            'png_name': png_name,
            'is_marker': is_marker,
            # New fields written to PSL for map packing
            'marker_number': marker_number if marker_number is not None else 0,
            'sprite_number': sprite_number,
            'type_name': type_name or '',
            'group_name': group_name or '',
            'rate': layer_rate if layer_rate is not None else 0,
        }
        records.append(rec)
        layer_id_counter += 1

        # Export PNG (skip markers, zero-size, and already-exported names)
        if not is_marker and w > 0 and h > 0:
            out_png = os.path.join(exported_dir, f"{png_name}.png")
            if not os.path.exists(out_png):
                try:
                    img = layer.composite()
                    if img is not None:
                        img = img.convert('RGBA')
                        img.save(out_png)
                except Exception as e:
                    print(f"    WARNING: failed to composite '{name}': {e}")

    # Write pivot log
    if _custom_pivots:
        pivot_log = os.path.join(exported_dir, f"{stem}_pivots.log")
        with open(pivot_log, 'w') as f:
            f.write(f"Custom pivots for {stem} ({len(_custom_pivots)} sprites)\n")
            f.write(f"{'Sprite':<30s} {'Size':>10s} {'Pivot':>16s} {'Center':>16s} {'Offset':>16s}\n")
            f.write('-' * 100 + '\n')
            for pname, pw, ph, pvx, pvy in _custom_pivots:
                cx, cy = pw / 2.0, ph / 2.0
                dx, dy = pvx - cx, pvy - cy
                f.write(f"{pname:<30s} {pw:>4d}x{ph:<4d} "
                        f"({pvx:>6.1f},{pvy:>6.1f}) "
                        f"({cx:>6.1f},{cy:>6.1f}) "
                        f"({dx:>+6.1f},{dy:>+6.1f})\n")
        print(f"    {len(_custom_pivots)} sprites with custom pivots (see {pivot_log})")

    # Write CSV
    csv_path = os.path.join(exported_dir, f"{stem}.csv")
    with open(csv_path, 'w', newline='') as f:
        f.write('int Id,str Name,int GroupId,int Kind,str Bmp,int X,int Y,int W,int H,int LayerMark,float PivotX,float PivotY\n')
        for r in records:
            pvx = f'{r["pivot_x"]:.2f}' if r["pivot_x"] is not None else ''
            pvy = f'{r["pivot_y"]:.2f}' if r["pivot_y"] is not None else ''
            f.write(f'{r["id"]},"{r["name"]}",{r["group_id"]},{r["kind"]},"{r["bmp"]}",'
                    f'{r["x"]},{r["y"]},{r["w"]},{r["h"]},{r["layer_mark"]},'
                    f'{pvx},{pvy}\n')

    # Write PSL
    psl_type = 2 if is_map else 1
    psl_path = os.path.join(exported_dir, f"{stem}.psl")
    with open(psl_path, 'wb') as f:
        # Header: type, 0, 0, count
        f.write(struct.pack('<4I', psl_type, 0, 0, len(records)))
        for r in records:
            # Record: 700 bytes
            rec_buf = bytearray(700)
            # Name (24 bytes, lowercase, null-terminated)
            psl_name = r['png_name'] if not r['is_marker'] else ''
            name_bytes = psl_name.encode('ascii', errors='replace')[:23]
            rec_buf[:len(name_bytes)] = name_bytes
            # x, y, w, h (int32 — may be negative for off-canvas layers)
            struct.pack_into('<4i', rec_buf, 24, r['x'], r['y'], r['w'], r['h'])
            # LayerMark (int32)
            struct.pack_into('<i', rec_buf, 40, r['layer_mark'])
            # Side, side_cx, side_cy, reserved pair (both = 1 in utils.exe output)
            struct.pack_into('<4I', rec_buf, 44,
                             r['side'] if r['side'] >= 0 else 0,
                             r['side_cx'], r['side_cy'], 1)
            struct.pack_into('<I', rec_buf, 60, 1)
            # Rate suffix "rateN" at offset 120 (if !rate was present in name)
            if r.get('rate'):
                rate_str = f'rate{r["rate"]}'.encode('ascii')[:31]
                rec_buf[120:120 + len(rate_str)] = rate_str
            # Group name (bytes 392-423, 32 bytes, null-terminated)
            gname = (r.get('group_name') or '').encode('ascii', errors='replace')[:31]
            rec_buf[392:392 + len(gname)] = gname
            # Type name (bytes 424-439, 16 bytes, null-terminated)
            tname = (r.get('type_name') or '').encode('ascii', errors='replace')[:15]
            rec_buf[424:424 + len(tname)] = tname
            # Number (offset 440) — for =N layer markers the layer number,
            # for named sprites the =N value parsed from the layer name.
            if r.get('is_marker'):
                num_val = r.get('marker_number', 0)
            else:
                num_val = r.get('sprite_number', 0)
            struct.pack_into('<I', rec_buf, 440, num_val & 0xFFFFFFFF)
            f.write(rec_buf)

    return records, types_seen, groups_seen


def export_font_python(fnt_path, exported_dir):
    """
    Export a BMFont binary (.fnt + atlas PNG) into individual glyph PNGs.
    Produces font_N_CCCCC.png files matching WowCube font output format.

    BMFont binary format (version 3):
      Block 1 (info): font metadata
      Block 2 (common): line height, base, scale, pages
      Block 3 (pages): atlas filenames
      Block 4 (chars): per-character metrics + atlas coordinates
    """
    fnt_dir = str(Path(fnt_path).parent)
    font_stem = Path(fnt_path).stem  # e.g. "font_1"

    with open(fnt_path, 'rb') as f:
        # Header: "BMF" + version byte
        magic = f.read(3)
        if magic != b'BMF':
            print(f"    WARNING: not a BMFont file: {fnt_path}")
            return
        version = struct.unpack('B', f.read(1))[0]
        if version != 3:
            print(f"    WARNING: unsupported BMFont version {version}")
            return

        pages = []
        chars = []

        while True:
            block_header = f.read(5)
            if len(block_header) < 5:
                break
            block_type, block_size = struct.unpack('<BI', block_header)

            block_data = f.read(block_size)
            if len(block_data) < block_size:
                break

            if block_type == 1:
                # Info block — skip
                pass
            elif block_type == 2:
                # Common block — skip
                pass
            elif block_type == 3:
                # Pages block: null-terminated filenames
                pages = block_data.rstrip(b'\x00').split(b'\x00')
                pages = [p.decode('ascii', errors='replace') for p in pages if p]
            elif block_type == 4:
                # Chars block: 20 bytes per char
                n_chars = block_size // 20
                for i in range(n_chars):
                    off = i * 20
                    char_id, cx, cy, cw, ch, xoff, yoff, xadv, page, chnl = \
                        struct.unpack_from('<IHHHHhhhBB', block_data, off)
                    chars.append({
                        'id': char_id, 'x': cx, 'y': cy,
                        'w': cw, 'h': ch,
                        'xoff': xoff, 'yoff': yoff,
                        'xadvance': xadv, 'page': page,
                    })

    if not pages:
        print(f"    WARNING: no atlas pages in {fnt_path}")
        return

    # Load atlas image(s)
    atlases = {}
    for i, page_file in enumerate(pages):
        atlas_path = os.path.join(fnt_dir, page_file)
        if os.path.isfile(atlas_path):
            atlases[i] = Image.open(atlas_path).convert('RGBA')
        else:
            print(f"    WARNING: atlas not found: {atlas_path}")

    # Export each glyph
    exported_count = 0
    for ch in chars:
        if ch['w'] == 0 or ch['h'] == 0:
            continue
        if ch['id'] < 33:
            continue  # skip control chars and space
        atlas = atlases.get(ch['page'])
        if atlas is None:
            continue

        glyph = atlas.crop((ch['x'], ch['y'],
                            ch['x'] + ch['w'], ch['y'] + ch['h']))
        # Name: font_N_CCCCC.png (5-digit char code, zero-padded)
        out_name = f"{font_stem}_{ch['id']:05d}.png"
        glyph.save(os.path.join(exported_dir, out_name))
        exported_count += 1

    # Also generate PSL for font (type=1, no side info)
    psl_path = os.path.join(exported_dir, f"{font_stem}.psl")
    with open(psl_path, 'wb') as f:
        f.write(struct.pack('<4I', 1, 0, 0, len(chars)))
        for ch in chars:
            rec_buf = bytearray(700)
            name = f"{font_stem}_{ch['id']:05d}"
            name_bytes = name.encode('ascii', errors='replace')[:23]
            rec_buf[:len(name_bytes)] = name_bytes
            struct.pack_into('<4I', rec_buf, 24, ch['x'], ch['y'], ch['w'], ch['h'])
            struct.pack_into('<i', rec_buf, 40, -16777216)  # 0xFF000000
            struct.pack_into('<I', rec_buf, 56, 1)  # reserved
            f.write(rec_buf)

    print(f"    {exported_count} glyphs exported")
    return exported_count


def export_all_python(art_dir, exported_dir, map_filter=None, asset_names=None):
    """
    Export all PSD and FNT files using psd-tools (pure Python).

    Returns (asset_names_out, map_names_exported).
    """
    import shutil
    import glob as glob_mod

    if asset_names is None:
        asset_names = {'assets'}

    # Create and clean exported directory
    os.makedirs(exported_dir, exist_ok=True)
    for pattern in ['*.png', '*.psl', '*.csv', '*.log']:
        for f in glob_mod.glob(os.path.join(exported_dir, pattern)):
            try:
                os.remove(f)
            except OSError:
                pass  # skip files that can't be removed

    # Copy 0.png placeholder
    zero_png = os.path.join(art_dir, '0.png')
    if os.path.isfile(zero_png):
        shutil.copy2(zero_png, os.path.join(exported_dir, '0.png'))

    asset_names_out = []
    map_names_exported = []

    # 1. Export fonts
    fonts_dir = os.path.join(art_dir, 'fonts')
    if os.path.isdir(fonts_dir):
        for fnt in sorted(Path(fonts_dir).glob('*.fnt')):
            print(f"  Export font: {fnt.name}")
            export_font_python(str(fnt), exported_dir)

    # 2. Export PSD files
    for psd in sorted(Path(art_dir).glob('*.psd')):
        name = psd.stem

        # Determine if this PSD is a map or asset
        is_map = False
        if map_filter is not None:
            if isinstance(map_filter, list):
                is_map = name in map_filter
            elif map_filter == 'all':
                is_map = (name not in asset_names)
        else:
            is_map = (name not in asset_names)

        label = 'map' if is_map else 'assets'
        print(f"  Export {label}: {psd.name}")

        records, types, groups = export_psd_file_python(
            str(psd), exported_dir, is_map=is_map)
        print(f"    {len(records)} layers, {len(types)} types, {len(groups)} groups")

        if is_map:
            map_names_exported.append(name)
        else:
            asset_names_out.append(name)

    # Count exported files
    n_png = len(list(Path(exported_dir).glob('*.png')))
    n_csv = len(list(Path(exported_dir).glob('*.csv')))
    n_psl = len(list(Path(exported_dir).glob('*.psl')))
    print(f"\n  Exported: {n_png} PNGs, {n_csv} CSVs, {n_psl} PSLs")
    if len(asset_names_out) > 1:
        print(f"  Assets: {', '.join(asset_names_out)}")

    return asset_names_out, map_names_exported


# ── PSD export (pure Python via psd-tools) ──────────────────────────────────


def export_psd(art_dir, exported_dir, map_filter=None, asset_names=None):
    """
    Export PSD/FNT files into the exported/ directory using psd-tools.

    art_dir      -- directory containing *.psd, fonts/, 0.png
    exported_dir -- output directory for exported PNGs, CSVs, PSLs
    map_filter   -- list of map names, 'all', or None (auto-detect)
    asset_names  -- set of PSD names to treat as assets (default: {'assets'})

    Returns (asset_names_out, map_names) listing what was exported.
    """
    return export_all_python(art_dir, exported_dir, map_filter, asset_names)


# ── Map (PSL/CSV) packing ───────────────────────────────────────────────────

PSL_HEADER_SIZE = 16
PSL_RECORD_SIZE = 700


def parse_psl(psl_path):
    """
    Parse a PSL binary map file.

    PSL format (little-endian):
      Header (16 bytes): uint32[4] = {type, 0, 0, record_count}
      Records (700 bytes each):
        - 0-23:   Name string (24 bytes, null-terminated, lowercase)
        - 24-27:  X (uint32, PSD global coordinate)
        - 28-31:  Y (uint32, PSD global coordinate)
        - 32-35:  W (uint32)
        - 36-39:  H (uint32)
        - 40-43:  LayerMark (int32, typically 0xFF000000)
        - 44-47:  Side index (uint32, cube face 0-5)
        - 48-51:  Side center X in PSD (uint32)
        - 52-55:  Side center Y in PSD (uint32)
        - 56-59:  Reserved (uint32, usually 1)
        - 60-63:  Reserved (uint32, usually 1)
        - 64-391: Reserved (zeros)
        - 392-423: Group name string (32 bytes, null-terminated)
        - 424-439: Type name string (16 bytes, null-terminated)
        - 440-443: Number (uint32)
        - 444-699: Reserved (zeros)

    Returns list of dicts with parsed fields.
    """
    with open(psl_path, 'rb') as f:
        data = f.read()

    header = struct.unpack_from('<4I', data, 0)
    psl_type = header[0]
    record_count = header[3]

    records = []
    for i in range(record_count):
        off = PSL_HEADER_SIZE + i * PSL_RECORD_SIZE
        rec = data[off:off + PSL_RECORD_SIZE]

        # Name (bytes 0-23)
        name_end = rec.find(0, 0, 24)
        if name_end < 0:
            name_end = 24
        name = rec[:name_end].decode('ascii', errors='replace')

        # Coordinates and dimensions (signed — PSD layers can extend
        # off-canvas, giving negative x/y).
        x, y, w, h = struct.unpack_from('<4i', rec, 24)
        layer_mark = struct.unpack_from('<i', rec, 40)[0]
        side = struct.unpack_from('<I', rec, 44)[0]
        center_x = struct.unpack_from('<I', rec, 48)[0]
        center_y = struct.unpack_from('<I', rec, 52)[0]

        # Group name (bytes 392-423)
        grp_end = rec.find(0, 392, 424)
        if grp_end < 0:
            grp_end = 424
        group_name = rec[392:grp_end].decode('ascii', errors='replace')

        # Type name (bytes 424-439)
        typ_end = rec.find(0, 424, 440)
        if typ_end < 0:
            typ_end = 440
        type_name = rec[424:typ_end].decode('ascii', errors='replace')

        # Number (bytes 440-443)
        number = struct.unpack_from('<I', rec, 440)[0]

        # Rate suffix (bytes 120-...) — "rateN" string, optional
        rate_val = 0
        rate_end = rec.find(0, 120, 152)
        if rate_end < 0:
            rate_end = 152
        rate_str = rec[120:rate_end].decode('ascii', errors='replace')
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


def parse_map_csv(csv_path):
    """
    Parse a map CSV file.

    CSV columns: int Id, str Name, int GroupId, int Kind, str Bmp,
                 int X, int Y, int W, int H, int LayerMark

    Name annotations:
      %type    - Object type (e.g. "PH-1%placeholder" → type=placeholder)
      &group   - Object group (e.g. "MainGear_00&game" → group=game)
      =number  - Number value (e.g. "n_0=5%Numbers" → number=5)
      !rateN   - Animation rate (e.g. "Twist_00!rate10" → rate=10)

    Special names:
      "=N" (no base name) - Layer marker, sets layer for following objects

    Returns list of dicts.
    """
    import csv as csv_mod
    import re

    records = []
    with open(csv_path, 'r') as f:
        reader = csv_mod.reader(f)
        header = next(reader)  # skip header

        for row in reader:
            if len(row) < 10:
                continue

            csv_id = int(row[0])
            raw_name = row[1]
            group_id = int(row[2])
            kind = int(row[3])
            bmp_name = row[4]
            x = int(row[5])
            y = int(row[6])
            w = int(row[7])
            h = int(row[8])
            layer_mark = int(row[9])

            # Parse name annotations
            type_name = ''
            group_name = ''
            number = 0
            rate = 0
            base_name = raw_name

            # Split on annotation markers
            parts = re.split(r'([%&=!])', raw_name)
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
                    # !rateN → extract the number
                    m = re.match(r'rate(\d+)', value, re.I)
                    if m:
                        rate = int(m.group(1))
                i += 2

            # Normalize sprite name: lowercase, replace hyphens/spaces
            sprite_name = base_name.lower().replace('-', '_').replace(' ', '_')

            records.append({
                'csv_id': csv_id,
                'raw_name': raw_name,
                'sprite_name': sprite_name,
                'base_name': base_name,
                'type_name': type_name,
                'group_name': group_name,
                'number': number,
                'rate': rate,
                'x': x, 'y': y, 'w': w, 'h': h,
                'layer_mark': layer_mark,
                'bmp_name': bmp_name,
                'group_id': group_id,
                'kind': kind,
            })

    return records


def build_bmp_name_index(packed_dir, exported_dir):
    """
    Build alphabetically-sorted BMP name → index mapping from packed sprites.
    This mirrors how the WowCube simulator loads resources.
    """
    names = set()

    # Collect sprite names.
    # utils.exe builds the alphabetical index including 'pal' (palette is
    # loaded into the same resource cache) but excluding '0' (the
    # placeholder is accessed by a fixed index, not by name lookup).
    if os.path.isdir(packed_dir):
        for f in Path(packed_dir).glob('*.png'):
            name = f.stem
            if name != '0':
                names.add(name)

    # Also check exported directory for names
    if os.path.isdir(exported_dir):
        for f in Path(exported_dir).glob('*.png'):
            name = f.stem
            if name != '0' and not name.endswith('.csv'):
                names.add(name)

    # Always include 'pal' — it's a resource loaded by name at runtime.
    names.add('pal')

    # Include map names — maps get packed as PNGs alongside sprites and
    # share the same alphabetical index space in the engine's runtime.
    # Each map PSL (type=2 in header) becomes a PNG; asset PSLs (type=1)
    # are skipped so their stems don't pollute the sprite index.
    if os.path.isdir(exported_dir):
        for f in Path(exported_dir).glob('*.psl'):
            try:
                with open(f, 'rb') as fh:
                    psl_type = struct.unpack('<I', fh.read(4))[0]
            except Exception:
                psl_type = 0
            if psl_type != 2:
                continue  # asset PSL — not a map output
            name = f.stem
            if name.startswith('map_'):
                name = name[4:]
            if name and name not in ('pal', '0'):
                names.add(name)

    # Sort alphabetically and assign indices (BMP_0 = 0, first real = 1)
    sorted_names = sorted(names)
    name_to_idx = {name: idx + 1 for idx, name in enumerate(sorted_names)}
    return name_to_idx, sorted_names


def build_metadata_maps(exported_dir):
    """
    Scan all CSV files and collect metadata → index mappings for app_ids.h.

    Extracts four categories from raw layer names:
      $names  — unique base names (without _NN animation suffix and metadata)
      %types  — unique %type values
      &groups — unique &group values
      #tags   — unique #tag values

    Returns (name_map, type_map, group_map, tag_map).
    Each map is {str: int} with sequential indices starting from 1.
    """
    import csv as csv_mod
    import re

    names = set()
    types = set()
    groups = set()
    tags = set()

    for csv_path in sorted(Path(exported_dir).glob('*.csv')):
        with open(csv_path, 'r') as f:
            reader = csv_mod.reader(f)
            try:
                next(reader)  # skip header
            except StopIteration:
                continue
            for row in reader:
                if len(row) < 2:
                    continue
                raw_name = row[1]

                # Parse all metadata from the raw layer name
                _, obj_name, type_name, group_name, tag_name = parse_layer_metadata(raw_name)

                if obj_name:
                    names.add(obj_name)
                if type_name:
                    types.add(type_name)
                if group_name:
                    groups.add(group_name)
                if tag_name:
                    tags.add(tag_name)

    # Assign sequential indices (starting from 1), sorted alphabetically
    name_map = {n: i + 1 for i, n in enumerate(sorted(names))}
    type_map = {n: i + 1 for i, n in enumerate(sorted(types))}
    group_map = {n: i + 1 for i, n in enumerate(sorted(groups))}
    tag_map = {n: i + 1 for i, n in enumerate(sorted(tags))}
    return name_map, type_map, group_map, tag_map


def _load_packed_pivots(packed_dir):
    """Read stored pivot (PivotX, PivotY) and packed (W, H) from every
    sprite in packed_dir. Returns dict name -> (pivot_x, pivot_y, W, H)."""
    pivots = {}
    if not os.path.isdir(packed_dir):
        return pivots
    for f in Path(packed_dir).glob('*.png'):
        name = f.stem
        if name in ('pal',):
            continue
        try:
            img = Image.open(f)
            raw = img.tobytes()
            if len(raw) < 48:
                continue
            px = struct.unpack_from('<f', raw, 4)[0]
            py = struct.unpack_from('<f', raw, 8)[0]
            pw = struct.unpack_from('<h', raw, 36)[0]
            ph = struct.unpack_from('<h', raw, 38)[0]
            pivots[name] = (px, py, pw, ph)
        except Exception:
            pass
    return pivots


def psl_to_octplace(records, bmp_index, type_map, group_map,
                    packed_pivots=None):
    """
    Convert parsed PSL records to octPlace_t binary array.

    Matches the behavior of the original utils.exe linker:
      - Position formula: 2*(psd_coord - side_center + pivot_pixel), with
        Y-flip. For sprites, pivot_pixel is derived from the packed sprite
        header (default sprite pivot is (W-0.5, H-0.5) → pixel pivot
        (W-1)/2). A sign-dependent ±0.5 correction matches utils.exe's
        half-pixel rounding.
      - Rate: default 1 (or value from !rate suffix stored in PSL).
      - Name: always 0 (utils.exe doesn't assign unique IDs).
      - Layer markers (=N layers): Number = N from PSL, bmp=0, name=0.

    octPlace_t (28 bytes, little-endian):
      float    X, Y        (0-7)
      uint32   Tags        (8-11)
      int16    W, H        (12-15)
      int16    BmpIdx      (16-17)
      int16    Number      (18-19)
      uint16   Flags       (20-21)
      int8     Side        (22)
      int8     Rate        (23)
      uint8    Name        (24)
      uint8    Group       (25)
      uint8    Parent      (26)
      uint8    Type        (27)

    Map blob (no leading dimensions word — engine prepends that on load):
      int32    version = 1
      int32    count
      octPlace_t[count]
    """
    if packed_pivots is None:
        packed_pivots = {}

    places = []
    for rec in records:
        name = rec.get('name', rec.get('sprite_name', ''))
        x_psd = rec['x']
        y_psd = rec['y']
        w = rec['w']
        h = rec['h']
        sid = rec.get('side', 0)
        cx = rec.get('center_x', 0)
        cy = rec.get('center_y', 0)
        type_name = rec.get('type_name', '')
        group_name = rec.get('group_name', '')
        number = rec.get('number', 0)
        rate = rec.get('rate', 0)

        # Layer marker: empty name, tiny bbox (=N layers exported as 1x1).
        is_layer_marker = (not name and w <= 1 and h <= 1)

        # Resolve BMP index and stored pivot from packed sprite (if any)
        if name and name in bmp_index:
            bmp_idx = bmp_index[name]
        else:
            bmp_idx = 0

        if name and name in packed_pivots:
            stored_pvx, stored_pvy, _, _ = packed_pivots[name]
        else:
            # Markers or missing sprites have no packed sprite; pivot = 0
            stored_pvx = 0.0
            stored_pvy = 0.0

        # Position formula matching utils.exe exactly:
        #   local_x = 2*(psd_x - side_cx) + stored_pivot_x
        #   local_y = -2*(psd_y - side_cy) - stored_pivot_y   (Y-flipped)
        # Then an asymmetric half-pixel rounding:
        #   if local_x < 0: local_x -= 1
        #   if local_y > 0: local_y += 1
        local_x = 2.0 * (x_psd - cx) + stored_pvx
        local_y = -2.0 * (y_psd - cy) - stored_pvy
        if local_x < 0:
            local_x -= 1
        if local_y > 0:
            local_y += 1

        # Resolve type and group
        type_idx = type_map.get(type_name, 0) if type_name else 0
        group_idx = group_map.get(group_name, 0) if group_name else 0

        # Flags: Looped bit (0x0002) is set automatically for the first
        # frame of an animation sequence. utils.exe marks every sprite
        # whose name ends with '_00' as the animation start (engine walks
        # subsequent _01, _02, ... frames via the sprite Seq field).
        flags = 0
        if name and name.endswith('_00'):
            flags |= 0x0002  # Looped
        if rate > 0:
            flags |= 0x0002  # also set when !rate suffix is present

        # Animation frame rate: default 1 if no !rate suffix
        rate_out = rate if rate > 0 else 1

        # For layer markers, Number is the =N value and everything else is 0
        if is_layer_marker:
            number_field = number & 0x7FFF
            bmp_idx = 0
            type_idx = 0
            group_idx = 0
            flags = 0
            rate_out = 1
        else:
            number_field = number & 0x7FFF

        # Pack octPlace_t (28 bytes). Name is always 0 — matches utils.exe.
        place_data = struct.pack('<ff', local_x, local_y)           # X, Y
        place_data += struct.pack('<I', 0)                          # Tags
        place_data += struct.pack('<hh', w & 0x7FFF, h & 0x7FFF)    # W, H
        place_data += struct.pack('<h', bmp_idx)                    # BmpIdx
        place_data += struct.pack('<h', number_field)               # Number
        place_data += struct.pack('<H', flags)                      # Flags
        place_data += struct.pack('<b', sid if sid < 128 else -1)   # Side
        place_data += struct.pack('<b', rate_out & 0xFF)            # Rate
        place_data += struct.pack('<B', 0)                          # Name (always 0)
        place_data += struct.pack('<B', group_idx)                  # Group
        place_data += struct.pack('<B', 0)                          # Parent
        place_data += struct.pack('<B', type_idx)                   # Type

        places.append(place_data)

    count = len(places)
    header = struct.pack('<ii', 1, count)
    return header + b''.join(places)


def csv_to_octplace(csv_records, bmp_index, type_map, group_map):
    """
    Convert parsed CSV map records to octPlace_t binary array.
    NOTE: CSV records have PSD global coordinates but no side info.
    For CSV-only maps (no PSL), coordinates are stored as-is (no
    side conversion). Use PSL when available for proper side mapping.
    """
    places = []
    name_counter = 1
    current_layer = 0

    for rec in csv_records:
        raw_name = rec['raw_name']
        sprite_name = rec['sprite_name']
        x = rec['x']
        y = rec['y']
        w = rec['w']
        h = rec['h']
        type_name = rec['type_name']
        group_name = rec['group_name']
        number = rec['number']
        rate = rec['rate']

        # Check for layer marker: "=N" with no base name
        if raw_name.startswith('=') and not sprite_name:
            # Layer marker: BmpIdx=0, Name=0, Number=layer
            try:
                layer_num = int(raw_name[1:])
            except ValueError:
                layer_num = 0
            current_layer = layer_num

            place_data = struct.pack('<ff', float(x), float(y))
            place_data += struct.pack('<I', 0)
            place_data += struct.pack('<hh', w, h)
            place_data += struct.pack('<hh', 0, layer_num)
            place_data += struct.pack('<H', 0)
            place_data += struct.pack('<bb', -1, 0)
            place_data += struct.pack('<BBBB', 0, 0, 0, 0)
            places.append(place_data)
            continue

        # Resolve BMP index
        bmp_idx = bmp_index.get(sprite_name, 0)

        # Resolve type and group
        type_idx = type_map.get(type_name, 0) if type_name else 0
        group_idx = group_map.get(group_name, 0) if group_name else 0

        # Flags
        flags = 0

        obj_name = name_counter & 0xFF
        name_counter += 1

        place_data = struct.pack('<ff', float(x), float(y))
        place_data += struct.pack('<I', 0)
        place_data += struct.pack('<hh', w, h)
        place_data += struct.pack('<h', bmp_idx)
        place_data += struct.pack('<h', number)
        place_data += struct.pack('<H', flags)
        place_data += struct.pack('<bb', -1, rate)
        place_data += struct.pack('<B', obj_name)
        place_data += struct.pack('<B', group_idx)
        place_data += struct.pack('<B', 0)
        place_data += struct.pack('<B', type_idx)

        places.append(place_data)

    count = len(places)
    # Map binary format (as stored in PNG pixel data):
    #   int version = 1
    #   int placesnum = count
    #   octPlace_t[placesnum]
    #
    # Note: NO leading zero. The engine's resource loader prepends
    # a 4-byte dimensions word (raw[0]) before pixel data, so
    # OCT_add_map reads: raw[0]=dimensions, raw[1]=version, raw[2]=count.
    header = struct.pack('<ii', 1, count)
    blob = header + b''.join(places)
    return blob


def pack_maps(exported_dir, packed_dir, output_dir, map_filter=None,
              asset_names=None):
    """
    Pack map files (PSL or CSV) into pseudo-sprite PNGs.

    Source priority: PSL file (binary, has side info) > CSV file (fallback).
    When both exist for a map, PSL is preferred because it contains side
    centers needed for PSD→local coordinate conversion.

    map_filter controls which files are treated as maps:
      - None (default): auto-detect from PSL header (type==2), skip font*/assets
      - list of names: only pack these exact maps (e.g. ['game', 'start', 'tutorial'])
      - 'all': treat every PSL/CSV file as a map (no skipping)

    asset_names -- set of names to skip in auto-detect mode (default: {'assets'})

    Returns map names for app_ids.h generation.
    """
    # Build sprite name index and packed pivot table
    bmp_index, sorted_names = build_bmp_name_index(packed_dir, exported_dir)
    name_map, type_map, group_map, tag_map = build_metadata_maps(exported_dir)
    # Use the freshly packed sprites from output_dir (preferred) or packed_dir.
    pivot_src = output_dir if os.path.isdir(output_dir) and any(
        Path(output_dir).glob('*.png')) else packed_dir
    packed_pivots = _load_packed_pivots(pivot_src)

    print(f"  BMP index: {len(bmp_index)} sprites")
    print(f"  Packed pivots: {len(packed_pivots)} sprites (from {pivot_src})")
    print(f"  Names: {name_map}")
    print(f"  Types: {type_map}")
    print(f"  Groups: {group_map}")
    print(f"  Tags: {tag_map}")

    map_names = []

    # Collect all available map sources: PSL and/or CSV
    psl_files = {p.stem: p for p in sorted(Path(exported_dir).glob('*.psl'))}
    csv_files = {p.stem: p for p in sorted(Path(exported_dir).glob('*.csv'))}
    all_map_candidates = sorted(set(psl_files.keys()) | set(csv_files.keys()))

    # Build explicit filter set if provided
    explicit_set = None
    if isinstance(map_filter, list):
        explicit_set = set(map_filter)

    for map_name in all_map_candidates:
        has_psl = map_name in psl_files
        has_csv = map_name in csv_files

        if explicit_set is not None:
            # Explicit list mode: only process named maps
            if map_name not in explicit_set:
                continue
        elif map_filter != 'all':
            # Auto-detect mode: skip known non-map files (fonts, assets)
            skip_assets = asset_names if asset_names else {'assets'}
            if map_name.startswith('font') or map_name in skip_assets:
                continue

        # Prefer PSL over CSV
        if has_psl:
            print(f"\n  Map: {map_name} (from PSL)")
            psl_type, records = parse_psl(str(psl_files[map_name]))
            print(f"    PSL type={psl_type}, {len(records)} records")

            if explicit_set is None and map_filter != 'all' and psl_type != 2:
                print(f"    Skipping (not a map PSL, type={psl_type})")
                continue

            blob = psl_to_octplace(records, bmp_index, type_map, group_map,
                                   packed_pivots=packed_pivots)

        elif has_csv:
            print(f"\n  Map: {map_name} (from CSV, no side conversion)")
            csv_records = parse_map_csv(str(csv_files[map_name]))
            print(f"    CSV: {len(csv_records)} records")

            if len(csv_records) == 0:
                print(f"    Skipping (empty CSV)")
                continue

            blob = csv_to_octplace(csv_records, bmp_index, type_map, group_map)
        else:
            continue

        # Strip "map_" prefix for output name (map_game → game)
        clean_name = map_name[4:] if map_name.startswith('map_') else map_name

        # Save as packed PNG
        packed_img = blob_to_packed_png(blob)
        out_path = os.path.join(output_dir, f"{clean_name}.png")
        packed_img.save(out_path)

        # Verify blob contents
        version = struct.unpack_from('<i', blob, 0)[0]
        count = struct.unpack_from('<i', blob, 4)[0]  # {version(4), count(4), data...}
        print(f"    Packed: version={version}, {count} places, {len(blob)} bytes -> {out_path}")

        # Verify the saved PNG matches the blob
        verify_img = Image.open(out_path)
        verify_raw = verify_img.tobytes()
        w_verify = verify_img.size[0]
        dims_val = w_verify | (verify_img.size[1] << 16)
        print(f"    On-disk verify: {verify_img.size}, "
              f"dimensions_word={dims_val} (0x{dims_val:08x}), "
              f"blob match={verify_raw == blob}")

        map_names.append(clean_name)

    return map_names, bmp_index, sorted_names, name_map, type_map, group_map, tag_map


def generate_app_ids_h(sorted_sprite_names, map_names,
                       name_map, type_map, group_map, tag_map,
                       output_path, exported_dir):
    """
    Generate app_ids.h with BMP enum, MAP enum, and
    NAME_/TYPE_/GROUP_/TAG_ constant sections.

    BMP indices are assigned alphabetically. Map entries are interleaved
    in the alphabetical sort, sharing the BMP namespace.
    """
    import csv as csv_mod
    import re

    # Merge sprites and maps into one sorted list.
    # Maps share the index namespace but do NOT get BMP_ enum entries —
    # they only appear in the MAP enum.
    map_name_set = set(map_names)
    all_entries = []
    for name in sorted_sprite_names:
        if name in map_name_set:
            continue  # will be added as 'map' below
        all_entries.append(('bmp', name))
    for name in map_names:
        all_entries.append(('map', name))

    # Sort everything alphabetically by name
    all_entries.sort(key=lambda e: e[1])

    # Assign indices (0 = none/placeholder)
    lines = ['enum BMP { BMP_none = 0, \nBMP_0 = 0, \n']
    map_lines = ['enum MAP { MAP_none = 0, \n']

    idx = 1
    prev_bmp = {}  # track animation sequences

    # Scan for animation sequences (name_00, name_01, ...)
    # Only sequences starting at _00 get base/end aliases (matches original utils.exe)
    seq_groups = {}  # base_name -> [(full_name, seq_num)]
    for entry_type, name in all_entries:
        if entry_type != 'bmp':
            continue
        m = re.match(r'^(.+?)_(\d{2,})$', name)
        if m:
            base = m.group(1)
            seq_num = int(m.group(2))
            if base not in seq_groups:
                seq_groups[base] = []
            seq_groups[base].append((name, seq_num))

    # Filter: only keep groups that start at 0 (animation sequences)
    seq_groups = {base: sorted(members, key=lambda x: x[1])
                  for base, members in seq_groups.items()
                  if any(num == 0 for _, num in members)}

    # Track first index of each sequence for deferred base alias
    seq_first_idx = {}  # base_name -> first_index

    # Now generate the enum
    idx = 1
    assigned = {}
    for entry_type, name in all_entries:
        if entry_type == 'map':
            # Maps get MAP_ entries only (no BMP_ entry)
            map_lines.append(f'MAP_{name} = {idx}, \n')
            assigned[name] = idx
        else:
            # Regular sprite: BMP_ entry
            enum_name = f"BMP_{name}"
            lines.append(f'{enum_name} = {idx}, \n')
            assigned[name] = idx

            # Check if this is part of a recognized animation sequence
            m = re.match(r'^(.+?)_(\d{2,})$', name)
            if m:
                base = m.group(1)
                seq_num = int(m.group(2))
                group = seq_groups.get(base)
                if group:
                    # First element → remember its index
                    if group[0][1] == seq_num:
                        seq_first_idx[base] = idx
                    # Last element → emit both base alias and _end alias
                    if group[-1][1] == seq_num:
                        first = seq_first_idx.get(base, idx)
                        lines.append(f'BMP_{base} = {first}, \n')
                        lines.append(f'BMP_{base}_end = {idx}, \n')

        idx += 1

    lines.append('BMP_last};\n\n')
    map_lines.append('MAP_last};\n\n')

    # Build full header
    out = ''.join(lines) + ''.join(map_lines)
    out += 'typedef enum BMP BMP;\ntypedef enum MAP MAP;\n\n'

    # Name constants
    out += '//$names\n'
    for nname, nidx in sorted(name_map.items(), key=lambda x: x[1]):
        out += f'const uint8_t NAME_{nname} = {nidx};\n'
    out += f'const uint8_t NAME_last = {max(name_map.values()) + 1 if name_map else 1};\n\n'

    # Type constants
    out += '//%types\n'
    for tname, tidx in sorted(type_map.items(), key=lambda x: x[1]):
        out += f'const uint8_t TYPE_{tname} = {tidx};\n'
    out += f'const uint8_t TYPE_last = {max(type_map.values()) + 1 if type_map else 1};\n\n'

    # Group constants
    out += '//&groups\n'
    for gname, gidx in sorted(group_map.items(), key=lambda x: x[1]):
        out += f'const uint8_t GROUP_{gname} = {gidx};\n'
    out += f'const uint8_t GROUP_last = {max(group_map.values()) + 1 if group_map else 1};\n\n'

    # Tag constants
    out += '//#tags\n'
    for tgname, tgidx in sorted(tag_map.items(), key=lambda x: x[1]):
        out += f'const uint8_t TAG_{tgname} = {tgidx};\n'
    if tag_map:
        out += f'const uint8_t TAG_last = {max(tag_map.values()) + 1};\n'
    out += '\n\n'

    with open(output_path, 'w') as f:
        f.write(out)

    print(f"\n  Generated {output_path}")
    print(f"    {len(sorted_sprite_names)} sprites, {len(map_names)} maps")
    print(f"    {len(name_map)} names, {len(type_map)} types, {len(group_map)} groups, {len(tag_map)} tags")

    return assigned


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="WowCube Packed Sprite Encoder")
    parser.add_argument('files', nargs='*',
                        help='Exported PNGs to pack (default: all from exported/)')
    parser.add_argument('--exported-dir', default='exported',
                        help='Directory with exported RGBA PNGs')
    parser.add_argument('--packed-dir', default='packed',
                        help='Directory with existing packed PNGs (for header reuse)')
    parser.add_argument('--output-dir', default='packed_new',
                        help='Output directory for packed PNGs')
    parser.add_argument('--pal', default=None,
                        help='Path to pal.png (default: packed/pal.png)')
    parser.add_argument('--no-reuse-headers', action='store_true',
                        help='Generate new headers instead of reusing existing ones')
    parser.add_argument('--build-palette', action='store_true',
                        help='Auto-generate grouped palettes from exported sprites')
    parser.add_argument('--max-colors', type=int, default=256,
                        help='Max palette size per group (default: 256)')
    parser.add_argument('--single-palette', action='store_true',
                        help='Force single palette instead of grouped')
    parser.add_argument('--target-colors', type=int, default=None,
                        help='Force exact palette size (e.g. 16, 32, 64) [single-palette mode]')
    parser.add_argument('--quality-threshold', type=int, default=8,
                        help='Mean error threshold for auto-size selection (default: 8)')
    parser.add_argument('--pre-reduce', type=int, default=None,
                        help='Pre-reduce sprites to N colors before grouping. '
                             'Lower = fewer groups but more lossy. (default: max_colors/2)')
    parser.add_argument('--color-tolerance', type=int, default=0,
                        help='Merge similar colors within this distance in 565 space '
                             'during grouping. 0=exact, 1=slight, 2=moderate, 3=aggressive. '
                             '(default: 0)')
    parser.add_argument('--export', action='store_true',
                        help='Export PSD/FNT layers to PNGs before packing (uses psd-tools)')
    parser.add_argument('--art-dir', default='.',
                        help='Art directory containing *.psd and fonts/ (default: current dir)')
    parser.add_argument('--assets', default=None,
                        help='Comma-separated PSD names to treat as assets (not maps). '
                             'If omitted, auto-detected from *assets*.psd in art-dir. '
                             'Example: "assets,items,backgrounds"')
    parser.add_argument('--build-maps', action='store_true',
                        help='Pack map PSL files into pseudo-sprite PNGs')
    parser.add_argument('--map-filter', default=None,
                        help='Which PSL files to pack as maps. Options: '
                             '"auto" (default: if map_*.psd found, use those stems; '
                             'map_ prefix is stripped from output names), '
                             '"all" (treat every PSL as a map), '
                             'or comma-separated stems: "map_game,map_start,map_tutorial"')
    parser.add_argument('--build-ids', action='store_true',
                        help='Generate app_ids.h with BMP/MAP enums and TYPE/GROUP constants')
    parser.add_argument('--ids-output', default=None,
                        help='Output path for app_ids.h (default: app_ids.h in current dir)')
    args = parser.parse_args()

    # ── Auto-detect assets and maps from PSD filenames ─────────────────
    # --assets: explicit list or auto-detect *assets*.psd
    if args.assets is not None:
        asset_names_set = {n.strip() for n in args.assets.split(',') if n.strip()}
    else:
        # Auto-detect: find all *assets*.psd in art-dir
        asset_psds = sorted(Path(args.art_dir).glob('*assets*.psd'))
        if asset_psds:
            asset_names_set = {p.stem for p in asset_psds}
        else:
            asset_names_set = {'assets'}  # fallback default
        print(f"  Auto-detected assets: {', '.join(sorted(asset_names_set))}")

    # --map-filter: explicit list or auto-detect map_*.psd
    if args.map_filter is None:
        map_psds = sorted(Path(args.art_dir).glob('map_*.psd'))
        if map_psds:
            # Found map_*.psd files — use their stems as map filter
            auto_map_names = [p.stem for p in map_psds]
            args.map_filter = ','.join(auto_map_names)
            print(f"  Auto-detected maps: {', '.join(auto_map_names)}")

    # ── PSD export phase (optional) ────────────────────────────────────
    if args.export:
        print("=== Exporting PSD/FNT layers (psd-tools) ===")

        # Parse map filter for export
        mf = args.map_filter
        if mf is None or mf == 'auto':
            export_map_filter = None  # auto: everything except assets
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

    # Determine files to pack
    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = sorted(Path(args.exported_dir).glob('*.png'))

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # ── Palette: auto-build or load existing ────────────────────────────
    sprite_assignments = None  # dict name -> (pidx, palette, sym_bits)
    palettes = {}

    # Check if palette is available; skip loading when not needed
    pal_path = args.pal or os.path.join(args.packed_dir, 'pal.png')
    has_palette = args.build_palette or os.path.exists(pal_path)

    if not has_palette and (args.build_maps or args.build_ids):
        # No palette but maps/ids requested — skip sprite packing
        print("No palette found, skipping sprite packing (maps/ids only).")
    elif args.build_palette:
        file_strs = [str(f) for f in files]

        if args.single_palette or args.target_colors:
            # Single-palette mode (backward compat)
            print("=== Auto-building single palette ===")
            auto_pal, auto_size, auto_sym, auto_colors = build_auto_palette(
                file_strs,
                max_colors=args.max_colors,
                target_colors=args.target_colors,
                quality_threshold=args.quality_threshold,
            )
            pal_out = os.path.join(args.output_dir, 'pal.png')
            save_palette_png(auto_colors, pal_out, has_alpha=True)
            palettes = {1: auto_pal}
            # Build simple assignment: everyone uses palette 1
            sprite_assignments = {}
            for f in files:
                name = f.stem
                if name not in ('pal', '0') and f.suffix.lower() == '.png':
                    sprite_assignments[name] = (1, auto_pal, auto_sym)
            print()
        else:
            # Multi-palette grouped mode (default)
            print("=== Auto-building grouped palettes ===")
            sprite_assignments, all_palette_data = build_grouped_palettes(
                file_strs,
                max_colors=args.max_colors,
                quality_threshold=args.quality_threshold,
                pre_reduce=args.pre_reduce,
                color_tolerance=args.color_tolerance,
            )
            # Save multi-palette pal.png
            pal_out = os.path.join(args.output_dir, 'pal.png')
            all_colors_lists = [colors for colors, _ in all_palette_data]
            save_palette_png(all_colors_lists, pal_out, has_alpha=True)
            # Also build palettes dict for fallback
            palettes = {}
            for i, (colors, sym_bits) in enumerate(all_palette_data):
                palettes[i + 1] = EncoderPalette(colors, has_alpha=True)
            print()
    else:
        # Load existing palette
        pal_path = args.pal or os.path.join(args.packed_dir, 'pal.png')
        if not os.path.exists(pal_path):
            print(f"Error: palette not found: {pal_path}")
            print(f"  Use --build-palette to auto-generate one.")
            sys.exit(1)

        print(f"Loading palette from {pal_path}...")
        palettes, pal_raw = load_palette_for_encoding(pal_path)
        print(f"  Loaded {len(palettes)} palette(s)")
        for pidx, pal in palettes.items():
            print(f"    [{pidx}] {len(pal.colors)} colors, alpha={pal.has_alpha}")

        # Copy pal.png to output
        import shutil
        pal_dst = os.path.join(args.output_dir, 'pal.png')
        if os.path.abspath(pal_path) != os.path.abspath(pal_dst):
            shutil.copy2(pal_path, pal_dst)
            print(f"  Copied pal.png to {args.output_dir}/")

    # ── Ensure 0.png is in exported/ for packing ─────────────────────────
    # 0.png is a placeholder sprite (index 0).  The original !pack.bat
    # copies it from art/ into exported/ before the linker runs.  When
    # --export is not used we still need it in exported/ for the pack loop.
    import shutil as _shutil
    zero_art = os.path.join(args.art_dir, '0.png')
    zero_exp = os.path.join(args.exported_dir, '0.png')
    if os.path.isfile(zero_art) and not os.path.isfile(zero_exp):
        os.makedirs(args.exported_dir, exist_ok=True)
        _shutil.copy2(zero_art, zero_exp)
        print(f"  Copied 0.png from {args.art_dir}/ to {args.exported_dir}/")

    # ── Pre-compute map names to exclude from sprite packing ────────────
    # Maps are packed separately by pack_maps(); if a sprite with the same
    # name (e.g. game.png from game.psd) exists in exported/, packing it as
    # a regular sprite would overwrite the map PNG.  Compute the set of map
    # candidate names up-front so the sprite loop can skip them.
    map_skip_names = set()
    if args.build_maps or args.build_ids:
        mf = args.map_filter
        psl_cands = {p.stem for p in Path(args.exported_dir).glob('*.psl')}
        csv_cands = {p.stem for p in Path(args.exported_dir).glob('*.csv')}
        all_cands = psl_cands | csv_cands
        if isinstance(mf, str) and ',' in (mf or ''):
            # explicit comma list
            map_skip_names = {n.strip() for n in mf.split(',') if n.strip()}
        elif mf == 'all':
            map_skip_names = all_cands
        else:
            # auto or explicit list: exclude non-map PSLs (fonts, assets)
            map_skip_names = {n for n in all_cands
                              if not n.startswith('font')
                              and n not in asset_names_set}
        if map_skip_names:
            print(f"  Map names (will skip in sprite packing): "
                  f"{', '.join(sorted(map_skip_names))}")

    # ── Load pivot data from CSV files ──────────────────────────────────
    # Maps sprite png_name -> (pivot_x, pivot_y) from exported CSVs
    sprite_pivots = {}
    import csv as _csv
    for csv_file in sorted(Path(args.exported_dir).glob('*.csv')):
        try:
            with open(csv_file, 'r') as f:
                reader = _csv.reader(f)
                header_row = next(reader, None)
                if header_row is None:
                    continue
                # Find PivotX, PivotY column indices
                col_names = [c.split()[-1] if ' ' in c else c for c in header_row]
                has_pivot = 'PivotX' in col_names and 'PivotY' in col_names
                if not has_pivot:
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
                    png_name = normalize_layer_name(raw_name)
                    sprite_pivots[png_name] = (pvx, pvy)
        except Exception:
            pass
    if sprite_pivots:
        print(f"  Loaded pivot data for {len(sprite_pivots)} sprites from CSVs")

    # ── Pack sprites (skip if no palette available) ───────────────────────
    ok_count = 0
    skip_count = 0
    err_count = 0
    total_orig_bytes = 0
    total_packed_bytes = 0

    if not has_palette and not args.build_palette:
        files = []  # skip sprite packing loop

    for fpath in files:
        name = fpath.stem

        # Skip special files (0.png is packed normally — it's the placeholder sprite)
        if name == 'pal' or name.endswith('.csv') or name.endswith('.psl'):
            skip_count += 1
            continue

        # Skip map-named PNGs — they are packed by pack_maps() separately
        if name in map_skip_names:
            print(f"  [SKIP] {name}.png (map, will be packed by pack_maps)")
            skip_count += 1
            continue

        if fpath.suffix.lower() != '.png':
            skip_count += 1
            continue

        try:
            # Try to load existing packed header
            existing_packed = os.path.join(args.packed_dir, f"{name}.png")
            header_bytes = None
            if not args.no_reuse_headers and os.path.exists(existing_packed):
                header_bytes = read_existing_header(existing_packed)

            # Determine palette from assignment or fallback
            sym_override = None
            if sprite_assignments and name in sprite_assignments:
                pidx, palette, sym_override = sprite_assignments[name]
            elif header_bytes:
                pidx_from_header = header_bytes[45]
                palette = palettes.get(pidx_from_header, next(iter(palettes.values())))
                pidx = pidx_from_header
            else:
                if 'font' in name:
                    pidx = 1
                    palette = palettes.get(1, next(iter(palettes.values())))
                else:
                    pidx = 0
                    palette = palettes.get(0, next(iter(palettes.values())))

            # Pack (with pivot from CSV if available)
            pvx, pvy = sprite_pivots.get(name, (None, None))
            # Special case: 0.png placeholder has a fixed pivot (-0.5, -0.5)
            # matching the original utils.exe behavior.
            if name == '0':
                pvx, pvy = -0.5, -0.5
            blob = pack_sprite(
                str(fpath), palette,
                header_bytes=header_bytes,
                pidx=pidx,
                symbol_bitness_override=sym_override,
                pivot_x=pvx,
                pivot_y=pvy,
            )

            if blob is None:
                skip_count += 1
                continue

            # Save as packed PNG
            packed_img = blob_to_packed_png(blob)
            out_path = os.path.join(args.output_dir, f"{name}.png")
            packed_img.save(out_path)

            # Stats
            compression = struct.unpack_from('<I', blob, 32)[0]
            sym_bits = compression & 0xFF
            w, h_val = struct.unpack_from('<hh', blob, 36)

            img_src = Image.open(fpath)
            total_orig_bytes += len(img_src.tobytes())
            total_packed_bytes += len(blob)

            mode = "reuse" if header_bytes else "new"
            print(f"  [OK] {name}.png ({w}x{h_val}, sym={sym_bits}bit, "
                  f"pal={pidx}, {len(blob)}B, header={mode})")
            ok_count += 1

        except Exception as e:
            import traceback
            print(f"  [ERR] {name}: {e}")
            traceback.print_exc()
            err_count += 1

    print(f"\nDone: {ok_count} packed, {skip_count} skipped, {err_count} errors")
    if total_orig_bytes > 0:
        ratio = total_packed_bytes / total_orig_bytes
        print(f"  Raw RGBA: {total_orig_bytes:,} bytes -> Packed: {total_packed_bytes:,} bytes "
              f"(ratio {ratio:.3f}x, saved {100*(1-ratio):.1f}%)")

    # ── Map packing ─────────────────────────────────────────────────────
    if args.build_maps or args.build_ids:
        print("\n=== Building maps and/or app_ids.h ===")

        # Parse --map-filter
        mf = args.map_filter
        if mf is None or mf == 'auto':
            map_filter_val = None
        elif mf == 'all':
            map_filter_val = 'all'
        else:
            map_filter_val = [n.strip() for n in mf.split(',') if n.strip()]

        map_names, bmp_index, sorted_names, name_map, type_map, group_map, tag_map = pack_maps(
            args.exported_dir, args.packed_dir, args.output_dir,
            map_filter=map_filter_val,
            asset_names=asset_names_set,
        )
        print(f"\n  Maps packed: {len(map_names)} ({', '.join(map_names)})")

        if args.build_ids:
            ids_path = args.ids_output
            if ids_path is None:
                # Default: app_ids.h in current directory
                ids_path = 'app_ids.h'
            ids_dir = os.path.dirname(ids_path)
            if ids_dir:
                os.makedirs(ids_dir, exist_ok=True)
            generate_app_ids_h(
                sorted_names, map_names,
                name_map, type_map, group_map, tag_map,
                ids_path, args.exported_dir
            )


    # ── Print custom pivots summary ──────────────────────────────────────
    if sprite_pivots:
        custom = [(name, px, py) for name, (px, py) in sprite_pivots.items()
                  if px is not None]
        if custom:
            print(f"\n=== Custom pivots ({len(custom)} sprites) ===")
            for name, px, py in sorted(custom):
                print(f"  {name:<30s} pivot=({px:.1f}, {py:.1f})")


if __name__ == '__main__':
    main()
