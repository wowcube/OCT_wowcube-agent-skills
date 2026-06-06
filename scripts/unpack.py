#!/usr/bin/env python3
"""
WowCube Packed Sprite Decoder
==============================
Unpacks sprites from packed PNG format (single-pixel-high strips)
back into regular RGBA PNG images.

Packed sprite format:
  - 48-byte header (octBmp_t without the PackerSizes field)
  - Scanline trim array (H bytes, aligned to multiple of 4)
  - Bit-packed texel stream (palette symbol + RLE length code)

Palette is stored in a separate "pal.png" resource.

Usage:
  python unpack.py                          # unpack all into unpacked/
  python unpack.py packed/coin.png          # unpack a single file
  python unpack.py --output-dir my_output   # specify output directory
"""

import struct
import sys
import os
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)


# ── Constants from oct_consts.h ──────────────────────────────────────────────

COMPR1_LEN_DECODE = [
    1,15,1,3,1,2,1,5,1,15,1,4,1,2,1,7,
    1,15,1,3,1,2,1,6,1,15,1,4,1,2,1,11,
    1,15,1,3,1,2,1,5,1,15,1,4,1,2,1,9,
    1,15,1,3,1,2,1,6,1,15,1,4,1,2,1,13,
    1,15,1,3,1,2,1,5,1,15,1,4,1,2,1,8,
    1,15,1,3,1,2,1,6,1,15,1,4,1,2,1,12,
    1,15,1,3,1,2,1,5,1,15,1,4,1,2,1,10,
    1,15,1,3,1,2,1,6,1,15,1,4,1,2,1,14,
]

COMPR1_LEN_CONSUME = [
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
    1,3,1,4,1,3,1,5,1,3,1,4,1,3,1,7,
]

COMPR1_LEN_DECODE_MASK = 127

# Sprite flags
OCT_FLAG_ALPHA    = 1 << 0
OCT_FLAG_FULLSIZE = 1 << 1
OCT_FLAG_ADDITIVE = 1 << 2
OCT_FLAG_BG       = 1 << 3


# ── octBmp_t header parser ────────────────────────────────────────────────────

class OctBmp:
    """Packed sprite header (48 bytes in file, without PackerSizes)."""

    HEADER_SIZE = 48

    def __init__(self, data: bytes):
        if len(data) < self.HEADER_SIZE:
            raise ValueError(f"Header too short: {len(data)} < {self.HEADER_SIZE}")

        (
            self.num_pixels,
            self.pivot_x, self.pivot_y,
            self.bx, self.by, self.bw, self.bh,
            self.tags,
            self.compression,
        ) = struct.unpack_from('<I ff ffff I I', data, 0)

        self.w, self.h = struct.unpack_from('<hh', data, 36)
        self.number,    = struct.unpack_from('<h', data, 40)
        self.group      = data[42]
        self.type       = data[43]
        self.flags      = data[44]
        self.pidx       = data[45]
        self.seq        = struct.unpack_from('<b', data, 46)[0]
        self.rate       = struct.unpack_from('<b', data, 47)[0]

        # Parse Compression field
        self.symbol_bitness = self.compression & 0xFF
        self.offset_bitness = (self.compression >> 8) & 0xFF

    @property
    def has_alpha(self):
        return bool(self.flags & OCT_FLAG_ALPHA)

    @property
    def is_fullsize(self):
        return bool(self.flags & OCT_FLAG_FULLSIZE)

    def __repr__(self):
        return (
            f"OctBmp(w={self.w}, h={self.h}, "
            f"symbol_bits={self.symbol_bitness}, offset_bits={self.offset_bitness}, "
            f"pidx={self.pidx}, flags=0x{self.flags:02x}, "
            f"pivot=({self.pivot_x:.1f},{self.pivot_y:.1f}))"
        )


# ── Palette ──────────────────────────────────────────────────────────────────

