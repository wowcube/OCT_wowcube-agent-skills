"""Fidelity tests for the PSD exporter against the reference ``psd.exe``.

Every expectation here was derived by diffing our exporter's output against
``OCT_get_started/art/exported/`` — 478 artifacts produced by the real
``psd.exe`` — and confirmed by running the exe itself in a scratch directory:

  * ``-map`` PSDs emit ``.csv``/``.psl``/``.log`` but **no PNGs**;
  * the CSV ``Id`` column is Photoshop's own layer id + 1;
  * the CSV keeps zero-area layers, the PSL drops them;
  * the side block is ``side id, marker x, y, w, h`` with side ``-1`` and an
    all-zero rect when the PSD declares no ``~sideN``;
  * Assets-mode records carry a pivot block (sentinel ``-3`` then a rect);
    Map-mode records leave it zeroed;
  * the pivot rect is the ``~pivot`` marker blob overlapping the layer, and
    the layer's own rect when no marker overlaps it.

With these in place all 9 CSVs and all 9 PSLs of the reference corpus come
out byte-identical.
"""
from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image

import config
from pack_psd import (
    SpriteRecord, _write_records_csv, _write_records_psl,
    find_pivot_markers, parse_psl, pivot_for_layer,
)


def _record(name="spr", **kw):
    base = dict(
        id=1, name=name, group_id=0, kind=0, bmp="",
        x=0, y=0, w=4, h=4, layer_mark=config.DEFAULT_LAYER_MARK,
        side=-1, side_cx=0, side_cy=0, png_name=name,
        is_marker=False, marker_number=0, sprite_number=0,
        type_name="", group_name="", rate=0,
    )
    base.update(kw)
    return SpriteRecord(**base)


class _FakeLayer:
    """Duck-typed stand-in for a psd-tools layer."""

    def __init__(self, name, img, left=0, top=0):
        self.name, self._img, self.left, self.top = name, img, left, top

    def composite(self):
        return self._img


