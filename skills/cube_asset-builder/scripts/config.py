"""
WowCube Packed Sprite Encoder — configuration constants.

All tuning knobs, binary-format offsets, flags, and magic numbers live here.
Keep this module free of logic; it must stay importable with zero side
effects so that any subsystem can consume it cheaply.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag


# ─────────────────────────────────────────────────────────────────────────────
# octBmp_t header (packed sprite) — binary layout (little-endian)
# ─────────────────────────────────────────────────────────────────────────────

HEADER_SIZE = 48                 # total size of octBmp_t without PackerSizes

# Field offsets inside the 48-byte header
HDR_OFF_NUM_PIXELS    = 0        # uint32
HDR_OFF_PIVOT_X       = 4        # float
HDR_OFF_PIVOT_Y       = 8        # float
HDR_OFF_BBOX          = 12       # 4 floats (bx, by, bw, bh)
HDR_OFF_TAGS          = 28       # uint32
HDR_OFF_COMPRESSION   = 32       # uint32 = (offset_bitness<<8) | symbol_bitness
HDR_OFF_WIDTH         = 36       # int16
HDR_OFF_HEIGHT        = 38       # int16
HDR_OFF_NUMBER        = 40       # int16
HDR_OFF_GROUP         = 42       # uint8
HDR_OFF_SPRITE_TYPE   = 43       # uint8
HDR_OFF_FLAGS         = 44       # uint8
HDR_OFF_PIDX          = 45       # uint8
HDR_OFF_SEQ           = 46       # int8
HDR_OFF_RATE          = 47       # int8


# ─────────────────────────────────────────────────────────────────────────────
# Sprite and place flags
# ─────────────────────────────────────────────────────────────────────────────

class SpriteFlag(IntFlag):
    """octBmp_t Flags byte."""
    NONE     = 0
    ALPHA    = 1 << 0
    FULLSIZE = 1 << 1
    ADDITIVE = 1 << 2
    BG       = 1 << 3


class PlaceFlag(IntFlag):
    """octPlace_t Flags word."""
    NONE   = 0
    LOOPED = 0x0002


# ─────────────────────────────────────────────────────────────────────────────
# Compression / RLE
# ─────────────────────────────────────────────────────────────────────────────

COMPR1_LEN_DECODE_MASK = 127
RLE_MAX_RUN            = 15

# Run length -> (bit_pattern, num_bits). Built from COMPR1_LEN_DECODE /
# COMPR1_LEN_CONSUME tables in oct_consts.h.
RLE_ENCODE: dict[int, tuple[int, int]] = {
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

# Default bit widths written into a newly-built header
DEFAULT_OFFSET_BITNESS = 7  # matches the reference pack format used by the sim


# ─────────────────────────────────────────────────────────────────────────────
# Color / palette storage (RGB565 + A5)
# ─────────────────────────────────────────────────────────────────────────────

R_BITS, G_BITS, B_BITS, A_BITS = 5, 6, 5, 5
R_MAX,  G_MAX,  B_MAX,  A_MAX  = 31, 63, 31, 31

# Pre-split "blend-friendly" RGB565 mask (R and B in high half, G in low half)
PRESPLIT_MASK   = 0x07E0F81F
ALPHA5_SHIFT    = 27
ALPHA5_MASK     = 0x1F
RGB565_MASK     = 0xFFFF
PACKED_COLOR_MASK = 0x07FFFFFF   # everything except alpha5 bits

# Channel distance weights used by the median-cut splitter (compensates
# different channel bit widths so G's 0..63 range isn't doubly counted).
MEDIAN_CUT_CHANNEL_WEIGHTS = (2.0, 1.0, 2.0, 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# Palette tiering
# ─────────────────────────────────────────────────────────────────────────────

# Usable colors per tier (index 0 is reserved for transparent)
PALETTE_TIERS_USABLE: tuple[int, ...] = (15, 31, 63, 127, 255)
# Full sizes we try for single-palette auto-build
PALETTE_SIZES_TRIED: tuple[int, ...]  = (16, 32, 64, 128, 256)

PAL_TRANSPARENT_IDX  = 0
PAL_MAX_PALETTES     = 63       # pidx uint8; leave slot 0 for engine use
PAL_MAX_TOTAL_COLORS = 4096     # OctPalsData capacity (16 * 256)
PAL_DESCRIPTOR_SIZE  = 12       # octPal_t descriptor

DEFAULT_QUALITY_THRESHOLD = 8   # mean per-pixel error accepted during auto-fit
DEFAULT_PALETTE_FILENAME  = 'pal.png'


# ─────────────────────────────────────────────────────────────────────────────
# PSL (PSD layer binary) format
# ─────────────────────────────────────────────────────────────────────────────

PSL_HEADER_SIZE      = 16
PSL_RECORD_SIZE      = 700
PSL_NAME_OFFSET      = 0
PSL_NAME_SIZE        = 24
PSL_XYWH_OFFSET      = 24        # 4 × int32
PSL_LAYERMARK_OFFSET = 40        # int32
PSL_SIDE_OFFSET      = 44        # uint32
PSL_CENTER_X_OFFSET  = 48        # uint32
PSL_CENTER_Y_OFFSET  = 52        # uint32
PSL_RESERVED_1       = 56        # uint32 (=1)
PSL_RESERVED_2       = 60        # uint32 (=1)
PSL_RATE_OFFSET      = 120       # "rateN" string, up to 32 bytes
PSL_RATE_SIZE        = 32
PSL_GROUP_OFFSET     = 392
PSL_GROUP_SIZE       = 32
PSL_TYPE_OFFSET      = 424
PSL_TYPE_SIZE        = 16
PSL_NUMBER_OFFSET    = 440       # uint32

PSL_TYPE_ASSET = 1               # non-map PSL
PSL_TYPE_MAP   = 2               # map PSL with side centers


# ─────────────────────────────────────────────────────────────────────────────
# octPlace_t layout (used by maps)
# ─────────────────────────────────────────────────────────────────────────────

OCT_PLACE_SIZE         = 28
OCT_PLACE_RATE_DEFAULT = 1

DEFAULT_LAYER_MARK = -16777216   # 0xFF000000 as signed int32


# ─────────────────────────────────────────────────────────────────────────────
# Filesystem / special sprites
# ─────────────────────────────────────────────────────────────────────────────

PLACEHOLDER_SPRITE_NAME = '0'
PLACEHOLDER_SPRITE_PIVOT = (-0.5, -0.5)
# Reserved sprite slot 0 (BMP_0 = BMP_none = 0) is a TECHNICAL REQUIREMENT
# of the engine: BMP_none is the "no sprite / clear" sentinel and must point
# at a real, harmless asset. If `0.png` is missing the packer auto-creates
# it from these defaults. See _ensure_placeholder_sprite() in pack.py.
PLACEHOLDER_SPRITE_SIZE  = (1, 1)            # 1x1 pixel - minimum legal PNG
PLACEHOLDER_SPRITE_COLOR = (0, 0, 0, 0)      # fully transparent RGBA
PALETTE_SPRITE_NAME     = 'pal'

DEFAULT_ASSET_NAME = 'assets'
MAP_FILENAME_PREFIX = 'map_'


# ─────────────────────────────────────────────────────────────────────────────
# BMFont binary parser
# ─────────────────────────────────────────────────────────────────────────────

BMFONT_MAGIC      = b'BMF'
BMFONT_VERSION    = 3
BMFONT_BLOCK_INFO   = 1
BMFONT_BLOCK_COMMON = 2
BMFONT_BLOCK_PAGES  = 3
BMFONT_BLOCK_CHARS  = 4
BMFONT_CHAR_SIZE    = 20
BMFONT_FIRST_PRINTABLE = 33      # skip control codes + space


# ─────────────────────────────────────────────────────────────────────────────
# Miscellaneous
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Sprite pivot encoding
# ─────────────────────────────────────────────────────────────────────────────

class PivotMode(IntEnum):
    """How the sprite pivot is stored in the octBmp_t header.

    ATLAS  - utils.exe convention: pivot encodes the sprite's top-left
             position on the PSD canvas, scaled and negated:
                 pivot = -(atlas_xy * PIVOT_SCALE + PIVOT_HALFPIX)
    LEGACY - legacy psd.exe / hand-tuned convention: pivot is stored in the
             sprite's own local pixel coordinates with a half-pixel offset:
                 pivot = (w - PIVOT_LOCAL_OFFSET, h - PIVOT_LOCAL_OFFSET)
             Matches the byte-exact layout of packed_old/.
    """
    ATLAS  = 0
    LEGACY = 1


# Active pivot encoding mode for newly built headers. Switch to ATLAS only
# when targeting the utils.exe-based runtime; the engine in this repo
# expects LEGACY pivots.
PIVOT_MODE = PivotMode.LEGACY

# Half-pixel offset used by the LEGACY pivot encoding (pivot points to the
# sprite's bottom-right pixel center).
PIVOT_LOCAL_OFFSET = 0.5

PIVOT_SCALE    = 2               # utils.exe stores pivot * 2x zoom
PIVOT_HALFPIX  = 0.5             # + half-pixel offset (used by ATLAS mode)
NUMBER_FIELD_MASK = 0x7FFF       # 15-bit Number field in octPlace_t
BYTES_PER_RGBA  = 4              # RGBA PNG container stride
WORD_BITS       = 32
# (config rev 2026-04-29: a