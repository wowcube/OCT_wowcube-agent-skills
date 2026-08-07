"""Where a map place lands, and what number a ``=NN`` layer marker carries.

Both rules were measured by driving the real reference toolchain
(``octavios/utils/psd.exe`` + ``utils.exe``) over the ``OCT_ladybug`` sources
and over synthetic PSDs built by mutating a real one, then reading the bytes
it produced.  Nothing here is inferred from a single app.

──────────────────────────────────────────────────────────────────────────────
1.  ``octPlace_t.X / .Y``
──────────────────────────────────────────────────────────────────────────────

A place is *the sprite's pivot point, measured from the centre of its cube
side, in the engine's 2x (half-pixel) units*::

    place.x =  2 * (layer_x + pivot_local_x - side_centre_x)
    place.y = -2 * (layer_y + pivot_local_y - side_centre_y)

``pivot_local`` is the pivot in sprite-local pixels; the packed ``octBmp_t``
stores it already doubled and biased, ``pivot = 2*pivot_local - 0.5``
(``test_pivot_parity``), so in terms of the stored field::

    place.x =  2 * (layer_x - side_centre_x) + pivot_x + 0.5
    place.y = -2 * (layer_y - side_centre_y) - pivot_y - 0.5

and ``side_centre = side_marker_left + side_marker_width / 2`` — the ``~sideN``
marker's *centre*, not its top-left corner.  A place with no artwork (a layer
marker, a ``$name`` anchor) has ``pivot = 0`` and the same formula applies.

Y is negated because PSD coordinates grow downwards and side space grows up.

Reproduces all 272 map places of ``app_ladybug.oct`` (APP_VERSION 260) with
zero residual on both axes, and both ``OCT_get_started`` map places.

──────────────────────────────────────────────────────────────────────────────
2.  The ``~sideN`` marker rect, as ``psd.exe`` reports it
──────────────────────────────────────────────────────────────────────────────

``psd.exe`` copies the marker layer's rect into the PSL verbatim — *except*
when the layer is exactly 1x1, where it emits a 2x2 rect whose origin is
shifted by a per-side constant.  Measured by rewriting ``~sideN`` rects in a
real map PSD (``complete.psd``) and in ``ico.psd``, then re-running
``psd.exe``; the shift follows the side *index*, not the layer order, and
fires only for 1x1 (1x2, 2x1, 1x3 and 3x1 all pass through untouched).

That single pixel is not cosmetic: it moves the side centre by half a pixel
and every place on that side by one engine unit.  ``OCT_ladybug``'s seven map
PSDs all use 1x1 markers, ``OCT_get_started``'s two use 2x2 ones.

──────────────────────────────────────────────────────────────────────────────
3.  Which side a layer belongs to
──────────────────────────────────────────────────────────────────────────────

``psd.exe`` picks the ``~sideN`` marker nearest the layer's **top-left
corner**, not its centre, measuring to the *normalised* marker origin and
keeping the first marker on a tie.  ``OCT_ladybug``'s ``ico.psd`` is the
discriminating case: its 145x141 icon sits between side 0 and side 1 and
``psd.exe`` files it under side 0, which only the corner rule predicts.

──────────────────────────────────────────────────────────────────────────────
4.  ``=NN`` layer markers
──────────────────────────────────────────────────────────────────────────────

``=NN`` is the layer-name grammar's layer marker: a 1x1 dot whose whole name
is the token.  ``psd.exe`` writes ``NN`` into the PSL record's Number slot and
``utils.exe`` copies it into ``octPlace_t.Number``; the engine reads it in
``OCT_add_map`` as *the draw layer every following place is spawned into*::

    if (BmpIdx == 0 && Name == 0 && Tags == 0 && Type == 0 && Number > 0)
        { layer = Number; continue; }

A marker that arrives with ``Number == 0`` fails that test, so it is not
consumed as a layer mark at all — it becomes a stray invisible sprite and
every place behind it stays on layer 0.  The eleven markers of the
``OCT_ladybug`` maps are pinned below straight out of the v260 container.
"""
from __future__ import annotations

import struct

from config import SIDE_MARKER_1PX_ORIGIN_SHIFT
from pack_psd import (
    LayerName,
    nearest_side,
    psl_to_octplace,
    side_marker_rect,
)

PLACE = 28


def _xy(blob: bytes, i: int = 0) -> tuple[float, float]:
    return struct.unpack_from("<ff", blob, 8 + i * PLACE)


