"""Pivot parity with the legacy ``psd.exe`` + ``utils.exe`` chain.

Reverse-engineered rule (verified against the whole OCT_get_started corpus —
450/450 packed sprites, see ``docs/superpowers/plans/2026-08-05-part3-python-parity.md``):

  * ``psd.exe`` reads the PSD's ``~pivot``/``~pivots`` layer and treats every
    4-connected blob of non-transparent pixels as one marker.  A sprite layer
    gets the marker whose bbox overlaps it; with no overlapping marker it gets
    its own rect.  The chosen rect goes into the PSL record's pivot block
    (``scripts/pack_psd.py::find_pivot_markers`` / ``pivot_for_layer``).
  * ``utils.exe`` then packs, per axis,
        ``pivot = SCALE * (marker_centre - layer_xy) - 0.5``
    with ``SCALE = 2`` for a normal sprite (the engine draws palette sprites at
    2x zoom) and ``SCALE = 1`` for a ``<FULLSIZE>`` one (drawn 1:1, so the
    pivot must not be doubled).

Every expectation below is transcribed from the golden toolchain output in
``OCT_get_started``: layer rect + pivot rect from ``art/exported/*.psl``
(``psd.exe``), flags and pivot floats from ``art/packed/*.raw`` (``utils.exe``,
octBmp_t offsets 44, 4 and 8).  That corpus is read-only and gitignored, so the
numbers are pinned here rather than read at test time.
"""
from __future__ import annotations

import struct

import pytest

from config import (
    HDR_OFF_PIVOT_X,
    HDR_OFF_PIVOT_Y,
    PIVOT_MODE,
    PivotMode,
    SpriteFlag,
)
from pack_codec import build_header, compute_psd_marker_pivot
from pack_psd import find_pivot_markers, pivot_for_layer


# ─────────────────────────────────────────────────────────────────────────────
# Golden fixture: 12 sprites from the OCT_get_started corpus
#
#   name, layer (x, y, w, h), pivot rect (x, y, w, h), flags, golden pivot
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_PIVOTS: list[tuple[str, tuple[int, int, int, int],
                          tuple[int, int, int, int], int,
                          tuple[float, float]]] = [
    # marker-anchored, no flags — the example pinned in the fidelity study
    ("ic_twist_00",          (20, 20, 37, 36),    (37, 37, 2, 2),        0, (35.5, 35.5)),
    # same marker, a later "=num" sequence frame with a different layer size:
    # the pivot must stay put even though w/h changed (LEGACY would move it)
    ("ic_twist_01",          (20, 20, 36, 38),    (37, 37, 2, 2),        0, (35.5, 35.5)),
    ("ic_twist_02",          (20, 20, 36, 40),    (37, 37, 2, 2),        0, (35.5, 35.5)),
    # a large marker blob far to the left of the layer -> negative pivot
    ("transit_w_new_01",     (103, 120, 17, 17),  (0, 120, 120, 120),    1, (-86.5, 119.5)),
    ("transit_w_new_04",     (54, 120, 66, 67),   (0, 120, 120, 120),    1, (11.5, 119.5)),
    # <FULLSIZE> sprites: SCALE 1, not 2
    ("selectcube_00",        (69, 289, 113, 105), (124, 341, 2, 2),      3, (55.5, 52.5)),
    ("selectcube_orange_00", (242, 289, 113, 105), (298, 341, 2, 2),     3, (56.5, 52.5)),
    # <FULLSIZE> and also present in a Map-mode PSL (ahover.psl) whose pivot
    # block is zeroed — the Assets-mode record must win
    ("ahover_00",            (8, 0, 144, 145),    (80, 80, 2, 2),        2, (72.5, 80.5)),
    ("ico_get_started",      (8, 0, 144, 145),    (80, 80, 2, 2),        2, (72.5, 80.5)),
    # own-rect fallback (eyes.psd / text.psd carry no ~pivot layer)
    ("eyesappear_00",        (40, 40, 120, 120),  (40, 40, 120, 120),    0, (119.5, 119.5)),
    ("eyesblink_00",         (40, 600, 120, 120), (40, 600, 120, 120),   0, (119.5, 119.5)),
    ("t_usehalftwist",       (555, 93, 99, 17),   (555, 93, 99, 17),     1, (98.5, 16.5)),
]


def _header_pivot(blob: bytes) -> tuple[float, float]:
    return (struct.unpack_from('<f', blob, HDR_OFF_PIVOT_X)[0],
            struct.unpack_from('<f', blob, HDR_OFF_PIVOT_Y)[0])


