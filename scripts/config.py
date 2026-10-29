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
    """octBmp_t Flags byte.

    Bit values 0x10/0x20/0x40 were read back out of ``utils.exe`` by packing a
    probe sprite tagged ``<BUMP>`` / ``<DUDV>`` / ``<REFL>`` in ``!pack.txt``
    and inspecting octBmp_t offset 44; the palette codec does not use them,
    but ``!pack.txt`` can set them (see :mod:`packtxt`).
    """
    NONE     = 0
    ALPHA    = 1 << 0
    FULLSIZE = 1 << 1
    ADDITIVE = 1 << 2
    BG       = 1 << 3
    BUMP     = 1 << 4
    DUDV     = 1 << 5
    REFL     = 1 << 6


class PlaceFlag(IntFlag):
    """octPlace_t Flags word.

    Every bit below was read back out of ``utils.exe``: a synthetic map PSL
    carrying one place per marker token was packed and the resulting
    ``octPlace_t.Flags`` word read at offset 20 (see
    :data:`MAP_MARKER_PLACE_FLAGS`). They line up one-for-one with the
    bitfield ``oct_types.h`` declares.
    """
    NONE      = 0
    TWISTABLE = 0x0001
    LOOPED    = 0x0002
    HIDDEN    = 0x0004
    PAUSED    = 0x0008
    PINGPONG  = 0x0010
    FLIPH     = 0x0080
    FLIPV     = 0x0100
    ROT_CCW   = 0x0200          # Rot = 1  (90 deg counter-clockwise)
    ROT_180   = 0x0400          # Rot = 2
    ROT_CW    = 0x0600          # Rot = 3  (90 deg clockwise)


# octPlace_t's bitfield, LSB first (oct_types.h)::
#
#     Twistable:1 Looped:1 Hidden:1 Paused:1 PingPong:1 Label:2 FlipH:1
#     FlipV:1 Rot:2
#
# `Label` is the font index of a text placement, straight from the layer's
# `!font` / `!fontN` suffix. OCT_add_map copies it verbatim
# (`spr->Label = plc->Label`) and OCT_label_set returns immediately when it is
# zero, so a place that loses this field is not a mis-styled label -- it draws
# nothing at all.
OCT_PLACE_LABEL_SHIFT = 5
OCT_PLACE_LABEL_MASK  = 0x0060

# OCT_add_label asserts `font_idx` is in [1..3] and calls OCT_terminate
# otherwise, so an out-of-range suffix must fail the build, not ship.
OCT_PLACE_FONT_MIN = 1
OCT_PLACE_FONT_MAX = 3

# A label place stores its ALIGNMENT in the Rate byte (OCT_add_map does
# `spr->Data2 = plc->Rate`, which OCT_add_label consumes as `align`).
# ALIGN_CENTER == 0 (oct_shared.h), which is what all 64 legacy label places
# carry -- labels must not inherit OCT_PLACE_RATE_DEFAULT.
OCT_PLACE_LABEL_ALIGN_DEFAULT = 0


# ─────────────────────────────────────────────────────────────────────────────
# `!marker` grammar (PSD layer name suffixes)
# ─────────────────────────────────────────────────────────────────────────────
#
# A PSD layer name is  <base>[$name][%type][&group][#tag][=num][!marker]...  .
# `psd.exe` does NOT interpret the `!marker` tokens: it copies each one
# verbatim into the record's MARKER SLOT (PSL_RATE_OFFSET), one token per
# PSL_MARKER_CELL_SIZE-byte cell, in source order. `utils.exe` is what gives
# them meaning, and it means different things in Assets mode and Map mode.
#
# The two tables below are the complete vocabulary, read out of `utils.exe`'s
# own string pool and then confirmed by packing a synthetic PSL with one
# record per token and reading the produced `.raw` back:
#
#   Assets mode -- only `rateN` does anything at all. `pause`, `font*`,
#   `label*`, `pingpong`, `hide`, and any unknown token leave the octBmp_t
#   byte-identical to a record with an empty slot.
#
#   Map mode -- the table below. `cw` is real even though it is only the tail
#   of the pooled string "cwcw"; it sets Rot = 3.
#
# Anything not in either table is inert: `utils.exe` silently ignores it.
# `!full_size` is the notable example -- it appears on 12 ladybug layers and
# is a comment to the artist, not a packer instruction (the FULLSIZE flag
# comes from the `<FULLSIZE>` bucket tag in `!pack.txt`).

PSL_MARKER_CELL_SIZE = 16        # bytes per token inside the marker slot
PSL_MARKER_MAX       = 2         # PSL_RATE_SIZE / PSL_MARKER_CELL_SIZE

