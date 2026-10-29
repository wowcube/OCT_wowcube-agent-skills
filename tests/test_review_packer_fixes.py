"""Regression tests for the packer findings of the pipeline-overhaul PR review.

One section per finding; each test fails on the pre-fix code.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys

import numpy as np
import pytest
from PIL import Image

import pack_beta
from config import HDR_OFF_FLAGS, HDR_OFF_PIVOT_X, HDR_OFF_RATE, SpriteFlag
from pack_beta import (
    OCT_FLAG_FULLSIZE, OCT_FLAG_RAW565, parse_bmp_header, patch_palette_sprite,
)
from pack_codec import (
    EncoderPalette, RowTooLongError, build_auto_palette, build_header,
    clamp_rate, pack_sprite,
)


def _pivot(blob: bytes) -> tuple[float, float]:
    return struct.unpack_from("<ff", blob, HDR_OFF_PIVOT_X)


def _coin_png(path, size=8):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(2, size - 2):
        for x in range(2, size - 2):
            img.putpixel((x, y), (250, 200, 20, 255))
    img.save(path)
    return path


# ── 1. FULLSIZE palette sprites / 240 palette icon: pivot in zoom-1 units ───

def test_patch_palette_sprite_rescales_pivot_when_fullsize_is_added():
    legacy = build_header(240, 240, 8, 7, pidx=0, flags=int(SpriteFlag.ALPHA))
    assert _pivot(legacy) == (239.5, 239.5)              # zoom-2 own-rect pivot
    beta = patch_palette_sprite(legacy + b"payload", pal_id=1,
                                extra_flags=OCT_FLAG_FULLSIZE)
    hdr = parse_bmp_header(beta)
    assert (hdr.pivot_x, hdr.pivot_y) == (119.5, 119.5)  # utils.exe zoom 1
    assert hdr.flags & OCT_FLAG_FULLSIZE


def test_patch_palette_sprite_keeps_pivot_of_an_already_fullsize_blob():
    legacy = build_header(
        240, 240, 8, 7, pidx=0,
        flags=int(SpriteFlag.ALPHA | SpriteFlag.FULLSIZE),
        pivot_x=10.5, pivot_y=20.5)
    beta = patch_palette_sprite(legacy + b"payload", pal_id=1,
                                extra_flags=OCT_FLAG_FULLSIZE)
    assert _pivot(beta) == (10.5, 20.5)


def test_patch_palette_sprite_without_fullsize_keeps_pivot():
    legacy = build_header(240, 240, 8, 7, pidx=0, flags=int(SpriteFlag.ALPHA))
    assert _pivot(patch_palette_sprite(legacy, pal_id=1)) == (239.5, 239.5)


def _pack_argv(tmp_path, manifest_sprites, extra_args=(), icon_size=64):
    exported = tmp_path / "exported"
    exported.mkdir(exist_ok=True)
    for s in manifest_sprites:
        _coin_png(exported / f"{s['name']}.png", s["size"][0])
    art = tmp_path / "art"
    art.mkdir(exist_ok=True)
    icon = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
    for y in range(8, icon_size - 8):
        for x in range(8, icon_size - 8):
            icon.putpixel((x, y), (10, 200, 30, 255))
    icon.save(art / "icon.png")
    manifest = tmp_path / "tiny_assets.json"
    manifest.write_text(json.dumps({
        "game": "tiny", "schema_version": 1,
        "sprites": manifest_sprites, "sounds": []}), encoding="utf-8")
    app = tmp_path / "app_tiny"
    packed = tmp_path / "packed"
    return app, [
        "pack.py", "--build-palette",
        "--exported-dir", str(exported), "--packed-dir", str(packed),
        "--output-dir", str(packed), "--art-dir", str(art),
        "--assets", "assets", "--beta-app-dir", str(app),
        "--app-name", "app_tiny", "--manifest", str(manifest), *extra_args,
    ]


def test_pack_py_fullsize_palette_icon_and_sprite_pivots(tmp_path, monkeypatch):
    import pack

    app, argv = _pack_argv(
        tmp_path,
        [{"name": "coin", "size": [8, 8], "description": "c"},
         {"name": "panel", "size": [8, 8], "description": "p",
          "flags": {"fullsize": True}}],
        extra_args=["--icon-color", "palette", "--icon-side", "240"])
    monkeypatch.setattr(sys, "argv", argv)
    pack.main()

    packed = app / "art" / "packed"
    ico = parse_bmp_header((packed / "ico_idle.raw").read_bytes())
    assert (ico.w, ico.h) == (240, 240)
    assert ico.flags & OCT_FLAG_FULLSIZE and not ico.flags & OCT_FLAG_RAW565
    assert (ico.pivot_x, ico.pivot_y) == (119.5, 119.5)

    panel = parse_bmp_header((packed / "panel.raw").read_bytes())
    assert panel.flags & OCT_FLAG_FULLSIZE
    assert (panel.pivot_x, panel.pivot_y) == (3.5, 3.5)
    coin = parse_bmp_header((packed / "coin.raw").read_bytes())
    assert (coin.pivot_x, coin.pivot_y) == (7.5, 7.5)    # x2 tier untouched


# ── 2. row length table is u8: no silent wrap ───────────────────────────────

def _noise_png(path, side=240, seed=7):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(side, side, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    Image.fromarray(arr, "RGBA").save(path)
    return path


def _row_lengths_consistent(blob: bytes) -> bool:
    w, h = struct.unpack_from("<hh", blob, 36)
    num = struct.unpack_from("<I", blob, 0)[0]
    table = blob[48:48 + h]
    return sum(table) == num


def test_pack_sprite_rejects_rows_over_255_bytes(tmp_path):
    png = _noise_png(tmp_path / "noise.png")
    colors = [(0, 0, 0, 0)] + [(i, 255 - i, (i * 7) & 0xFF, 255)
                               for i in range(1, 256)]
    pal = EncoderPalette(colors, has_alpha=True)
    with pytest.raises(RowTooLongError):
        pack_sprite(str(png), pal, symbol_bitness=8)


def test_palette_icon_240_falls_back_to_a_smaller_palette(tmp_path):
    import pack

    icon = _noise_png(tmp_path / "icon.png")
    blob, pal565 = pack._encode_palette_icon(icon, 240)
    w, h = struct.unpack_from("<hh", blob, 36)
    assert (w, h) == (240, 240)
    assert max(blob[48:48 + h]) <= 255 and _row_lengths_consistent(blob)
    assert len(pal565) <= 128


# ── 3. header reuse refreshes what the sources know ─────────────────────────

def _reuse_setup(tmp_path):
    png = _coin_png(tmp_path / "s.png")
    pal, _size, sym, _c = build_auto_palette([str(png)])
    old = build_header(8, 8, sym, 7, pidx=0, flags=int(SpriteFlag.ALPHA),
                       rate=5)
    return png, pal, old


def test_reuse_keeps_rate_when_no_source_states_one(tmp_path):
    png, pal, old = _reuse_setup(tmp_path)
    blob = pack_sprite(str(png), pal, header_bytes=old)
    assert struct.unpack_from("<b", blob, HDR_OFF_RATE)[0] == 5
    blob = pack_sprite(str(png), pal, header_bytes=old, rate=3)
    assert struct.unpack_from("<b", blob, HDR_OFF_RATE)[0] == 3


def test_reuse_refreshes_flags_and_marker_pivot(tmp_path):
    png, pal, old = _reuse_setup(tmp_path)
    assert _pivot(old) == (7.5, 7.5)
    # unknown flags / no pivot source -> old header bytes survive
    blob = pack_sprite(str(png), pal, header_bytes=old)
    assert blob[HDR_OFF_FLAGS] == int(SpriteFlag.ALPHA)
    assert _pivot(blob) == (7.5, 7.5)
    # a new <FULLSIZE> tag and a ~pivot marker reach the reused header
    blob = pack_sprite(str(png), pal, header_bytes=old,
                       flags=int(SpriteFlag.ALPHA | SpriteFlag.FULLSIZE),
                       layer_x=10, layer_y=10, pivot_rect=(12, 12, 2, 2))
    assert blob[HDR_OFF_FLAGS] == int(SpriteFlag.ALPHA | SpriteFlag.FULLSIZE)
    assert _pivot(blob) == (2.5, 2.5)          # zoom 1: (13 - 10) - 0.5
    # an explicit pivot also wins over the stale one
    blob = pack_sprite(str(png), pal, header_bytes=old,
                       pivot_x=1.0, pivot_y=2.0)
    assert _pivot(blob) == (1.0, 2.0)


def test_reuse_recomputes_the_default_pivot_when_the_sprite_was_resized(tmp_path):
    """A header reused from a pack of the old size must not keep the old size's pivot."""
    from PIL import Image
    png, pal, old = _reuse_setup(tmp_path)          # header of an 8x8 sprite, pivot 7.5
    big = tmp_path / "big.png"
    Image.open(png).convert("RGBA").resize((12, 12), Image.NEAREST).save(big)
    blob = pack_sprite(str(big), pal, header_bytes=old)
    assert _pivot(blob) == (11.5, 11.5)             # the x2 default for 12x12, as a fresh header
    assert struct.unpack_from("<b", blob, HDR_OFF_RATE)[0] == 5   # the rate still survives


