#!/usr/bin/env python3
"""
WowCube Packed Sprite Encoder — PSD/FNT module
==============================================

PSD/FNT-specific I/O split out of pack.py:

  * PSD layer-name parsing (LayerName + the metadata regexes and helpers).
  * SpriteRecord and the per-PSD CSV/PSL writers.
  * PSD export via psd-tools (export_psd_file_python, export_all_python,
    export_psd wrapper) and BMFont export (export_font_python).
  * Map binary parsing (parse_psl, parse_map_csv) and the octPlace_t packer
    (psl_to_octplace, csv_to_octplace, pack_maps).
  * BMP-name index, metadata index maps, and app_ids.h generator.

Imports the codec helpers it needs from ``pack_codec``.
"""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import numpy as np  # noqa: F401  (kept for parity with original module)
    from PIL import Image
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)

from config import (
    BMFONT_BLOCK_CHARS, BMFONT_BLOCK_COMMON, BMFONT_BLOCK_PAGES,
    BMFONT_CHAR_SIZE,
    BMFONT_FIRST_PRINTABLE, BMFONT_MAGIC, BMFONT_VERSION,
    DEFAULT_ASSET_NAME,
    HDR_OFF_HEIGHT, HDR_OFF_PIVOT_X, HDR_OFF_PIVOT_Y, HDR_OFF_WIDTH,
    HEADER_SIZE, LAYER_MARK_COLOR_MASK, MAP_FILENAME_PREFIX,
    MAP_MARKER_LABEL, MAP_MARKER_PLACE_FLAGS, MARKER_RATE_PREFIX,
    NUMBER_FIELD_MASK,
    OCT_PLACE_FONT_MAX, OCT_PLACE_FONT_MIN,
    OCT_PLACE_LABEL_ALIGN_DEFAULT, OCT_PLACE_LABEL_MASK,
    OCT_PLACE_LABEL_SHIFT, OCT_PLACE_RATE_DEFAULT,
    PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME,
    PLACEHOLDER_SPRITE_SIZE, PLACEHOLDER_SPRITE_COLOR,
    PSL_CENTER_X_OFFSET, PSL_CENTER_Y_OFFSET, PSL_GROUP_OFFSET,
    PSL_GROUP_SIZE, PSL_HEADER_SIZE, PSL_LAYERMARK_OFFSET,
    PSL_MARKER_CELL_SIZE, PSL_MARKER_MAX,
    PSL_NAME_OFFSET, PSL_NAME_SIZE, PSL_NUMBER_OFFSET,
    PSL_PIVOT_MARK_ASSET, PSL_PIVOT_MARK_OFFSET, PSL_PIVOT_OFFSET,
    PSL_RATE_OFFSET,
    PSL_RATE_SIZE, PSL_RECORD_SIZE,
    PSL_FONT_ADVANCE_OFFSET, PSL_FONT_LINEHEIGHT_OFFSET,
    PSL_FONT_PIVOT_X_OFFSET, PSL_FONT_PIVOT_Y_OFFSET, PSL_FONT_RATE_STRING,
    PSL_SIDE_OFFSET, PSL_TYPE_ASSET, PSL_TYPE_FONT, PSL_TYPE_MAP,
    PSL_TYPE_OFFSET,
    PSL_TYPE_SIZE, PSL_XYWH_OFFSET, PlaceFlag,
    layer_mark_of, rate_from_layer_mark,
)

from pack_codec import blob_to_packed_png


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
# `!font` marks a text placement and carries its font index. The digit is
# optional: ladybug's win.psd spells all 14 of its anchors `$pat!font`, and the
# legacy container gives every one of them Label == 1, so a bare suffix is
# font 1. `$score!font2` -> 2.
_RE_FONT_SUFFIX  = re.compile(r'!font(\d*)', re.I)
_RE_FONT_INLINE  = re.compile(r'font(\d*)$', re.I)
_RE_SPRITE_NUM   = re.compile(r'=([0-9]+)')
_RE_SEQ_FRAME    = re.compile(r'^(.+?)_(\d{2,})$')
# Every `!token` of a layer name, in source order. `psd.exe` does not know the
# vocabulary -- it copies each token verbatim into the PSL marker slot, and
# `utils.exe` is what interprets them (see config.MAP_MARKER_PLACE_FLAGS).
_RE_MARKERS      = re.compile(r'!([^!%&=$#]*)')


def _norm(s: str) -> str:
    """Normalize a free-form string to a lowercase snake-case identifier."""
    return s.lower().replace('-', '_').replace(' ', '_')


# A layer whose name *starts* with `$` is a NAME DECLARATION, not artwork.
NAME_DECL_PREFIX = '$'


def is_name_declaration(name: str) -> bool:
    """True for a ``$name`` layer: a named anchor, never a sprite.

    ``$`` normally annotates a sprite layer (``hero$player`` is the sprite
    ``hero`` carrying ``NAME_player``). When it is the *first* character
    there is no artwork left in front of it: the layer is a bare placement
    anchor the app looks up by ``NAME_``. ``OCT_ladybug``'s map PSDs hold 26
    of them (``$score!font2``, 2x2 px), and the legacy container proves what
    ``utils.exe`` does with them — ``index.bin`` has 544 records and not one
    name starting with ``$``, while ``src/app_ids.h`` defines
    ``NAME_score``. They register in the NAME_ table and produce no asset.

    Letting one through is not a cosmetic miscount: ``BMP_$score`` is not a
    C identifier, so :func:`pack_beta.generate_beta_ids_h` raises and the
    whole pack dies.
    """
    return name.startswith(NAME_DECL_PREFIX)


# ─────────────────────────────────────────────────────────────────────────────
# PSD layer name parsing
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LayerName:
    """Parsed PSD layer name (with %type / &group / #tag / =num / !marker suffixes)."""
    base: str
    png_name: str
    obj_name: str
    type_name: str
    group_name: str
    tag_name: str
    rate: int | None
    sprite_number: int
    marker_number: int | None
    font: int | None = None
    # every `!token`, in source order and lower-cased, capped at the
    # PSL_MARKER_MAX cells the marker slot holds. `psd.exe` writes exactly
    # these, verbatim; `utils.exe` interprets them.
    markers: tuple[str, ...] = ()

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

        # `!font` with no digit is font 1 (see _RE_FONT_SUFFIX).
        m = _RE_FONT_SUFFIX.search(name)
        font = (int(m.group(1)) if m.group(1) else 1) if m else None

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

        markers = tuple(m.lower() for m in _RE_MARKERS.findall(name)
                        if m)[:PSL_MARKER_MAX]

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
            font=font,
            markers=markers,
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