MARKER_RATE_PREFIX = 'rate'      # `rateN` -> Rate = N (both modes)

# Map-mode marker -> the octPlace_t flag bits it sets.
MAP_MARKER_PLACE_FLAGS: dict[str, int] = {
    'twistable': 0x0001,
    'loop':      0x0002,
    'once':      0x0000,         # explicit "not looped"; sets nothing
    'hide':      0x0004,
    'pause':     0x0008,
    'pingpong':  0x0010,
    'fliph':     0x0080,
    'flipv':     0x0100,
    'ccw':       0x0200,
    'cwcw':      0x0400,
    'cw':        0x0600,
}

# Map-mode marker -> the Label (font) index it selects. A label place also
# forces Rate to OCT_PLACE_LABEL_ALIGN_DEFAULT, which is why it is kept apart
# from MAP_MARKER_PLACE_FLAGS.
MAP_MARKER_LABEL: dict[str, int] = {
    'font': 1, 'font1': 1, 'font2': 2, 'font3': 3,
    'label': 1, 'label1': 1, 'label2': 2, 'label3': 3,
}


# ─────────────────────────────────────────────────────────────────────────────
# Layer mark -> Rate
# ─────────────────────────────────────────────────────────────────────────────
#
# `psd.exe` writes the Photoshop LAYER SHEET COLOUR (the `lclr` tagged block,
# the colour swatch in the Layers panel: 0 none, 1 red, 2 orange, 3 yellow,
# 4 green, 5 blue, 6 violet, 7 gray) into bits 8..15 of the PSL LayerMark
# field, on top of the 0xFF000000 base. `utils.exe` turns that into
#
#     Rate = sheet_colour + 1
#
# for BOTH octBmp_t.Rate and octPlace_t.Rate, and an explicit `!rateN` marker
# overrides it. Measured by packing a PSL whose eight records carry marks
# 0xFF000000..0xFF000700: the rates came back 1..8, and the record that also
# carried `rate10` came back 10.
#
# This is not cosmetic. `oct_scene.h` makes the effective frame delay
# `bmp->Rate * spr->FrameRate`, so a group that loses its colour label plays
# 4-10x too fast. In `OCT_ladybug` 66 of the 70 non-default rates come from
# the sheet colour alone (yellow -> 4, green -> 5) and only 4 from `!rate10`.
LAYER_MARK_BASE        = 0xFF000000
LAYER_MARK_COLOR_SHIFT = 8
LAYER_MARK_COLOR_MASK  = 0xFF


def layer_mark_of(sheet_color: int) -> int:
    """PSL LayerMark int32 for a Photoshop sheet colour (0 = no label)."""
    value = LAYER_MARK_BASE | ((sheet_color & LAYER_MARK_COLOR_MASK)
                               << LAYER_MARK_COLOR_SHIFT)
    return value - (1 << 32) if value >= (1 << 31) else value


def rate_from_layer_mark(layer_mark: int) -> int:
    """``utils.exe``'s default Rate for a record: sheet colour + 1."""
    return ((layer_mark >> LAYER_MARK_COLOR_SHIFT)
            & LAYER_MARK_COLOR_MASK) + 1


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
PSL_SIDE_OFFSET      = 44        # int32  - ~sideN id, -1 when the PSD has none
PSL_CENTER_X_OFFSET  = 48        # int32  - ~sideN marker left
PSL_CENTER_Y_OFFSET  = 52        # int32  - ~sideN marker top
PSL_SIDE_W_OFFSET    = 56        # int32  - ~sideN marker width  (0 when no side)
PSL_SIDE_H_OFFSET    = 60        # int32  - ~sideN marker height (0 when no side)
# Pivot block. psd.exe writes a sentinel then the pivot rect the packer turns
# into octBmp_t.PivotX/Y as  pivot = 2*(rect_centre - layer_xy) - 0.5 .
PSL_PIVOT_MARK_OFFSET = 84       # int32 - PSL_PIVOT_MARK_ASSET in Assets mode, 0 in Map mode
PSL_PIVOT_OFFSET      = 88       # 4 × int32 (x, y, w, h)
PSL_PIVOT_MARK_ASSET  = -3       # constant psd.exe stores at PSL_PIVOT_MARK_OFFSET
PSL_RATE_OFFSET      = 120       # "rateN" string, up to 32 bytes
PSL_RATE_SIZE        = 32
PSL_GROUP_OFFSET     = 392
PSL_GROUP_SIZE       = 32
PSL_TYPE_OFFSET      = 424
PSL_TYPE_SIZE        = 16
PSL_NUMBER_OFFSET    = 440       # uint32

