"""Font glyph metrics parity with the legacy ``psd.exe`` + ``utils.exe`` chain.

A font glyph is not an ordinary sprite. ``oct_scene.h::OCT_label_set`` lays
text out straight off the glyph's ``octBmp_t``::

    cx += zoom * bmp->Bw;                        // pen advance
    cy -= bmp->Bh;                               // newline
    OCT_add(..., cx + 2 * bmp->PivotX, cy, ...)  // left bearing

so ``Bw`` carries the advance, ``Bh`` the line height and ``PivotX`` the left
bearing (doubled at the call site to cancel the renderer's ``-PivotX`` shift).
Packed with the sprite defaults instead — pivot ``(w-0.5, h-0.5)``, ``Bw = 0``
— every glyph anchors at its own bottom-right corner and the pen never
advances, which is exactly the "all text collapsed into one blob" artefact
seen on a real cube.

The rule, derived (not guessed) by pairing all 282 font descriptors of the
shipped legacy ``app_ladybug.oct`` against ``OCT_ladybug/art/font_{1,2,3}.fnt``
and confirmed to reproduce every one of them with zero residual::

    PivotX = xoffset
    PivotY = base - yoffset
    Bw     = xadvance
    Bh     = lineHeight
    Bx = By = 0

Not scaled by the FULLSIZE draw zoom: the engine applies ``zoom`` itself, and
reads ``zoom = 1`` off the FULLSIZE bit every glyph carries.

The numbers below are transcribed from those two read-only, gitignored corpora
(``.fnt`` metrics on the left, shipped ``.oct`` descriptor on the right) so the
formula cannot silently regress without the corpus present.
"""
from __future__ import annotations

import struct

import pytest

from config import (
    HDR_OFF_BBOX,
    HDR_OFF_PIVOT_X,
    HDR_OFF_PIVOT_Y,
    PSL_FONT_ADVANCE_OFFSET,
    PSL_FONT_LINEHEIGHT_OFFSET,
    PSL_FONT_PIVOT_X_OFFSET,
    PSL_FONT_PIVOT_Y_OFFSET,
    PSL_HEADER_SIZE,
    PSL_RATE_OFFSET,
    PSL_RECORD_SIZE,
    PSL_TYPE_FONT,
    PSL_XYWH_OFFSET,
)
from pack_codec import build_header, patch_font_metrics
from pack_psd import derive_font_glyph_metrics, export_font_python, parse_psl


# ─────────────────────────────────────────────────────────────────────────────
# Golden fixture: 14 glyphs from the OCT_ladybug corpus
#
#   name, font, base, lineHeight,
#   .fnt (w, h, xoffset, yoffset, xadvance),
#   shipped octBmp_t (PivotX, PivotY, Bw, Bh)
#
# Chosen for spread: negative / zero / positive xoffset, a comma sitting far
# below the cap line (yoffset 25 of base 31), an ascender poking above the
# baseline, and all three font sizes.
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_GLYPHS: list[tuple[str, int, int, int,
                          tuple[int, int, int, int, int],
                          tuple[float, float, float, float]]] = [
    ("font_1_00033", 1, 31, 45, (8, 21, -1, 10, 9),   (-1.0, 21.0,  9.0, 45.0)),
    ("font_1_00044", 1, 31, 45, (9, 9, -2, 25, 8),    (-2.0,  6.0,  8.0, 45.0)),
    ("font_1_00065", 1, 31, 45, (23, 21, -2, 10, 21), (-2.0, 21.0, 21.0, 45.0)),
    ("font_1_00103", 1, 31, 45, (18, 23, -1, 15, 19), (-1.0, 16.0, 19.0, 45.0)),
    ("font_1_00112", 1, 31, 45, (19, 22, -1, 15, 19), (-1.0, 16.0, 19.0, 45.0)),
    ("font_1_00126", 1, 31, 45, (16, 6, -1, 19, 16),  (-1.0, 12.0, 16.0, 45.0)),
    ("font_2_00036", 2, 24, 35, (15, 22, 0, 5, 15),   ( 0.0, 19.0, 15.0, 35.0)),
    ("font_2_00048", 2, 24, 35, (14, 18, 1, 7, 16),   ( 1.0, 17.0, 16.0, 35.0)),
    ("font_2_00087", 2, 24, 35, (19, 17, 0, 7, 19),   ( 0.0, 17.0, 19.0, 35.0)),
    ("font_2_00121", 2, 24, 35, (14, 17, 0, 12, 14),  ( 0.0, 12.0, 14.0, 35.0)),
    ("font_3_00038", 3, 17, 25, (12, 13, 0, 5, 12),   ( 0.0, 12.0, 12.0, 25.0)),
    ("font_3_00074", 3, 17, 25, (10, 13, 0, 5, 11),   ( 0.0, 12.0, 11.0, 25.0)),
    ("font_3_00106", 3, 17, 25, (5, 15, -1, 5, 5),    (-1.0, 12.0,  5.0, 25.0)),
    ("font_3_00125", 3, 17, 25, (7, 16, 0, 4, 7),     ( 0.0, 13.0,  7.0, 25.0)),
]