def _number(blob: bytes, i: int = 0) -> int:
    return struct.unpack_from("<h", blob, 8 + i * PLACE + 18)[0]


def _rec(name, x, y, w, h, side, rect, number=0) -> dict:
    """One parsed PSL record, the way :func:`pack_psd.parse_psl` hands it over."""
    return dict(name=name, x=x, y=y, w=w, h=h, layer_mark=0, side=side,
                center_x=rect[0], center_y=rect[1],
                side_w=rect[2], side_h=rect[3],
                pivot_x=0, pivot_y=0, pivot_w=0, pivot_h=0,
                group_name="", type_name="", number=number, rate=0,
                markers=(), mark_rate=1)


# ─────────────────────────────────────────────────────────────────────────────
# Golden places, transcribed from app_ladybug.oct (APP_VERSION 260) together
# with the psd.exe PSL record and the utils.exe packed pivot behind each one.
#
#   map, psl (name, x, y, w, h), side, psd.exe side rect, packed pivot,
#   golden (place.x, place.y)
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_PLACES = [
    # a `=20` layer marker on side 4: no sprite, so pivot 0
    ("complete", ("", 92, 148, 1, 1), 4, (129, 405, 2, 2), (0.0, 0.0),
     (-75.5, 515.5)),
    # a full 120x120 background quadrant, default (centre) pivot
    ("complete", ("winscreen_back", 1, 277, 120, 120), 4, (129, 405, 2, 2),
     (121.5, 121.5), (-136.0, 136.0)),
    # side 2: the one side whose 1x1 marker psd.exe leaves where it is
    ("complete", ("", 659, 230, 1, 1), 2, (681, 405, 2, 2), (0.0, 0.0),
     (-45.5, 351.5)),
    ("complete", ("winscreen_00", 437, 302, 76, 76), 1, (405, 405, 2, 2),
     (75.5, 75.5), (138.0, 132.0)),
    # a 2x2 `$name` anchor: no artwork, pivot 0, positive x
    ("complete", ("", 337, 328, 2, 2), 1, (405, 405, 2, 2), (0.0, 0.0),
     (-137.5, 155.5)),
    ("complete", ("qr_code", 847, 297, 80, 80), 3, (957, 405, 2, 2),
     (79.5, 79.5), (-142.0, 138.0)),
    # an off-centre pivot marker: x and y pivots differ
    ("complete", ("twist_00", 458, 453, 34, 34), 1, (405, 405, 2, 2),
     (32.5, 38.5), (137.0, -133.0)),
    # side 0, the only side whose 1x1 marker moves on both axes
    ("ico", ("icon", 403, 261, 145, 141), 0, (405, 129, 2, 2),
     (72.5, 75.5), (67.0, -338.0)),
    ("hud", ("", 243, 57, 1, 1), 0, (405, 129, 2, 2), (0.0, 0.0),
     (-325.5, 145.5)),
    ("hud", ("health_full", 279, 4, 13, 11), 0, (405, 129, 2, 2),
     (12.5, 10.5), (-241.0, 241.0)),
    ("hud", ("health_full", 294, 4, 13, 11), 0, (405, 129, 2, 2),
     (12.5, 10.5), (-211.0, 241.0)),
    ("win", ("winscreen_back", 1, 277, 120, 120), 4, (129, 405, 2, 2),
     (121.5, 121.5), (-136.0, 136.0)),
]


def test_place_xy_matches_utils_exe():
    for mapname, psl, side, rect, pivot, expected in GOLDEN_PLACES:
        name, x, y, w, h = psl
        blob = psl_to_octplace(
            [_rec(name, x, y, w, h, side, rect)],
            {name: 3} if name else {}, {}, {},
            packed_pivots={name: (pivot[0], pivot[1], w, h)} if name else {},
        )
        assert _xy(blob) == expected, f"{mapname} {name or '(marker)'}"


def test_place_xy_is_the_pivot_measured_from_the_side_centre():
    # The same numbers, stated the other way round: no half-pixel bias left
    # over once the pivot is expressed in sprite-local pixels.
    for _mapname, psl, side, rect, pivot, expected in GOLDEN_PLACES:
        name, x, y, w, h = psl
        pvlx, pvly = (pivot[0] + 0.5) / 2, (pivot[1] + 0.5) / 2
        scx, scy = rect[0] + rect[2] / 2, rect[1] + rect[3] / 2
        assert (2.0 * (x + pvlx - scx), -2.0 * (y + pvly - scy)) == expected


