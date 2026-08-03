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
RAW565_PLAIN, RAW565_RLE = 0, 1


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


def build_index_bin(records: list[tuple[int, str]]) -> bytes:
    if len(records) > ASSETS_CAP:
        raise SystemExit(f"{len(records)} assets exceeds OCT_ASSETS_CAP ({ASSETS_CAP})")
    out = [struct.pack("<i", len(records))]
    for kind, name in records:
        encoded = name.encode("ascii")
        if len(encoded) >= ASSET_NAME_MAXLEN:
            raise SystemExit(f"asset name '{name}' exceeds {ASSET_NAME_MAXLEN - 1} chars")
        out.append(INDEX_RECORD.pack(kind, encoded))
    return b"".join(out)


def read_index_bin(path: Path) -> list[tuple[int, str]]:
    blob = Path(path).read_bytes()
    count, = struct.unpack_from("<i", blob, 0)
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
    out = []
    for off in range(0, len(blob), 4):
        a, b = struct.unpack_from("<HH", blob, off)
        assert a == b, f"pal entry mismatch at {off}: {a:04x} != {b:04x}"
        out.append(a)
    return out


def build_map(bmp_id: int, w: int, h: int, *, x=120.0, y=120.0, looped=False) -> bytes:
    place = b"".join((
        struct.pack("<ff", x, y),
        struct.pack("<I", 0),                       # Tags
        struct.pack("<hh", w, h),
        struct.pack("<h", bmp_id),
        struct.pack("<h", 0),                       # Number
        struct.pack("<H", (1 << 1) if looped else 0),  # PLACE_LOOPED
        struct.pack("<bb", 1, 0),                   # Side, Rate
        struct.pack("<BBBB", 0, 0, 0, 0),           # Name, Group, Parent, Type
    ))
    assert len(place) == 28
    return struct.pack("<ii", 1, 1) + place