# ── 4. BOM manifest ─────────────────────────────────────────────────────────

def test_load_manifest_accepts_utf8_bom(tmp_path, minimal_manifest):
    from manifest_schema import load_manifest

    path = tmp_path / "bom.json"
    path.write_text(json.dumps(minimal_manifest), encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    m = load_manifest(path, strict=True)
    assert m.sprites[0].name == "coin"


# ── 5. case-insensitive PSD / !pack.txt lookup ──────────────────────────────

def test_glob_ci_and_find_pack_txt_ignore_case(tmp_path):
    from packtxt import find_pack_txt, glob_ci

    (tmp_path / "Hero_Assets.PSD").write_bytes(b"")
    (tmp_path / "map_a.psd").write_bytes(b"")
    (tmp_path / "x.png").write_bytes(b"")
    (tmp_path / "!PACK.TXT").write_text("exported\n", encoding="utf-8")
    names = [p.name for p in glob_ci(tmp_path, "*.psd")]
    assert names == ["Hero_Assets.PSD", "map_a.psd"]
    assert [p.name for p in glob_ci(tmp_path, "*assets*.psd")] == \
        ["Hero_Assets.PSD"]
    found = find_pack_txt(tmp_path)
    assert found is not None and found.name.lower() == "!pack.txt"


# ── 6. !pack.bat: quoted set, %~dp0 ─────────────────────────────────────────

def test_packbat_quoted_set_and_batch_dir_prefix(tmp_path):
    from packbat import ids_header_name, parse_pack_bat

    bat = tmp_path / "!pack.bat"
    bat.write_text(
        '@echo off\r\n'
        'set "app=app_quoted"\r\n'
        '"%~dp0psd.exe" "%~dp0hero-assets.psd" "%~dp0exported"\r\n'
        '%~dp0psd.exe %~dp0\\hud.psd exported -map\r\n'
        '%~dp0utils.exe "%~dp0!pack.txt" packed "%~dp0..\\src\\%app%_ids.h"\r\n',
        encoding="utf-8")
    pb = parse_pack_bat(bat)
    assert pb.variables["app"] == "app_quoted"
    assert pb.assets == ["hero-assets"]
    assert pb.maps == ["hud"]
    assert pb.exported_dir == "exported"
    assert pb.pack_config == "!pack.txt"
    assert ids_header_name(pb) == "app_quoted_ids.h"


# ── 7. APP_TITLE escapes ────────────────────────────────────────────────────

def test_app_title_c_escapes_are_resolved(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text(
        '#define APP_TITLE "Say \\"hi\\" \\\\ caf\\xC3\\xA9"\n'
        '#define APP_GUID1 0x1234\n', encoding="utf-8")
    assert pack_beta.read_app_defines(app_h)["title"] == 'Say "hi" \\ café'


def test_c_unescape_plain_text_unchanged():
    assert pack_beta.c_unescape("Orb Catch") == "Orb Catch"
    assert pack_beta.c_unescape(r"a\tb\101") == "a\tbA"


# ── 8. minor ────────────────────────────────────────────────────────────────

class _Layer:
    def __init__(self, name, img, visible=True):
        self.name, self._img, self.visible = name, img, visible
        self.left = self.top = 0

    def composite(self):
        return self._img


def test_hidden_pivot_layer_is_ignored():
    from pack_psd import find_pivot_markers

    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    img.putpixel((3, 3), (255, 0, 0, 255))
    assert find_pivot_markers([_Layer("~pivot", img, visible=False)]) == []
    assert find_pivot_markers([_Layer("~pivot", img)]) == [(3, 3, 1, 1)]


def test_rate_over_127_is_clamped_not_a_crash(capsys):
    from pack_psd import _pack_octplace

    hdr = build_header(8, 8, 8, 7, pidx=0, flags=1, rate=128)
    assert struct.unpack_from("<b", hdr, HDR_OFF_RATE)[0] == 127
    assert clamp_rate(200, "x") == 127 and clamp_rate(5) == 5
    place = _pack_octplace(0.0, 0.0, 8, 8, 1, 0, 0, 1, 128, 0, 0, 0, 0)
    assert struct.unpack_from("<b", place, 23)[0] == 127
    assert "clamped" in capsys.readouterr().out


def test_failed_emit_leaves_no_stale_ids_header(tmp_path):
    app = tmp_path / "app_x"
    ids = app / "src" / "app_x_ids.h"
    ids.parent.mkdir(parents=True)
    ids.write_text("// stale\n", encoding="ascii")
    with pytest.raises(Exception):
        pack_beta.emit_beta_layout(
            app, "app_x",
            full_sprites=[("gem", tmp_path / "missing.png", (8, 8), 0)])
    assert not ids.exists()


def test_unknown_pack_txt_tags_are_warned(tmp_path, capsys):
    import pack

    cfg = tmp_path / "!pack.txt"
    cfg.write_text("exported\n\n256\n<FULLSIZE><NOPE>\n*\n", encoding="utf-8")
    args = argparse.Namespace(no_pack_config=False, manifest=None,
                              pack_config=str(cfg), art_dir=str(tmp_path))
    pack._resolve_pack_config(args)
    out = capsys.readouterr().out
    assert "WARNING" in out and "<NOPE>" in out


def test_placeholder_is_packed_on_the_first_run(tmp_path, monkeypatch):
    import pack

    exported = tmp_path / "exported"
    exported.mkdir()
    _coin_png(exported / "coin.png")
    art = tmp_path / "art"
    art.mkdir()
    packed = tmp_path / "packed"
    monkeypatch.setattr(sys, "argv", [
        "pack.py", "--build-palette",
        "--exported-dir", str(exported), "--packed-dir", str(packed),
        "--output-dir", str(packed), "--art-dir", str(art),
        "--assets", "assets"])
    pack.main()
    assert (packed / "coin.png").is_file()
    assert (packed / "0.png").is_file()