def test_a_place_with_no_sprite_has_no_pivot_term():
    # `packed_pivots` has no entry: the place is still anchored on the side
    # centre, which is what puts the ladybug layer markers on the .5 grid.
    blob = psl_to_octplace([_rec("", 92, 148, 1, 1, 4, (129, 405, 2, 2))],
                           {}, {}, {})
    assert _xy(blob) == (-75.5, 515.5)


def test_side_centre_is_the_marker_centre_not_its_corner():
    # A 2x2 marker at (405,405) has its centre at (406,406); anchoring on the
    # top-left corner the PSL actually stores would shift every place on that
    # side by one unit on each axis.
    rec = _rec("", 337, 328, 2, 2, 1, (405, 405, 2, 2))
    assert _xy(psl_to_octplace([rec], {}, {}, {})) == (-137.5, 155.5)
    on_the_corner = _rec("", 337, 328, 2, 2, 1, (405, 405, 0, 0))
    assert _xy(psl_to_octplace([on_the_corner], {}, {}, {})) == (-135.5, 153.5)


def test_place_position_is_linear_in_the_layer_position():
    # The old packer nudged x by -1 once it came out negative and y by +1 once
    # it came out positive, which kinked the mapping at the side centre. Four
    # layers straddling the centre must now sit on one straight line of
    # slope +2 in x and -2 in y.
    rect = (405, 405, 2, 2)

    def place(lx, ly):
        return _xy(psl_to_octplace([_rec("", lx, ly, 2, 2, 1, rect)], {}, {}, {}))

    xs = [place(v, 406)[0] for v in (306, 386, 426, 506)]
    assert [b - a for a, b in zip(xs, xs[1:])] == [160.0, 80.0, 160.0]
    ys = [place(406, v)[1] for v in (306, 386, 426, 506)]
    assert [b - a for a, b in zip(ys, ys[1:])] == [-160.0, -80.0, -160.0]


# ─────────────────────────────────────────────────────────────────────────────
# The ~sideN marker rect
#
# Measured: `psd.exe complete.psd -log -map` / `psd.exe ico.psd -log -map`
# with the marker layers rewritten to the rect on the left.
# ─────────────────────────────────────────────────────────────────────────────

MARKER_RECTS = [
    # the shipped OCT_ladybug map PSDs: 1x1 markers, one per side
    (0, (406, 130, 1, 1), (405, 129, 2, 2)),
    (1, (406, 405, 1, 1), (405, 405, 2, 2)),
    (2, (681, 405, 1, 1), (681, 405, 2, 2)),
    (3, (957, 405, 1, 1), (957, 405, 2, 2)),
    (4, (130, 405, 1, 1), (129, 405, 2, 2)),
    (5, (406, 681, 1, 1), (405, 681, 2, 2)),
    # ...and the same six markers moved to arbitrary places: the shift tracks
    # the side index, not the position and not the layer order
    (0, (300, 500, 1, 1), (299, 499, 2, 2)),
    (1, (400, 500, 1, 1), (399, 500, 2, 2)),
    (2, (500, 500, 1, 1), (500, 500, 2, 2)),
    (3, (960, 410, 1, 1), (960, 410, 2, 2)),
    (4, (700, 500, 1, 1), (699, 500, 2, 2)),
    (5, (800, 500, 1, 1), (799, 500, 2, 2)),
    # OCT_get_started's map PSDs ship 2x2 markers: verbatim
    (0, (405, 129, 2, 2), (405, 129, 2, 2)),
    (4, (129, 405, 2, 2), (129, 405, 2, 2)),
    # every other size is verbatim too, including the near misses
    (0, (400, 200, 1, 2), (400, 200, 1, 2)),
    (0, (400, 200, 2, 1), (400, 200, 2, 1)),
    (0, (400, 200, 1, 3), (400, 200, 1, 3)),
    (0, (400, 200, 3, 1), (400, 200, 3, 1)),
    (0, (300, 500, 3, 3), (300, 500, 3, 3)),
    (1, (400, 500, 3, 3), (400, 500, 3, 3)),
    (0, (400, 200, 5, 5), (400, 200, 5, 5)),
    (0, (400, 200, 6, 3), (400, 200, 6, 3)),
]


def test_side_marker_rect_matches_psd_exe():
    for side, given, expected in MARKER_RECTS:
        assert side_marker_rect(side, *given) == expected, (side, given)


def test_only_a_one_pixel_marker_is_widened():
    for side in range(6):
        assert side_marker_rect(side, 400, 200, 2, 2) == (400, 200, 2, 2)
        assert side_marker_rect(side, 400, 200, 1, 1)[2:] == (2, 2)