# Two glyphs of a *different* font (rogue_escape_vibe, base 42 / lineHeight 60)
# whose values are pinned from a legacy-toolchain ``font_1.psl``. They guard
# against a formula that happens to fit only ladybug's three fonts.
GOLDEN_GLYPHS_OTHER_FONT = [
    ("font_1_00033", 42, 60, (7, 28, 2, 14, 11),  (2.0, 28.0, 11.0, 60.0)),
    ("font_1_00035", 42, 60, (24, 25, 1, 16, 27), (1.0, 26.0, 27.0, 60.0)),
]


def _char(w: int, h: int, xoff: int, yoff: int, xadv: int,
          cid: int = 33, x: int = 0, y: int = 0) -> dict:
    return {'id': cid, 'x': x, 'y': y, 'w': w, 'h': h,
            'xoff': xoff, 'yoff': yoff, 'xadvance': xadv, 'page': 0}


@pytest.mark.parametrize("name,_font,base,line_h,fnt,golden", GOLDEN_GLYPHS,
                         ids=[g[0] for g in GOLDEN_GLYPHS])
def test_glyph_metrics_match_the_shipped_ladybug_descriptors(
        name, _font, base, line_h, fnt, golden):
    w, h, xoff, yoff, xadv = fnt
    got = derive_font_glyph_metrics(
        _char(w, h, xoff, yoff, xadv),
        {'base': base, 'lineHeight': line_h})
    assert got == golden


@pytest.mark.parametrize("name,base,line_h,fnt,golden", GOLDEN_GLYPHS_OTHER_FONT,
                         ids=[f"{g[0]}@60" for g in GOLDEN_GLYPHS_OTHER_FONT])
def test_glyph_metrics_generalise_beyond_the_ladybug_fonts(
        name, base, line_h, fnt, golden):
    w, h, xoff, yoff, xadv = fnt
    got = derive_font_glyph_metrics(
        _char(w, h, xoff, yoff, xadv),
        {'base': base, 'lineHeight': line_h})
    assert got == golden


def test_pivot_is_not_the_own_rect_fallback():
    """The regression this pins down: `,` must not anchor bottom-right.

    ``font_1_00044`` is 9x21 in the atlas but sits 25 px below the cap line;
    the sprite default would give (8.5, 8.5) and a zero advance.
    """
    px, py, bw, bh = derive_font_glyph_metrics(
        _char(9, 9, -2, 25, 8), {'base': 31, 'lineHeight': 45})
    assert (px, py) != (8.5, 8.5)
    assert (px, py, bw, bh) == (-2.0, 6.0, 8.0, 45.0)


