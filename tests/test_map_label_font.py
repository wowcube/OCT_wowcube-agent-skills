"""A ``!font`` suffix makes a map place a LABEL; without it no text renders.

Ground truth, ``OCT_ladybug``. Its map PSDs carry 64 text anchors whose layer
names end in ``!font`` / ``!font2`` (``$score!font2`` in ``hud.psd``,
``$pat!font`` in ``win.psd``). The shipped legacy container has exactly 64 map
places with a non-zero ``octPlace_t.Label``, and the per-map, per-index counts
line up one-for-one with the PSD suffixes::

    map               PSD !font layers      legacy Label histogram
    complete          font1 x6, font2 x7    {1: 6, 2: 7}
    game_over         font1 x5, font2 x3    {1: 5, 2: 3}
    hud               font2 x18             {2: 18}
    splash            font1 x2, font2 x3    {1: 2, 2: 3}
    splash_wo_saves   font1 x5, font2 x1    {1: 5, 2: 1}
    win               font1 x14             {1: 14}
                                     total  64 == 64

Why it matters: ``OCT_add_map`` copies the field verbatim
(``spr->Label = plc->Label``, oct_scene.h) and ``OCT_label_set`` returns
immediately on a falsy ``Label``. A place that loses its font index is not a
mis-styled label, it is not a label at all -- the app's ``SetLabelValue`` /
``Cache_SetLabelByPlane`` calls silently draw nothing. Before this rule the
packer parsed ``!rate`` but had no notion of ``!font``, so all 272 ladybug map
places shipped with ``Label = 0`` and every HUD / score / game-over string was
invisible on device.

Label places also store their ALIGNMENT in the ``Rate`` byte
(``spr->Data2 = plc->Rate``, consumed as ``OCT_add_label``'s ``align``). All 64
legacy label places use ``Rate = 0`` (``ALIGN_CENTER``), so a label must NOT
pick up the ``OCT_PLACE_RATE_DEFAULT`` of 1 that ordinary places get -- that
would silently left-align every string in the app.
"""
from __future__ import annotations

import struct

from config import OCT_PLACE_LABEL_SHIFT
from pack_psd import LayerName, csv_to_octplace, parse_layer_font, psl_to_octplace

PLACE = 28


def _fields(blob: bytes, i: int = 0):
    off = 8 + i * PLACE
    bmp, = struct.unpack_from("<h", blob, off + 16)
    bits, = struct.unpack_from("<H", blob, off + 20)
    rate, = struct.unpack_from("<b", blob, off + 23)
    return {
        "bmp": bmp,
        "bits": bits,
        "label": (bits >> OCT_PLACE_LABEL_SHIFT) & 3,
        "rate": rate,
    }


def _psl_rec(name: str, **over) -> dict:
    rec = dict(name=name, x=10, y=20, w=2, h=2, layer_mark=0, side=0,
               center_x=0, center_y=0, pivot_x=0, pivot_y=0,
               pivot_w=0, pivot_h=0, group_name="", type_name="",
               number=0, rate=0)
    rec.update(over)
    return rec


# ── suffix parsing ───────────────────────────────────────────────────────────

def test_bare_font_suffix_means_font_1():
    # win.psd spells its 14 anchors "$pat!font" with no digit, and every one of
    # them is Label == 1 in the legacy container.
    assert parse_layer_font("$pat!font") == 1
    assert LayerName.parse("$pat!font").font == 1


def test_numbered_font_suffix_is_the_font_index():
    assert parse_layer_font("$score!font2") == 2
    assert parse_layer_font("$time_bonus!font2") == 2
    assert parse_layer_font("$x!font3") == 3


def test_no_font_suffix_is_not_a_label():
    assert parse_layer_font("$score") is None
    assert parse_layer_font("hero") is None
    assert parse_layer_font("hero%type&group#tag") is None


def test_font_suffix_does_not_disturb_the_other_suffixes():
    ln = LayerName.parse("$score!font2")
    assert ln.obj_name == "score", "the NAME_ anchor must survive"
    assert ln.font == 2
    assert ln.rate is None, "!font is not !rate"


def test_rate_suffix_is_still_not_a_font():
    ln = LayerName.parse("flame_00!rate3")
    assert ln.rate == 3
    assert ln.font is None


# ── the place bitfield ───────────────────────────────────────────────────────

def test_place_carries_the_font_index_in_the_label_bits():
    # octPlace_t bitfield: Twistable:1 Looped:1 Hidden:1 Paused:1 PingPong:1
    #                      Label:2 FlipH:1 FlipV:1 Rot:2   -> Label at bit 5
    blob = psl_to_octplace([_psl_rec("$score")], {}, {}, {},
                           name_map={"score": 4},
                           layer_meta={("$score", 10, 20, 2, 2):
                                       ("score", "", 2)})
    f = _fields(blob)
    assert f["label"] == 2
    assert f["bits"] == 0x40, "legacy hud label places are exactly 0x40"


def test_font_1_label_places_match_the_legacy_bit_pattern():
    blob = psl_to_octplace([_psl_rec("$pat")], {}, {}, {},
                           name_map={"pat": 9},
                           layer_meta={("$pat", 10, 20, 2, 2): ("pat", "", 1)})
    assert _fields(blob)["bits"] == 0x20, "legacy win label places are 0x20"


def test_label_place_aligns_center_not_the_rate_default():
    # Rate is the label's ALIGN (OCT_add_map: spr->Data2 = plc->Rate).
    # All 64 legacy label places use 0 == ALIGN_CENTER.
    blob = psl_to_octplace([_psl_rec("$score")], {}, {}, {},
                           name_map={"score": 4},
                           layer_meta={("$score", 10, 20, 2, 2):
                                       ("score", "", 2)})
    assert _fields(blob)["rate"] == 0


def test_ordinary_place_keeps_the_rate_default_and_no_label():
    blob = psl_to_octplace([_psl_rec("hero", w=32, h=32)], {"hero": 7}, {}, {})
    f = _fields(blob)
    assert f["label"] == 0
    assert f["rate"] == 1, "non-label places still get OCT_PLACE_RATE_DEFAULT"


def test_label_place_points_at_no_artwork():
    # Legacy: all 64 label places have BmpIdx == 0.
    blob = psl_to_octplace([_psl_rec("$score")], {"$score": 3}, {}, {},
                           name_map={"score": 4},
                           layer_meta={("$score", 10, 20, 2, 2):
                                       ("score", "", 2)})
    assert _fields(blob)["bmp"] == 0


def test_csv_path_sets_the_label_too():
    rec = dict(raw_name="$score!font2", sprite_name="$score",
               png_name="$score", obj_name="score", tag_name="",
               type_name="", group_name="", number=0, rate=0,
               x=10, y=20, w=2, h=2, font=2)
    blob = csv_to_octplace([rec], {}, {}, {}, name_map={"score": 4})
    f = _fields(blob)
    assert f["label"] == 2
    assert f["rate"] == 0


def test_out_of_range_font_index_is_refused():
    # OCT_add_label hard-terminates outside [1..3]; never ship such a place.
    import pytest
    with pytest.raises(ValueError, match="font"):
        psl_to_octplace([_psl_rec("$score")], {}, {}, {},
                        name_map={"score": 4},
                        layer_meta={("$score", 10, 20, 2, 2):
                                    ("score", "", 7)})
