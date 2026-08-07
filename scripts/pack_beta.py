"""Beta (octavios dev) asset-container primitives.

The beta simulator loads an app from:
  <APP_DIR>/index.bin                  - kind-tagged asset manifest; record index == asset id
  <APP_DIR>/art/packed/<name>.raw      - sprites (48B octBmp_t + payload) and maps
  <APP_DIR>/art/packed/<name>.pal      - palettes, 4 bytes per color in one of
                                         two forms (see build_pal): plain
                                         `c | c << 16` for an opaque group, or
                                         `alpha5 << 27 | pre-spread RGB` for a
                                         group whose sprites carry OCT_FLAG_ALPHA
  <APP_DIR>/sound/assets/<name>.mp3    - sounds (22050 Hz mono CBR 32k)

Struct layouts mirror octavios/engine/oct_types.h + oct_pack.h and are pinned
by tests/test_beta_container.py against golden files packed by the real beta
utils.exe (from the app_hulk example).
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

KIND_SPRITE, KIND_SOUND, KIND_PAL, KIND_MAP = 0, 1, 2, 3
ASSET_NAME_MAXLEN = 24          # incl. NUL, oct_consts.h OCT_ASSET_NAME_MAXLEN
ASSETS_CAP = 2048               # oct_pack.h OCT_ASSETS_CAP
EXT_MAX_DESCS = 512             # launcher sees only the first 512 descriptors
INDEX_RECORD = struct.Struct("<i24s")
BMP_SIZE = 48

# .oct pack layout, mirrors engine/oct_pack.h (field offsets confirmed by
# tests against a real simulator-built pack)
OCT_HEADER_SIZE = 232           # sizeof(octPackHeader_t)
OCT_DESC_SIZE = 84              # sizeof(octAssetDesc_t)
OCT_PACK_MAGIC = bytes((0xCC, 0x00, 0x00, 0xBB))
OCT_PACK_FORMAT_SUPPORTED = 4
OCT_ENGINE_VERSION_CURRENT = 2
SOFTWARE_NAME_MAXLEN = 80       # oct_consts.h OCT_SOFTWARE_NAME_MAXLEN

# APP_CATEGORIES macro spellings (engine/oct_consts.h) so an app.h that says
# `(APP_CATEGORY_GAME)` resolves without a C preprocessor
_CATEGORY_MACROS = {
    "OCT_CAT_LAUNCHER": 1 << 0, "OCT_CAT_CHARGER": 1 << 1,
    "OCT_CAT_SCREENSAVER": 1 << 2, "OCT_CAT_SYSTEM": 1 << 3,
    "OCT_CAT_GETSTARTED": 1 << 4, "OCT_CAT_SLEEP": 1 << 5,
    "APP_CATEGORY_GAME": 0,
    "APP_CATEGORY_LAUNCHER": 1 << 0, "APP_CATEGORY_CHARGER": 1 << 1,
    "APP_CATEGORY_SCREENSAVER": 1 << 2, "APP_CATEGORY_SYSTEM": 1 << 3,
    "APP_CATEGORY_GETSTARTED": 1 << 4, "APP_CATEGORY_SLEEP": 1 << 5,
}

OCT_FLAG_ALPHA = 1 << 0
OCT_FLAG_FULLSIZE = 1 << 1
OCT_FLAG_ADDITIVE = 1 << 2
OCT_FLAG_BG = 1 << 3
OCT_FLAG_RAW565 = 1 << 7
# octBmp_t::Compression sub-format for a RAW565 payload, mirrors engine/oct_consts.h
RAW565_PLAIN, RAW565_RLE = 0, 1

# .pal word layout for a group whose sprites carry OCT_FLAG_ALPHA, mirrors
# engine/oct_render.h::OCT_BLEND_alpha (`alpha = pe >> 27`, `fg = pe &
# 0x07FFFFFF`, "Already spread in pallette"). Without the flag the word is
# plain `c | c << 16` instead -- see build_pal.
PAL_SPREAD_MASK = 0x07E0F81F        # engine SPREAD_MASK
PAL_ALPHA5_SHIFT = 27
PAL_ALPHA5_MASK = 0x1F

# legacy octBmp_t byte offsets, as pack_codec.build_header writes them
HDR_OFF_FLAGS = 44
HDR_OFF_LEGACY_PIDX = 45

# RLE control-byte threshold and limits
RAW565_RUN = 0x80
MAX_LITERAL = RAW565_RUN
MAX_RUN = 0xFF - RAW565_RUN + 2


@dataclass
class BmpHeader:
    pidx: int; seq: int
    pivot_x: float; pivot_y: float
    bx: float; by: float; bw: float; bh: float
    tags: int; compression: int
    w: int; h: int
    number: int; group: int; type: int
    flags: int; rate: int


def build_bmp_header(*, w, h, flags, pidx=0, seq=0, compression=0,
                      pivot=None, bbox=(0.0, 0.0, 0.0, 0.0),
                      tags=0, number=0, group=0, type_=0, rate=1) -> bytes:
    if pivot is None:
        pivot = ((w - 1) / 2.0 if w else 0.0, (h - 1) / 2.0 if h else 0.0)
    blob = b"".join((
        struct.pack("<HH", pidx, seq),
        struct.pack("<ff", pivot[0], pivot[1]),
        struct.pack("<ffff", *bbox),
        struct.pack("<I", tags),
        struct.pack("<I", compression),
        struct.pack("<hh", w, h),
        struct.pack("<h", number),
        struct.pack("<BB", group, type_),
        struct.pack("<Bb", flags, rate),
        struct.pack("<BB", 0, 0),
    ))
    assert len(blob) == BMP_SIZE
    return blob


def parse_bmp_header(blob: bytes) -> BmpHeader:
    pidx, seq = struct.unpack_from("<HH", blob, 0)
    px, py = struct.unpack_from("<ff", blob, 4)
    bx, by, bw, bh = struct.unpack_from("<ffff", blob, 12)
    tags, compression = struct.unpack_from("<II", blob, 28)
    w, h = struct.unpack_from("<hh", blob, 36)
    number, = struct.unpack_from("<h", blob, 40)
    group, type_, flags = struct.unpack_from("<BBB", blob, 42)
    rate, = struct.unpack_from("<b", blob, 45)
    return BmpHeader(pidx, seq, px, py, bx, by, bw, bh, tags, compression,
                      w, h, number, group, type_, flags, rate)


# Intentionally kept but currently uncalled: ported from videopack.py as the
# documented knob for smoothing noisy full-color video source frames before
# run-encoding. No caller wires it up yet (no --smooth flag exists); kept
# in place for when that option is added rather than re-derived from scratch.
def smooth_rows(texels, width, height, threshold):
    # the run encoder needs texels that match EXACTLY, so a generated clip's faint noise costs it everything: a gradient drifting by one step every other pixel yields runs of two, which save nothing
    # this drags a sticky value along each row and snaps anything within threshold onto it, turning near-matches into real runs at the price of some horizontal streaking in smooth areas
    # green gets twice the slack because RGB565 gives it 6 bits against the other two channels' 5, so one step there is half as large
    pixels = np.frombuffer(texels, dtype="<u2").reshape(height, width)
    red = ((pixels >> 11) & 0x1F).astype(np.int16)
    green = ((pixels >> 5) & 0x3F).astype(np.int16)
    blue = (pixels & 0x1F).astype(np.int16)

    # the scan is sequential within a row but every row is independent, so step along the columns with all rows in one vector
    current_red = red[:, 0].copy()
    current_green = green[:, 0].copy()
    current_blue = blue[:, 0].copy()

    for column in range(width):
        close = ((np.abs(red[:, column] - current_red) <= threshold)
                 & (np.abs(green[:, column] - current_green) <= threshold * 2)
                 & (np.abs(blue[:, column] - current_blue) <= threshold))

        red[:, column] = np.where(close, current_red, red[:, column])
        green[:, column] = np.where(close, current_green, green[:, column])
        blue[:, column] = np.where(close, current_blue, blue[:, column])

        # a snapped texel leaves the sticky value alone and a rejected one becomes it, which is what the column now holds either way
        current_red = red[:, column]
        current_green = green[:, column]
        current_blue = blue[:, column]

    out = (red.astype("<u2") << 11) | (green.astype("<u2") << 5) | blue.astype("<u2")

    return out.tobytes()


def _floyd_steinberg(channel, levels):
    """Serpentine Floyd-Steinberg error diffusion of one 0..255 channel.

    Quantizes to ``levels + 1`` evenly spaced values (the 5- or 6-bit RGB565
    lattice) and returns the integer level indices as an (h, w) uint16 array.
    Works in level space so the lattice points are exactly the integers; the
    scan alternates direction per row (serpentine), which breaks up the
    diagonal worm artifacts of a fixed left-to-right scan.

    Deliberately a plain python loop: FS error diffusion is sequential per
    pixel (each result feeds the next pixel's input), so rows cannot be
    vectorized the way rle_tokens vectorizes runs. 240x240 is ~58k pixels
    per channel, well inside interactive time.
    """
    h, w = channel.shape
    buf = (channel * (levels / 255.0)).tolist()   # plain lists: fast scalar access
    out = [[0] * w for _ in range(h)]
    for y in range(h):
        row = buf[y]
        nxt = buf[y + 1] if y + 1 < h else None
        rightward = not (y & 1)
        step = 1 if rightward else -1
        for x in (range(w) if rightward else range(w - 1, -1, -1)):
            old = row[x]
            q = int(old + 0.5)          # buf can dip slightly negative,
            if q < 0:                   # so clamp after rounding
                q = 0
            elif q > levels:
                q = levels
            out[y][x] = q
            err = old - q
            ahead = x + step
            behind = x - step
            if 0 <= ahead < w:
                row[ahead] += err * 0.4375          # 7/16
            if nxt is not None:
                if 0 <= behind < w:
                    nxt[behind] += err * 0.1875     # 3/16
                nxt[x] += err * 0.3125              # 5/16
                if 0 <= ahead < w:
                    nxt[ahead] += err * 0.0625      # 1/16
    return np.asarray(out, dtype=np.uint16)


def to_rgb565(image, size, dither=False):
    """Convert a PIL image to little-endian RGB565 texels.

    ``size`` as an int centre-crops the image to a square and resizes to
    that side (videopack's original behaviour); ``size`` as a (w, h) tuple
    resizes straight to exactly w x h. Alpha (or any transparency info) is
    always flattened onto black before conversion, since RGB565 carries no
    alpha channel. Returns ``width * height * 2`` bytes.

    Each 8-bit channel maps to the NEAREST 5/6-bit level -- truncation
    (``>> 3``) would bias dark and band on smooth gradients. With
    ``dither=True`` the per-channel quantization error is Floyd-Steinberg
    diffused instead, trading banding for high-frequency noise: right for
    photographic art, pointless for flat-color sprites (a color already on
    the lattice comes out identical either way).
    """
    # RGB565 carries no alpha, so flatten onto black instead of letting the undefined colour under fully transparent pixels through
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        image = image.convert("RGBA")
        flattened = Image.new("RGBA", image.size, (0, 0, 0, 255))
        flattened.alpha_composite(image)
        image = flattened

    image = image.convert("RGB")

    if isinstance(size, tuple):
        # sprites may be non-square: resize straight to the exact w x h target
        target_w, target_h = size
        if image.size != (target_w, target_h):
            image = image.resize((target_w, target_h), Image.LANCZOS)
    else:
        # square target (videopack's original behaviour): centre-crop to a
        # square first, then resize, so the frame isn't stretched
        side = size
        width, height = image.size
        if width != height:
            edge = min(width, height)
            left = (width - edge) // 2
            top = (height - edge) // 2
            image = image.crop((left, top, left + edge, top + edge))

        if image.size != (side, side):
            image = image.resize((side, side), Image.LANCZOS)

    if dither:
        pixels = np.asarray(image, dtype=np.float64)
        red = _floyd_steinberg(pixels[:, :, 0], 31) << 11
        green = _floyd_steinberg(pixels[:, :, 1], 63) << 5
        blue = _floyd_steinberg(pixels[:, :, 2], 31)
    else:
        # (v * levels + 127) // 255 is exact round-to-nearest for integer v:
        # the remainder is an integer, so the +127 bias tips exactly the
        # values whose fractional part is >= 128/255 > 0.5 upward
        pixels = np.asarray(image, dtype=np.uint32)
        red = ((pixels[:, :, 0] * 31 + 127) // 255).astype(np.uint16) << 11
        green = ((pixels[:, :, 1] * 63 + 127) // 255).astype(np.uint16) << 5
        blue = ((pixels[:, :, 2] * 31 + 127) // 255).astype(np.uint16)

    return (red | green | blue).astype("<u2").tobytes()


def rle_tokens(pixels, width, height):
    # a control byte below RAW565_RUN opens a literal run of (control + 1) texels, at or above it repeats one texel (control - RAW565_RUN + 2) times
    # literals are what keep a noisy row from inflating, the worst case costs one byte per 128 texels
    #
    # every step below runs over the whole image at once, because a per-texel python loop over 920 frames of 57600 texels takes minutes
    # rows stay independent by forcing a group break at every row start, so no token ever straddles two rows and the row length table below stays exact
    flat = pixels.reshape(-1)
    count = flat.size

    breaks = np.zeros(count, dtype=bool)
    breaks[0] = True
    breaks[1:] = flat[1:] != flat[:-1]
    breaks[::width] = True

    starts = np.flatnonzero(breaks)
    lengths = np.diff(starts, append=count)

    # a run longer than MAX_RUN needs several tokens, so cut every group into MAX_RUN-sized pieces
    if lengths.max(initial=0) > MAX_RUN:
        pieces = -(-lengths // MAX_RUN)
        starts = np.repeat(starts, pieces)
        offsets = np.arange(starts.size) - np.repeat(np.cumsum(pieces) - pieces, pieces)
        starts = starts + offsets * MAX_RUN
        lengths = np.minimum(np.repeat(lengths, pieces) - offsets * MAX_RUN, MAX_RUN)

    return starts, lengths


def rle_blocks(starts, lengths, width):
    # single texels are folded into literal blocks, everything longer becomes a run token
    # a block is a maximal stretch of singles inside one row, capped at MAX_LITERAL because the control byte holds count - 1
    single = lengths == 1
    rows = starts // width

    # a block opens on a single whose predecessor is not a single of the same row
    opens = np.zeros(single.size, dtype=bool)
    opens[0] = single[0]
    opens[1:] = single[1:] & (~single[:-1] | (rows[1:] != rows[:-1]))

    block_of = np.cumsum(opens) - 1
    sizes = np.bincount(block_of[single], minlength=max(int(opens.sum()), 1))[:int(opens.sum())]
    block_start = np.flatnonzero(opens)

    # split a block that outgrew the control byte, the tail pieces open right after their predecessor
    if sizes.size and sizes.max() > MAX_LITERAL:
        pieces = -(-sizes // MAX_LITERAL)
        block_start = np.repeat(block_start, pieces)
        offsets = np.arange(block_start.size) - np.repeat(np.cumsum(pieces) - pieces, pieces)
        block_start = block_start + offsets * MAX_LITERAL
        sizes = np.minimum(np.repeat(sizes, pieces) - offsets * MAX_LITERAL, MAX_LITERAL)

    return block_start, sizes


def rle_encode(texels, width, height):
    pixels = np.frombuffer(texels, dtype="<u2").reshape(height, width)
    starts, lengths = rle_tokens(pixels, width, height)
    block_start, block_size = rle_blocks(starts, lengths, width)

    run = lengths >= 2
    run_at = np.flatnonzero(run)

    # tokens keep their positional order, so interleave the runs and the literal blocks back by the group they open on
    token_at = np.concatenate((run_at, block_start))
    token_bytes = np.concatenate((np.full(run_at.size, 3), 1 + 2 * block_size.astype(np.int64)))
    order = np.argsort(token_at, kind="stable")
    token_at = token_at[order]
    token_bytes = token_bytes[order]

    # the row table is what lets a clipped sprite skip straight to its first visible row
    rows = starts[token_at] // width
    lengths_per_row = np.bincount(rows, weights=token_bytes, minlength=height).astype(np.int64)
    if lengths_per_row.max(initial=0) > 0xFFFF:
        # raised as ValueError here (library, not CLI)
        raise ValueError("a compressed row overflows the 16-bit row length table")

    # every token writes at a byte offset the engine reaches by walking the stream, so lay them out by prefix sum
    token_off = np.concatenate(((0,), np.cumsum(token_bytes)[:-1])).astype(np.int64)
    body = np.zeros(int(token_bytes.sum()), dtype=np.uint8)

    flat = pixels.reshape(-1)
    is_run = np.zeros(token_at.size, dtype=bool)
    is_run[np.searchsorted(token_at, run_at)] = True

    run_off = token_off[is_run]
    run_val = flat[starts[token_at[is_run]]]
    body[run_off] = (RAW565_RUN + lengths[token_at[is_run]] - 2).astype(np.uint8)
    body[run_off + 1] = (run_val & 0xFF).astype(np.uint8)
    body[run_off + 2] = (run_val >> 8).astype(np.uint8)

    lit_off = token_off[~is_run]
    lit_at = token_at[~is_run]
    lit_size = ((token_bytes[~is_run] - 1) // 2).astype(np.int64)
    body[lit_off] = (lit_size - 1).astype(np.uint8)

    # fan every block out to its own texels, index inside the block drives both the source group and the destination byte
    inside = np.arange(int(lit_size.sum())) - np.repeat(np.cumsum(lit_size) - lit_size, lit_size)
    lit_val = flat[starts[np.repeat(lit_at, lit_size) + inside]]
    lit_dst = np.repeat(lit_off, lit_size) + 1 + 2 * inside
    body[lit_dst] = (lit_val & 0xFF).astype(np.uint8)
    body[lit_dst + 1] = (lit_val >> 8).astype(np.uint8)

    # the stream starts 4-byte aligned so the engine's row table stays aligned too
    table = lengths_per_row.astype("<u2").tobytes()
    table += b"\0" * ((-len(table)) & 3)

    return table + body.tobytes()


def rle_decode(payload, width, height):
    # a reference decoder, used by tests and --verify-style checks, mirrors OCT_RENDER_raw565_row
    table = height * 2
    cursor = (table + 3) & ~3
    lengths = np.frombuffer(payload[:table], dtype="<u2")

    out = np.zeros(width * height, dtype="<u2")
    for row in range(height):
        end = cursor + int(lengths[row])
        column = 0
        while cursor < end:
            control = payload[cursor]
            cursor += 1
            if control < RAW565_RUN:
                count = control + 1
                texels = np.frombuffer(payload[cursor:cursor + 2 * count], dtype="<u2")
                out[row * width + column:row * width + column + count] = texels
                cursor += 2 * count
            else:
                count = control - RAW565_RUN + 2
                out[row * width + column:row * width + column + count] = payload[cursor] | (payload[cursor + 1] << 8)
                cursor += 2

            column += count

        if column != width:
            # raised as ValueError here (library, not CLI)
            raise ValueError(f"row {row} decodes to {column} texels, expected {width}")

    return out.tobytes()


def build_raw565_sprite(texels: bytes, w: int, h: int, *, flags, seq=0, rate=1) -> bytes:
    """48-byte octBmp_t + RGB565 payload; keeps RLE only when it shrinks."""
    flags |= OCT_FLAG_RAW565
    body = rle_encode(texels, w, h)
    if len(body) >= len(texels):
        return build_bmp_header(w=w, h=h, flags=flags, seq=seq, rate=rate,
                                compression=RAW565_PLAIN) + texels
    return build_bmp_header(w=w, h=h, flags=flags, seq=seq, rate=rate,
                            compression=RAW565_RLE) + body


def build_index_bin(records: list[tuple[int, str]]) -> bytes:
    if len(records) > ASSETS_CAP:
        raise ValueError(f"{len(records)} assets exceeds OCT_ASSETS_CAP ({ASSETS_CAP})")
    out = [struct.pack("<i", len(records))]
    for kind, name in records:
        encoded = name.encode("ascii")
        if len(encoded) >= ASSET_NAME_MAXLEN:
            raise ValueError(f"asset name '{name}' exceeds {ASSET_NAME_MAXLEN - 1} chars")
        out.append(INDEX_RECORD.pack(kind, encoded))
    return b"".join(out)


def read_index_bin(path: Path) -> list[tuple[int, str]]:
    blob = Path(path).read_bytes()
    count, = struct.unpack_from("<i", blob, 0)
    if count < 0:
        raise ValueError(f"index.bin has negative record count {count}")
    if 4 + count * INDEX_RECORD.size > len(blob):
        raise ValueError(
            f"index.bin claims {count} records ({4 + count * INDEX_RECORD.size} bytes) "
            f"but the file is only {len(blob)} bytes"
        )
    records = []
    for i in range(count):
        kind, raw = INDEX_RECORD.unpack_from(blob, 4 + i * INDEX_RECORD.size)
        records.append((kind, raw.split(b"\0", 1)[0].decode("ascii")))
    return records


def pal_word_plain(rgb565: int) -> int:
    """The opaque palette word: RGB565 duplicated into both halves.

    ``OCT_BLEND_opaque`` does ``back[pix] = pal[t]`` and only the low half
    ever reaches the framebuffer, so the duplication is free redundancy —
    but it is what ``utils.exe`` writes, byte for byte.
    """
    rgb565 &= 0xFFFF
    return (rgb565 | (rgb565 << 16)) & 0xFFFFFFFF


def pal_word_spread(rgb565: int, alpha8: int) -> int:
    """The alpha palette word: 5-bit alpha over pre-spread RGB.

    ``OCT_BLEND_alpha`` (engine ``oct_render.h``) reads it as::

        alpha = pe >> 27;              // 5 bits
        fg    = pe & 0x07FFFFFF;       // already (fg | fg << 16) & 0x07e0f81f

    i.e. green is lifted into bits 26..21 so the blend can do all three
    channels in one 32-bit add.
    """
    a5 = (alpha8 >> 3) & PAL_ALPHA5_MASK
    rgb565 &= 0xFFFF
    return (a5 << PAL_ALPHA5_SHIFT) | ((rgb565 | (rgb565 << 16)) & PAL_SPREAD_MASK)


def pal_is_spread(words) -> bool:
    """True when a ``.pal`` word list is in the alpha (spread) format.

    A plain palette has ``low16 == high16`` in every word; the spread form
    scatters green into the high half and alpha above it, which no plain
    entry can imitate.  An all-zero palette is identical in both forms and
    reports plain (corpus group 16, ``eyes_bg*``, is exactly that).
    """
    return any((w & 0xFFFF) != ((w >> 16) & 0xFFFF) for w in words)


def build_pal(colors_rgb565: list[int], alphas: list[int] | None = None) -> bytes:
    """Serialise one palette group.

    ``alphas`` is what picks the format, and the caller must derive it from
    the group's ``OCT_FLAG_ALPHA`` bit — the two are one decision, not two
    (see :func:`pal_word_spread`; a plain palette read by ``OCT_BLEND_alpha``
    would use its RED channel as alpha, and a spread one read by
    ``OCT_BLEND_opaque`` would lose green).  ``utils.exe`` keeps them in
    lockstep for all 46 palette groups of the reference corpus.

      * ``alphas is None`` — plain ``c | c << 16``, for sprites WITHOUT
        ``OCT_FLAG_ALPHA``.
      * ``alphas`` given (0..255 per entry) — the spread alpha format, for
        sprites WITH it.

    Index 0 is the keyed-out slot every blend routine skips
    (``if (t == 0) continue``); it is written as all-zero in both forms.
    """
    if alphas is None:
        # each entry stores the RGB565 value twice (see golden 5.pal)
        return b"".join(struct.pack("<HH", c, c) for c in colors_rgb565)
    if len(alphas) != len(colors_rgb565):
        raise ValueError(
            f"palette has {len(colors_rgb565)} colors but {len(alphas)} alphas")
    words = [pal_word_spread(c, a) for c, a in zip(colors_rgb565, alphas)]
    if words:
        words[0] = 0
    return b"".join(struct.pack("<I", w) for w in words)


def _read_pal_words(path: Path) -> list[int]:
    blob = Path(path).read_bytes()
    if len(blob) % 4 != 0:
        raise ValueError(f"{path}: truncated .pal file, {len(blob)} bytes is not a multiple of 4")
    return [struct.unpack_from("<I", blob, off)[0]
            for off in range(0, len(blob), 4)]


def read_pal(path: Path) -> list[int]:
    """The palette's RGB565 colors, whichever of the two formats it is in."""
    return [c for c, _a in read_pal_rgba(path)]


def read_pal_rgba(path: Path) -> list[tuple[int, int]]:
    """``[(rgb565, alpha8)]``; a plain palette reads back fully opaque.

    Index 0 always reads back ``(0, 0)`` — it is the transparent slot.
    """
    words = _read_pal_words(path)
    out: list[tuple[int, int]] = []
    if pal_is_spread(words):
        for w in words:
            a5 = (w >> PAL_ALPHA5_SHIFT) & PAL_ALPHA5_MASK
            r5, g6, b5 = (w >> 11) & 0x1F, (w >> 21) & 0x3F, w & 0x1F
            out.append(((r5 << 11) | (g6 << 5) | b5, (a5 << 3) | (a5 >> 2)))
    else:
        out = [(w & 0xFFFF, 255) for w in words]
    if out:
        out[0] = (0, 0)
    return out


def split_pal_entries(entries) -> tuple[list[int], list[int]]:
    """Normalise a palette group to ``([rgb565], [alpha8])``.

    Accepts the historic ``[rgb565, ...]`` form (everything opaque) as well
    as ``[(rgb565, alpha8), ...]``.
    """
    colors: list[int] = []
    alphas: list[int] = []
    for entry in entries:
        if isinstance(entry, (tuple, list)):
            color, alpha = entry
        else:
            color, alpha = entry, 255
        colors.append(int(color) & 0xFFFF)
        alphas.append(int(alpha) & 0xFF)
    return colors, alphas


def patch_palette_sprite(blob: bytes, *, pal_id: int, seq_id: int = 0,
                         extra_flags: int = 0) -> bytes:
    """Convert a legacy packed-sprite blob into a beta one, payload untouched.

    The legacy octBmp_t (pack_codec.build_header) and the beta octBmp_t
    (oct_types.h) are the same 48 bytes except for four fields:

        offset   legacy                     beta
        0..3     num_pixels (u32)           Pidx (u16) + Seq (u16)
        44       Flags (u8)                 Flags (u8)          (unchanged)
        45       Pidx (u8)                  Rate (i8)
        46       Seq (i8)                   Reserved = 0
        47       Rate (i8)                  Reserved = 0

    Beta Pidx/Seq are ASSET IDS (index.bin record indices), not the legacy
    palette-group / sibling-sprite indices, so the caller supplies them.
    The legacy Rate byte is preserved by moving it into the beta slot.

    `extra_flags` ORs additional OCT_FLAG_* bits into the Flags byte @44 --
    the seam that lets manifest flags (fullsize/additive/bg) reach a palette
    sprite's beta header. The legacy bits already present (ALPHA) are kept;
    the default of 0 leaves the byte exactly as the legacy packer wrote it.
    """
    if len(blob) < BMP_SIZE:
        raise ValueError(f"sprite blob is {len(blob)} bytes, needs at least {BMP_SIZE}")
    hdr = bytearray(blob[:BMP_SIZE])
    rate, = struct.unpack_from("<b", hdr, 47)
    struct.pack_into("<HH", hdr, 0, pal_id, seq_id)
    hdr[44] |= extra_flags & 0xFF
    struct.pack_into("<bBB", hdr, 45, rate, 0, 0)
    return bytes(hdr) + blob[BMP_SIZE:]


def build_map(bmp_id: int, w: int, h: int, *, x=120.0, y=120.0, looped=False, rate=1) -> bytes:
    place = b"".join((
        struct.pack("<ff", x, y),
        struct.pack("<I", 0),                       # Tags
        struct.pack("<hh", w, h),
        struct.pack("<h", bmp_id),
        struct.pack("<h", 0),                       # Number
        struct.pack("<H", (1 << 1) if looped else 0),  # PLACE_LOOPED
        struct.pack("<bb", 1, rate),                # Side, Rate
        struct.pack("<BBBB", 0, 0, 0, 0),           # Name, Group, Parent, Type
    ))
    assert len(place) == 28
    return struct.pack("<ii", 1, 1) + place


# ─────────────────────────────────────────────────────────────────────────────
# Beta container emit layer
# ─────────────────────────────────────────────────────────────────────────────

# animation frames are named <base>_NN (two or more digits), same rule the
# legacy pack_psd.generate_app_ids_h uses for its base/_end aliases
_RE_SEQ_FRAME = re.compile(r"^(.+?)_(\d{2,})$")


def _seq_frame_groups(names) -> dict[str, list[tuple[int, str]]]:
    """Group sprite names into animation sequences, sorted by frame number.

    Only sequences that start at their natural base count: zero-based
    (coin_00, mirrors generate_app_ids_h) or one-based (frame_001, the
    convention video-cut frame sets use). A stray coin_05 without coin_00
    or coin_01 stays a plain static sprite.
    """
    raw: dict[str, list[tuple[int, str]]] = {}
    for name in names:
        m = _RE_SEQ_FRAME.match(name)
        if m:
            raw.setdefault(m.group(1), []).append((int(m.group(2)), name))
    return {base: sorted(members)
            for base, members in raw.items()
            if min(num for num, _ in members) in (0, 1)}


def _seq_chain(sprite_ids: dict[str, int]) -> dict[str, int]:
    """Map each animation frame name to the ASSET ID of its next frame.

    Frames chain 00 -> 01 -> ... -> last -> 00 (the engine walks Seq to
    advance animation). Single-frame groups get no chain: Seq = 0 stops the
    walk on the frame itself, which is what a static sprite wants.
    """
    chain: dict[str, int] = {}
    for members in _seq_frame_groups(sprite_ids).values():
        if len(members) < 2:
            continue
        for (_, cur), (_, nxt) in zip(members, members[1:] + members[:1]):
            chain[cur] = sprite_ids[nxt]
    return chain


def _write_raw(path: Path, blob: bytes) -> None:
    # the sim streams payloads in whole and keeps the next one 4-byte aligned;
    # utils.exe always emits %4 sizes, so never ship a file that is not
    path.write_bytes(blob + b"\0" * ((-len(blob)) & 3))


def _load_rgb565(image, size, dither=False) -> bytes:
    """to_rgb565 for a Path or an already-open PIL image.

    Only images this function opened get closed; a caller-supplied Image
    stays usable after the call.
    """
    if isinstance(image, Image.Image):
        return to_rgb565(image, size, dither=dither)
    with Image.open(image) as img:
        return to_rgb565(img, size, dither=dither)


def generate_beta_ids_h(records: list[tuple[int, str]]) -> str:
    """Kind-aware ids header text for a beta record list (index == asset id).

    enum BMP carries every KIND_SPRITE record except the reserved slot-0
    "zero" (covered by BMP_none = 0), enum MAP every KIND_MAP, enum SND every
    KIND_SOUND. Animation sequences additionally get the legacy aliases:
    BMP_<base> = first frame, BMP_<base>_end = last frame.

    Raises ValueError when two records (or a record and an animation alias)
    would produce the same enum identifier, and when an asset name contains
    characters that make the identifier invalid C (e.g. "coin-gold"): such
    names are rejected loudly instead of shipping a header that surprises
    downstream tooling. Digit-leading names ("000", "1up") are fine - the
    BMP_/MAP_/SND_ prefix supplies the leading letter.
    """
    seen = {"BMP_none", "BMP_0", "BMP_last",
            "MAP_none", "MAP_last", "SND_none", "SND_last"}

    def ident(prefix: str, name: str) -> str:
        result = f"{prefix}_{name}"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", result):
            raise ValueError(
                f"asset name '{name}' yields '{result}', which is not a "
                f"valid C enum identifier - use only letters, digits and "
                f"underscores in asset names")
        if result in seen:
            raise ValueError(
                f"duplicate enum identifier '{result}' in the generated ids "
                f"header - two assets, or an asset and an animation alias "
                f"(a sprite named '<base>' next to a '<base>_00' sequence "
                f"generates BMP_<base> twice), claim the same name - rename "
                f"one of them")
        seen.add(result)
        return result

    bmp = [(i, n) for i, (k, n) in enumerate(records)
           if k == KIND_SPRITE and not (i == 0 and n == "zero")]
    maps = [(i, n) for i, (k, n) in enumerate(records) if k == KIND_MAP]
    snds = [(i, n) for i, (k, n) in enumerate(records) if k == KIND_SOUND]

    bmp_ids = {n: i for i, n in bmp}
    groups = _seq_frame_groups(bmp_ids)
    last_frame_of = {members[-1][1]: base for base, members in groups.items()}

    lines = ["// generated by pack_beta.py (emit_beta_layout), do not edit\n",
             "enum BMP { BMP_none = 0, \n", "BMP_0 = 0, \n"]
    for i, name in bmp:
        lines.append(f"{ident('BMP', name)} = {i}, \n")
        base = last_frame_of.get(name)
        if base is not None:
            members = groups[base]
            lines.append(f"{ident('BMP', base)} = {bmp_ids[members[0][1]]}, \n")
            lines.append(f"{ident('BMP', base + '_end')} = {i}, \n")
    lines.append("BMP_last};\n\n")

    lines.append("enum MAP { MAP_none = 0, \n")
    lines.extend(f"{ident('MAP', name)} = {i}, \n" for i, name in maps)
    lines.append("MAP_last};\n\n")

    lines.append("enum SND { SND_none = 0, \n")
    lines.extend(f"{ident('SND', name)} = {i}, \n" for i, name in snds)
    lines.append("SND_last};\n\n")

    lines.append("typedef enum BMP BMP;\ntypedef enum MAP MAP;\ntypedef enum SND SND;\n")
    return "".join(lines)


def emit_beta_layout(
    app_dir: str | Path,
    app_name: str,
    *,
    palettes: dict[int, list[int] | list[tuple[int, int]]] | None = None,
    palette_sprites=(),
    full_sprites=(),
    icon: str | Path | Image.Image | bytes | None = None,
    icon_side: int = 160,
    icon_dither: bool = False,
    icon_palette: list[int] | list[tuple[int, int]] | None = None,
    sounds: list[str] | None = None,
    ids_path: str | Path | None = None,
) -> list[tuple[int, str]]:
    """Write the complete beta asset container for one app directory.

    Produces <app_dir>/index.bin, <app_dir>/art/packed/*.{raw,pal} and the
    kind-aware ids header (default <app_dir>/src/<app_name>_ids.h). Record
    index in index.bin == runtime asset id, in this fixed order:

      0. ("zero", SPRITE)     - reserved empty sprite, 48-byte zero header
      1. one PAL per palette group, named "1", "2", ...; when the icon is
         palette-encoded (`icon_palette` given) its dedicated pal follows as
         the next numeric name
      2. icon assets (only when `icon` is given): ico_idle SPRITE (RAW565
         icon at icon_side², or the palette-encoded blob when `icon_palette`
         is given) + "ico"/"ahover" MAPs pointing at it - the launcher looks
         these up by name within the first EXT_MAX_DESCS descriptors
         (mirrors app_hulk's videopack.build_icon_assets)
      3. every palette sprite, header patched from legacy to beta layout
         (Pidx -> pal ASSET id, Seq -> next-frame asset id for _NN chains)
      4. every full-color sprite, RAW565-encoded at its target size
      5. one SOUND per mp3 (payload stays in sound/assets/, nothing written)

    Arguments:
      palettes:        {legacy_pidx: [rgb565, ...]} or
                       {legacy_pidx: [(rgb565, alpha8), ...]} - keyed by
                       whatever Pidx values the legacy sprite headers
                       actually carry. Whether a group's .pal is written in
                       the plain or the alpha (spread) format is NOT this
                       argument's call: it follows the OCT_FLAG_ALPHA bit of
                       the sprites that reference the group, because the two
                       are one decision in the engine (see build_pal). The
                       alphas are simply dropped for a group whose sprites
                       are opaque, and default to 255 when a caller passes
                       the bare-rgb565 form for a group that has the flag.
      palette_sprites: iterable of (name, legacy_blob) or
                       (name, legacy_blob, extra_flags) - 48-byte legacy
                       octBmp_t + opaque payload, as read from the current
                       packer's output containers. extra_flags (default 0)
                       ORs OCT_FLAG_* bits into the beta Flags byte, which
                       is how manifest flags.fullsize/additive/bg reach a
                       palette sprite's header.
      full_sprites:    iterable of (name, png_path_or_image, (w, h), flags)
                       or (..., dither) - flags WITHOUT OCT_FLAG_RAW565
                       (ORed in automatically); dither (default False) runs
                       the RGB565 conversion through Floyd-Steinberg error
                       diffusion (see to_rgb565).
      icon:            source image for the launcher icon, or None. With
                       `icon_palette` set it is instead the icon's
                       pre-encoded LEGACY palette-sprite blob (bytes, 48-byte
                       legacy octBmp_t + payload, as pack_codec.pack_sprite
                       returns) - the palette-icon tiers.
      icon_side:       full-color icon target side (square). Ignored for a
                       palette icon: its dimensions live in the blob header.
      icon_dither:     full-color icon only - Floyd-Steinberg dithering,
                       exactly like a full sprite's dither flag.
      icon_palette:    the palette icon's OWN colors ([rgb565, ...] or
                       [(rgb565, alpha8), ...], same rule as `palettes`).
                       Emitted as a dedicated KIND_PAL record (next numeric
                       name after the palette groups) that ico_idle's Pidx
                       points at. FULLSIZE is derived from the blob dimensions:
                       a side over 120 draws 1:1 (240 tier), 120 and under
                       draws at x2 (cheap tier).
      sounds:          mp3 basenames; None scans <app_dir>/sound/assets/.

    Legacy PSD maps are NOT emitted: their embedded bmp indices are legacy
    enum values, meaningless in the beta asset-id space.

    Returns the records written (same shape read_index_bin returns).
    """
    app_dir = Path(app_dir)
    palettes = dict(palettes or {})
    # normalize (name, blob) / (name, blob, extra_flags) to 3-tuples
    palette_sprites = [(t[0], t[1], t[2] if len(t) > 2 else 0)
                       for t in palette_sprites]
    # normalize (name, image, size, flags) / (..., dither) to 5-tuples
    full_sprites = [(t[0], t[1], t[2], t[3], t[4] if len(t) > 4 else False)
                    for t in full_sprites]

    if icon_palette is not None and not isinstance(icon, (bytes, bytearray)):
        raise TypeError(
            "icon_palette means the icon is a pre-encoded legacy "
            "palette-sprite blob (bytes), but icon is "
            f"{type(icon).__name__} - encode the PNG through "
            "pack_codec first (see pack.py's palette-icon path)")
    if isinstance(icon, (bytes, bytearray)):
        if icon_palette is None:
            raise TypeError("a bytes icon (palette-encoded blob) needs its "
                            "icon_palette colors")
        if len(icon) < BMP_SIZE:
            raise ValueError(f"palette icon blob is {len(icon)} bytes, "
                             f"needs at least {BMP_SIZE}")

    if sounds is None:
        snd_dir = app_dir / "sound" / "assets"
        sounds = sorted(p.stem for p in snd_dir.glob("*.mp3")) if snd_dir.is_dir() else []

    # ── plan the id space first: record index == asset id ──────────────────
    records: list[tuple[int, str]] = [(KIND_SPRITE, "zero")]

    pal_asset_id: dict[int, int] = {}
    for n, legacy_pidx in enumerate(sorted(palettes), start=1):
        pal_asset_id[legacy_pidx] = len(records)
        records.append((KIND_PAL, str(n)))

    icon_pal_id = None
    if icon is not None and icon_palette is not None:
        # the palette icon's dedicated pal: next numeric name in the row
        icon_pal_id = len(records)
        records.append((KIND_PAL, str(len(pal_asset_id) + 1)))

    ico_idle_id = None
    if icon is not None:
        ico_idle_id = len(records)
        records.append((KIND_SPRITE, "ico_idle"))
        records.append((KIND_MAP, "ico"))
        records.append((KIND_MAP, "ahover"))
        if len(records) > EXT_MAX_DESCS:
            raise ValueError(
                f"icon assets reach id {len(records) - 1}, past the "
                f"{EXT_MAX_DESCS} descriptors the launcher can see")

    sprite_ids: dict[str, int] = {}
    for name, _blob, _extra in palette_sprites:
        sprite_ids[name] = len(records)
        records.append((KIND_SPRITE, name))
    for name, _image, _size, _flags, _dither in full_sprites:
        sprite_ids[name] = len(records)
        records.append((KIND_SPRITE, name))

    for name in sounds:
        records.append((KIND_SOUND, name))

    # sprites and maps share one on-disk namespace (art/packed/<name>.raw)
    raw_names = [n for k, n in records if k in (KIND_SPRITE, KIND_MAP)]
    dupes = {n for n in raw_names if raw_names.count(n) > 1}
    if dupes:
        raise ValueError(
            f"asset name collision in art/packed/: {', '.join(sorted(dupes))}")
    build_index_bin(records)   # validates count <= ASSETS_CAP and name lengths early

    seq = _seq_chain(sprite_ids)

    # ── write payloads ──────────────────────────────────────────────────────
    packed_dir = app_dir / "art" / "packed"
    packed_dir.mkdir(parents=True, exist_ok=True)

    # rate=0 keeps the reserved record all-zero, matching the real toolchain's
    # 48-byte pure-zero zero.raw (the rate default of 1 would set byte 45)
    _write_raw(packed_dir / "zero.raw", build_bmp_header(w=0, h=0, flags=0, rate=0))

    # A group's .pal format is decided by its sprites' OCT_FLAG_ALPHA bit, not
    # by whether the palette happens to hold a non-opaque entry: utils.exe sets
    # the flag per group from pooled anti-aliasing, and several corpus groups
    # (cubetext_hi_*, main*) do have semi-transparent pixels yet stay opaque.
    # Emitting the wrong form is not a rounding error -- OCT_BLEND_alpha would
    # read a plain word's RED channel as alpha, and OCT_BLEND_opaque would
    # write a spread word's green-less low half straight to the framebuffer.
    pal_wants_alpha: dict[int, bool] = {}
    for _name, blob, extra in palette_sprites:
        legacy_pidx = blob[HDR_OFF_LEGACY_PIDX]
        has_alpha = bool((blob[HDR_OFF_FLAGS] | extra) & OCT_FLAG_ALPHA)
        pal_wants_alpha[legacy_pidx] = \
            pal_wants_alpha.get(legacy_pidx, False) or has_alpha

    for legacy_pidx, asset_id in pal_asset_id.items():
        _kind, pal_name = records[asset_id]
        colors, alphas = split_pal_entries(palettes[legacy_pidx])
        spread = pal_wants_alpha.get(legacy_pidx, False)
        (packed_dir / f"{pal_name}.pal").write_bytes(
            build_pal(colors, alphas if spread else None))

    if icon is not None:
        if icon_pal_id is not None:
            # palette-icon tiers: dedicated pal + header patched to beta
            # layout with Pidx -> the icon's own pal asset id. FULLSIZE by
            # blob dimensions: over 120 is the 1:1 (240) tier, at or under
            # 120 is the cheap x2-upscale tier.
            _kind, icon_pal_name = records[icon_pal_id]
            icon_colors, icon_alphas = split_pal_entries(icon_palette)
            (packed_dir / f"{icon_pal_name}.pal").write_bytes(
                build_pal(icon_colors,
                          icon_alphas if icon[HDR_OFF_FLAGS] & OCT_FLAG_ALPHA
                          else None))
            icon_w, icon_h = struct.unpack_from("<hh", icon, 36)
            fullsize = OCT_FLAG_FULLSIZE if max(icon_w, icon_h) > 120 else 0
            _write_raw(packed_dir / "ico_idle.raw",
                       patch_palette_sprite(bytes(icon), pal_id=icon_pal_id,
                                            extra_flags=fullsize))
        else:
            icon_w = icon_h = icon_side
            texels = _load_rgb565(icon, icon_side, dither=icon_dither)
            _write_raw(packed_dir / "ico_idle.raw",
                       build_raw565_sprite(texels, icon_side, icon_side,
                                           flags=OCT_FLAG_FULLSIZE))
        # both maps point at the same static sprite (Seq=0 stops the chain
        # walk, so the icon just holds either way), but ahover is the hover
        # ANIMATION map and the real toolchain packs it looped (PLACE_LOOPED,
        # see golden app_hulk ahover.raw) while ico stays static
        _write_raw(packed_dir / "ico.raw",
                   build_map(ico_idle_id, icon_w, icon_h))
        _write_raw(packed_dir / "ahover.raw",
                   build_map(ico_idle_id, icon_w, icon_h, looped=True))

    for name, blob, extra_flags in palette_sprites:
        if len(blob) < BMP_SIZE:
            raise ValueError(f"sprite '{name}': blob is {len(blob)} bytes, "
                             f"needs at least {BMP_SIZE}")
        legacy_pidx = blob[45]                     # legacy header: Pidx @45
        pal_id = pal_asset_id.get(legacy_pidx)
        if pal_id is None:
            if not pal_asset_id:
                raise ValueError(f"sprite '{name}' needs a palette "
                                 f"but no palette groups were provided")
            # Mirror the encoder's palettes.get(pidx, first) fallback.
            # Ordering assumption: all current palette sources (grouped
            # build, single-palette build, load_palette_for_encoding) build
            # their dicts in ascending-pidx order, so the encode-side
            # "first-inserted" fallback coincides with min-key ONLY under
            # that assumption; a source inserting out of order would make
            # this substitution diverge from what the encoder actually used.
            fallback_pidx = min(pal_asset_id)
            pal_id = pal_asset_id[fallback_pidx]
            print(f"  WARNING: sprite '{name}' carries legacy palette index "
                  f"{legacy_pidx}, which has no palette group here - "
                  f"substituting palette group {fallback_pidx} "
                  f"(PAL asset id {pal_id})")
        _write_raw(packed_dir / f"{name}.raw",
                   patch_palette_sprite(blob, pal_id=pal_id,
                                        seq_id=seq.get(name, 0),
                                        extra_flags=extra_flags))

    for name, image, (w, h), flags, dither in full_sprites:
        texels = _load_rgb565(image, (w, h), dither=dither)
        _write_raw(packed_dir / f"{name}.raw",
                   build_raw565_sprite(texels, w, h, flags=flags,
                                       seq=seq.get(name, 0)))

    # ── index.bin + ids header ──────────────────────────────────────────────
    (app_dir / "index.bin").write_bytes(build_index_bin(records))

    ids_file = Path(ids_path) if ids_path else app_dir / "src" / f"{app_name}_ids.h"
    ids_file.parent.mkdir(parents=True, exist_ok=True)
    ids_file.write_text(generate_beta_ids_h(records), encoding="ascii")

    return records


# ─────────────────────────────────────────────────────────────────────────────
# .oct pack assembly (pure-python replacement for the simulator's
# SIM_build_pack, octavios/sim/src/sim.h)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_c_int(token: str) -> int | None:
    """Parse a C integer literal ('102', '0xDF...', with u/U/l/L suffixes)."""
    m = re.fullmatch(r"(0[xX][0-9a-fA-F]+|\d+)[uUlL]*", token)
    return int(m.group(1), 0) if m else None


def _parse_int_expr(text: str, define: str) -> int:
    """Evaluate a `#define` value that is an OR of int literals and the
    APP_CATEGORY_*/OCT_CAT_* macros (the only expressions app.h files use).
    Parens are transparent because `|` is the sole operator."""
    total = 0
    for term in text.replace("(", " ").replace(")", " ").split("|"):
        term = term.strip()
        if not term:
            raise ValueError(f"{define}: empty term in '{text}'")
        value = _parse_c_int(term)
        if value is None:
            value = _CATEGORY_MACROS.get(term)
        if value is None:
            raise ValueError(f"{define}: unknown token '{term}' in '{text}' - "
                             f"use an integer or an APP_CATEGORY_*/OCT_CAT_* macro")
        total |= value
    return total


def read_app_defines(app_h: str | Path) -> dict:
    """Extract the pack-header defines from an app's src/app.h.

    Returns only the keys actually present: title (str), guid1, app_version,
    categories, colors (ints). Mirrors videopack.py's read_app_guid but for
    the whole define set the pack header needs. Reads with utf-8-sig because
    real app.h files carry a BOM.
    """
    text = Path(app_h).read_text(encoding="utf-8-sig")
    out: dict = {}

    def value_of(name: str) -> str | None:
        m = re.search(rf"^\s*#\s*define\s+{name}\s+(.+)$", text, re.M)
        if not m:
            return None
        return m.group(1).split("//", 1)[0].strip()

    title = value_of("APP_TITLE")
    if title is not None:
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', title)
        if not m:
            raise ValueError(f"APP_TITLE is not a plain string literal: {title}")
        out["title"] = m.group(1)

    for define, key in (("APP_GUID1", "guid1"), ("APP_VERSION", "app_version"),
                        ("APP_CATEGORIES", "categories"), ("APP_COLORS", "colors")):
        raw = value_of(define)
        if raw is not None:
            out[key] = _parse_int_expr(raw, define)
    return out


def extract_gnu_build_id(elf: bytes) -> bytes | None:
    """20-byte GNU build-id (NT_GNU_BUILD_ID) of a little-endian ELF32 image,
    or None. Mirrors the sim's SIM_extract_gnu_build_id
    (octavios/sim/src/oct_elf_build_id.h): malformed input yields None."""
    if len(elf) < 52 or elf[:4] != b"\x7fELF" or elf[4] != 1 or elf[5] != 1:
        return None
    sh_off, = struct.unpack_from("<I", elf, 32)
    sh_entsize, sh_num = struct.unpack_from("<HH", elf, 46)
    if sh_num == 0 or sh_entsize < 40 or sh_off + sh_num * sh_entsize > len(elf):
        return None
    for i in range(sh_num):
        shdr = sh_off + i * sh_entsize
        if struct.unpack_from("<I", elf, shdr + 4)[0] != 7:    # SHT_NOTE
            continue
        note_off, = struct.unpack_from("<I", elf, shdr + 16)
        note_size, = struct.unpack_from("<I", elf, shdr + 20)
        note_end = note_off + note_size
        if note_end > len(elf):
            continue
        pos = note_off
        while pos + 12 <= note_end:
            namesz, descsz, type_ = struct.unpack_from("<III", elf, pos)
            name_at = pos + 12
            desc_at = name_at + ((namesz + 3) & ~3)
            nxt = desc_at + ((descsz + 3) & ~3)
            if nxt > note_end:
                break
            if (namesz == 4 and type_ == 3 and descsz == 20
                    and elf[name_at:name_at + 4] == b"GNU\0"):
                return elf[desc_at:desc_at + 20]
            pos = nxt
    return None


def _asset_payload_path(app_dir: Path, kind: int, name: str) -> Path:
    if kind == KIND_SOUND:
        return app_dir / "sound" / "assets" / f"{name}.mp3"
    if kind == KIND_PAL:
        return app_dir / "art" / "packed" / f"{name}.pal"
    if kind in (KIND_SPRITE, KIND_MAP):
        return app_dir / "art" / "packed" / f"{name}.raw"
    raise ValueError(f"index.bin has unknown asset kind {kind} for '{name}'")


def build_oct(app_dir: str | Path, code_bin: str | Path, out_path: str | Path,
              *, title: str | None = None, guid1: int | None = None,
              app_version: int | None = None, categories: int | None = None,
              colors: int | None = None) -> Path:
    """Assemble the cube-loadable .oct pack, byte-identical to the beta
    simulator's SIM_build_pack except BuildDateTime (the sim stamps wall-clock
    time; this builder pins 0 so the same inputs always produce the same
    bytes).

    Layout (engine/oct_pack.h): 232-byte octPackHeader_t, then one 84-byte
    octAssetDesc_t per index.bin record (record index == asset id; sprite
    descs embed the payload's leading octBmp_t so the engine can cull without
    the disk), then the payloads 4-byte aligned in id order, then the ARM
    code as the final chunk. CRC32 over bytes 8..Size lands at offset 4.
    BuildId is the GNU build-id of the ELF sitting next to `code_bin`
    (out/<app>.elf), zeros when absent - same telemetry contract as the sim.

    `title`/`guid1`/`app_version`/`categories`/`colors` fall back to the
    APP_* defines in <app_dir>/src/app.h when omitted; guid1 and app_version
    have no safe default, so missing both ways raises ValueError.
    """
    app_dir = Path(app_dir)
    code_bin = Path(code_bin)
    out_path = Path(out_path)

    index_path = app_dir / "index.bin"
    if not index_path.is_file():
        raise ValueError(f"no {index_path} - pack the assets first")
    records = read_index_bin(index_path)
    if not records:
        raise ValueError(f"{index_path} holds no assets")
    if len(records) > ASSETS_CAP:
        raise ValueError(f"{index_path} claims {len(records)} assets, "
                         f"over OCT_ASSETS_CAP ({ASSETS_CAP})")

    if None in (title, guid1, app_version, categories, colors):
        app_h = app_dir / "src" / "app.h"
        defines = read_app_defines(app_h) if app_h.is_file() else {}
        if title is None:
            # the sim compiles without APP_TITLE too (catalog falls back to
            # the pack name), so an absent define is a zero title, not an error
            title = defines.get("title", "")
        if guid1 is None:
            guid1 = defines.get("guid1")
            if guid1 is None:
                raise ValueError(f"no APP_GUID1 in {app_h} and no guid1 given")
        if app_version is None:
            app_version = defines.get("app_version")
            if app_version is None:
                raise ValueError(f"no APP_VERSION in {app_h} and no app_version given")
        if categories is None:
            categories = defines.get("categories", 0)
        if colors is None:
            colors = defines.get("colors", 0)

    if not code_bin.is_file():
        raise ValueError(f"ARM module not found: {code_bin} - build it first "
                         f"(cmake -G Ninja -S <octavios>/apps -B out && cmake --build out)")
    code = code_bin.read_bytes()
    if not code:
        raise ValueError(f"{code_bin} is empty - the ARM build produced no code")

    # ── descriptor table + payloads, id order, 4-byte aligned ───────────────
    descs = bytearray(OCT_DESC_SIZE * len(records))
    payloads = bytearray()
    cursor = (OCT_HEADER_SIZE + len(descs) + 3) & ~3
    for i, (kind, name) in enumerate(records):
        src = _asset_payload_path(app_dir, kind, name)
        if not src.is_file():
            raise ValueError(f"asset '{name}' (id {i}): no payload at {src}")
        payload = src.read_bytes()
        if not payload:
            raise ValueError(f"asset '{name}' (id {i}): {src} is empty")

        desc_off = i * OCT_DESC_SIZE
        descs[desc_off:desc_off + len(name)] = name.encode("ascii")
        struct.pack_into("<II", descs, desc_off + 24, cursor, len(payload))
        descs[desc_off + 32] = kind                 # Flags/ExtId/Reserved stay 0
        if kind == KIND_SPRITE:
            # the sim memcpys sizeof(octBmp_t) from its zeroed pack buffer,
            # so a shorter payload embeds zero-padded - mirror that
            bmp = payload[:BMP_SIZE].ljust(BMP_SIZE, b"\0")
            descs[desc_off + 36:desc_off + 36 + BMP_SIZE] = bmp

        padding = (-len(payload)) & 3
        payloads += payload + b"\0" * padding
        cursor += len(payload) + padding

    code_offset = cursor
    total = code_offset + len(code)

    # ── octPackHeader_t ──────────────────────────────────────────────────────
    header = bytearray(OCT_HEADER_SIZE)
    header[0:4] = OCT_PACK_MAGIC
    struct.pack_into("<I", header, 8, OCT_PACK_FORMAT_SUPPORTED)
    struct.pack_into("<Q", header, 16, guid1)
    struct.pack_into("<I", header, 32, app_version)
    struct.pack_into("<I", header, 36, OCT_ENGINE_VERSION_CURRENT)
    struct.pack_into("<I", header, 44, categories)
    # BuildDateTime (offset 48) stays 0: deterministic output, unlike the sim
    struct.pack_into("<I", header, 52, total)
    encoded_title = title.encode("utf-8")[:SOFTWARE_NAME_MAXLEN - 1]
    header[56:56 + len(encoded_title)] = encoded_title
    struct.pack_into("<I", header, 136, colors)
    struct.pack_into("<II", header, 140, code_offset, len(code))
    struct.pack_into("<II", header, 148, OCT_HEADER_SIZE, len(records))
    # SoundDescs mirrors AssetDescs, SoundCount 0: one unified table, sounds
    # are found by Kind (see SIM_build_pack)
    struct.pack_into("<II", header, 156, OCT_HEADER_SIZE, 0)

    elf_path = code_bin.with_suffix(".elf")
    if elf_path.is_file():
        build_id = extract_gnu_build_id(elf_path.read_bytes())
        if build_id:
            header[164:184] = build_id

    pack = bytearray(total)
    pack[0:OCT_HEADER_SIZE] = header
    pack[OCT_HEADER_SIZE:OCT_HEADER_SIZE + len(descs)] = descs
    payload_offset = (OCT_HEADER_SIZE + len(descs) + 3) & ~3
    pack[payload_offset:payload_offset + len(payloads)] = payloads
    pack[code_offset:total] = code
    struct.pack_into("<I", pack, 4, zlib.crc32(bytes(pack[8:total])) & 0xFFFFFFFF)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pack)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="beta asset-container tools (see module docstring)")
    parser.add_argument("--build-oct", action="store_true", required=True,
                        help="assemble the cube-loadable .oct from a packed app dir")
    parser.add_argument("--app-dir", required=True, type=Path,
                        help="app folder holding index.bin, art/packed, sound/assets")
    parser.add_argument("--code", required=True, type=Path,
                        help="ARM module binary, out/<app>.bin")
    parser.add_argument("--out", required=True, type=Path,
                        help="destination .oct path")
    parser.add_argument("--title", help="pack title (default: APP_TITLE from src/app.h)")
    parser.add_argument("--guid", help="pack Guid1 (default: APP_GUID1 from src/app.h)")
    parser.add_argument("--version", type=int,
                        help="app version (default: APP_VERSION from src/app.h)")
    parser.add_argument("--categories", type=lambda s: int(s, 0),
                        help="category bitmask (default: APP_CATEGORIES from src/app.h)")
    parser.add_argument("--colors", type=lambda s: int(s, 0),
                        help="Colors field (default: APP_COLORS from src/app.h)")
    args = parser.parse_args(argv)

    try:
        path = build_oct(args.app_dir, args.code, args.out,
                         title=args.title,
                         guid1=int(args.guid, 0) if args.guid else None,
                         app_version=args.version,
                         categories=args.categories,
                         colors=args.colors)
    except (ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    size = path.stat().st_size
    code_size = Path(args.code).stat().st_size
    print(f"{path}: {size} bytes (assets + {code_size} bytes ARM code)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
