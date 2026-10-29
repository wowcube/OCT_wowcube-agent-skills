"""``$name`` layers are NAME_ declarations, never sprites.

Ground truth, ``OCT_ladybug``: its map PSDs hold 26 layers whose names begin
with ``$`` (``$score!font2``, 2x2 px text anchors). The legacy container has
544 records and ZERO names starting with ``$``, while the committed
``src/app_ids.h`` defines ``NAME_score`` and the app reads
``octObject_t.Name == NAME_score`` to find its HUD labels.

Before this rule the packer turned every one of them into a sprite and then
died in ``generate_beta_ids_h``: ``BMP_$score`` is not a C identifier, so the
whole pack aborted with a ValueError.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image

from pack_beta import KIND_SPRITE, generate_beta_ids_h
from pack_psd import (
    build_bmp_name_index,
    csv_to_octplace,
    generate_app_ids_h,
    is_name_declaration,
    psl_to_octplace,
    tag_bits,
)

PLACE = 28


def _png(path: Path, size=(2, 2)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (0, 0, 0, 0)).save(path)


def test_prefix_is_the_marker_not_mere_presence():
    assert is_name_declaration("$score")
    assert is_name_declaration("$time_bonus")
    # `$` after a base name annotates a real sprite: `hero` carrying NAME_player
    assert not is_name_declaration("hero$player")
    assert not is_name_declaration("score")


def test_declaration_pngs_never_enter_the_bmp_index(tmp_path: Path):
    exported = tmp_path / "exported"
    for name in ("hero", "$score", "$time_bonus"):
        _png(exported / f"{name}.png")
    index, names = build_bmp_name_index(str(tmp_path / "packed"), str(exported))
    assert "hero" in names
    assert not [n for n in names if n.startswith("$")]
    assert not [n for n in index if n.startswith("$")]


def test_committed_declaration_pngs_in_packed_are_ignored_too(tmp_path: Path):
    """CI packs a committed art/exported|packed as-is; a real psd.exe run can
    have left the anchors there."""
    packed = tmp_path / "packed"
    _png(packed / "hero.png")
    _png(packed / "$score.png")
    index, names = build_bmp_name_index(str(packed), str(tmp_path / "nope"))
    assert "$score" not in names and "$score" not in index


def test_legacy_ids_header_has_no_dollar_enum(tmp_path: Path):
    out = tmp_path / "app_ids.h"
    generate_app_ids_h(["hero"], [], {"score": 1}, {}, {}, {},
                       str(out), str(tmp_path))
    text = out.read_text()
    assert "$" not in text.split("//$names")[0]
    assert "const uint8_t NAME_score = 1;" in text


def test_beta_ids_header_would_reject_a_dollar_name():
    """The blocker itself: proof the filter above is what keeps the pack
    alive, not luck."""
    with pytest.raises(ValueError, match=r"not a valid C enum identifier"):
        generate_beta_ids_h([(KIND_SPRITE, "zero"), (KIND_SPRITE, "$score")])


# ── the anchor still does its job: Name byte, no artwork ─────────────────────

def _place_fields(blob: bytes, i: int = 0):
    off = 8 + i * PLACE
    tags, = struct.unpack_from("<I", blob, off + 8)
    bmp, = struct.unpack_from("<h", blob, off + 16)
    name_b, group_b, parent_b, type_b = struct.unpack_from("<BBBB", blob, off + 24)
    return {"tags": tags, "bmp": bmp, "name": name_b,
            "group": group_b, "type": type_b}


def _psl_rec(name: str, **over) -> dict:
    rec = dict(name=name, x=10, y=20, w=2, h=2, layer_mark=0, side=0,
               center_x=0, center_y=0, pivot_x=0, pivot_y=0,
               pivot_w=0, pivot_h=0, group_name="", type_name="",
               number=0, rate=0)
    rec.update(over)
    return rec


def test_anchor_place_carries_the_name_and_no_sprite():
    bmp_index = {"hero": 7, "$score": 3}
    blob = psl_to_octplace([_psl_rec("$score")], bmp_index, {}, {},
                           name_map={"score": 4})
    f = _place_fields(blob)
    assert f["bmp"] == 0, "a name declaration must not point at artwork"
    assert f["name"] == 4, "the anchor is useless without its NAME_ index"


def test_ordinary_sprite_place_keeps_its_bmp_index():
    blob = psl_to_octplace([_psl_rec("hero", w=32, h=32)], {"hero": 7}, {}, {},
                           name_map={"score": 4})
    assert _place_fields(blob)["bmp"] == 7


def test_place_tags_come_from_the_csv_sidecar():
    """The PSL layout we mirror from psd.exe has no slot for ``#tag``; the
    per-PSD CSV does. ladybug's four health hearts are distinguished only by
    TAG_health1..4."""
    meta = {("health_full", 10, 20, 13, 11): ("", "health3")}
    tag_map = {"health1": 1, "health2": 2, "health3": 3, "health4": 4}
    blob = psl_to_octplace(
        [_psl_rec("health_full", w=13, h=11)], {"health_full": 5}, {}, {},
        tag_map=tag_map, layer_meta=meta)
    assert _place_fields(blob)["tags"] == 4      # TAG_health3 == 1 << 2


def test_tags_default_to_zero_without_a_sidecar():
    blob = psl_to_octplace([_psl_rec("health_full", w=13, h=11)],
                           {"health_full": 5}, {}, {})
    assert _place_fields(blob)["tags"] == 0


def test_csv_map_path_honours_declarations_too():
    recs = [dict(raw_name="$score!font2", sprite_name="", png_name="$score",
                 obj_name="score", tag_name="", type_name="", group_name="",
                 number=0, rate=0, x=1, y=2, w=2, h=2)]
    blob = csv_to_octplace(recs, {"$score": 9}, {}, {},
                           name_map={"score": 4}, tag_map={})
    f = _place_fields(blob)
    assert (f["bmp"], f["name"]) == (0, 4)


def test_tag_bits_is_a_bitmask():
    tag_map = {"health1": 1, "health2": 2, "health3": 3, "health4": 4}
    assert [tag_bits(f"health{i}", tag_map) for i in (1, 2, 3, 4)] == [1, 2, 4, 8]
    assert tag_bits("", tag_map) == 0
    assert tag_bits("nope", tag_map) == 0
