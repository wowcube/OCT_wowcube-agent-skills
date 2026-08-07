"""The complete ``!marker`` grammar, and where a sprite's ``Rate`` comes from.

Three defects of the same shape have now been found in this parser (``$name``
declarations, ``!font``, ``!rate``): a token the PSD layer name carries, that
``psd.exe`` faithfully hands on, and that our packer silently dropped between
the exporter and the header. This file closes the class -- it pins the WHOLE
vocabulary, marker by marker, including the ones that are deliberately inert.

Ground truth is the reference ``utils.exe`` itself, driven with synthetic PSLs
(one record per token, everything else held constant) and read back out of the
``.raw`` it produced:

    Assets mode -- only ``rateN`` changes anything. ``pause``, ``font*``,
    ``label*``, ``pingpong``, ``hide`` and unknown tokens leave the octBmp_t
    byte-identical to an empty marker slot.

    Map mode -- octPlace_t.Flags, measured per token:

        (none)      0x0000     font  / label   0x0020 (Label 1, Rate 0)
        twistable   0x0001     font2 / label2  0x0040 (Label 2, Rate 0)
        loop        0x0002     font3 / label3  0x0060 (Label 3, Rate 0)
        once        0x0000     fliph           0x0080
        hide        0x0004     flipv           0x0100
        pause       0x0008     ccw             0x0200
        pingpong    0x0010     cwcw            0x0400
        rateN       Rate = N   cw              0x0600

Rate itself has TWO sources and the marker is the minority one. ``psd.exe``
folds the Photoshop layer sheet colour into bits 8..15 of the PSL LayerMark,
and ``utils.exe`` reads it back as ``Rate = colour + 1``. Packing a PSL whose
eight records carry marks 0xFF000000..0xFF000700 returns rates 1..8, and the
record that also carries ``rate10`` returns 10 -- the marker wins.

In ``OCT_ladybug`` that accounts for every non-default rate in the shipped
container: 36 sprites at 4 (yellow-labelled layers: ``backtwist_*``, ``fly_*``,
``lb0_*``, ``lb2_*``, ``poisonbug_*``), 30 at 5 (green: ``eat_*``, ``hit_*``,
``lb1_*``, ``lb3_*``, ``rebound``, ``rotate_*``) and only 4 at 10 from an
actual ``!rate10`` (``pat_00``, ``pat_01``, ``twist_00``, ``twist_01``).
``oct_scene.h`` makes the frame delay ``bmp->Rate * spr->FrameRate``, so
dropping this played every ladybug animation 4-10x too fast.
"""
from __future__ import annotations

import struct

import pytest

from config import (
    LAYER_MARK_BASE,
    MAP_MARKER_LABEL,
    MAP_MARKER_PLACE_FLAGS,
    OCT_PLACE_LABEL_SHIFT,
    PSL_MARKER_CELL_SIZE,
    PSL_MARKER_MAX,
    PSL_RATE_OFFSET,
    PSL_RECORD_SIZE,
    PlaceFlag,
    layer_mark_of,
    rate_from_layer_mark,
)
from pack_psd import (
    LayerName,
    SpriteRecord,
    _write_records_psl,
    parse_layer_markers,
    parse_psl,
    psl_to_octplace,
)

PLACE = 28


# ── the layer-mark rate rule ────────────────────────────────────────────────

@pytest.mark.parametrize("colour,rate", [(0, 1), (1, 2), (2, 3), (3, 4),
                                         (4, 5), (5, 6), (6, 7), (7, 8)])
def test_sheet_colour_is_rate_minus_one(colour, rate):
    """utils.exe returned exactly these eight rates for marks 0xFF0000NN00."""
    mark = layer_mark_of(colour)
    assert mark & 0xFFFFFFFF == LAYER_MARK_BASE | (colour << 8)
    assert rate_from_layer_mark(mark) == rate


def test_unlabelled_layer_keeps_the_default_rate():
    """0xFF000000 is what psd.exe writes for a layer with no colour swatch --
    all 452 records of the OCT_get_started corpus carry it, and all 452 of its
    golden .raw sprites carry Rate 1."""
    assert rate_from_layer_mark(-16777216) == 1


class _Blocks:
    def __init__(self, value):
        self._value = value

    def get_data(self, key):
        assert key == b'lclr'
        return self._value


class _Layer:
    def __init__(self, blocks):
        self.tagged_blocks = blocks


@pytest.mark.parametrize("raw,expected", [
    (None, 0),          # no colour swatch -> psd-tools has no lclr block
    (0, 0),
    (3, 3),             # yellow, ladybug's rate-4 groups
    (4, 4),             # green, ladybug's rate-5 groups
    ((5,), 5),          # some psd-tools versions wrap it in a 1-tuple
    ("nonsense", 0),
])
def test_sheet_colour_is_read_out_of_the_lclr_block(raw, expected):
    from pack_psd import layer_sheet_color
    assert layer_sheet_color(_Layer(_Blocks(raw))) == expected