class OctPalette:
    """Single palette: array of colors in RGB565 format (+ optional 5-bit alpha)."""

    def __init__(self, pal_id, k, flags, colors_raw):
        self.id = pal_id
        self.k = k                     # number of colors = k + 1
        self.flags = flags
        self.has_alpha = bool(flags & OCT_FLAG_ALPHA)
        self.is_additive = bool(flags & OCT_FLAG_ADDITIVE)
        self.colors_rgba = self._decode_colors(colors_raw)

    def _decode_colors(self, colors_raw):
        """Convert array of uint32 to RGBA8888."""
        result = []
        for c32 in colors_raw:
            if self.has_alpha:
                # Upper 5 bits = alpha, lower 27 bits = pre-split RGB565
                alpha5 = (c32 >> 27) & 0x1F
                alpha8 = (alpha5 << 3) | (alpha5 >> 2)  # expand to 8 bits

                # Pre-split format: 0x07e0f81f
                # Encoding was: expanded = (rgb565 | (rgb565 << 16)) & 0x07e0f81f
                # This separates G from R and B:
                #   Bits 0-4:   B (5 bits)
                #   Bits 11-15: R (5 bits)
                #   Bits 21-26: G (6 bits)
                # Reverse: rgb565 = (expanded | (expanded >> 16)) & 0xFFFF
                packed = c32 & 0x07FFFFFF
                rgb565 = (packed | (packed >> 16)) & 0xFFFF
                r5 = (rgb565 >> 11) & 0x1F
                g6 = (rgb565 >> 5) & 0x3F
                b5 = rgb565 & 0x1F
            else:
                # Plain RGB565 in lower 16 bits
                rgb565 = c32 & 0xFFFF
                r5 = (rgb565 >> 11) & 0x1F
                g6 = (rgb565 >> 5) & 0x3F
                b5 = rgb565 & 0x1F
                alpha8 = 255

            # Expand to 8 bits per channel
            r8 = (r5 << 3) | (r5 >> 2)
            g8 = (g6 << 2) | (g6 >> 4)
            b8 = (b5 << 3) | (b5 >> 2)

            result.append((r8, g8, b8, alpha8))
        return result

    def get_color(self, index):
        """Get RGBA color by palette index. Index 0 = transparent."""
        if index == 0:
            return (0, 0, 0, 0)
        if index < len(self.colors_rgba):
            r, g, b, a = self.colors_rgba[index]
            if a == 0:
                return (0, 0, 0, 0)  # normalize transparent pixels
            return (r, g, b, a)
        return (255, 0, 255, 255)  # magenta for errors


def load_palettes(pal_png_path):
    """Load all palettes from pal.png."""
    img = Image.open(pal_png_path)
    raw = img.tobytes()

    # First 4 bytes = number of palettes
    num_palettes = struct.unpack_from('<I', raw, 0)[0]

    # Read octPal_t descriptors (12 bytes each)
    off = 4
    pal_descriptors = []
    for i in range(num_palettes):
        pal_id = raw[off]
        blend  = raw[off + 1]
        k      = raw[off + 2]      # color count minus one
        anims  = raw[off + 3]
        flags  = struct.unpack_from('<I', raw, off + 4)[0]
        cbi    = struct.unpack_from('<i', raw, off + 8)[0]
        pal_descriptors.append((pal_id, blend, k, anims, flags, cbi))
        off += 12

    # Remaining data = array of uint32 colors
    colors_offset = off
    num_color_words = (len(raw) - colors_offset) // 4
    all_colors = list(struct.unpack_from(f'<{num_color_words}I', raw, colors_offset))

    # Build palette objects
    palettes = {}
    for i, (pal_id, blend, k, anims, flags, cbi) in enumerate(pal_descriptors):
        num_colors = k + 1
        colors_raw = all_colors[cbi:cbi + num_colors]
        pal = OctPalette(pal_id, k, flags, colors_raw)
        palettes[i + 1] = pal  # Pidx is 1-based (0 = no palette)

    return palettes


# ── Bitstream decoder ────────────────────────────────────────────────────────

class BitReader:
    """
    Bit-level reader matching the turnover buffer from oct_render.h.
    Reads bits from a byte array, LSB-first within each uint32 word.
    """

    def __init__(self, data: bytes, start_byte_offset: int = 0):
        self.data = data
        self.start = start_byte_offset

    def decode_line(self, line_start_bytes, symbol_bitness, width):
        """
        Decode one scanline from the bitstream.

        Returns a list of `width` palette indices.
        """
        symbol_mask = (1 << symbol_bitness) - 1
        deficit_threshold = 32 - (symbol_bitness + 7)

        # Pointer into uint32 array and bit offset within current word
        word_index = line_start_bytes // 4
        cur_bit_index = (line_start_bytes % 4) * 8

        # Turnover buffer
        turnover = 0
        deficit = 32

        pixels = []
        tex_x = 0

        while tex_x < width:
            # Replenish turnover when deficit is large enough
            if deficit > deficit_threshold:
                word_offset = self.start + word_index * 4
                if word_offset + 4 <= len(self.data):
                    bits_val = struct.unpack_from('<I', self.data, word_offset)[0]
                else:
                    bits_val = 0

                turnover |= ((bits_val >> cur_bit_index) & 0xFFFFFFFF) << (32 - deficit)
                turnover &= 0xFFFFFFFF

                rest = 32 - cur_bit_index
                if rest >= deficit:
                    cur_bit_index += deficit
                else:
                    # Not enough bits in current word, advance to next
                    deficit -= rest
                    word_index += 1
                    cur_bit_index = deficit

                    word_offset = self.start + word_index * 4
                    if word_offset + 4 <= len(self.data):
                        bits_val = struct.unpack_from('<I', self.data, word_offset)[0]
                    else:
                        bits_val = 0

                    turnover |= (bits_val & 0xFFFFFFFF) << (32 - deficit)
                    turnover &= 0xFFFFFFFF

                # Prevent bit index from staying at 32 (UB in C for >> 32)
                if cur_bit_index == 32:
                    word_index += 1
                    cur_bit_index = 0

                deficit = 0

            # Read literal symbol (palette index)
            texel = turnover & symbol_mask
            turnover >>= symbol_bitness
            turnover &= 0xFFFFFFFF

            # Read RLE run-length code via lookup table
            overcode = turnover & COMPR1_LEN_DECODE_MASK
            consume = COMPR1_LEN_CONSUME[overcode]
            turnover >>= consume
            turnover &= 0xFFFFFFFF

            # Repeat symbol for the decoded run length
            repeat = COMPR1_LEN_DECODE[overcode]
            for _ in range(repeat):
                if tex_x >= width:
                    break
                pixels.append(texel)
                tex_x += 1

            # Update deficit counter
            deficit += symbol_bitness + consume

        return pixels


