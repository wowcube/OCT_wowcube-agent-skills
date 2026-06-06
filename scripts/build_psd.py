#!/usr/bin/env python3
"""
Build a PSD atlas from a folder of PNGs.

Each PNG becomes a separate layer, arranged on a single canvas so that
no two layers overlap. Output is compatible with the pack.py pipeline
(each layer name equals the source PNG stem, lowercased).

Usage:
  python build_psd.py images assets.psd
  python build_psd.py images assets.psd --padding 4
  python build_psd.py images assets.psd --padding 2 --width 1024

The packing algorithm is a simple shelf (row-based) packer. It sorts
sprites by height descending, then lays them out left-to-right, wrapping
to a new row when the current row exceeds the target width.
"""

import argparse
import math
import os
import sys
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("Required: pip install Pillow numpy", file=sys.stderr)
    sys.exit(1)

try:
    from pytoshop.user import nested_layers
    from pytoshop import enums
    from pytoshop.tagged_block import GenericTaggedBlock
except ImportError:
    print("Required: pip install pytoshop", file=sys.stderr)
    sys.exit(1)

# Protected Setting ('lspf') tagged block payload: uint32 big-endian.
# Bits:  transparency(0x01) | composite(0x02) | position(0x04) | all-lock(0x80000000)
# For the UI "lock all" (padlock) we set the all-lock bit plus the three
# individual flags. Photoshop displays this as a solid lock icon.
LOCK_ALL_PAYLOAD = (0x80000000 | 0x01 | 0x02 | 0x04).to_bytes(4, 'big')


def shelf_pack(items, canvas_w, padding=0):
    """
    Simple shelf bin packing.

    items: list of (name, w, h, data...)
    canvas_w: target width (may be exceeded by a single very wide item)
    padding: space between items in pixels

    Returns: list of (name, x, y, w, h, data...) and (canvas_w, canvas_h).
    """
    # Sort by height descending, then width descending (better shelf utilization)
    items_sorted = sorted(items, key=lambda i: (-i[2], -i[1]))

    placed = []
    x = padding
    y = padding
    shelf_h = 0
    max_x = 0

    for item in items_sorted:
        name, w, h = item[0], item[1], item[2]
        rest = item[3:]

        # Wrap to a new shelf if the item doesn't fit in the current row
        if x + w + padding > canvas_w and x > padding:
            x = padding
            y += shelf_h + padding
            shelf_h = 0

        placed.append((name, x, y, w, h) + tuple(rest))
        x += w + padding
        max_x = max(max_x, x)
        shelf_h = max(shelf_h, h)

    total_w = max(max_x, canvas_w) + padding
    total_h = y + shelf_h + padding
    return placed, total_w, total_h


def load_images(images_dir):
    """Load all PNGs from images_dir. Returns list of (name, w, h, pil_image)."""
    images = []
    for f in sorted(Path(images_dir).glob('*.png')):
        try:
            img = Image.open(f).convert('RGBA')
            images.append((f.stem, img.size[0], img.size[1], img))
        except Exception as e:
            print(f"  WARNING: failed to load {f.name}: {e}", file=sys.stderr)
    return images


def make_layer(name, x, y, pil_img):
    """Build a pytoshop layer from a PIL RGBA image at (x, y)."""
    arr = np.array(pil_img)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError(f"Image '{name}' is not RGB/RGBA")

    w, h = pil_img.size
    if arr.shape[2] == 4:
        r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    else:
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        a = np.full((h, w), 255, dtype=np.uint8)

    return nested_layers.Image(
        name=name,
        top=int(y),
        left=int(x),
        bottom=int(y + h),
        right=int(x + w),
        channels={0: r, 1: g, 2: b, -1: a},
    )


def make_solid_layer(name, canvas_w, canvas_h, rgba):
    """
    Create a full-canvas layer filled with a single RGBA color.

    Width and height are swapped to match the canvas orientation
    produced by pytoshop's size parameter (which interprets the tuple
    opposite to its docstring).
    """
    w, h = canvas_h, canvas_w  # swapped to match actual canvas
    r = np.full((h, w), rgba[0], dtype=np.uint8)
    g = np.full((h, w), rgba[1], dtype=np.uint8)
    b = np.full((h, w), rgba[2], dtype=np.uint8)
    a = np.full((h, w), rgba[3], dtype=np.uint8)
    return nested_layers.Image(
        name=name,
        top=0, left=0,
        bottom=h, right=w,
        channels={0: r, 1: g, 2: b, -1: a},
    )


def make_transparent_layer(name, canvas_w, canvas_h):
    """
    Create a full-canvas fully-transparent layer.

    pytoshop drops layers where every alpha pixel equals 0, so we set a
    single corner pixel to alpha=1 (imperceptible). The layer stays
    effectively empty for all practical purposes.
    """
    r = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    g = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    b = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    a = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
    a[0, 0] = 1  # prevent pytoshop from dropping the layer
    return nested_layers.Image(
        name=name,
        top=0, left=0,
        bottom=canvas_h, right=canvas_w,
        channels={0: r, 1: g, 2: b, -1: a},
    )