def test_a_layer_without_tagged_blocks_is_unlabelled():
    from pack_psd import layer_sheet_color
    assert layer_sheet_color(_Layer(None)) == 0


def test_the_colour_lives_in_the_second_byte_not_the_first():
    """A regression guard with teeth: marks 0xFF000001..07 (colour in the LOW
    byte) came back with Rate 1 from utils.exe -- the field is at bits 8..15."""
    assert rate_from_layer_mark(LAYER_MARK_BASE | 0x07 - (1 << 32)) == 1
    assert rate_from_layer_mark(layer_mark_of(7)) == 8


# ── the marker list on a layer name ─────────────────────────────────────────

def test_every_bang_token_is_captured_in_source_order():
    assert parse_layer_markers("winscreen_00!rate5!pingpong") == ("rate5",
                                                                  "pingpong")
    assert parse_layer_markers("$score!font2") == ("font2",)
    assert parse_layer_markers("lb0_00!full_size") == ("full_size",)
    assert parse_layer_markers("plain_00") == ()


def test_markers_stop_at_the_next_metadata_separator():
    ln = LayerName.parse("pat_01!rate10&icons")
    assert ln.markers == ("rate10",)
    assert ln.group_name == "icons"
    assert ln.rate == 10


def test_marker_list_is_capped_at_the_slot_capacity():
    """The slot is PSL_RATE_SIZE bytes of PSL_MARKER_CELL_SIZE-byte cells."""
    ln = LayerName.parse("x!loop!pingpong!hide!fliph")
    assert len(ln.markers) == PSL_MARKER_MAX == 2
    assert ln.markers == ("loop", "pingpong")


# ── the PSL marker slot ─────────────────────────────────────────────────────

def _record(name: str, markers=(), rate: int = 0, colour: int = 0,
            **over) -> SpriteRecord:
    kw = dict(id=1, name=name, group_id=0, kind=0, bmp="", x=0, y=0,
              w=4, h=4, layer_mark=layer_mark_of(colour), side=-1,
              side_cx=0, side_cy=0, png_name=name, is_marker=False,
              marker_number=0, sprite_number=0, type_name="", group_name="",
              rate=rate, markers=tuple(markers))
    kw.update(over)
    return SpriteRecord(**kw)


def test_marker_slot_is_one_token_per_cell(tmp_path):
    """psd.exe puts 'rate5' at +0 and 'pingpong' at +16 for
    win.psd's `winscreen_00!rate5!pingpong` -- read straight off the golden
    PSL, not inferred."""
    psl = tmp_path / "m.psl"
    _write_records_psl(str(psl), [_record("winscreen_00",
                                          ("rate5", "pingpong"), rate=5)], 1)
    blob = psl.read_bytes()
    slot = blob[16 + PSL_RATE_OFFSET:16 + PSL_RATE_OFFSET + 32]
    assert slot[:6] == b"rate5\0"
    assert slot[PSL_MARKER_CELL_SIZE:PSL_MARKER_CELL_SIZE + 9] == b"pingpong\0"


def test_psl_roundtrips_markers_and_both_rate_sources(tmp_path):
    psl = tmp_path / "m.psl"
    _write_records_psl(str(psl), [
        _record("plain", colour=0),
        _record("yellow", colour=3),
        _record("green_but_marked", ("rate10",), rate=10, colour=4),
    ], 1)
    _type, recs = parse_psl(str(psl))
    by = {r["name"]: r for r in recs}
    # `rate` stays "the explicit marker, or 0"; `mark_rate` is the colour rule
    assert (by["plain"]["rate"], by["plain"]["mark_rate"]) == (0, 1)
    assert (by["yellow"]["rate"], by["yellow"]["mark_rate"]) == (0, 4)
    assert by["green_but_marked"]["rate"] == 10
    assert by["green_but_marked"]["mark_rate"] == 5
    assert by["green_but_marked"]["markers"] == ("rate10",)


def test_a_record_written_from_rate_alone_still_reads_back(tmp_path):
    """Callers that build a SpriteRecord by hand (no markers tuple) must not
    lose the rate -- the writer synthesises the `rateN` cell."""
    psl = tmp_path / "m.psl"
    _write_records_psl(str(psl), [_record("legacy", rate=7)], 1)
    _type, recs = parse_psl(str(psl))
    assert recs[0]["rate"] == 7
    assert recs[0]["markers"] == ("rate7",)