def parse_layer_font(name: str) -> int | None:
    """Font index from a ``!font`` / ``!fontN`` suffix, else None."""
    return LayerName.parse(name).font


def parse_layer_markers(name: str) -> tuple[str, ...]:
    """Every ``!token`` of a layer name, in source order, lower-cased."""
    return LayerName.parse(name).markers


def layer_sheet_color(layer) -> int:
    """The Photoshop sheet colour of a psd-tools layer (0 when unlabelled).

    ``psd.exe`` folds this into the PSL LayerMark, and ``utils.exe`` turns it
    into the default Rate — see :func:`config.rate_from_layer_mark`. It lives
    in the layer's ``lclr`` tagged block; a layer with no colour swatch has no
    block at all.
    """
    blocks = getattr(layer, 'tagged_blocks', None)
    if blocks is None:
        return 0
    try:
        value = blocks.get_data(b'lclr')
    except Exception:                            # pragma: no cover - psd-tools
        return 0
    if value is None:
        return 0
    # psd-tools hands back either the bare enum/int or a 1-tuple of it
    if isinstance(value, (tuple, list)):
        value = value[0] if value else 0
    try:
        return int(value) & LAYER_MARK_COLOR_MASK
    except (TypeError, ValueError):              # pragma: no cover
        return 0


def parse_marker_number(name: str) -> int | None:
    return LayerName.parse(name).marker_number


def parse_sprite_number(name: str) -> int:
    return LayerName.parse(name).sprite_number


# ─────────────────────────────────────────────────────────────────────────────
# PSD export (pure Python via psd-tools)
# ─────────────────────────────────────────────────────────────────────────────

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
    # every `!token` of the layer name, in source order; written verbatim into
    # the PSL marker slot, one per PSL_MARKER_CELL_SIZE-byte cell
    markers: tuple[str, ...] = ()
    # ~sideN marker size (0 x 0 when the PSD declares no sides).
    side_w: int = 0
    side_h: int = 0
    # Pivot rect: the ~pivot marker blob overlapping this layer, else the
    # layer's own rect.  The packer turns it into the octBmp_t pivot as
    #     pivot = 2 * (rect_centre - layer_xy) - 0.5
    pivot_x: int = 0
    pivot_y: int = 0
    pivot_w: int = 0
    pivot_h: int = 0


