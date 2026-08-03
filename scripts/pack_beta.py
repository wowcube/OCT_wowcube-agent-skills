"""Beta (octavios dev) asset-container primitives.

The beta simulator loads an app from:
  <APP_DIR>/index.bin                  - kind-tagged asset manifest; record index == asset id
  <APP_DIR>/art/packed/<name>.raw      - sprites (48B octBmp_t + payload) and maps
  <APP_DIR>/art/packed/<name>.pal      - palettes (4 bytes per color: RGB565 twice)
  <APP_DIR>/sound/assets/<name>.mp3    - sounds (22050 Hz mono CBR 32k)

Struct layouts mirror octavios/engine/oct_types.h + oct_pack.h and are pinned
by tests/test_beta_container.py against golden files packed by the real beta
utils.exe (from the app_hulk example).
"""
from __future__ import annotations

import struct
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

OCT_FLAG_ALPHA = 1 << 0
OCT_FLAG_FULLSIZE = 1 << 1
OCT_FLAG_ADDITIVE = 1 << 2
OCT_FLAG_BG = 1 << 3
OCT_FLAG_RAW565 = 1 << 7
# octBmp_t::Compression sub-format for a RAW565 payload, mirrors engine/oct_consts.h
RAW565_PLAIN, RAW565_RLE = 0, 1

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


def to_rgb565(image, size):
    """Convert a PIL image to little-endian RGB565 texels.

    ``size`` as an int centre-crops the image to a square and resizes to
    that side (videopack's original behaviour); ``size`` as a (w, h) tuple
    resizes straight to exactly w x h. Alpha (or any transparency info) is
    always flattened onto black before conversion, since RGB565 carries no
    alpha channel. Returns ``width * height * 2`` bytes.
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

    pixels = np.asarray(image, dtype=np.uint16)
    red = (pixels[:, :, 0] >> 3) << 11
    green = (pixels[:, :, 1] >> 2) << 5
    blue = pixels[:, :, 2] >> 3

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


def build_pal(colors_rgb565: list[int]) -> bytes:
    # each entry stores the RGB565 value twice (see golden 5.pal)
    return b"".join(struct.pack("<HH", c, c) for c in colors_rgb565)


def read_pal(path: Path) -> list[int]:
    blob = Path(path).read_bytes()
    if len(blob) % 4 != 0:
        raise ValueError(f"{path}: truncated .pal file, {len(blob)} bytes is not a multiple of 4")
    out = []
    for off in range(0, len(blob), 4):
        a, b = struct.unpack_from("<HH", blob, off)
        if a != b:
            raise ValueError(f"pal entry mismatch at {off}: {a:04x} != {b:04x}")
        out.append(a)
    return out


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