PSL_TYPE_ASSET = 1               # non-map PSL
PSL_TYPE_MAP   = 2               # map PSL with side centers
PSL_TYPE_FONT  = 3               # BMFont PSL: one record per glyph

# ~sideN marker normalisation, as psd.exe performs it.
#
# psd.exe copies the marker layer's rect into the PSL verbatim, except when the
# layer is exactly 1x1: then it writes a SIDE_MARKER_MIN_SIZE square whose
# origin is shifted by a per-side constant. Measured by rewriting the ~sideN
# rects of a real map PSD and re-running psd.exe (see
# tests/test_map_place_geometry.py): the shift follows the side *index* — not
# the marker's position, not the layer order — and fires only for 1x1 (1x2,
# 2x1, 1x3, 3x1 and everything larger pass through untouched).
#
# It is a one-pixel correction with a two-unit consequence: the side centre is
# marker_left + marker_w/2, so half a pixel there moves every place on that
# side by one engine unit. OCT_ladybug's seven map PSDs all ship 1x1 markers.
SIDE_MARKER_MIN_SIZE = 2
SIDE_MARKER_1PX_ORIGIN_SHIFT = {
    0: (-1, -1),
    1: (-1,  0),
    2: ( 0,  0),
    3: ( 0,  0),
    4: (-1,  0),
    5: (-1,  0),
}

# octPlace_t.X/Y half-pixel bias. The packed octBmp_t pivot is stored as
# 2*pivot_local - 0.5 (see PIVOT_MODE below), so undoing that bias is what
# turns "the sprite's pivot" into "the place's position":
#     place.x =  2*(layer_x - side_centre_x) + pivot_x + PLACE_PIVOT_BIAS
#     place.y = -2*(layer_y - side_centre_y) - pivot_y - PLACE_PIVOT_BIAS
PLACE_PIVOT_BIAS = 0.5

# Font PSL extras. `psd.exe <font>.fnt` writes a type-3 PSL whose records
# carry the BMFont metrics the packer needs to fill octBmp_t. The XYWH block
# holds the glyph's atlas rect; the four fields below hold everything else.
# Verified byte-for-byte against a legacy-toolchain `font_1.psl`
# (rogue_escape_vibe/assets/exported) and against the glyph descriptors of the
# shipped `app_ladybug.oct` — see `derive_font_glyph_metrics`.
PSL_FONT_ADVANCE_OFFSET    = 76   # int32 - BMFont xadvance   -> octBmp_t.Bw
PSL_FONT_LINEHEIGHT_OFFSET = 80   # int32 - BMFont lineHeight -> octBmp_t.Bh
PSL_FONT_PIVOT_X_OFFSET    = 112  # float - octBmp_t.PivotX
PSL_FONT_PIVOT_Y_OFFSET    = 116  # float - octBmp_t.PivotY
PSL_FONT_RATE_STRING       = 'letter'   # what psd.exe puts in the rate slot


# ─────────────────────────────────────────────────────────────────────────────
# octPlace_t layout (used by maps)
# ─────────────────────────────────────────────────────────────────────────────

OCT_PLACE_SIZE         = 28
OCT_PLACE_RATE_DEFAULT = 1

# octBmp_t.Rate for an unlabelled layer with no `!rateN` marker: sheet colour
# 0 -> 1 (see rate_from_layer_mark). One frame per spr->FrameRate tick.
BMP_RATE_DEFAULT = 1

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

# Placement maps the launcher looks up BY NAME, so a PSD called this is a map
# whatever its filename prefix. The engine reads "ico" directly
# (oct_shell.h: OCT_external_map(guid1, guid2, "ico")); "ahover" is its hover
# twin. Reference corpus check: art/!pack.bat runs psd.exe -map on exactly
# ico.psd and ahover.psd.
RESERVED_MAP_NAMES = ('ico', 'ahover')


# ─────────────────────────────────────────────────────────────────────────────
# !pack.txt — the legacy utils.exe palette-bucket config (see packtxt.py)
# ─────────────────────────────────────────────────────────────────────────────

PACK_TXT_FILENAME = '!pack.txt'

# Tag -> flag bits. Measured by packing a probe sprite carrying each tag with
# the reference utils.exe and reading octBmp_t offset 44 back.
PACK_TXT_TAG_FLAGS: dict[str, 'SpriteFlag'] = {
    '<FULLSIZE>': SpriteFlag.FULLSIZE,
    '<ADD>':      SpriteFlag.ADDITIVE,
    '<BG>':       SpriteFlag.BG,
    '<BUMP>':     SpriteFlag.BUMP,
    '<DUDV>':     SpriteFlag.DUDV,
    '<REFL>':     SpriteFlag.REFL,
}
# These two do not set a bit of their own — they move the auto-detection's
# threshold (see PACK_TXT_ALPHA_TAGGED_RATIO below).
PACK_TXT_TAG_ALPHA  = '<ALPHA>'
PACK_TXT_TAG_OPAQUE = '<OPAQUE>'