# ─────────────────────────────────────────────────────────────────────────────
# The formula itself
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,layer,rect,flags,expected", GOLDEN_PIVOTS,
                         ids=[g[0] for g in GOLDEN_PIVOTS])
def test_compute_psd_marker_pivot_matches_utils_exe(name, layer, rect, flags, expected):
    got = compute_psd_marker_pivot(
        layer[0], layer[1], rect,
        fullsize=bool(flags & SpriteFlag.FULLSIZE))
    assert got == pytest.approx(expected)


def test_fullsize_halves_the_pivot():
    """SCALE is the only difference between the two variants."""
    normal = compute_psd_marker_pivot(69, 289, (124, 341, 2, 2), fullsize=False)
    full = compute_psd_marker_pivot(69, 289, (124, 341, 2, 2), fullsize=True)
    assert normal == pytest.approx((111.5, 105.5))
    assert full == pytest.approx((55.5, 52.5))
    # full = (normal + 0.5) / 2 - 0.5
    assert full[0] == pytest.approx((normal[0] + 0.5) / 2 - 0.5)
    assert full[1] == pytest.approx((normal[1] + 0.5) / 2 - 0.5)


def test_own_rect_fallback_equals_the_legacy_local_pivot():
    """A sprite with no overlapping marker keeps (w-0.5, h-0.5).

    This is why the old LEGACY mode was right for 249 of the 450 corpus
    sprites and wrong for the rest.
    """
    from pack_codec import compute_legacy_local_pivot
    assert compute_psd_marker_pivot(40, 600, (40, 600, 120, 120)) == \
        pytest.approx(compute_legacy_local_pivot(120, 120))


# ─────────────────────────────────────────────────────────────────────────────
# build_header wiring (what actually lands in the packed bytes)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,layer,rect,flags,expected", GOLDEN_PIVOTS,
                         ids=[g[0] for g in GOLDEN_PIVOTS])
def test_build_header_writes_the_psd_pivot(name, layer, rect, flags, expected):
    blob = build_header(
        layer[2], layer[3], 8, 7, pidx=0, flags=flags,
        layer_x=layer[0], layer_y=layer[1], pivot_rect=rect,
    )
    assert _header_pivot(blob) == pytest.approx(expected)


def test_build_header_without_a_pivot_rect_is_unchanged():
    """Manifest-driven / full-color apps pass no pivot rect and must not move."""
    with_rect = build_header(37, 36, 8, 7, pidx=0, flags=0)
    assert _header_pivot(with_rect) == pytest.approx((36.5, 35.5))


def test_explicit_pivot_still_wins_over_the_rect():
    blob = build_header(37, 36, 8, 7, pidx=0, flags=0,
                        layer_x=20, layer_y=20, pivot_rect=(37, 37, 2, 2),
                        pivot_x=-0.5, pivot_y=-0.5)
    assert _header_pivot(blob) == pytest.approx((-0.5, -0.5))


def test_psd_mode_is_the_active_default():
    """PSD mode falls back to the LEGACY formula when there is no marker data,
    so switching the default cannot move a byte in a manifest-driven pack."""
    assert PIVOT_MODE == PivotMode.PSD


def test_legacy_mode_ignores_the_pivot_rect(monkeypatch):
    import pack_codec
    monkeypatch.setattr(pack_codec, 'PIVOT_MODE', PivotMode.LEGACY)
    blob = pack_codec.build_header(37, 36, 8, 7, pidx=0, flags=0,
                                   layer_x=20, layer_y=20,
                                   pivot_rect=(37, 37, 2, 2))
    assert _header_pivot(blob) == pytest.approx((36.5, 35.5))


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end: marker discovery -> rect selection -> packed pivot
# ─────────────────────────────────────────────────────────────────────────────

class _FakeLayer:
    """Minimal stand-in for a psd_tools layer (see test_pack_psd_export.py)."""

    def __init__(self, name, img, left=0, top=0):
        self.name, self._img, self.left, self.top = name, img, left, top

    def composite(self):
        return self._img


def test_marker_discovery_to_packed_pivot_round_trip():
    """Reproduce ic_twist_00 from a synthetic ~pivot layer."""
    from PIL import Image

    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    for yy in range(37, 39):
        for xx in range(37, 39):
            img.putpixel((xx, yy), (255, 0, 0, 255))

    markers = find_pivot_markers([_FakeLayer('~pivot', img)])
    assert markers == [(37, 37, 2, 2)]

    rect = pivot_for_layer(20, 20, 37, 36, markers)
    blob = build_header(37, 36, 8, 7, pidx=0, flags=0,
                        layer_x=20, layer_y=20, pivot_rect=rect)
    assert _header_pivot(blob) == pytest.approx((35.5, 35.5))