def test_metrics_reach_the_octbmp_header():
    """build_header must place the metrics where the engine reads them."""
    px, py, bw, bh = derive_font_glyph_metrics(
        _char(8, 21, -1, 10, 9), {'base': 31, 'lineHeight': 45})
    hdr = build_header(8, 21, 8, 8, pidx=1, flags=3,
                       pivot_x=px, pivot_y=py, bw=bw, bh=bh)
    assert struct.unpack_from('<f', hdr, HDR_OFF_PIVOT_X)[0] == -1.0
    assert struct.unpack_from('<f', hdr, HDR_OFF_PIVOT_Y)[0] == 21.0
    # Bx, By stay 0; Bw is the advance and Bh the line height
    assert struct.unpack_from('<4f', hdr, HDR_OFF_BBOX) == (0.0, 0.0, 9.0, 45.0)


def test_patch_font_metrics_overwrites_a_stale_reused_header():
    """A packed/ header from before this fix must not survive a repack."""
    stale = build_header(8, 21, 8, 8, pidx=1, flags=3)          # (7.5, 20.5), Bw 0
    assert struct.unpack_from('<ff', stale, HDR_OFF_PIVOT_X) == (7.5, 20.5)
    fixed = patch_font_metrics(stale, -1.0, 21.0, 9.0, 45.0)
    assert struct.unpack_from('<ff', fixed, HDR_OFF_PIVOT_X) == (-1.0, 21.0)
    assert struct.unpack_from('<4f', fixed, HDR_OFF_BBOX) == (0.0, 0.0, 9.0, 45.0)
    # nothing else moved
    assert fixed[8 + 4 + 16:] == stale[8 + 4 + 16:]
    assert fixed[:4] == stale[:4]


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: .fnt -> exporter -> font PSL -> packer
#
# The record layout is pinned byte-for-byte against a legacy ``psd.exe``
# ``font_1.psl`` (rogue_escape_vibe/assets/exported): type 3 header, the atlas
# rect at PSL_XYWH_OFFSET, xadvance/lineHeight as int32 at 76/80, the two pivot
# floats at 112/116, "letter" in the rate slot, everything else zero.
# ─────────────────────────────────────────────────────────────────────────────

def _build_fnt(tmp_path, chars, base: int, line_h: int, atlas_side: int = 64):
    """Write a minimal BMFont binary + its atlas PNG. Returns the .fnt path."""
    from PIL import Image

    blocks = b''
    common = struct.pack('<HHHHHBBBBB', line_h, base, atlas_side, atlas_side,
                         1, 0, 0, 0, 0, 0)
    blocks += struct.pack('<BI', 2, len(common)) + common

    pages = b'atlas_0.png\x00'
    blocks += struct.pack('<BI', 3, len(pages)) + pages

    chars_blob = b''.join(
        struct.pack('<IHHHHhhhBB', c['id'], c['x'], c['y'], c['w'], c['h'],
                    c['xoff'], c['yoff'], c['xadvance'], 0, 15)
        for c in chars)
    blocks += struct.pack('<BI', 4, len(chars_blob)) + chars_blob

    fnt = tmp_path / "font_1.fnt"
    fnt.write_bytes(b'BMF\x03' + blocks)
    Image.new('RGBA', (atlas_side, atlas_side),
              (255, 0, 0, 255)).save(tmp_path / "atlas_0.png")
    return str(fnt)


def _psl_record(blob: bytes, i: int) -> bytes:
    base = PSL_HEADER_SIZE + i * PSL_RECORD_SIZE
    return blob[base:base + PSL_RECORD_SIZE]