# utils.exe's per-group ALPHA auto-detection. A pixel is invisible at or below
# TRANSPARENT_MAX_ALPHA and counts as fully opaque at or above OPAQUE_MIN_ALPHA
# ("AA-tolerance: N/M semi-transparent pixels forced opaque"); the group gets
# OCT_FLAG_ALPHA when the remaining semi-transparent share of the *visible*
# pixels is STRICTLY above ENABLE_RATIO ("Alpha enabled: N/M").
#
# All three were pinned by binary-searching the reference utils.exe with
# synthetic sprites: alpha 8 is still invisible and 9 is not; 229 is still
# anti-aliased and 230 is not; 1500/10000 stays opaque and 1501/10000 does not.
PACK_TXT_TRANSPARENT_MAX_ALPHA = 8
PACK_TXT_OPAQUE_MIN_ALPHA      = 230
PACK_TXT_ALPHA_ENABLE_RATIO    = 0.15

# `<ALPHA>` does NOT force the bit on -- it lowers the same threshold to zero,
# so the group gets OCT_FLAG_ALPHA iff it has AT LEAST ONE semi-transparent
# pixel. A `<ALPHA>` group whose alpha channel is purely binary is packed
# OPAQUE, and utils.exe prints no decision line for it at all.
#
# Measured on OCT_ladybug: `eat_*` (0/29910 semi), `hit_*` (0/23834) and
# `reboun*` (0/4266) are all tagged `<FULLSIZE><ALPHA>` in art/!pack_pal.txt,
# yet utils.exe's own bucket listing prints them "FULLSIZE" with no ALPHA and
# the shipped container gives all 14 of their sprites Flags = 0x02. The other
# ten `<ALPHA>` buckets have semi > 0 and get 0x03 whatever their ratio --
# `bonus0` enables alpha at 0.9 %, far under the 15 % auto threshold, while
# untagged `splash_nam*` is forced opaque at 7.8 %.
PACK_TXT_ALPHA_TAGGED_RATIO = 0.0


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

    ATLAS  - pivot encodes the sprite's top-left position on the PSD canvas,
             scaled and negated:
                 pivot = -(atlas_xy * PIVOT_SCALE + PIVOT_HALFPIX)
    LEGACY - hand-tuned convention: pivot is stored in the sprite's own local
             pixel coordinates with a half-pixel offset:
                 pivot = (w - PIVOT_LOCAL_OFFSET, h - PIVOT_LOCAL_OFFSET)
             Matches the byte-exact layout of packed_old/.
    PSD    - full utils.exe parity: the pivot is the ``~pivot`` marker rect
             psd.exe attached to the layer, expressed relative to the layer
             origin and scaled by the engine's draw zoom:
                 pivot = SCALE * (rect_centre - layer_xy) - PIVOT_HALFPIX
             with SCALE = PIVOT_SCALE (2) normally and PIVOT_FULLSIZE_SCALE
             (1) for a <FULLSIZE> sprite, which the engine draws 1:1.
             A sprite with no marker gets its own rect as the pivot rect,
             which reduces exactly to the LEGACY formula — so PSD mode is a
             strict superset of LEGACY and only differs where real marker
             data exists.
    """
    ATLAS  = 0
    LEGACY = 1
    PSD    = 2


# Active pivot encoding mode for newly built headers. PSD is the utils.exe
# parity mode; with no marker data (manifest-driven / full-color packs, which
# have no PSD sources at all) it produces byte-identical headers to LEGACY.
PIVOT_MODE = PivotMode.PSD

# Half-pixel offset used by the LEGACY pivot encoding (pivot points to the
# sprite's bottom-right pixel center).
PIVOT_LOCAL_OFFSET = 0.5

PIVOT_SCALE    = 2               # utils.exe stores pivot * 2x zoom
PIVOT_FULLSIZE_SCALE = 1         # <FULLSIZE> sprites are drawn 1:1, not 2x
PIVOT_HALFPIX  = 0.5             # + half-pixel offset (used by ATLAS mode)
NUMBER_FIELD_MASK = 0x7FFF       # 15-bit Number field in octPlace_t
BYTES_PER_RGBA  = 4              # RGBA PNG container stride
WORD_BITS       = 32