def test_the_one_pixel_shift_table_is_closed():
    assert set(SIDE_MARKER_1PX_ORIGIN_SHIFT) == set(range(6))


def test_an_unknown_side_index_is_left_alone():
    # A PSD with `~side9` is malformed, but it must not crash the export.
    assert side_marker_rect(9, 400, 200, 1, 1) == (400, 200, 2, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Side assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_side_is_the_marker_nearest_the_layers_top_left_corner():
    # OCT_ladybug ico.psd, the discriminating case. The 145x141 icon at
    # (403,261) is nearer side 1 by its centre and nearer side 0 by its
    # corner; psd.exe files it under side 0.
    markers = {0: (405, 129, 2, 2), 1: (405, 405, 2, 2), 2: (681, 405, 2, 2),
               3: (957, 405, 2, 2), 4: (129, 405, 2, 2), 5: (405, 681, 2, 2)}
    assert nearest_side(403, 261, 145, 141, markers) == 0


def test_side_assignment_ties_keep_the_first_marker():
    # Two 2x2 markers 100 px apart: psd.exe hands the exact midpoint to the
    # first marker and the next pixel over to the second.
    markers = {0: (400, 100, 2, 2), 1: (500, 100, 2, 2)}
    assert nearest_side(450, 100, 10, 10, markers) == 0
    assert nearest_side(451, 100, 10, 10, markers) == 1


def test_side_assignment_measures_to_the_normalised_marker():
    # The same two markers as 1x1 layers: psd.exe normalises them to
    # (399,99) and (499,100) first, which moves the boundary one pixel left.
    markers = {sid: side_marker_rect(sid, x, y, 1, 1)
               for sid, (x, y) in {0: (400, 100), 1: (500, 100)}.items()}
    assert markers == {0: (399, 99, 2, 2), 1: (499, 100, 2, 2)}
    assert nearest_side(448, 100, 10, 10, markers) == 0
    assert nearest_side(449, 100, 10, 10, markers) == 1


# ─────────────────────────────────────────────────────────────────────────────
# `=NN` layer markers
# ─────────────────────────────────────────────────────────────────────────────

def test_equals_number_layer_is_a_marker():
    assert LayerName.parse("=20").is_marker
    assert LayerName.parse("=20").marker_number == 20
    assert LayerName.parse("=50").is_marker
    assert not LayerName.parse("winscreen_back").is_marker
    assert not LayerName.parse("countdown3_00").is_marker


def test_a_sprite_carrying_a_number_is_not_a_layer_marker():
    # `eat=3` numbers the sprite, it does not open a draw layer.
    parsed = LayerName.parse("eat=3")
    assert not parsed.is_marker
    assert parsed.sprite_number == 3
    assert parsed.marker_number is None


# The eleven `=NN` markers of the OCT_ladybug maps, straight out of the
# v260 container: (map, place index, Number, place x, y).
GOLDEN_LAYER_MARKS = [
    ("complete", 0, 20), ("complete", 17, 21),
    ("countdown", 0, 40),
    ("game_over", 0, 20), ("game_over", 25, 21), ("game_over", 30, 42),
    ("hud", 0, 50),
    ("splash", 21, 1), ("splash_wo_saves", 21, 1),
    ("win", 0, 20), ("win", 25, 21),
]


def test_layer_marker_place_keeps_its_number():
    for _mapname, _idx, number in GOLDEN_LAYER_MARKS:
        blob = psl_to_octplace(
            [_rec("", 92, 148, 1, 1, 4, (129, 405, 2, 2), number=number)],
            {}, {}, {})
        assert _number(blob) == number


def test_layer_marker_place_stays_bare_apart_from_its_number():
    # OCT_add_map only treats a place as a layer mark when everything else is
    # zero, so the number must arrive without dragging a bmp/name/tag along.
    blob = psl_to_octplace(
        [_rec("", 92, 148, 1, 1, 4, (129, 405, 2, 2), number=20)],
        {}, {}, {})
    off = 8
    tags, = struct.unpack_from("<I", blob, off + 8)
    bmp, = struct.unpack_from("<h", blob, off + 16)
    flags, = struct.unpack_from("<H", blob, off + 20)
    name_b, group_b, _parent, type_b = struct.unpack_from("<4B", blob, off + 24)
    assert (tags, bmp, flags, name_b, group_b, type_b) == (0, 0, 0, 0, 0, 0)
    assert _number(blob) == 20