def test_export_font_writes_a_legacy_shaped_font_psl(tmp_path):
    chars = [_char(8, 21, -1, 10, 9, cid=33, x=142, y=91),
             _char(9, 9, -2, 25, 8, cid=44, x=7, y=200)]
    fnt = _build_fnt(tmp_path, chars, base=31, line_h=45, atlas_side=256)
    out = tmp_path / "exported"
    out.mkdir()

    assert export_font_python(fnt, str(out)) == 2

    blob = (out / "font_1.psl").read_bytes()
    assert struct.unpack_from('<4I', blob, 0) == (PSL_TYPE_FONT, 0, 0, 2)
    assert len(blob) == PSL_HEADER_SIZE + 2 * PSL_RECORD_SIZE

    rec = _psl_record(blob, 0)
    assert rec[:24].split(b'\x00')[0] == b'font_1_00033'
    assert struct.unpack_from('<4i', rec, PSL_XYWH_OFFSET) == (142, 91, 8, 21)
    assert struct.unpack_from('<i', rec, PSL_FONT_ADVANCE_OFFSET)[0] == 9
    assert struct.unpack_from('<i', rec, PSL_FONT_LINEHEIGHT_OFFSET)[0] == 45
    assert struct.unpack_from('<f', rec, PSL_FONT_PIVOT_X_OFFSET)[0] == -1.0
    assert struct.unpack_from('<f', rec, PSL_FONT_PIVOT_Y_OFFSET)[0] == 21.0
    assert rec[PSL_RATE_OFFSET:PSL_RATE_OFFSET + 7] == b'letter\x00'
    # the layer-mark / side / ~pivot-marker blocks are a PSD notion; a glyph
    # has none of them and psd.exe leaves them zeroed
    assert rec[40:PSL_FONT_ADVANCE_OFFSET] == bytes(36)
    assert rec[84:PSL_FONT_PIVOT_X_OFFSET] == bytes(28)


def test_export_font_skips_space_and_zero_area_glyphs(tmp_path):
    """psd.exe emits 94 records for a 95-char font: id 32 has no bitmap."""
    chars = [_char(0, 0, 0, 0, 12, cid=32),
             _char(8, 21, -1, 10, 9, cid=33),
             _char(4, 4, 0, 0, 4, cid=31)]     # below the printable range
    fnt = _build_fnt(tmp_path, chars, base=31, line_h=45)
    out = tmp_path / "exported"
    out.mkdir()

    assert export_font_python(fnt, str(out)) == 1
    blob = (out / "font_1.psl").read_bytes()
    assert struct.unpack_from('<4I', blob, 0)[3] == 1
    assert _psl_record(blob, 0)[:24].split(b'\x00')[0] == b'font_1_00033'


def test_font_psl_without_a_common_block_is_refused(tmp_path):
    """No baseline means no derivable pivot; fail loudly instead of shipping
    collapsed text."""
    from PIL import Image

    chars_blob = struct.pack('<IHHHHhhhBB', 33, 0, 0, 8, 21, -1, 10, 9, 0, 15)
    fnt = tmp_path / "font_1.fnt"
    fnt.write_bytes(b'BMF\x03'
                    + struct.pack('<BI', 3, 12) + b'atlas_0.png\x00'
                    + struct.pack('<BI', 4, len(chars_blob)) + chars_blob)
    Image.new('RGBA', (64, 64)).save(tmp_path / "atlas_0.png")
    out = tmp_path / "exported"
    out.mkdir()

    assert export_font_python(str(fnt), str(out)) is None
    assert not (out / "font_1.psl").exists()


def test_packer_loads_the_metrics_back_out_of_the_psl(tmp_path):
    from pack import _load_font_metrics_from_psls

    chars = [_char(8, 21, -1, 10, 9, cid=33, x=142, y=91),
             _char(9, 9, -2, 25, 8, cid=44, x=7, y=200)]
    fnt = _build_fnt(tmp_path, chars, base=31, line_h=45, atlas_side=256)
    out = tmp_path / "exported"
    out.mkdir()
    export_font_python(fnt, str(out))

    assert _load_font_metrics_from_psls(str(out)) == {
        'font_1_00033': (-1.0, 21.0, 9.0, 45.0),
        'font_1_00044': (-2.0, 6.0, 8.0, 45.0),
    }


def test_asset_psls_expose_no_font_fields(tmp_path):
    """The font metrics live at offsets that mean something else in an
    Assets/Map PSL, so they must not leak into non-font records."""
    from config import PSL_TYPE_ASSET

    p = tmp_path / "hud.psl"
    rec = bytearray(PSL_RECORD_SIZE)
    rec[:4] = b'spr\x00'
    p.write_bytes(struct.pack('<4I', PSL_TYPE_ASSET, 0, 0, 1) + bytes(rec))

    psl_type, records = parse_psl(str(p))
    assert psl_type == PSL_TYPE_ASSET
    assert 'font_pivot_x' not in records[0]
