"""PSD placement maps and the metadata constants in the beta ids header.

``OCT_ladybug``'s legacy container has eight KIND_MAP records (``ico`` plus
seven scene maps) and its committed ``src/app_ids.h`` carries the
``$names``/``%types``/``&groups``/``#tags`` constant blocks. Because the beta
emit OVERWRITES that very file, a header without those blocks does not just
lose parity - the app stops compiling (``NAME_score``, ``TYPE_health``,
``TAG_health2`` are all referenced from ``src/app.h``).
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image

import pack_beta
from pack_beta import (
    KIND_MAP,
    KIND_PAL,
    KIND_SPRITE,
    build_bmp_header,
    emit_beta_layout,
    generate_beta_ids_h,
    read_index_bin,
    remap_map_bmp_ids,
)
from pack_psd import emit_index_blocks

PLACE = 28


def _legacy_map(*bmp_indices: int) -> bytes:
    out = [struct.pack("<ii", 1, len(bmp_indices))]
    for b in bmp_indices:
        out.append(struct.pack("<ff", 0.0, 0.0) + struct.pack("<I", 0)
                   + struct.pack("<hh", 8, 8) + struct.pack("<h", b)
                   + struct.pack("<h", 0) + struct.pack("<H", 0)
                   + struct.pack("<bb", 1, 1) + struct.pack("<BBBB", 0, 0, 0, 0))
    return b"".join(out)


def _bmp(name: str = "x") -> bytes:
    return build_bmp_header(w=8, h=8, flags=1, pidx=1) + b"\0" * 8


def _icon(tmp_path: Path) -> Path:
    p = tmp_path / "icon.png"
    Image.new("RGBA", (160, 160), (255, 0, 0, 255)).save(p)
    return p


# ── BmpIdx translation ───────────────────────────────────────────────────────

def test_map_bmp_indices_are_translated_to_asset_ids():
    """A legacy map stores the sprite's index in the ALPHABETICAL legacy BMP
    enum; the beta container needs its index.bin record index instead."""
    blob = _legacy_map(4, 9)
    out = remap_map_bmp_ids(blob, {4: "hero", 9: "coin"},
                            {"hero": 37, "coin": 102})
    got = [struct.unpack_from("<h", out, 8 + i * PLACE + 16)[0] for i in (0, 1)]
    assert got == [37, 102]


def test_untranslatable_reference_falls_back_to_the_empty_sprite(capsys):
    out = remap_map_bmp_ids(_legacy_map(4), {4: "gone"}, {})
    assert struct.unpack_from("<h", out, 8 + 16)[0] == 0
    assert "not sprites in this container" in capsys.readouterr().out


def test_zero_reference_stays_zero():
    out = remap_map_bmp_ids(_legacy_map(0), {}, {"hero": 5})
    assert struct.unpack_from("<h", out, 8 + 16)[0] == 0


def test_truncated_map_payload_is_rejected():
    with pytest.raises(ValueError, match="places"):
        remap_map_bmp_ids(struct.pack("<ii", 1, 4) + b"\0" * 8, {}, {})


# ── records ──────────────────────────────────────────────────────────────────

def test_psd_maps_become_map_records(tmp_path: Path):
    recs = emit_beta_layout(
        tmp_path, "app_t", palettes={1: [0x1234]},
        palette_sprites=[("hero", _bmp())],
        psd_maps=[("hud", _legacy_map(4))],
        legacy_bmp_names={4: "hero"})
    maps = [n for k, n in recs if k == KIND_MAP]
    assert "hud" in maps
    hero_id = next(i for i, (k, n) in enumerate(recs) if n == "hero")
    payload = (tmp_path / "art" / "packed" / "hud.raw").read_bytes()
    assert struct.unpack_from("<h", payload, 8 + 16)[0] == hero_id


def test_psd_maps_require_the_legacy_index(tmp_path: Path):
    with pytest.raises(ValueError, match="legacy_bmp_names"):
        emit_beta_layout(tmp_path, "app_t", palettes={1: [0x1234]},
                         palette_sprites=[("hero", _bmp())],
                         psd_maps=[("hud", _legacy_map(4))])


# ── the launcher-map rule ────────────────────────────────────────────────────

def test_no_psd_maps_synthesizes_both_launcher_maps(tmp_path: Path):
    """The AI-generated shape - unchanged behaviour, and the golden
    app_gbhotel .oct depends on it."""
    recs = emit_beta_layout(tmp_path, "app_t", palettes={1: [0x1234]},
                            palette_sprites=[("hero", _bmp())],
                            icon=_icon(tmp_path))
    assert [n for k, n in recs if k == KIND_MAP] == ["ico", "ahover"]


def test_an_app_that_declares_only_ico_gets_only_ico(tmp_path: Path):
    """ladybug ships ico.psd and no ahover.psd; its legacy container has
    exactly one launcher map among the eight."""
    recs = emit_beta_layout(
        tmp_path, "app_t", palettes={1: [0x1234]},
        palette_sprites=[("hero", _bmp())], icon=_icon(tmp_path),
        psd_maps=[("ico", _legacy_map(4)), ("hud", _legacy_map(4))],
        legacy_bmp_names={4: "hero"})
    assert [n for k, n in recs if k == KIND_MAP] == ["ico", "hud"]


def test_an_app_that_declares_both_keeps_both(tmp_path: Path):
    """get_started's !pack.bat runs ico.psd AND ahover.psd through -map."""
    recs = emit_beta_layout(
        tmp_path, "app_t", palettes={1: [0x1234]},
        palette_sprites=[("hero", _bmp())], icon=_icon(tmp_path),
        psd_maps=[("ico", _legacy_map(4)), ("ahover", _legacy_map(4))],
        legacy_bmp_names={4: "hero"})
    assert [n for k, n in recs if k == KIND_MAP] == ["ico", "ahover"]