def find_pivot_markers(psd) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of every marker blob on the PSD's ``~pivot*`` layer(s).

    psd.exe treats each 4-connected run of non-transparent pixels on a layer
    whose name starts with ``~pivot`` as one pivot marker, and gives a sprite
    layer the marker whose bbox overlaps it.  Returned in raster (top-left
    first) order, in canvas coordinates, as ``(x, y, w, h)``.
    """
    blobs: list[tuple[int, int, int, int]] = []
    for layer in psd:
        if not layer.name.startswith('~pivot'):
            continue
        try:
            img = layer.composite()
        except Exception as e:                      # pragma: no cover - psd-tools
            print(f"    WARNING: failed to composite '{layer.name}': {e}")
            continue
        if img is None:
            continue
        alpha = np.array(img.convert('RGBA'))[:, :, 3] > 0
        ys, xs = np.nonzero(alpha)
        remaining = set(zip(ys.tolist(), xs.tolist()))
        ox, oy = layer.left, layer.top
        for seed in sorted(remaining):
            if seed not in remaining:
                continue
            remaining.discard(seed)
            stack = [seed]
            min_y = max_y = seed[0]
            min_x = max_x = seed[1]
            while stack:
                cy, cx = stack.pop()
                if cy < min_y: min_y = cy
                if cy > max_y: max_y = cy
                if cx < min_x: min_x = cx
                if cx > max_x: max_x = cx
                for nb in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                    if nb in remaining:
                        remaining.discard(nb)
                        stack.append(nb)
            blobs.append((min_x + ox, min_y + oy,
                          max_x - min_x + 1, max_y - min_y + 1))
    blobs.sort(key=lambda b: (b[1], b[0]))
    return blobs


def pivot_for_layer(x: int, y: int, w: int, h: int,
                    markers: list[tuple[int, int, int, int]]
                    ) -> tuple[int, int, int, int]:
    """Pivot rect for a layer: the first overlapping marker, else its own rect."""
    for mx, my, mw, mh in markers:
        if _rects_overlap((x, y, w, h), (mx, my, mw, mh)):
            return mx, my, mw, mh
    return x, y, w, h


def _rects_overlap(a: tuple[int, int, int, int],
                   b: tuple[int, int, int, int]) -> bool:
    """Half-open (x, y, w, h) rectangle overlap test."""
    return (a[0] < b[0] + b[2] and a[0] + a[2] > b[0]
            and a[1] < b[1] + b[3] and a[1] + a[3] > b[1])


def nearest_side(x: int, y: int, w: int, h: int,
                 side_centers: dict[int, tuple[int, ...]]) -> int:
    """Return the ~sideN id whose marker is closest to the layer center."""
    cx, cy = x + w / 2.0, y + h / 2.0
    best_side, best_dist = -1, math.inf
    for sn, rect in side_centers.items():
        sx, sy = rect[0], rect[1]
        d = math.hypot(cx - sx, cy - sy)
        if d < best_dist:
            best_dist, best_side = d, sn
    return best_side


def _rects_intersect(r1: tuple[int, int, int, int],
                     r2: tuple[int, int, int, int]) -> bool:
    return r1[0] <= r2[2] and r1[2] >= r2[0] and r1[1] <= r2[3] and r1[3] >= r2[1]


def _write_records_csv(csv_path: str, records: list[SpriteRecord]) -> None:
    with open(csv_path, 'w', newline='') as f:
        f.write('int Id,str Name,int GroupId,int Kind,str Bmp,int X,int Y,'
                'int W,int H,int LayerMark\n')
        for r in records:
            f.write(f'{r.id},"{r.name}",{r.group_id},{r.kind},"{r.bmp}",'
                    f'{r.x},{r.y},{r.w},{r.h},{r.layer_mark}\n')


def _write_records_psl(psl_path: str, records: list[SpriteRecord], psl_type: int) -> None:
    # psd.exe keeps zero-area layers in the CSV but drops them from the PSL.
    records = [r for r in records if r.w > 0 and r.h > 0]
    is_map = psl_type == PSL_TYPE_MAP
    with open(psl_path, 'wb') as f:
        f.write(struct.pack('<4I', psl_type, 0, 0, len(records)))
        for r in records:
            rec_buf = bytearray(PSL_RECORD_SIZE)

            psl_name = '' if r.is_marker else r.png_name
            name_bytes = psl_name.encode('ascii', errors='replace')[:PSL_NAME_SIZE - 1]
            rec_buf[:len(name_bytes)] = name_bytes

            struct.pack_into('<4i', rec_buf, PSL_XYWH_OFFSET, r.x, r.y, r.w, r.h)
            struct.pack_into('<i',  rec_buf, PSL_LAYERMARK_OFFSET, r.layer_mark)
            # side block: id then the ~sideN marker rect (all zero when absent)
            struct.pack_into('<5i', rec_buf, PSL_SIDE_OFFSET,
                             r.side, r.side_cx, r.side_cy, r.side_w, r.side_h)
            # pivot block: only Assets-mode PSLs carry it
            if not is_map:
                struct.pack_into('<i', rec_buf, PSL_PIVOT_MARK_OFFSET,
                                 PSL_PIVOT_MARK_ASSET)
                struct.pack_into('<4i', rec_buf, PSL_PIVOT_OFFSET,
                                 r.pivot_x, r.pivot_y, r.pivot_w, r.pivot_h)

            # Marker slot: psd.exe writes every `!token` of the layer name
            # verbatim, one per PSL_MARKER_CELL_SIZE-byte cell, in source
            # order ("winscreen_00!rate5!pingpong" -> 'rate5' at +0,
            # 'pingpong' at +16). It interprets none of them.
            markers = r.markers
            if not markers and r.rate:
                markers = (f'{MARKER_RATE_PREFIX}{r.rate}',)
            for cell, marker in enumerate(markers[:PSL_MARKER_MAX]):
                token = marker.encode('ascii', errors='replace')[
                    :PSL_MARKER_CELL_SIZE - 1]
                off = PSL_RATE_OFFSET + cell * PSL_MARKER_CELL_SIZE
                rec_buf[off:off + len(token)] = token

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

    # Pass 1a: collect ~sideN marker rects (used by Map-mode PSLs).
    side_centers: dict[int, tuple[int, int, int, int]] = {}
    for layer in psd:
        if layer.name.startswith('~side'):
            try:
                sn = int(layer.name[5:])
                side_centers[sn] = (layer.left, layer.top,
                                    layer.width, layer.height)
            except ValueError:
                pass

    # Pass 1b: collect ~pivot marker blobs (Assets-mode PSLs only — psd.exe
    # leaves the pivot block zeroed in -map mode).
    pivot_markers = [] if is_map else find_pivot_markers(psd)

    types_seen: dict[str, int] = {}
    groups_seen: dict[str, int] = {}
    records: list[SpriteRecord] = []
    fallback_id = 1

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
        side, side_cx, side_cy, side_w, side_h = -1, 0, 0, 0, 0
        if side_centers:
            side = nearest_side(x, y, w, h, side_centers)
            if side in side_centers:
                side_cx, side_cy, side_w, side_h = side_centers[side]

        pivot_x, pivot_y, pivot_w, pivot_h = pivot_for_layer(
            x, y, w, h, pivot_markers)

        # psd.exe writes Photoshop's own layer id + 1 into the CSV Id column.
        psd_layer_id = getattr(layer, 'layer_id', None)
        csv_id = fallback_id if psd_layer_id is None else psd_layer_id + 1

        records.append(SpriteRecord(
            id=csv_id,
            name=name,
            group_id=group_id,
            kind=kind,
            bmp='',
            x=x, y=y, w=w, h=h,
            # The layer's Photoshop colour swatch rides in the mark, and
            # utils.exe reads it back as the default Rate.
            layer_mark=layer_mark_of(layer_sheet_color(layer)),
            side=side,
            side_cx=side_cx, side_cy=side_cy,
            png_name=parsed.png_name,
            is_marker=parsed.is_marker,
            marker_number=parsed.marker_number or 0,
            sprite_number=parsed.sprite_number,
            type_name=parsed.type_name,
            group_name=parsed.group_name,
            rate=parsed.rate or 0,
            markers=parsed.markers,
            side_w=side_w, side_h=side_h,
            pivot_x=pivot_x, pivot_y=pivot_y,
            pivot_w=pivot_w, pivot_h=pivot_h,
        ))
        fallback_id += 1

        # Export PNG (skip markers, name declarations, zero-size,
        # already-exported names).
        # -map PSDs are placement documents: psd.exe emits no PNGs for them,
        # their layers only reference sprites another PSD already exported.
        if not is_map and not parsed.is_marker \
                and not is_name_declaration(parsed.png_name) \
                and w > 0 and h > 0:
            out_png = os.path.join(exported_dir, f"{parsed.png_name}.png")
            if not os.path.exists(out_png):
                try:
                    img = layer.composite()
                    if img is not None:
                        img.convert('RGBA').save(out_png)
                except Exception as e:
                    print(f"    WARNING: failed to composite '{name}': {e}")

    _write_records_csv(os.path.join(exported_dir, f"{stem}.csv"), records)
    psl_type = PSL_TYPE_MAP if is_map else PSL_TYPE_ASSET
    _write_records_psl(os.path.join(exported_dir, f"{stem}.psl"), records, psl_type)

    return records, types_seen, groups_seen


# ─────────────────────────────────────────────────────────────────────────────
# Font (BMFont) export
# ─────────────────────────────────────────────────────────────────────────────

def derive_font_glyph_metrics(ch: dict, common: dict
                              ) -> tuple[float, float, float, float]:
    """BMFont char + `common` block -> octBmp_t (PivotX, PivotY, Bw, Bh).

    The engine treats a glyph descriptor as font metrics, not as a plain
    sprite (``oct_scene.h::OCT_label_set``)::

        cx += zoom * bmp->Bw;                       // pen advance
        cy -= bmp->Bh;                              // newline
        OCT_add(..., cx + 2 * bmp->PivotX, cy, ...) // left bearing

    so ``Bw`` is the advance, ``Bh`` the line height and ``PivotX`` the left
    bearing (doubled at the call site to cancel the renderer's ``-PivotX``
    shift). ``PivotY`` lifts the glyph off the baseline. Hence:

        PivotX = xoffset
        PivotY = base - yoffset
        Bw     = xadvance
        Bh     = lineHeight
        Bx = By = 0

    Reproduces all 282 font glyph descriptors of the shipped legacy
    ``app_ladybug.oct`` with zero residual, and the pivot/advance/lineHeight
    fields of a legacy-toolchain ``font_1.psl``. Note the values are *not*
    scaled by the FULLSIZE draw zoom: the engine applies ``zoom`` itself and
    reads ``zoom = 1`` off the FULLSIZE bit, which every glyph carries.
    """
    return (float(ch['xoff']),
            float(common['base'] - ch['yoff']),
            float(ch['xadvance']),
            float(common['lineHeight']))


def resolve_font_atlas(fnt_path: str, page: int, declared: str) -> str | None:
    """Locate page ``page``'s atlas PNG for a BMFont ``.fnt``.

    The name embedded in the ``.fnt`` pages block is NOT authoritative. It is
    whatever the generating tool happened to write, and it goes stale: ladybug's
    ``art/font_3.fnt`` declares ``font_1_0.png`` while its real atlas
    ``font_3_0.png`` sits beside it. Trusting the declared name silently
    exported all 94 font_3 glyphs as crops of the font_1 atlas — and because
    font_3 is a 25px face indexing into a 45px sheet, its rects landed on the
    inter-glyph padding, so glyphs came out nearly blank ('R' kept 1 ink pixel
    of 120) rather than obviously wrong.

    So resolve by the ``<stem>_<page>.png`` convention first, which is what the
    legacy ``psd.exe`` does (it derives the atlas from the ``.fnt`` filename and
    ignores the embedded name), and fall back to the declared name only when the
    conventional file is absent. Returns None when neither exists.
    """
    fnt_dir = os.path.dirname(fnt_path)
    stem = Path(fnt_path).stem

    conventional = os.path.join(fnt_dir, f"{stem}_{page}.png")
    if os.path.isfile(conventional):
        # A stale page name is a real authoring defect in the .fnt; say so
        # rather than fixing it silently a second time.
        if declared and declared != f"{stem}_{page}.png":
            print(f"    NOTE: {os.path.basename(fnt_path)} page {page} declares "
                  f"{declared!r}; using {stem}_{page}.png (filename convention, "
                  f"matching psd.exe)")
        return conventional

    fallback = os.path.join(fnt_dir, declared) if declared else None
    if fallback and os.path.isfile(fallback):
        return fallback
    return None


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
        common: dict = {}

        while True:
            block_header = f.read(5)
            if len(block_header) < 5:
                break
            block_type, block_size = struct.unpack('<BI', block_header)
            block_data = f.read(block_size)
            if len(block_data) < block_size:
                break

            if block_type == BMFONT_BLOCK_COMMON:
                line_height, base = struct.unpack_from('<HH', block_data, 0)
                common = {'lineHeight': line_height, 'base': base}
            elif block_type == BMFONT_BLOCK_PAGES:
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
    if not common:
        # Without `common` there is no baseline and no line height, so every
        # glyph would silently fall back to a sprite-shaped pivot and the
        # engine's pen would never advance (all text drawn on top of itself).
        print(f"    WARNING: no `common` block in {fnt_path} - "
              f"cannot derive glyph metrics")
        return None

    atlases: dict[int, Image.Image] = {}
    for i, page_file in enumerate(pages):
        atlas_path = resolve_font_atlas(fnt_path, i, page_file)
        if atlas_path is not None:
            atlases[i] = Image.open(atlas_path).convert('RGBA')
        else:
            print(f"    WARNING: atlas not found for page {i} of {fnt_path} "
                  f"(declared {page_file!r})")

    glyphs = [ch for ch in chars
              if ch['w'] > 0 and ch['h'] > 0
              and ch['id'] >= BMFONT_FIRST_PRINTABLE]

    exported_count = 0
    for ch in glyphs:
        atlas = atlases.get(ch['page'])
        if atlas is None:
            continue
        glyph = atlas.crop((ch['x'], ch['y'],
                            ch['x'] + ch['w'], ch['y'] + ch['h']))
        glyph.save(os.path.join(exported_dir, f"{font_stem}_{ch['id']:05d}.png"))
        exported_count += 1

    # Font PSL (type 3), mirroring what `psd.exe <font>.fnt` emits: the atlas
    # rect in the XYWH block, the BMFont metrics the packer turns into
    # octBmp_t.PivotX/PivotY/Bw/Bh, and a "letter" rate slot. The layer-mark,
    # side and ~pivot-marker blocks stay zeroed - a glyph is not a PSD layer,
    # it has no side and no marker rect, and the pivot arrives as a float pair
    # rather than as a rect to be reduced.
    psl_path = os.path.join(exported_dir, f"{font_stem}.psl")
    with open(psl_path, 'wb') as f:
        f.write(struct.pack('<4I', PSL_TYPE_FONT, 0, 0, len(glyphs)))
        for ch in glyphs:
            pivot_x, pivot_y, bw, bh = derive_font_glyph_metrics(ch, common)
            rec_buf = bytearray(PSL_RECORD_SIZE)
            name = f"{font_stem}_{ch['id']:05d}"
            name_bytes = name.encode('ascii', errors='replace')[:PSL_NAME_SIZE - 1]
            rec_buf[:len(name_bytes)] = name_bytes
            struct.pack_into('<4i', rec_buf, PSL_XYWH_OFFSET,
                             ch['x'], ch['y'], ch['w'], ch['h'])
            struct.pack_into('<i', rec_buf, PSL_FONT_ADVANCE_OFFSET, int(bw))
            struct.pack_into('<i', rec_buf, PSL_FONT_LINEHEIGHT_OFFSET, int(bh))
            struct.pack_into('<f', rec_buf, PSL_FONT_PIVOT_X_OFFSET, pivot_x)
            struct.pack_into('<f', rec_buf, PSL_FONT_PIVOT_Y_OFFSET, pivot_y)
            rate_bytes = PSL_FONT_RATE_STRING.encode('ascii')[:PSL_RATE_SIZE - 1]
            rec_buf[PSL_RATE_OFFSET:PSL_RATE_OFFSET + len(rate_bytes)] = rate_bytes
            f.write(rec_buf)

    print(f"    {exported_count} glyphs exported")
    return exported_count


def _ensure_placeholder_sprite(art_dir: str) -> str:
    """Guarantee the reserved `0.png` placeholder exists in art_dir.

    Slot 0 of the BMP enum is hard-aliased to BMP_none by the engine
    (`enum BMP { BMP_none = 0, BMP_0 = 0, ... }`). The packer must fill
    that slot with a real, harmless asset, otherwise the next sprite
    slides into ID 0 and silently corrupts every code site that uses
    BMP_none as the 'no sprite' sentinel.

    Idempotent: a hand-crafted 0.png is preserved if already present;
    if missing, a fresh one is generated from PLACEHOLDER_SPRITE_SIZE
    / PLACEHOLDER_SPRITE_COLOR defined in config.py. Returns the
    absolute path to the placeholder file.
    """
    os.makedirs(art_dir, exist_ok=True)
    zero_path = os.path.join(art_dir, f'{PLACEHOLDER_SPRITE_NAME}.png')
    if not os.path.isfile(zero_path):
        Image.new('RGBA', PLACEHOLDER_SPRITE_SIZE,
                  PLACEHOLDER_SPRITE_COLOR).save(zero_path)
        print(f'  Auto-created reserved placeholder {PLACEHOLDER_SPRITE_NAME}.png '
              f'at {zero_path} (BMP_none/BMP_0 slot)')
    return zero_path


def export_all_python(art_dir: str, exported_dir: str,
                      map_filter=None,
                      asset_names: set[str] | None = None,
                      psd_names: list[str] | None = None,
                      font_sources: list[str] | None = None,
                      ) -> tuple[list[str], list[str]]:
    """Export all PSD and FNT files using psd-tools.

    ``psd_names`` / ``font_sources``, when given, are the exact source list
    declared by the app's ``art/!pack.bat`` (see :mod:`packbat`) and replace
    the ``art/*.psd`` + ``art/fonts/*.fnt`` globs. A PSD the batch file never
    mentions is not part of the pack: ``OCT_get_started`` keeps a stray
    ``map_18_18.psd`` and ``OCT_ladybug`` keeps ``ladybug-assets.psd`` (the
    pre-split original of ``ladybug-assets_1/_2``), neither of which the
    legacy container contains.
    """
    if asset_names is None:
        asset_names = {DEFAULT_ASSET_NAME}

    # Recreate and clean the exported directory
    os.makedirs(exported_dir, exist_ok=True)
    removed_pngs = 0
    for pattern in ('*.png', '*.psl', '*.csv', '*.log'):
        for f in Path(exported_dir).glob(pattern):
            try:
                f.unlink()
                if pattern == '*.png':
                    removed_pngs += 1
            except OSError:
                pass

    # The exported dir is a build product of the PSD/FNT sources in art_dir.
    # If it held PNGs but there is no PSD to re-export, the caller almost
    # certainly pre-placed plain-PNG sprites there and did NOT want --export
    # to destroy them - say so loudly (the pack phase will then fail on the
    # empty palette).
    if removed_pngs and not sorted(Path(art_dir).glob('*.psd')):
        print(f"  WARNING: --export cleaned {removed_pngs} PNG(s) out of "
              f"{exported_dir}/ but {art_dir}/ has no .psd to re-export. "
              f"If those PNGs were your sprites, restore them and re-run "
              f"WITHOUT --export (plain-PNG workflows never need it).")

    # Reserved placeholder: BMP_0 / BMP_none - must always exist in slot 0.
    # Auto-create in art_dir if missing, then copy into exported_dir.
    zero_png = _ensure_placeholder_sprite(art_dir)
    shutil.copy2(zero_png, os.path.join(exported_dir, f'{PLACEHOLDER_SPRITE_NAME}.png'))

    asset_names_out: list[str] = []
    map_names_exported: list[str] = []

    # Fonts. A declared list wins: ladybug ships art/font_1.fnt AND a
    # DIFFERENT art/fonts/font_1.fnt, and !pack.bat names the former.
    if font_sources is not None:
        fnts = [Path(art_dir) / f.replace('\\', '/') for f in font_sources]
        for fnt in fnts:
            if not fnt.is_file():
                print(f"  WARNING: !pack.bat declares font {fnt} - not found")
                continue
            print(f"  Export font: {fnt.name}")
            export_font_python(str(fnt), exported_dir)
    else:
        fonts_dir = os.path.join(art_dir, 'fonts')
        if os.path.isdir(fonts_dir):
            for fnt in sorted(Path(fonts_dir).glob('*.fnt')):
                print(f"  Export font: {fnt.name}")
                export_font_python(str(fnt), exported_dir)

    # PSDs
    psds = sorted(Path(art_dir).glob('*.psd'))
    if psd_names is not None:
        declared = list(psd_names)
        by_stem = {p.stem: p for p in psds}
        missing = [n for n in declared if n not in by_stem]
        for n in missing:
            print(f"  WARNING: !pack.bat declares {n}.psd - not found in {art_dir}")
        skipped = [p.stem for p in psds if p.stem not in set(declared)]
        if skipped:
            print(f"  Not exported (not declared in !pack.bat): "
                  f"{', '.join(skipped)}")
        psds = [by_stem[n] for n in declared if n in by_stem]

    for psd in psds:
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
               map_filter=None, asset_names: set[str] | None = None,
               psd_names: list[str] | None = None,
               font_sources: list[str] | None = None,
               ) -> tuple[list[str], list[str]]:
    """Wrapper: export PSD/FNT into exported_dir using psd-tools."""
    return export_all_python(art_dir, exported_dir, map_filter, asset_names,
                             psd_names=psd_names, font_sources=font_sources)


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
        pivot_x, pivot_y, pivot_w, pivot_h = \
            struct.unpack_from('<4i', rec, PSL_PIVOT_OFFSET)

        group_name = _bytes_to_str_at(rec, PSL_GROUP_OFFSET, PSL_GROUP_SIZE)
        type_name  = _bytes_to_str_at(rec, PSL_TYPE_OFFSET,  PSL_TYPE_SIZE)
        number = struct.unpack_from('<I', rec, PSL_NUMBER_OFFSET)[0]

        # Marker slot: up to PSL_MARKER_MAX tokens, one per
        # PSL_MARKER_CELL_SIZE-byte cell (see _write_records_psl).
        markers = tuple(
            m for m in (
                _bytes_to_str_at(rec,
                                 PSL_RATE_OFFSET + c * PSL_MARKER_CELL_SIZE,
                                 PSL_MARKER_CELL_SIZE).lower()
                for c in range(PSL_MARKER_MAX))
            if m
        )
        rate_val = 0
        for marker in markers:
            if marker.startswith(MARKER_RATE_PREFIX):
                try:
                    rate_val = int(marker[len(MARKER_RATE_PREFIX):])
                except ValueError:
                    rate_val = 0
                break

        parsed = {
            'name': name,
            'x': x, 'y': y, 'w': w, 'h': h,
            'layer_mark': layer_mark,
            'side': side,
            'center_x': center_x, 'center_y': center_y,
            'pivot_x': pivot_x, 'pivot_y': pivot_y,
            'pivot_w': pivot_w, 'pivot_h': pivot_h,
            'group_name': group_name,
            'type_name': type_name,
            'number': number,
            # `rate` stays "the explicit !rateN, or 0" -- callers need to tell
            # a declared rate from the layer-colour default below.
            'rate': rate_val,
            'markers': markers,
            'mark_rate': rate_from_layer_mark(layer_mark),
        }

        # Font PSLs reuse the tail of the record for BMFont metrics; the same
        # offsets mean something else (or nothing) in Assets/Map mode, so they
        # are only surfaced for type 3.
        if psl_type == PSL_TYPE_FONT:
            parsed['font_advance'] = struct.unpack_from(
                '<i', rec, PSL_FONT_ADVANCE_OFFSET)[0]
            parsed['font_lineheight'] = struct.unpack_from(
                '<i', rec, PSL_FONT_LINEHEIGHT_OFFSET)[0]
            parsed['font_pivot_x'] = struct.unpack_from(
                '<f', rec, PSL_FONT_PIVOT_X_OFFSET)[0]
            parsed['font_pivot_y'] = struct.unpack_from(
                '<f', rec, PSL_FONT_PIVOT_Y_OFFSET)[0]

        records.append(parsed)

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

            parsed = LayerName.parse(raw_name)
            records.append({
                'csv_id': int(row[0]),
                'raw_name': raw_name,
                'sprite_name': _norm(base_name),
                'base_name': base_name,
                'png_name': parsed.png_name,
                'obj_name': parsed.obj_name,
                'tag_name': parsed.tag_name,
                'font': parsed.font,
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

    # A `$name.png` on disk is not a sprite (see is_name_declaration): a real
    # psd.exe run may have left one in art/exported/, and CI packs committed
    # exports as-is, so filter here as well as in the exporter.
    if os.path.isdir(packed_dir):
        for f in Path(packed_dir).glob('*.png'):
            if f.stem != PLACEHOLDER_SPRITE_NAME \
                    and not is_name_declaration(f.stem):
                names.add(f.stem)

    if os.path.isdir(exported_dir):
        for f in Path(exported_dir).glob('*.png'):
            stem = f.stem
            if stem != PLACEHOLDER_SPRITE_NAME and not stem.endswith('.csv') \
                    and not is_name_declaration(stem):
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
                   type_idx: int, tags: int = 0) -> bytes:
    """Pack a single octPlace_t (28 bytes)."""
    return b''.join((
        struct.pack('<ff', x, y),
        struct.pack('<I',  tags & 0xFFFFFFFF),              # Tags
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


def _label_bits(font: int, where: str = '') -> int:
    """``!font`` index -> the Label bits of an octPlace_t flags word.

    Refuses an out-of-range index rather than shipping it: OCT_add_label
    asserts ``font_idx`` is in [1..3] and calls OCT_terminate otherwise, so a
    bad suffix would take the app down on the cube instead of here.
    """
    if not (OCT_PLACE_FONT_MIN <= font <= OCT_PLACE_FONT_MAX):
        raise ValueError(
            f"layer {where!r}: !font{font} is out of the [{OCT_PLACE_FONT_MIN}.."
            f"{OCT_PLACE_FONT_MAX}] range the engine accepts "
            f"(OCT_add_label terminates outside it)")
    return (font << OCT_PLACE_LABEL_SHIFT) & OCT_PLACE_LABEL_MASK


def _unpack_layer_meta(entry, name: str) -> tuple[str, str, int | None]:
    """``layer_meta`` lookup -> ``(obj_name, tag_name, font)``.

    Falls back to what the layer name alone still carries when the PSD was
    exported without its CSV sidecar.
    """
    if entry is None:
        parsed = LayerName.parse(name) if name else None
        return (parsed.obj_name if parsed else '', '',
                parsed.font if parsed else None)
    if len(entry) == 2:          # sidecar written before !font was carried
        return entry[0], entry[1], None
    return entry[0], entry[1], entry[2]


def psl_to_octplace(records: list[dict],
                    bmp_index: dict[str, int],
                    type_map: dict[str, int],
                    group_map: dict[str, int],
                    packed_pivots: dict[str, tuple[float, float, int, int]] | None = None,
                    name_map: dict[str, int] | None = None,
                    tag_map: dict[str, int] | None = None,
                    layer_meta: dict[tuple, tuple[str, str]] | None = None,
                    ) -> bytes:
    """Convert parsed PSL records to an octPlace_t binary blob (map payload).

    ``name_map``/``tag_map`` are the ``$names``/``#tags`` index maps from
    :func:`build_metadata_maps`; they fill octPlace_t's ``Name`` byte and
    ``Tags`` word, which is how the app finds a placement at runtime
    (``octObject_t.Name == NAME_score``, ``.Tags & TAG_health2``).

    A ``$name`` layer (see :func:`is_name_declaration`) is an anchor with no
    artwork: its place keeps the rect and the ``Name`` byte but gets
    ``BmpIdx = 0``, matching the legacy container where no ``$`` asset exists.

    ``layer_meta`` maps ``(png_name, x, y, w, h)`` to
    ``(obj_name, tag_name, font)`` recovered from the PSD's own CSV, because
    the PSL record layout we mirror from ``psd.exe`` has slots for the group
    and type suffixes but none for ``$name``/``#tag``/``!font``. Without it
    those fall back to what the PSL name alone can carry (the ``$`` prefix),
    no tags, and no font index.

    A layer carrying ``!font``/``!fontN`` becomes a LABEL place: the font index
    goes into the ``Label`` bits of the flags word and the ``Rate`` byte
    becomes the label's alignment (``ALIGN_CENTER``), not the animation rate.
    """
    if packed_pivots is None:
        packed_pivots = {}
    name_map = name_map or {}
    tag_map = tag_map or {}
    layer_meta = layer_meta or {}

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
        markers = rec.get('markers', ())
        mark_rate = rec.get('mark_rate', OCT_PLACE_RATE_DEFAULT)

        is_layer_marker = (not name and w <= 1 and h <= 1)
        is_decl = is_name_declaration(name)
        bmp_idx = 0 if (is_decl or not name) else bmp_index.get(name, 0)

        obj_name, tag_name, font = _unpack_layer_meta(
            layer_meta.get((name, rec['x'], rec['y'], w, h)), name)
        if rec.get('font') is not None:
            font = rec['font']
        if font is None:
            # The PSL marker slot carries the label marker too, and it is the
            # only place `!label`/`!labelN` (utils.exe's synonym for `!font`)
            # survives -- LayerName only knows the `font` spelling.
            for marker in markers:
                if marker in MAP_MARKER_LABEL:
                    font = MAP_MARKER_LABEL[marker]
                    break
        name_byte = name_map.get(obj_name, 0) if obj_name else 0
        tags = tag_bits(tag_name, tag_map)

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

        # Animation start flag: name ends with "_00" or explicit !rate suffix.
        #
        # Both are PROXIES. utils.exe's actual rule, measured: a place is
        # Looped iff the octBmp_t it references has Seq != 0, i.e. the sprite
        # belongs to any `<base>_NN` group -- a place on eat_03, mid-sequence,
        # comes back Looped too, and an explicit `!rate7` on a lone sprite
        # does NOT. The two proxies happen to agree with it on all 272
        # OCT_ladybug places (every animated place there is a `_00` head), so
        # they are left alone rather than churned without a corpus that can
        # tell the difference.
        flags = 0
        if name and name.endswith('_00'):
            flags |= int(PlaceFlag.LOOPED)
        if rate > 0:
            flags |= int(PlaceFlag.LOOPED)

        # Every other `!marker` the grammar allows. `!pingpong` is the one
        # OCT_ladybug actually uses (win.psd's winscreen_00, place flags 0x12
        # in the shipped container); the rest are here so the table is closed
        # rather than discovered one crash at a time.
        for marker in markers:
            flags |= MAP_MARKER_PLACE_FLAGS.get(marker, 0)

        # No `!rateN`? The Rate is the layer's Photoshop colour swatch + 1,
        # exactly as for a sprite (config.rate_from_layer_mark).
        rate_out = rate if rate > 0 else mark_rate

        # A `!font` layer is a text placement, not artwork: the font index goes
        # into the Label bits and Rate carries the alignment instead.
        if font is not None:
            flags |= _label_bits(font, name)
            rate_out = OCT_PLACE_LABEL_ALIGN_DEFAULT

        if is_layer_marker:
            bmp_idx = type_idx = group_idx = name_byte = 0
            tags = 0
            flags = 0
            rate_out = OCT_PLACE_RATE_DEFAULT

        places.append(_pack_octplace(
            local_x, local_y, w, h, bmp_idx, number,
            flags, sid, rate_out, name_byte, group_idx, 0, type_idx,
            tags=tags,
        ))

    return struct.pack('<ii', 1, len(places)) + b''.join(places)


def csv_to_octplace(csv_records: list[dict],
                    bmp_index: dict[str, int],
                    type_map: dict[str, int],
                    group_map: dict[str, int],
                    name_map: dict[str, int] | None = None,
                    tag_map: dict[str, int] | None = None) -> bytes:
    """Convert parsed CSV records to an octPlace_t blob (map payload, no sides).

    With ``name_map``/``tag_map`` the ``Name`` byte and ``Tags`` word come
    from the layer's own ``$name``/``#tag`` suffixes (same rule as
    :func:`psl_to_octplace`); without them the historical behaviour is kept,
    where ``Name`` is just a running counter.
    """
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

        png_name = rec.get('png_name', sprite_name)
        bmp_idx = 0 if is_name_declaration(png_name) \
            else bmp_index.get(sprite_name, 0)
        type_idx = type_map.get(rec['type_name'], 0) if rec['type_name'] else 0
        group_idx = group_map.get(rec['group_name'], 0) if rec['group_name'] else 0

        if name_map is None:
            name_byte = name_counter & 0xFF
            tags = 0
        else:
            obj = rec.get('obj_name', '')
            name_byte = name_map.get(obj, 0) if obj else 0
            tags = tag_bits(rec.get('tag_name', ''), tag_map or {})

        # A `!font` layer is a label: font index into the Label bits, and Rate
        # carries the alignment rather than an animation rate.
        font = rec.get('font')
        if font is None:
            font = LayerName.parse(raw_name).font
        flags = 0
        rate_out = rec['rate']
        if font is not None:
            flags = _label_bits(font, raw_name)
            rate_out = OCT_PLACE_LABEL_ALIGN_DEFAULT

        places.append(_pack_octplace(
            float(x), float(y), w, h, bmp_idx, rec['number'],
            flags, -1, rate_out, name_byte, group_idx, 0, type_idx,
            tags=tags,
        ))
        name_counter += 1

    return struct.pack('<ii', 1, len(places)) + b''.join(places)


def _csv_layer_meta(csv_path) -> dict[tuple, tuple[str, str, int | None]]:
    """``(png_name, x, y, w, h) -> ($name, #tag, !font)`` from a per-PSD CSV.

    The PSL record layout we mirror from ``psd.exe`` has fixed slots for the
    ``&group`` and ``%type`` suffixes but none for ``$name``, ``#tag`` or
    ``!font``, so a map built from the PSL alone would lose all three. The CSV
    written by the same export carries the raw layer name, and (name, rect)
    identifies the layer in it — that is the sidecar this reads. Returns {}
    when the PSD was exported without ``-log`` (no CSV).

    Losing ``!font`` here is what silenced every ladybug label: the PSL name is
    already split at ``!`` (``$score!font2`` arrives as ``$score``), so this
    sidecar is the only place the font index still exists.
    """
    if csv_path is None or not Path(csv_path).is_file():
        return {}
    meta: dict[tuple, tuple[str, str, int | None]] = {}
    try:
        for rec in parse_map_csv(str(csv_path)):
            key = (rec['png_name'], rec['x'], rec['y'], rec['w'], rec['h'])
            meta.setdefault(key, (rec['obj_name'], rec['tag_name'],
                                  rec.get('font')))
    except Exception:
        return {}
    return meta


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
            layer_meta = _csv_layer_meta(csv_files.get(map_name))
            blob = psl_to_octplace(records, bmp_index, type_map, group_map,
                                   packed_pivots=packed_pivots,
                                   name_map=name_map, tag_map=tag_map,
                                   layer_meta=layer_meta)
        elif has_csv:
            print(f"\n  Map: {map_name} (from CSV, no side conversion)")
            csv_records = parse_map_csv(str(csv_files[map_name]))
            print(f"    CSV: {len(csv_records)} records")
            if not csv_records:
                print("    Skipping (empty CSV)")
                continue
            blob = csv_to_octplace(csv_records, bmp_index, type_map, group_map,
                                   name_map=name_map, tag_map=tag_map)
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
    """Append one ``//label`` + ``const … PREFIX_X = N;`` block.

    Shape measured on the two committed legacy headers
    (``OCT_ladybug/src/app_ids.h``, ``OCT_get_started/art/app_get_started_ids.h``):

      * only ``%types`` gets a ``TYPE_last`` sentinel, and it is emitted even
        when the block is empty (``const uint8_t TYPE_last = 1;`` in
        get_started, which declares no types at all). ``NAME_``/``GROUP_``/
        ``TAG_`` have no sentinel;
      * ``#tags`` is a BITMASK, not a counter: ladybug's four health tags are
        ``TAG_health1 = 1, TAG_health2 = 2, TAG_health3 = 4, TAG_health4 = 8``
        and the type is ``uint32_t``, because the app ORs them into
        ``octObject_t.Tags`` and tests with ``&``. Emitting the 1-based index
        (…= 3, …= 4) as ``uint8_t`` compiles fine and silently makes
        ``TAG_health3`` alias ``TAG_health1|TAG_health2``.
    """
    ctype = 'uint32_t' if prefix == 'TAG' else 'uint8_t'
    lines.append(f'//{label}\n')
    for name, idx in sorted(idx_map.items(), key=lambda x: x[1]):
        value = (1 << (idx - 1)) if prefix == 'TAG' else idx
        lines.append(f'const {ctype} {prefix}_{name} = {value};\n')
    if prefix == 'TYPE':
        last = (max(idx_map.values()) + 1) if idx_map else 1
        lines.append(f'const uint8_t TYPE_last = {last};\n')
    lines.append('\n')


def emit_index_blocks(name_map: dict[str, int], type_map: dict[str, int],
                      group_map: dict[str, int], tag_map: dict[str, int]) -> str:
    """The ``$names``/``%types``/``&groups``/``#tags`` tail of an ids header.

    Shared by the legacy :func:`generate_app_ids_h` and the beta
    ``pack_beta.generate_beta_ids_h`` so the two can never disagree: the beta
    header OVERWRITES the app's committed ``src/<app>_ids.h``, and an app that
    reads ``octObject_t.Name``/``.Type``/``.Tags`` (ladybug does, for its HUD
    labels and health hearts) stops compiling the moment these go missing.
    """
    parts: list[str] = []
    _emit_index_block(parts, 'NAME',  '$names',  name_map)
    _emit_index_block(parts, 'TYPE',  '%types',  type_map)
    _emit_index_block(parts, 'GROUP', '&groups', group_map)
    _emit_index_block(parts, 'TAG',   '#tags',   tag_map)
    return ''.join(parts)


def tag_bits(tag_name: str, tag_map: dict[str, int]) -> int:
    """``TAG_<tag_name>``'s bitmask value, or 0 for an unknown/absent tag."""
    idx = tag_map.get(tag_name, 0) if tag_name else 0
    return (1 << (idx - 1)) if idx > 0 else 0


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

    out_parts.append(emit_index_blocks(name_map, type_map, group_map, tag_map))

    with open(output_path, 'w') as f:
        f.write(''.join(out_parts))

    print(f"\n  Generated {output_path}")
    print(f"    {len(sorted_sprite_names)} sprites, {len(map_names)} maps")
    print(f"    {len(name_map)} names, {len(type_map)} types, "
          f"{len(group_map)} groups, {len(tag_map)} tags")
    return assigned