def _mask(w, h, pixels):
    """RGBA image of size w×h that is opaque exactly at ``pixels``."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for x, y in pixels:
        arr[y, x] = (255, 255, 255, 255)
    return Image.fromarray(arr, "RGBA")


# ── pivot marker discovery ───────────────────────────────────────────────────

def test_find_pivot_markers_returns_blob_bboxes():
    # two separate 2x2 markers, plus a lone pixel
    img = _mask(20, 20, [(2, 2), (3, 2), (2, 3), (3, 3),
                         (10, 5), (11, 5), (10, 6), (11, 6),
                         (17, 15)])
    blobs = find_pivot_markers([_FakeLayer("~pivot", img)])
    assert blobs == [(2, 2, 2, 2), (10, 5, 2, 2), (17, 15, 1, 1)]


def test_find_pivot_markers_offsets_by_layer_origin():
    img = _mask(4, 4, [(1, 1), (2, 1)])
    blobs = find_pivot_markers([_FakeLayer("~pivots", img, left=100, top=50)])
    assert blobs == [(101, 51, 2, 1)]


def test_find_pivot_markers_ignores_other_tilde_layers():
    img = _mask(4, 4, [(0, 0)])
    layers = [_FakeLayer("~bg", img), _FakeLayer("~side0", img),
              _FakeLayer("sprite", img)]
    assert find_pivot_markers(layers) == []


def test_find_pivot_markers_joins_diagonals_as_separate_blobs():
    # 4-connected: a diagonal pair is two blobs, not one
    img = _mask(6, 6, [(1, 1), (2, 2)])
    assert find_pivot_markers([_FakeLayer("~pivot", img)]) == \
        [(1, 1, 1, 1), (2, 2, 1, 1)]


# ── pivot selection ──────────────────────────────────────────────────────────

def test_pivot_for_layer_picks_overlapping_marker():
    markers = [(5, 5, 2, 2), (50, 50, 2, 2)]
    assert pivot_for_layer(0, 0, 10, 10, markers) == (5, 5, 2, 2)


def test_pivot_for_layer_falls_back_to_own_rect():
    assert pivot_for_layer(0, 0, 4, 4, [(50, 50, 2, 2)]) == (0, 0, 4, 4)
    assert pivot_for_layer(3, 7, 4, 5, []) == (3, 7, 4, 5)


def test_pivot_for_layer_overlap_is_half_open():
    # a marker starting exactly at the layer's right edge does not overlap
    assert pivot_for_layer(0, 0, 4, 4, [(4, 0, 2, 2)]) == (0, 0, 4, 4)
    assert pivot_for_layer(0, 0, 4, 4, [(3, 0, 2, 2)]) == (3, 0, 2, 2)


def test_utils_pivot_formula_matches_reference_packed_sprite():
    """utils.exe: pivot = 2*(rect_centre - layer_xy) - 0.5.

    Pinned on ``ic_twist_00`` from the reference corpus: layer (20,20,37x36),
    pivot marker (37,37,2x2), packed octBmp pivot (35.5, 35.5).
    """
    x, y = 20, 20
    px, py, pw, ph = pivot_for_layer(x, y, 37, 36, [(37, 37, 2, 2)])
    assert (2 * (px + pw / 2 - x) - 0.5, 2 * (py + ph / 2 - y) - 0.5) == (35.5, 35.5)


# ── PSL record layout ────────────────────────────────────────────────────────

def _one_record_psl(tmp_path, rec, psl_type):
    p = tmp_path / "t.psl"
    _write_records_psl(str(p), [rec], psl_type)
    return p.read_bytes()


def test_psl_assets_side_block_is_minus_one_and_zero_rect(tmp_path):
    blob = _one_record_psl(tmp_path, _record(), config.PSL_TYPE_ASSET)
    body = blob[config.PSL_HEADER_SIZE:]
    assert struct.unpack_from("<5i", body, config.PSL_SIDE_OFFSET) == (-1, 0, 0, 0, 0)


def test_psl_map_side_block_carries_marker_rect(tmp_path):
    rec = _record(side=1, side_cx=405, side_cy=405, side_w=2, side_h=2)
    blob = _one_record_psl(tmp_path, rec, config.PSL_TYPE_MAP)
    body = blob[config.PSL_HEADER_SIZE:]
    assert struct.unpack_from("<5i", body, config.PSL_SIDE_OFFSET) == (1, 405, 405, 2, 2)


def test_psl_assets_record_carries_pivot_block(tmp_path):
    rec = _record(x=20, y=20, w=37, h=36,
                  pivot_x=37, pivot_y=37, pivot_w=2, pivot_h=2)
    body = _one_record_psl(tmp_path, rec, config.PSL_TYPE_ASSET)[config.PSL_HEADER_SIZE:]
    assert struct.unpack_from("<i", body, config.PSL_PIVOT_MARK_OFFSET)[0] == \
        config.PSL_PIVOT_MARK_ASSET
    assert struct.unpack_from("<4i", body, config.PSL_PIVOT_OFFSET) == (37, 37, 2, 2)


def test_psl_map_record_leaves_pivot_block_zeroed(tmp_path):
    rec = _record(pivot_x=37, pivot_y=37, pivot_w=2, pivot_h=2)
    body = _one_record_psl(tmp_path, rec, config.PSL_TYPE_MAP)[config.PSL_HEADER_SIZE:]
    assert struct.unpack_from("<i", body, config.PSL_PIVOT_MARK_OFFSET)[0] == 0
    assert struct.unpack_from("<4i", body, config.PSL_PIVOT_OFFSET) == (0, 0, 0, 0)


def test_psl_drops_zero_area_layers(tmp_path):
    recs = [_record("a"), _record("zero", w=0, h=0), _record("b")]
    p = tmp_path / "t.psl"
    _write_records_psl(str(p), recs, config.PSL_TYPE_ASSET)
    psl_type, parsed = parse_psl(str(p))
    assert psl_type == config.PSL_TYPE_ASSET
    assert [r["name"] for r in parsed] == ["a", "b"]
    assert struct.unpack_from("<I", p.read_bytes(), 12)[0] == 2


def test_csv_keeps_zero_area_layers(tmp_path):
    """The CSV is the one artifact that still lists zero-area layers."""
    p = tmp_path / "t.csv"
    _write_records_csv(str(p), [_record("a"), _record("zero", w=0, h=0)])
    rows = p.read_text().splitlines()
    assert len(rows) == 3                              # header + 2
    assert '"zero"' in rows[2] and rows[2].endswith("0,0,0,0,-16777216")


def test_parse_psl_roundtrips_pivot(tmp_path):
    rec = _record(x=8, y=0, w=144, h=145,
                  pivot_x=80, pivot_y=80, pivot_w=2, pivot_h=2)
    p = tmp_path / "t.psl"
    _write_records_psl(str(p), [rec], config.PSL_TYPE_ASSET)
    _, parsed = parse_psl(str(p))
    got = parsed[0]
    assert (got["pivot_x"], got["pivot_y"], got["pivot_w"], got["pivot_h"]) == \
        (80, 80, 2, 2)


def test_csv_id_column_is_written_verbatim(tmp_path):
    """psd.exe stores Photoshop's layer id + 1, so the writer must not renumber."""
    p = tmp_path / "t.csv"
    _write_records_csv(str(p), [_record("a", id=4), _record("b", id=24)])
    assert [row.split(",")[0] for row in p.read_text().splitlines()[1:]] == ["4", "24"]


# ── map PSDs emit no PNGs ────────────────────────────────────────────────────

@pytest.mark.parametrize("is_map,expect_png", [(True, False), (False, True)])
def test_map_psds_emit_no_pngs(tmp_path, monkeypatch, is_map, expect_png):
    import pack_psd

    class _PSD(list):
        pass

    layer = _FakeLayer("spr", _mask(4, 4, [(1, 1)]))
    layer.width = layer.height = 4
    layer.is_visible = lambda: True
    monkeypatch.setattr(pack_psd, "PSDImage",
                        type("X", (), {"open": staticmethod(lambda p: _PSD([layer]))}),
                        raising=False)
    monkeypatch.setitem(__import__("sys").modules, "psd_tools",
                        type("M", (), {"PSDImage": type(
                            "X", (), {"open": staticmethod(lambda p: _PSD([layer]))})}))

    pack_psd.export_psd_file_python(str(tmp_path / "src.psd"), str(tmp_path),
                                    is_map=is_map)
    assert (tmp_path / "spr.png").exists() is expect_png
    assert (tmp_path / "src.csv").exists()
    assert (tmp_path / "src.psl").exists()