def test_record_size_is_untouched_by_the_marker_cells(tmp_path):
    psl = tmp_path / "m.psl"
    _write_records_psl(str(psl), [_record("a", ("loop", "pingpong"))], 1)
    assert len(psl.read_bytes()) == 16 + PSL_RECORD_SIZE


# ── map places: the flag table ──────────────────────────────────────────────

def _place_rec(name: str, markers=(), rate: int = 0, colour: int = 0) -> dict:
    return dict(name=name, x=10, y=20, w=8, h=8,
                layer_mark=layer_mark_of(colour), side=0,
                center_x=0, center_y=0, pivot_x=0, pivot_y=0,
                pivot_w=0, pivot_h=0, group_name="", type_name="",
                number=0, rate=rate, markers=tuple(markers),
                mark_rate=rate_from_layer_mark(layer_mark_of(colour)))


def _place(blob: bytes, i: int = 0):
    off = 8 + i * PLACE
    bits, = struct.unpack_from("<H", blob, off + 20)
    rate, = struct.unpack_from("<b", blob, off + 23)
    return bits, rate


@pytest.mark.parametrize("marker,bits", sorted(MAP_MARKER_PLACE_FLAGS.items()))
def test_map_marker_sets_its_place_bits(marker, bits):
    blob = psl_to_octplace([_place_rec("sprite", (marker,))], {"sprite": 3},
                           {}, {})
    got, _rate = _place(blob)
    assert got & bits == bits
    # nothing else in the low byte should light up (Looped is claimed by the
    # `_00` sequence rule, which this name deliberately avoids)
    assert got == bits


def test_pingpong_and_rate_combine_the_way_ladybug_ships_them():
    """win.psd's `winscreen_00!rate5!pingpong`: the shipped container gives
    that place Flags 0x12 (Looped | PingPong) and Rate 5."""
    blob = psl_to_octplace(
        [_place_rec("winscreen_00", ("rate5", "pingpong"), rate=5)],
        {"winscreen_00": 3}, {}, {})
    assert _place(blob) == (int(PlaceFlag.LOOPED | PlaceFlag.PINGPONG), 5)


@pytest.mark.parametrize("marker,index", sorted(MAP_MARKER_LABEL.items()))
def test_label_markers_carry_the_font_index_and_centre_alignment(marker, index):
    blob = psl_to_octplace([_place_rec("anchor", (marker,))], {"anchor": 3},
                           {}, {})
    bits, rate = _place(blob)
    assert (bits >> OCT_PLACE_LABEL_SHIFT) & 3 == index
    assert rate == 0, "a label place stores ALIGN_CENTER in Rate, not a rate"


def test_place_rate_falls_back_to_the_layer_colour():
    blob = psl_to_octplace([_place_rec("sprite", colour=4)], {"sprite": 3},
                           {}, {})
    assert _place(blob)[1] == 5


def test_an_explicit_rate_marker_beats_the_layer_colour():
    blob = psl_to_octplace(
        [_place_rec("sprite", ("rate10",), rate=10, colour=4)],
        {"sprite": 3}, {}, {})
    assert _place(blob)[1] == 10


# ── the inert half of the vocabulary ────────────────────────────────────────

INERT_MARKERS = ("full_size", "fullsize", "letter", "bogus")


@pytest.mark.parametrize("marker", INERT_MARKERS)
def test_unknown_markers_are_no_ops_for_a_place(marker):
    """utils.exe silently ignores them -- verified for `full_size` (12 ladybug
    layers), `fullsize`, `letter` and a made-up token, all of which produced
    Flags 0x0000 / Rate 1. `!full_size` in particular is a note to the artist:
    the FULLSIZE bit comes from the `<FULLSIZE>` bucket tag, not the name."""
    assert marker not in MAP_MARKER_PLACE_FLAGS
    assert marker not in MAP_MARKER_LABEL
    blob = psl_to_octplace([_place_rec("sprite", (marker,))], {"sprite": 3},
                           {}, {})
    assert _place(blob) == (0, 1)


def test_the_marker_table_is_exactly_what_utils_exe_recognises():
    """A closed enumeration, so a new token cannot be added without a
    measurement. `cw` is in the table even though the string pool only holds
    'ccw' and 'cwcw' -- it is the tail of 'cwcw' and utils.exe matches it,
    returning Rot = 3."""
    assert set(MAP_MARKER_PLACE_FLAGS) == {
        'twistable', 'loop', 'once', 'hide', 'pause', 'pingpong',
        'fliph', 'flipv', 'ccw', 'cwcw', 'cw'}
    assert set(MAP_MARKER_LABEL) == {
        'font', 'font1', 'font2', 'font3',
        'label', 'label1', 'label2', 'label3'}
    assert MAP_MARKER_PLACE_FLAGS['once'] == 0, "'once' is the absence of loop"
