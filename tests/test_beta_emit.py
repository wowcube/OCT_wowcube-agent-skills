"""Tests for pack_beta.emit_beta_layout — the beta asset-container emit layer.

Fixtures are built entirely in tmp_path: palette-sprite payloads are
handcrafted legacy blobs (48-byte legacy octBmp_t + opaque payload bytes),
full-color sprites and the icon are tiny Pillow PNGs, the sound is a fake
mp3. The emit layer must not care about palette payload internals beyond
the 48-byte header.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

import pack_beta
from pack_beta import (
    KIND_SPRITE, KIND_SOUND, KIND_PAL, KIND_MAP,
    OCT_FLAG_ALPHA, OCT_FLAG_RAW565, OCT_FLAG_FULLSIZE,
    parse_bmp_header, read_index_bin, read_pal,
)


def legacy_sprite_blob(w: int, h: int, pidx: int, *, seq: int = 0, rate: int = 1,
                       flags: int = OCT_FLAG_ALPHA, payload: bytes | None = None) -> bytes:
    """Handcraft a legacy packed-sprite blob: 48-byte legacy octBmp_t
    (num_pixels @0, flags @44, pidx @45, seq @46, rate @47) + dummy payload."""
    if payload is None:
        payload = bytes(((h + 3) // 4) * 4) + b"\x12\x34\x56\x78" * w
    hdr = b"".join((
        struct.pack("<I", len(payload)),        # num_pixels (legacy only)
        struct.pack("<ff", 3.5, 4.5),           # pivot
        struct.pack("<ffff", 0.0, 0.0, 0.0, 0.0),
        struct.pack("<I", 0),                   # tags
        struct.pack("<I", (7 << 8) | 4),        # compression: off=7, sym=4
        struct.pack("<hh", w, h),
        struct.pack("<h", 0),                   # number
        struct.pack("<BB", 0, 0),               # group, type
        struct.pack("<BB", flags, pidx),        # legacy: flags @44, pidx @45
        struct.pack("<bb", seq, rate),          # legacy: seq @46, rate @47
    ))
    assert len(hdr) == 48
    return hdr + payload


PAL_A = [0x0000, 0xF800, 0x07E0, 0x001F]      # legacy pidx 0
PAL_B = [0x0000, 0xFFFF]                      # legacy pidx 1


@pytest.fixture
def emitted(tmp_path):
    app = tmp_path / "app_tiny"
    (app / "sound" / "assets").mkdir(parents=True)
    (app / "sound" / "assets" / "blip.mp3").write_bytes(b"ID3-fake-mp3-bytes")

    icon = tmp_path / "icon.png"
    Image.new("RGB", (200, 100), (10, 200, 30)).save(icon)

    bg_png = tmp_path / "bg.png"
    grad = Image.new("RGB", (32, 32))
    grad.putdata([(x * 8, y * 8, 128) for y in range(32) for x in range(32)])
    grad.save(bg_png)

    gem_png = tmp_path / "gem.png"
    Image.new("RGB", (16, 8), (255, 0, 0)).save(gem_png)

    sprites = [
        ("anim_00", legacy_sprite_blob(8, 4, 0)),
        ("anim_01", legacy_sprite_blob(8, 4, 0)),
        ("anim_02", legacy_sprite_blob(8, 4, 0)),
        ("coin", legacy_sprite_blob(6, 6, 1, rate=2)),
    ]
    records = pack_beta.emit_beta_layout(
        app, "app_tiny",
        palettes={0: PAL_A, 1: PAL_B},
        palette_sprites=sprites,
        full_sprites=[("bg", bg_png, (32, 32), OCT_FLAG_FULLSIZE),
                      ("gem", gem_png, (16, 8), 0)],
        icon=icon,
    )
    return app, records


def _packed(app: Path) -> Path:
    return app / "art" / "packed"


# ── record 0: zero sprite ────────────────────────────────────────────────────

def test_record_zero(emitted):
    app, records = emitted
    assert records[0] == (KIND_SPRITE, "zero")
    zero = _packed(app) / "zero.raw"
    assert zero.is_file()
    blob = zero.read_bytes()
    # byte-for-byte what the real toolchain packs: 48 bytes of pure zeros
    # (in particular rate @45 must be 0, not the builder's default 1)
    assert blob == b"\x00" * 48
    hdr = parse_bmp_header(blob)
    assert (hdr.w, hdr.h, hdr.flags, hdr.pidx, hdr.seq) == (0, 0, 0, 0, 0)


# ── palettes ─────────────────────────────────────────────────────────────────

def test_pal_records_and_files(emitted):
    app, records = emitted
    assert records[1] == (KIND_PAL, "1")
    assert records[2] == (KIND_PAL, "2")
    assert read_pal(_packed(app) / "1.pal") == PAL_A
    assert read_pal(_packed(app) / "2.pal") == PAL_B


def test_sprite_pidx_points_at_pal_record(emitted):
    app, records = emitted
    for name, want_pal in (("anim_00", 1), ("anim_01", 1), ("anim_02", 1),
                           ("coin", 2)):
        hdr = parse_bmp_header((_packed(app) / f"{name}.raw").read_bytes())
        assert hdr.pidx == want_pal, name
        assert records[hdr.pidx][0] == KIND_PAL


def test_patched_header_preserves_legacy_fields(emitted):
    app, _records = emitted
    raw = (_packed(app) / "coin.raw").read_bytes()
    hdr = parse_bmp_header(raw)
    assert (hdr.w, hdr.h) == (6, 6)
    assert hdr.flags == OCT_FLAG_ALPHA          # flags byte kept @44
    assert hdr.rate == 2                        # legacy rate moved @47 -> @45
    assert raw[46:48] == b"\x00\x00"            # beta reserved bytes
    assert hdr.compression == (7 << 8) | 4      # untouched
    # payload after the header is passed through opaque
    original = legacy_sprite_blob(6, 6, 1, rate=2)
    assert raw[48:len(original)] == original[48:]


def test_patch_palette_sprite_extra_flags():
    """extra_flags ORs manifest flag bits into the beta Flags byte (@44)
    without disturbing the legacy bits already there; the default of 0
    keeps the byte untouched (legacy no-manifest behaviour)."""
    blob = legacy_sprite_blob(6, 6, 0, flags=OCT_FLAG_ALPHA)
    patched = pack_beta.patch_palette_sprite(
        blob, pal_id=1, seq_id=0, extra_flags=OCT_FLAG_FULLSIZE)
    hdr = parse_bmp_header(patched)
    assert hdr.flags == OCT_FLAG_ALPHA | OCT_FLAG_FULLSIZE
    default = parse_bmp_header(pack_beta.patch_palette_sprite(blob, pal_id=1))
    assert default.flags == OCT_FLAG_ALPHA


def test_emit_palette_sprite_with_extra_flags(tmp_path):
    """A (name, blob, extra_flags) palette-sprite triple carries the extra
    flag bits into the written header — tier 2 (palette fullsize) wiring."""
    app = tmp_path / "app_pf"
    records = pack_beta.emit_beta_layout(
        app, "app_pf",
        palettes={0: PAL_A},
        palette_sprites=[
            ("panel", legacy_sprite_blob(8, 8, 0), OCT_FLAG_FULLSIZE),
            ("coin", legacy_sprite_blob(6, 6, 0)),   # 2-tuples still work
        ],
    )
    panel = parse_bmp_header((_packed(app) / "panel.raw").read_bytes())
    assert panel.flags & OCT_FLAG_FULLSIZE
    assert panel.flags & OCT_FLAG_ALPHA            # legacy bit preserved
    assert records[panel.pidx][0] == KIND_PAL
    coin = parse_bmp_header((_packed(app) / "coin.raw").read_bytes())
    assert not coin.flags & OCT_FLAG_FULLSIZE


# ── icon assets ──────────────────────────────────────────────────────────────

def test_icon_assets(emitted):
    app, records = emitted
    ico_idle_id = records.index((KIND_SPRITE, "ico_idle"))
    ico_id = records.index((KIND_MAP, "ico"))
    ahover_id = records.index((KIND_MAP, "ahover"))
    assert ico_id == ico_idle_id + 1 and ahover_id == ico_idle_id + 2
    assert ahover_id < pack_beta.EXT_MAX_DESCS

    hdr = parse_bmp_header((_packed(app) / "ico_idle.raw").read_bytes())
    assert (hdr.w, hdr.h) == (160, 160)
    assert hdr.flags & OCT_FLAG_RAW565
    assert hdr.flags & OCT_FLAG_FULLSIZE

    ico = (_packed(app) / "ico.raw").read_bytes()
    ahover = (_packed(app) / "ahover.raw").read_bytes()
    for blob in (ico, ahover):
        assert struct.unpack_from("<ii", blob, 0) == (1, 1)
        assert struct.unpack_from("<hh", blob, 20) == (160, 160)
        bmp_id, = struct.unpack_from("<h", blob, 24)
        assert bmp_id == ico_idle_id
    # ahover is the hover ANIMATION map: PLACE_LOOPED (1 << 1), matching the
    # golden app_hulk ahover.raw; ico stays static -- and the loop flag @28
    # is the ONLY difference between the two maps
    assert struct.unpack_from("<H", ico, 28)[0] == 0
    assert struct.unpack_from("<H", ahover, 28)[0] == (1 << 1)
    assert ahover[:28] == ico[:28] and ahover[30:] == ico[30:]


def test_no_icon_no_launcher_records(tmp_path):
    app = tmp_path / "app_bare"
    records = pack_beta.emit_beta_layout(
        app, "app_bare",
        palettes={0: PAL_A},
        palette_sprites=[("coin", legacy_sprite_blob(6, 6, 0))],
    )
    names = [n for _, n in records]
    for launcher_name in ("ico_idle", "ico", "ahover"):
        assert launcher_name not in names


def test_icon_past_launcher_window_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(pack_beta, "EXT_MAX_DESCS", 5)
    icon = tmp_path / "icon.png"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(icon)
    with pytest.raises(ValueError):
        # zero(0) + pals 1,2,3 -> ico_idle=4, ico=5 already past window of 5
        pack_beta.emit_beta_layout(
            tmp_path / "app_x", "app_x",
            palettes={0: PAL_A, 1: PAL_B, 2: PAL_B},
            icon=icon,
        )


# ── animation Seq chaining ───────────────────────────────────────────────────

def test_seq_chaining(emitted):
    app, records = emitted
    ids = {name: i for i, (kind, name) in enumerate(records) if kind == KIND_SPRITE}
    for cur, nxt in (("anim_00", "anim_01"), ("anim_01", "anim_02"),
                     ("anim_02", "anim_00")):
        hdr = parse_bmp_header((_packed(app) / f"{cur}.raw").read_bytes())
        assert hdr.seq == ids[nxt], cur
    static = parse_bmp_header((_packed(app) / "coin.raw").read_bytes())
    assert static.seq == 0


def test_seq_chaining_one_based_three_digit(tmp_path):
    """Video-cut frame sets are named <base>_001.. (3-digit, one-based).
    They must chain cyclically and get the BMP_<base>/_end aliases exactly
    like zero-based _00 groups; a stray _05-only group must stay static."""
    png = tmp_path / "f.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(png)
    app = tmp_path / "app_vid"
    records = pack_beta.emit_beta_layout(
        app, "app_vid",
        full_sprites=[("clip_001", png, (8, 8), 0),
                      ("clip_002", png, (8, 8), 0),
                      ("clip_003", png, (8, 8), 0),
                      ("stray_05", png, (8, 8), 0)],
    )
    ids = {name: i for i, (kind, name) in enumerate(records) if kind == KIND_SPRITE}
    packed = _packed(app)
    for cur, nxt in (("clip_001", "clip_002"), ("clip_002", "clip_003"),
                     ("clip_003", "clip_001")):
        hdr = parse_bmp_header((packed / f"{cur}.raw").read_bytes())
        assert hdr.seq == ids[nxt], cur
    stray = parse_bmp_header((packed / "stray_05.raw").read_bytes())
    assert stray.seq == 0

    text = (app / "src" / "app_vid_ids.h").read_text()
    assert f"BMP_clip = {ids['clip_001']}" in text
    assert f"BMP_clip_end = {ids['clip_003']}" in text
    assert "BMP_stray =" not in text and "BMP_stray_end" not in text


# ── full-color sprites ───────────────────────────────────────────────────────

def test_full_sprite_headers(emitted):
    app, _records = emitted
    bg = parse_bmp_header((_packed(app) / "bg.raw").read_bytes())
    assert (bg.w, bg.h) == (32, 32)
    assert bg.flags & OCT_FLAG_RAW565
    assert bg.flags & OCT_FLAG_FULLSIZE

    gem = parse_bmp_header((_packed(app) / "gem.raw").read_bytes())
    assert (gem.w, gem.h) == (16, 8)
    assert gem.flags & OCT_FLAG_RAW565
    assert not gem.flags & OCT_FLAG_FULLSIZE


def test_full_sprite_payload_decodes(emitted):
    app, _records = emitted
    raw = (_packed(app) / "gem.raw").read_bytes()
    hdr = parse_bmp_header(raw)
    payload = raw[48:]
    if hdr.compression == pack_beta.RAW565_RLE:
        texels = pack_beta.rle_decode(payload, hdr.w, hdr.h)
    else:
        texels = payload[:hdr.w * hdr.h * 2]
    expected = struct.pack("<H", 0xF800) * (hdr.w * hdr.h)   # solid red
    assert texels == expected


def _decoded_texels(raw: bytes) -> bytes:
    hdr = parse_bmp_header(raw)
    payload = raw[48:]
    if hdr.compression == pack_beta.RAW565_RLE:
        return pack_beta.rle_decode(payload, hdr.w, hdr.h)
    return payload[:hdr.w * hdr.h * 2]


def test_emit_full_sprite_dither_wiring(tmp_path):
    """A 5th full-sprite tuple element turns on Floyd-Steinberg dithering;
    4-tuples keep the plain nearest-level conversion."""
    png = tmp_path / "grad.png"
    grad = Image.new("RGB", (32, 32))
    grad.putdata([(x * 8 + 3, y * 8 + 3, 128) for y in range(32) for x in range(32)])
    grad.save(png)

    app = tmp_path / "app_dith"
    pack_beta.emit_beta_layout(
        app, "app_dith",
        full_sprites=[("plain", png, (32, 32), 0),
                      ("dithered", png, (32, 32), 0, True)],
    )
    plain = _decoded_texels((_packed(app) / "plain.raw").read_bytes())
    dithered = _decoded_texels((_packed(app) / "dithered.raw").read_bytes())
    with Image.open(png) as img:
        assert plain == pack_beta.to_rgb565(img, (32, 32))
        assert dithered == pack_beta.to_rgb565(img, (32, 32), dither=True)
    assert plain != dithered


# ── sounds ───────────────────────────────────────────────────────────────────

def test_sound_record(emitted):
    app, records = emitted
    assert records[-1] == (KIND_SOUND, "blip")
    assert not (_packed(app) / "blip.raw").exists()
    assert (app / "sound" / "assets" / "blip.mp3").read_bytes() == b"ID3-fake-mp3-bytes"


# ── index.bin ────────────────────────────────────────────────────────────────

def test_index_bin_roundtrip_and_payloads(emitted):
    app, records = emitted
    assert read_index_bin(app / "index.bin") == records
    for kind, name in records:
        if kind in (KIND_SPRITE, KIND_MAP):
            f = _packed(app) / f"{name}.raw"
            assert f.is_file(), name
            assert f.stat().st_size > 0
            assert f.stat().st_size % 4 == 0, name
        elif kind == KIND_PAL:
            assert (_packed(app) / f"{name}.pal").is_file(), name


def test_expected_record_order(emitted):
    _app, records = emitted
    assert records == [
        (KIND_SPRITE, "zero"),
        (KIND_PAL, "1"),
        (KIND_PAL, "2"),
        (KIND_SPRITE, "ico_idle"),
        (KIND_MAP, "ico"),
        (KIND_MAP, "ahover"),
        (KIND_SPRITE, "anim_00"),
        (KIND_SPRITE, "anim_01"),
        (KIND_SPRITE, "anim_02"),
        (KIND_SPRITE, "coin"),
        (KIND_SPRITE, "bg"),
        (KIND_SPRITE, "gem"),
        (KIND_SOUND, "blip"),
    ]


def test_duplicate_raw_name_raises(tmp_path):
    icon = tmp_path / "icon.png"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(icon)
    with pytest.raises(ValueError):
        pack_beta.emit_beta_layout(
            tmp_path / "app_dup", "app_dup",
            palettes={0: PAL_A},
            palette_sprites=[("ico", legacy_sprite_blob(4, 4, 0))],
            icon=icon,
        )


# ── kind-aware ids header ────────────────────────────────────────────────────

def test_ids_header(emitted):
    app, records = emitted
    ids_file = app / "src" / "app_tiny_ids.h"
    assert ids_file.is_file()
    text = ids_file.read_text()

    assert "enum BMP { BMP_none = 0," in text.replace("\n", " ")
    assert "BMP_none = 0" in text
    ids = {name: i for i, (_k, name) in enumerate(records)}
    for name in ("anim_00", "anim_01", "anim_02", "coin", "bg", "gem", "ico_idle"):
        assert f"BMP_{name} = {ids[name]}" in text, name
    # animation aliases: base = first frame, _end = last frame
    assert f"BMP_anim = {ids['anim_00']}" in text
    assert f"BMP_anim_end = {ids['anim_02']}" in text
    # kind-aware MAP enum
    assert "enum MAP { MAP_none = 0," in text.replace("\n", " ")
    assert f"MAP_ico = {ids['ico']}" in text
    assert f"MAP_ahover = {ids['ahover']}" in text
    assert "MAP_last" in text and "BMP_last" in text
    # sounds share the id space, exposed as SND_
    assert f"SND_blip = {ids['blip']}" in text
    # no BMP_zero leak: record 0 is covered by BMP_none
    assert "BMP_zero" not in text


def test_ids_header_duplicate_identifier_raises():
    # a static sprite named "anim" next to an anim_00/_01 sequence generates
    # the BMP_anim alias on top of the real BMP_anim — must fail loudly
    records = [(KIND_SPRITE, "zero"), (KIND_SPRITE, "anim"),
               (KIND_SPRITE, "anim_00"), (KIND_SPRITE, "anim_01")]
    with pytest.raises(ValueError, match="duplicate enum identifier"):
        pack_beta.generate_beta_ids_h(records)


def test_ids_header_digit_leading_name_ok():
    # the BMP_/SND_ prefix supplies the leading letter, so digit-leading
    # asset names ("000", "1up") are valid — the shipped template uses them
    records = [(KIND_SPRITE, "zero"), (KIND_SPRITE, "000"), (KIND_SOUND, "1up")]
    text = pack_beta.generate_beta_ids_h(records)
    assert "BMP_000 = 1" in text
    assert "SND_1up = 2" in text


def test_ids_header_invalid_char_name_raises():
    records = [(KIND_SPRITE, "zero"), (KIND_SPRITE, "coin-gold")]
    with pytest.raises(ValueError, match="not a valid C enum identifier"):
        pack_beta.generate_beta_ids_h(records)


# ── pack.py wiring ───────────────────────────────────────────────────────────

def test_pack_py_emits_beta_container(tmp_path, monkeypatch):
    import pack

    exported = tmp_path / "exported"
    exported.mkdir()
    coin = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            coin.putpixel((x, y), (250, 200, 20, 255))
    coin.save(exported / "coin.png")
    Image.new("RGB", (16, 16), (30, 60, 200)).save(exported / "bg.png")
    Image.new("RGBA", (8, 8), (60, 90, 120, 255)).save(exported / "panel.png")

    art = tmp_path / "art"
    art.mkdir()
    Image.new("RGB", (64, 64), (10, 200, 30)).save(art / "icon.png")

    manifest = tmp_path / "tiny_assets.json"
    manifest.write_text(
        '{"game": "tiny", "schema_version": 1, "sprites": ['
        '{"name": "coin", "size": [8, 8], "description": "coin"},'
        '{"name": "panel", "size": [8, 8], "description": "palette fullsize",'
        ' "flags": {"fullsize": true, "additive": true}},'
        '{"name": "bg", "size": [16, 16], "description": "bg", "dither": true,'
        ' "color": "full", "flags": {"alpha": false, "fullsize": false}}'
        '], "sounds": [{"name": "blip", "description": "b"}]}',
        encoding="utf-8")

    app = tmp_path / "app_tiny"
    (app / "sound" / "assets").mkdir(parents=True)
    (app / "sound" / "assets" / "blip.mp3").write_bytes(b"mp3")

    packed = tmp_path / "packed"
    monkeypatch.setattr(sys, "argv", [
        "pack.py", "--build-palette",
        "--exported-dir", str(exported),
        "--packed-dir", str(packed),
        "--output-dir", str(packed),
        "--art-dir", str(art),
        "--assets", "assets",
        "--beta-app-dir", str(app),
        "--app-name", "app_tiny",
        "--manifest", str(manifest),
    ])
    pack.main()

    records = read_index_bin(app / "index.bin")
    assert records[0] == (KIND_SPRITE, "zero")
    kinds = {name: kind for kind, name in records}
    assert kinds["coin"] == KIND_SPRITE
    assert kinds["bg"] == KIND_SPRITE
    assert kinds["blip"] == KIND_SOUND
    assert kinds["ico"] == KIND_MAP and kinds["ahover"] == KIND_MAP
    assert KIND_PAL in {k for k, _n in records}

    packed_dir = app / "art" / "packed"
    ids = {name: i for i, (_k, name) in enumerate(records)}

    # palette sprite got its Pidx patched to a PAL asset id
    coin_hdr = parse_bmp_header((packed_dir / "coin.raw").read_bytes())
    assert records[coin_hdr.pidx][0] == KIND_PAL
    # ...and no manifest flags leak onto a sprite that didn't ask for any
    assert not coin_hdr.flags & pack_beta.OCT_FLAG_FULLSIZE

    # manifest flags.fullsize/additive reach the PALETTE sprite's beta header
    panel_hdr = parse_bmp_header((packed_dir / "panel.raw").read_bytes())
    assert records[panel_hdr.pidx][0] == KIND_PAL
    assert panel_hdr.flags & pack_beta.OCT_FLAG_FULLSIZE
    assert panel_hdr.flags & pack_beta.OCT_FLAG_ADDITIVE
    assert not panel_hdr.flags & OCT_FLAG_RAW565    # still palette-encoded

    # full-color sprite is RAW565 at manifest size, not palette-packed
    bg_raw = (packed_dir / "bg.raw").read_bytes()
    bg_hdr = parse_bmp_header(bg_raw)
    assert bg_hdr.flags & OCT_FLAG_RAW565
    assert (bg_hdr.w, bg_hdr.h) == (16, 16)
    assert not bg_hdr.flags & OCT_FLAG_FULLSIZE

    # ...and the manifest's "dither": true reached to_rgb565 through pack.py
    with Image.open(exported / "bg.png") as bg_img:
        expected = pack_beta.to_rgb565(bg_img, (16, 16), dither=True)
    assert _decoded_texels(bg_raw) == expected

    # icon maps point at ico_idle
    ico = (packed_dir / "ico.raw").read_bytes()
    assert struct.unpack_from("<h", ico, 24)[0] == ids["ico_idle"]

    header = (app / "src" / "app_tiny_ids.h").read_text()
    assert f"BMP_coin = {ids['coin']}" in header
    assert f"BMP_bg = {ids['bg']}" in header
    assert f"SND_blip = {ids['blip']}" in header

    # legacy outputs keep being written
    assert (packed / "pal.png").is_file()
    assert (packed / "coin.png").is_file()


def test_pack_py_beta_overwrites_legacy_emit_raw(tmp_path, monkeypatch):
    """--emit-raw AND --beta-app-dir into the same art/packed dir: the beta
    emit phase must run AFTER the legacy raw phase, so the .raw that survives
    is the beta-format one. Pins the phase order in pack.main() — the
    scaffolders no longer combine the two flags, but callers still may."""
    import pack

    exported = tmp_path / "exported"
    exported.mkdir()
    coin = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y in range(2, 6):
        for x in range(2, 6):
            coin.putpixel((x, y), (250, 200, 20, 255))
    coin.save(exported / "coin.png")

    art = tmp_path / "art"
    art.mkdir()

    app = tmp_path / "app_tiny"
    packed = app / "art" / "packed"
    monkeypatch.setattr(sys, "argv", [
        "pack.py", "--build-palette",
        "--exported-dir", str(exported),
        "--packed-dir", str(packed),
        "--output-dir", str(packed),
        "--art-dir", str(art),
        "--assets", "assets",
        "--emit-raw", "--raw-dir", str(packed),
        "--beta-app-dir", str(app),
        "--app-name", "app_tiny",
    ])
    pack.main()

    records = read_index_bin(app / "index.bin")
    hdr = parse_bmp_header((packed / "coin.raw").read_bytes())
    # Beta header: Pidx @0 is a PAL asset id. The legacy _phase_emit_raw
    # writes decoded-PNG-strip .raw whose first 4 bytes are the legacy
    # num_pixels u32 — if that version survived, Pidx would be a garbage
    # low word of a byte count, not a valid KIND_PAL record index.
    assert 0 < hdr.pidx < len(records)
    assert records[hdr.pidx][0] == KIND_PAL
    assert (hdr.w, hdr.h) == (8, 8)


def test_pack_py_export_wipe_of_png_workflow_fails_loudly(tmp_path, monkeypatch, capsys):
    """The classic plain-PNG-workflow trap: sprites pre-placed in the exported
    dir, then --export (which is PSD-only) wipes them. This must fail with
    exit 1 and actionable text, not 'succeed' (exit 0) over an empty pack —
    that silent success is exactly what stranded agents on the palette path."""
    import pack

    exported = tmp_path / "exported"
    exported.mkdir()
    Image.new("RGBA", (8, 8), (250, 200, 20, 255)).save(exported / "coin.png")

    art = tmp_path / "art"   # no .psd here — nothing for --export to export
    art.mkdir()

    monkeypatch.setattr(sys, "argv", [
        "pack.py", "--export", "--build-palette",
        "--exported-dir", str(exported),
        "--packed-dir", str(tmp_path / "packed"),
        "--output-dir", str(tmp_path / "packed"),
        "--art-dir", str(art),
        "--assets", "assets",
    ])
    with pytest.raises(SystemExit) as exc:
        pack.main()
    assert exc.value.code == 1

    out = capsys.readouterr().out
    # export phase warns that it destroyed pre-placed PNGs...
    assert "WARNING: --export cleaned" in out
    # ...and the pack phase names the fix instead of raising StopIteration
    assert "WITHOUT --export" in out
    assert "StopIteration" not in out


def test_pack_py_sprite_error_exits_nonzero(tmp_path, monkeypatch):
    """A sprite that fails to pack means a missing .raw in the container:
    pack.py must exit non-zero, not print [ERR] and report success."""
    import pack

    exported = tmp_path / "exported"
    exported.mkdir()
    Image.new("RGBA", (8, 8), (250, 200, 20, 255)).save(exported / "coin.png")

    art = tmp_path / "art"
    art.mkdir()

    def boom(*a, **kw):
        raise ValueError("synthetic pack failure")

    monkeypatch.setattr(pack, "pack_sprite", boom)
    monkeypatch.setattr(sys, "argv", [
        "pack.py", "--build-palette",
        "--exported-dir", str(exported),
        "--packed-dir", str(tmp_path / "packed"),
        "--output-dir", str(tmp_path / "packed"),
        "--art-dir", str(art),
        "--assets", "assets",
    ])
    with pytest.raises(SystemExit) as exc:
        pack.main()
    assert exc.value.code == 1


# ── build_pipeline wiring ────────────────────────────────────────────────────

def test_build_pipeline_passes_beta_args(tmp_path, monkeypatch):
    import build_pipeline

    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append([str(c) for c in cmd])
        return 0

    monkeypatch.setattr(build_pipeline, "_run", fake_run)

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    packed = workspace / "packed"
    packed.mkdir()
    (packed / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    # _run is faked, so pre-create the kind-aware header pack.py would emit
    (tmp_path / "app_tiny" / "src").mkdir(parents=True)
    (tmp_path / "app_tiny" / "src" / "app_tiny_ids.h").write_text(
        "enum BMP { BMP_none = 0, BMP_last};")

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
        "--app-dir", str(tmp_path / "app_tiny"),
        "--manifest", str(tmp_path / "tiny_assets.json"),
    ])
    assert rc == 0
    pack_cmd = calls[1]
    assert "--beta-app-dir" in pack_cmd
    assert pack_cmd[pack_cmd.index("--beta-app-dir") + 1] == str(tmp_path / "app_tiny")
    assert pack_cmd[pack_cmd.index("--app-name") + 1] == "app_tiny"
    assert pack_cmd[pack_cmd.index("--manifest") + 1] == str(tmp_path / "tiny_assets.json")


def test_build_pipeline_omits_beta_args_without_app_dir(tmp_path, monkeypatch):
    import build_pipeline

    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append([str(c) for c in cmd])
        return 0

    monkeypatch.setattr(build_pipeline, "_run", fake_run)

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    packed = workspace / "packed"
    packed.mkdir()
    (packed / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
    ])
    assert rc == 0
    assert "--beta-app-dir" not in calls[1]