# ─────────────────────────────────────────────────────────────────────────────
# pack.py plumbing: PSL records -> per-sprite pivot rects
# ─────────────────────────────────────────────────────────────────────────────

def _write_psl(path, psl_type, records):
    """Minimal PSL writer mirroring pack_psd._write_records_psl."""
    from config import (PSL_PIVOT_MARK_ASSET, PSL_PIVOT_MARK_OFFSET,
                        PSL_PIVOT_OFFSET, PSL_RECORD_SIZE, PSL_TYPE_MAP,
                        PSL_XYWH_OFFSET)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4I', psl_type, 0, 0, len(records)))
        for name, xywh, rect in records:
            buf = bytearray(PSL_RECORD_SIZE)
            nb = name.encode('ascii')
            buf[:len(nb)] = nb
            struct.pack_into('<4i', buf, PSL_XYWH_OFFSET, *xywh)
            if psl_type != PSL_TYPE_MAP:
                struct.pack_into('<i', buf, PSL_PIVOT_MARK_OFFSET,
                                 PSL_PIVOT_MARK_ASSET)
                struct.pack_into('<4i', buf, PSL_PIVOT_OFFSET, *rect)
            f.write(buf)


def test_load_sprite_pivot_rects_from_psls(tmp_path):
    from config import PSL_TYPE_ASSET
    from pack import _load_sprite_pivot_rects_from_psls

    _write_psl(tmp_path / 'assets.psl', PSL_TYPE_ASSET, [
        ('ic_twist_00', (20, 20, 37, 36), (37, 37, 2, 2)),
        ('eyesblink_00', (40, 600, 120, 120), (40, 600, 120, 120)),
        ('', (0, 0, 4, 4), (0, 0, 4, 4)),          # marker record, no png name
    ])
    rects = _load_sprite_pivot_rects_from_psls(str(tmp_path))
    assert rects == {
        'ic_twist_00': (20, 20, (37, 37, 2, 2)),
        'eyesblink_00': (40, 600, (40, 600, 120, 120)),
    }


def test_map_mode_psl_never_overrides_the_assets_record(tmp_path):
    """ahover_00 lives in both ahover.psl (-map, zeroed pivot block) and
    ahover_src.psl (assets).  The assets record must win regardless of the
    alphabetical order the PSLs are read in."""
    from config import PSL_TYPE_ASSET, PSL_TYPE_MAP
    from pack import _load_sprite_pivot_rects_from_psls

    _write_psl(tmp_path / 'ahover.psl', PSL_TYPE_MAP,
               [('ahover_00', (436, 304, 74, 67), (0, 0, 0, 0))])
    _write_psl(tmp_path / 'ahover_src.psl', PSL_TYPE_ASSET,
               [('ahover_00', (8, 0, 144, 145), (80, 80, 2, 2))])

    rects = _load_sprite_pivot_rects_from_psls(str(tmp_path))
    assert rects == {'ahover_00': (8, 0, (80, 80, 2, 2))}

    lx, ly, rect = rects['ahover_00']
    assert compute_psd_marker_pivot(lx, ly, rect, fullsize=True) == \
        pytest.approx((72.5, 80.5))


def test_degenerate_pivot_rect_is_ignored(tmp_path):
    """A zero-area pivot block carries no information — fall back, don't
    produce a bogus pivot at the canvas origin."""
    from config import PSL_TYPE_ASSET
    from pack import _load_sprite_pivot_rects_from_psls

    _write_psl(tmp_path / 'a.psl', PSL_TYPE_ASSET,
               [('lonely', (10, 10, 20, 20), (0, 0, 0, 0))])
    assert _load_sprite_pivot_rects_from_psls(str(tmp_path)) == {}


def test_pack_sprite_uses_the_psd_pivot(tmp_path):
    """The full pack_sprite path (not just build_header) carries the pivot."""
    import numpy as np
    from PIL import Image

    from pack_codec import EncoderPalette, pack_sprite

    png = tmp_path / 'ic_twist_00.png'
    Image.fromarray(
        np.zeros((36, 37, 4), dtype=np.uint8), 'RGBA').save(png)

    pal = EncoderPalette([(0, 0, 0, 0), (255, 0, 0, 255)])
    blob = pack_sprite(str(png), pal, flags=0,
                       layer_x=20, layer_y=20, pivot_rect=(37, 37, 2, 2))
    assert _header_pivot(blob) == pytest.approx((35.5, 35.5))