# ── Single sprite unpacker ────────────────────────────────────────────────────

def unpack_sprite(packed_png_path, palettes):
    """
    Unpack a single packed PNG into an RGBA pixel array.

    Returns (Image, OctBmp) or (None, None) on error.
    """
    img = Image.open(packed_png_path)
    raw = img.tobytes()
    name = Path(packed_png_path).stem

    # Skip special resources
    if name in ('pal', '0'):
        return None, None

    if len(raw) < OctBmp.HEADER_SIZE:
        print(f"  [SKIP] {name}: too small ({len(raw)} bytes)")
        return None, None

    # Parse header
    bmp = OctBmp(raw)

    if bmp.w <= 0 or bmp.h <= 0 or bmp.symbol_bitness == 0:
        print(f"  [SKIP] {name}: invalid header ({bmp})")
        return None, None

    # Find palette
    palette = palettes.get(bmp.pidx)
    if palette is None:
        # Try pidx as direct index
        if bmp.pidx == 0 and 1 in palettes:
            palette = palettes[1]
        else:
            print(f"  [WARN] {name}: palette {bmp.pidx} not found, using first available")
            palette = next(iter(palettes.values()))

    # Read scanline trim descriptors
    trims_start = OctBmp.HEADER_SIZE
    trims_size = ((bmp.h + 3) // 4) * 4
    trims = list(raw[trims_start:trims_start + bmp.h])

    # Compressed texel data starts after trims
    texels_start = trims_start + trims_size

    # Decode line by line
    reader = BitReader(raw, texels_start)
    output = np.zeros((bmp.h, bmp.w, 4), dtype=np.uint8)

    line_byte_offset = 0
    for y in range(bmp.h):
        indices = reader.decode_line(line_byte_offset, bmp.symbol_bitness, bmp.w)
        for x, idx in enumerate(indices):
            if x < bmp.w:
                output[y, x] = palette.get_color(idx)
        if y < len(trims):
            line_byte_offset += trims[y]

    return Image.fromarray(output, 'RGBA'), bmp


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="WowCube Packed Sprite Decoder")
    parser.add_argument('files', nargs='*', help='Files to unpack (default: all from packed/)')
    parser.add_argument('--packed-dir', default='packed', help='Directory with packed PNGs')
    parser.add_argument('--output-dir', default='unpacked', help='Output directory')
    parser.add_argument('--pal', default=None, help='Path to pal.png (default: packed/pal.png)')
    args = parser.parse_args()

    # Load palettes
    pal_path = args.pal or os.path.join(args.packed_dir, 'pal.png')
    if not os.path.exists(pal_path):
        print(f"Error: palette not found: {pal_path}")
        sys.exit(1)

    print(f"Loading palettes from {pal_path}...")
    palettes = load_palettes(pal_path)
    print(f"  Loaded {len(palettes)} palette(s)")
    for idx, pal in palettes.items():
        alpha_str = " (with alpha)" if pal.has_alpha else ""
        print(f"    [{idx}] id={pal.id}, {pal.k + 1} colors{alpha_str}")

    # Determine files to unpack
    if args.files:
        files = args.files
    else:
        files = sorted(Path(args.packed_dir).glob('*.png'))

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Unpack
    ok_count = 0
    skip_count = 0
    err_count = 0

    for fpath in files:
        fpath = Path(fpath)
        name = fpath.stem

        if name in ('pal', '0'):
            skip_count += 1
            continue

        try:
            result_img, bmp = unpack_sprite(str(fpath), palettes)
            if result_img is None:
                skip_count += 1
                continue

            out_path = os.path.join(args.output_dir, f"{name}.png")
            result_img.save(out_path)
            print(f"  [OK] {name}.png ({bmp.w}x{bmp.h}, pidx={bmp.pidx}, "
                  f"sym={bmp.symbol_bitness}bit, {'alpha' if bmp.has_alpha else 'opaque'})")
            ok_count += 1

        except Exception as e:
            print(f"  [ERR] {name}: {e}")
            err_count += 1

    print(f"\nDone: {ok_count} unpacked, {skip_count} skipped, {err_count} errors")


if __name__ == '__main__':
    main()