def test_ico_stays_inside_the_launcher_descriptor_window(tmp_path: Path):
    """The launcher resolves "ico" by name within the first EXT_MAX_DESCS
    descriptors, so it must NOT drift to the end with the scene maps."""
    recs = emit_beta_layout(
        tmp_path, "app_t", palettes={1: [0x1234]},
        palette_sprites=[(f"s{i:03d}", _bmp()) for i in range(600)],
        icon=_icon(tmp_path),
        psd_maps=[("ico", _legacy_map(0)), ("hud", _legacy_map(0))],
        legacy_bmp_names={})
    ico_id = next(i for i, (k, n) in enumerate(recs)
                  if k == KIND_MAP and n == "ico")
    hud_id = next(i for i, (k, n) in enumerate(recs)
                  if k == KIND_MAP and n == "hud")
    assert ico_id < pack_beta.EXT_MAX_DESCS < hud_id


def test_a_map_named_like_a_sprite_is_a_hard_error(tmp_path: Path):
    """Sprites and maps share art/packed/<name>.raw."""
    with pytest.raises(ValueError, match="collision"):
        emit_beta_layout(tmp_path, "app_t", palettes={1: [0x1234]},
                         palette_sprites=[("hud", _bmp())],
                         psd_maps=[("hud", _legacy_map(0))],
                         legacy_bmp_names={})


# ── the metadata constant blocks ─────────────────────────────────────────────

def test_ids_header_carries_the_metadata_blocks(tmp_path: Path):
    blocks = emit_index_blocks({"score": 1}, {"health": 1}, {"icons": 1},
                               {"health1": 1, "health3": 3})
    emit_beta_layout(tmp_path, "app_t", palettes={1: [0x1234]},
                     palette_sprites=[("hero", _bmp())],
                     metadata_blocks=blocks)
    text = (tmp_path / "src" / "app_t_ids.h").read_text()
    assert "const uint8_t NAME_score = 1;" in text
    assert "const uint8_t TYPE_health = 1;" in text
    assert "const uint8_t GROUP_icons = 1;" in text
    assert "const uint32_t TAG_health3 = 4;" in text


def test_tag_constants_are_a_bitmask_of_uint32():
    """Measured on the committed OCT_ladybug/src/app_ids.h: the four health
    tags are 1/2/4/8 and uint32_t, because the app ORs them into
    octObject_t.Tags. The 1-based index would make TAG_health3 alias
    TAG_health1|TAG_health2."""
    text = emit_index_blocks({}, {}, {}, {"health1": 1, "health2": 2,
                                          "health3": 3, "health4": 4})
    for name, value in (("health1", 1), ("health2", 2),
                        ("health3", 4), ("health4", 8)):
        assert f"const uint32_t TAG_{name} = {value};" in text


def test_only_the_type_block_gets_a_last_sentinel():
    """get_started's committed header: empty $names/&groups/#tags blocks and
    a bare `const uint8_t TYPE_last = 1;`."""
    text = emit_index_blocks({}, {}, {}, {})
    assert "const uint8_t TYPE_last = 1;" in text
    for prefix in ("NAME_last", "GROUP_last", "TAG_last"):
        assert prefix not in text


def test_header_without_metadata_is_unchanged():
    recs = [(KIND_SPRITE, "zero"), (KIND_PAL, "1"), (KIND_SPRITE, "hero")]
    assert generate_beta_ids_h(recs) == generate_beta_ids_h(recs, "")


def test_index_bin_round_trips_the_map_records(tmp_path: Path):
    emit_beta_layout(tmp_path, "app_t", palettes={1: [0x1234]},
                     palette_sprites=[("hero", _bmp())],
                     psd_maps=[("hud", _legacy_map(4))],
                     legacy_bmp_names={4: "hero"})
    recs = read_index_bin(tmp_path / "index.bin")
    assert (KIND_MAP, "hud") in recs