def lock_layer_records(psd, names_to_lock):
    """
    After the PsdFile is built, append an 'lspf' (Protected Setting)
    tagged block to the matching layer records so Photoshop shows a
    lock icon next to the layer name.
    """
    to_lock = set(names_to_lock)
    for lr in psd.layer_and_mask_info.layer_info.layer_records:
        if lr.name in to_lock:
            lr.blocks.append(GenericTaggedBlock(
                code=b'lspf', data=LOCK_ALL_PAYLOAD,
            ))


def parse_hex_color(hex_str):
    """Parse a hex color string ("#RRGGBB", "RRGGBB", "#RGB", "RGB")
    into an (r, g, b, a=255) tuple."""
    s = hex_str.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(c * 2 for c in s)  # e.g. "F0F" -> "FF00FF"
    if len(s) != 6:
        raise ValueError(f"Invalid hex color '{hex_str}' (expected #RRGGBB or #RGB)")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        raise ValueError(f"Invalid hex color '{hex_str}'")
    return (r, g, b, 255)


def build_psd(images_dir, output_psd, padding=2, target_width=None,
              bg_color=(255, 0, 255, 255)):
    images = load_images(images_dir)
    if not images:
        print(f"No PNG files found in {images_dir}", file=sys.stderr)
        return 1

    # Choose canvas width ≈ √(total_area * 1.3) so the result is roughly
    # square with a little slack for shelf packing inefficiency.
    if target_width is None:
        total_area = sum((w + padding) * (h + padding) for _, w, h, _ in images)
        target_width = int(math.sqrt(total_area * 1.3))
        # Round up to next multiple of 16 for cleaner numbers
        target_width = ((target_width + 15) // 16) * 16

    # Pack
    placed, canvas_w, canvas_h = shelf_pack(images, target_width, padding=padding)

    print(f"Input:  {len(images)} PNG(s) from '{images_dir}'")
    print(f"Canvas: {canvas_w}x{canvas_h} px (target width {target_width}, padding {padding})")

    # Build sprite layers (in original sorted order for deterministic PSD)
    by_name = {p[0]: p for p in placed}
    sprite_layers = []
    for name, _, _, img in sorted(images, key=lambda i: i[0]):
        x = by_name[name][1]
        y = by_name[name][2]
        sprite_layers.append(make_layer(name, x, y, img))

    # Build ~pivot (bottom, empty) and ~background (top, magenta).
    # pytoshop reverses the list order when writing, so the FIRST element
    # of `psd_layers` becomes the BOTTOM layer in Photoshop's Layers panel.
    pivot_layer = make_transparent_layer('~pivot', canvas_w, canvas_h)
    background_layer = make_solid_layer(
        '~background', canvas_w, canvas_h,
        rgba=bg_color,
    )

    # Order: [~pivot (bottom) ... sprites ... ~background (top)]
    psd_layers = [pivot_layer] + sprite_layers + [background_layer]

    # Write PSD — use raw compression because pytoshop 1.2.1 on Python 3.13
    # ships without a compiled packbits module, so the default RLE path fails.
    psd = nested_layers.nested_layers_to_psd(
        psd_layers,
        color_mode=enums.ColorMode.rgb,
        version=enums.Version.psd,
        compression=enums.Compression.raw,
        size=(canvas_h, canvas_w),
    )

    # Lock the two helper layers (padlock icon in Photoshop).
    lock_layer_records(psd, ['~pivot', '~background'])

    with open(output_psd, 'wb') as f:
        psd.write(f)

    bg_hex = '#{:02X}{:02X}{:02X}'.format(*bg_color[:3])
    print(f"Output: {output_psd} (+ ~background {bg_hex}, + ~pivot empty, both locked)")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Build a PSD atlas from a folder of PNGs (no overlap).")
    parser.add_argument('input_dir',
                        help='Folder containing source PNGs (e.g. images)')
    parser.add_argument('output_psd',
                        help='Output PSD file path (e.g. assets.psd)')
    parser.add_argument('--padding', type=int, default=2,
                        help='Padding in px between layers (default: 2)')
    parser.add_argument('--width', type=int, default=None,
                        help='Target canvas width (default: auto ≈ sqrt(area))')
    parser.add_argument('--bg-color', default='#FF00FF',
                        help='Background layer color in hex '
                             '(e.g. #FF00FF, FF00FF, #F0F) (default: magenta)')
    args = parser.parse_args()

    try:
        bg_rgba = parse_hex_color(args.bg_color)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(args.input_dir):
        print(f"Error: '{args.input_dir}' is not a directory", file=sys.stderr)
        sys.exit(1)

    sys.exit(build_psd(
        args.input_dir, args.output_psd,
        padding=args.padding, target_width=args.width,
        bg_color=bg_rgba,
    ))


if __name__ == '__main__':
    main()
