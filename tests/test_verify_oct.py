"""Mandatory .oct verification (pack_beta.verify_oct / --verify-oct, called by
scripts/build_device.*) and the OCT_ASSETS_CAP boundary.

The fixture app is built with the pack_beta primitives (same shapes as
tests/test_build_oct.py) plus a dev-layout src/app.h -> app_metadata.h ->
app_save.h, so the verifier compares the header against real defines.
"""
from __future__ import annotations

import json
import struct
import zlib

import pytest
from PIL import Image

import pack_beta
from pack_beta import (
    ASSETS_CAP, ASSETS_CAP_OLD_FIRMWARE, KIND_MAP, KIND_SPRITE, OCT_FLAG_FULLSIZE,
    build_index_bin, build_oct, read_index_bin, read_oct_assets, read_oct_header, verify_oct,
)

CODE = bytes(range(256)) * 3 + b"\x11\x22"
BUILD_ID = bytes(range(0x40, 0x54))
GUID = 0x8899AABBCCDDEEFF


def _elf(build_id: bytes) -> bytes:
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id
    shdr = bytearray(40)
    struct.pack_into("<I", shdr, 4, 7)
    struct.pack_into("<I", shdr, 16, 92)
    struct.pack_into("<I", shdr, 20, len(note))
    ehdr = bytearray(52)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 1
    ehdr[5] = 1
    struct.pack_into("<I", ehdr, 32, 52)
    struct.pack_into("<H", ehdr, 46, 40)
    struct.pack_into("<H", ehdr, 48, 1)
    return bytes(ehdr) + bytes(shdr) + note


def _legacy_blob(w: int, h: int) -> bytes:
    payload = bytes(((h + 3) // 4) * 4) + b"\x12\x34\x56\x78" * w
    hdr = b"".join((struct.pack("<I", len(payload)), struct.pack("<ff", 3.5, 4.5), bytes(16), struct.pack("<I", 0),
                    struct.pack("<I", (7 << 8) | 4), struct.pack("<hh", w, h), struct.pack("<h", 0),
                    struct.pack("<BB", 0, 0), struct.pack("<BB", 0, 0), struct.pack("<bb", 0, 1)))
    return hdr + payload


METADATA = """#pragma once
#include "oct_app_version.h"
#include "oct_app_categories.h"
#define APP_VERSION_MAJOR 1
#define APP_VERSION_MINOR 2
#define APP_VERSION_PATCH 3
#define APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, APP_VERSION_MINOR, APP_VERSION_PATCH)
#define APP_GUID1 0x8899AABBCCDDEEFFULL
#define APP_TITLE "Orb Catch"
#define APP_CATEGORIES (APP_CATEGORY_GAME)
#define APP_COLORS 0x00000000
#include "app_save.h"
"""
SAVE = """#pragma once
typedef struct { unsigned magic; unsigned short version, size; unsigned best; } saveRecord_t;
static_assert(sizeof(saveRecord_t) == 12, "wire size");
#define APP_SAVE_SIZE sizeof(saveRecord_t)
"""


@pytest.fixture
def app(tmp_path):
    app_dir = tmp_path / "app_vfy"
    (app_dir / "sound" / "assets").mkdir(parents=True)
    (app_dir / "sound" / "assets" / "blip.mp3").write_bytes(b"ID3-fake-mp3!")
    (app_dir / "app_vfy.target").write_text("")
    icon = tmp_path / "icon.png"
    Image.new("RGB", (32, 32), (10, 200, 30)).save(icon)
    gem = tmp_path / "gem.png"
    Image.new("RGB", (16, 8), (255, 0, 0)).save(gem)
    pack_beta.emit_beta_layout(app_dir, "app_vfy", palettes={0: [0, 0xF800, 0x07E0, 0x001F]},
                               palette_sprites=[("coin_00", _legacy_blob(8, 4)), ("coin_01", _legacy_blob(8, 4))],
                               full_sprites=[("gem", gem, (16, 8), OCT_FLAG_FULLSIZE)], icon=icon, icon_side=16)
    src = app_dir / "src"
    (src / "app.h").write_text('#pragma once\n#include "app_metadata.h"\n#include "app_vfy.h"\n', encoding="utf-8")
    (src / "app_metadata.h").write_text(METADATA, encoding="utf-8")
    (src / "app_save.h").write_text(SAVE, encoding="utf-8")
    (app_dir / "out").mkdir()
    (app_dir / "out" / "app_vfy.bin").write_bytes(CODE)
    (app_dir / "out" / "app_vfy.elf").write_bytes(_elf(BUILD_ID))
    return app_dir


@pytest.fixture
def oct_file(app, tmp_path):
    return build_oct(app, app / "out" / "app_vfy.bin", tmp_path / "dist" / "app_vfy.oct")


def _patch(path, off, fmt, value, *, fix_crc=True):
    b = bytearray(path.read_bytes())
    struct.pack_into(fmt, b, off, value)
    if fix_crc:
        size = struct.unpack_from("<I", b, 52)[0]
        struct.pack_into("<I", b, 4, zlib.crc32(bytes(b[8:size])) & 0xFFFFFFFF)
    path.write_bytes(bytes(b))


def _errors(oct_file, app, **kw):
    errors, _warnings, _hdr = verify_oct(oct_file, app, **kw)
    return errors


# ── a good pack verifies; the header reader matches the writer ────────────────

def test_good_pack_verifies(oct_file, app):
    errors, warnings, header = verify_oct(oct_file, app)
    assert errors == [] and warnings == []
    assert header["title"] == "Orb Catch" and header["guid1"] == GUID
    assert pack_beta.semver_str(header["app_version"]) == "1.2.3"
    assert header["save_size"] == 12 and header["build_id"] == BUILD_ID.hex()


def test_header_reader_mirrors_the_writer(oct_file, app):
    blob = oct_file.read_bytes()
    h = read_oct_header(blob)
    assert h["magic"] == "cc0000bb" and h["size"] == len(blob)
    assert h["crc"] == zlib.crc32(blob[8:]) & 0xFFFFFFFF
    assets = read_oct_assets(blob, h)
    assert [(a["kind"], a["name"]) for a in assets] == \
        [(pack_beta._KIND_NAMES[k], n) for k, n in read_index_bin(app / "index.bin")]


# ── every check fails loudly ──────────────────────────────────────────────────

def test_bad_crc_fails(oct_file, app):
    _patch(oct_file, 4, "<I", 0xDEADBEEF, fix_crc=False)
    assert any("CRC32" in e for e in _errors(oct_file, app))


def test_truncated_pack_fails(oct_file, app):
    oct_file.write_bytes(oct_file.read_bytes()[:-3])
    errors = _errors(oct_file, app)
    assert any("Size" in e for e in errors) and any("ARM" in e or "code" in e for e in errors)


def test_wrong_magic_fails(oct_file, app):
    _patch(oct_file, 0, "<I", 0x11223344)
    assert any("magic" in e for e in _errors(oct_file, app))


def test_code_tail_must_be_the_bin(oct_file, app):
    (app / "out" / "app_vfy.bin").write_bytes(CODE[:-1] + b"\x99")
    assert any("does NOT end with" in e for e in _errors(oct_file, app))


def test_zero_build_id_fails_for_every_builder(oct_file, app):
    b = bytearray(oct_file.read_bytes())
    b[164:184] = bytes(20)
    struct.pack_into("<I", b, 4, zlib.crc32(bytes(b[8:])) & 0xFFFFFFFF)
    oct_file.write_bytes(bytes(b))
    assert any("build id" in e for e in _errors(oct_file, app))


@pytest.mark.parametrize("off,fmt,value,word", [
    (16, "<Q", 0x1111, "GUID"),
    (32, "<I", (1 << 24) | (1 << 16) | (2 << 8) | 2, "version"),
    (44, "<I", 4, "categories"),
    (184, "<I", 0, "save size"),
])
def test_metadata_must_match_the_app_defines(oct_file, app, off, fmt, value, word):
    _patch(oct_file, off, fmt, value)
    assert any(word in e for e in _errors(oct_file, app))


def test_title_must_match(oct_file, app):
    b = bytearray(oct_file.read_bytes())
    b[56:136] = b"Other".ljust(80, b"\0")
    struct.pack_into("<I", b, 4, zlib.crc32(bytes(b[8:])) & 0xFFFFFFFF)
    oct_file.write_bytes(bytes(b))
    assert any("title" in e for e in _errors(oct_file, app))


def test_stale_pack_against_index_bin_fails(oct_file, app):
    records = read_index_bin(app / "index.bin")
    (app / "index.bin").write_bytes(build_index_bin(records + [(KIND_SPRITE, "extra")]))
    assert any("index.bin" in e for e in _errors(oct_file, app))


def test_missing_ico_map_fails(app, tmp_path):
    records = [r for r in read_index_bin(app / "index.bin") if r != (KIND_MAP, "ico")]
    (app / "index.bin").write_bytes(build_index_bin(records))
    out = build_oct(app, app / "out" / "app_vfy.bin", tmp_path / "noico.oct")
    assert any("MAP 'ico'" in e for e in _errors(out, app))


def test_cannot_verify_is_a_failure(oct_file, app):
    (app / "src" / "app.h").unlink()
    assert any("cannot verify" in e for e in _errors(oct_file, app))
    errors = _errors(oct_file, app, code_bin=app / "out" / "missing.bin")
    assert any("cannot verify the ARM code" in e for e in errors)


def test_unparsable_define_is_a_failure(oct_file, app):
    md = app / "src" / "app_metadata.h"
    md.write_text(md.read_text(encoding="utf-8").replace("(APP_CATEGORY_GAME)", "(APP_CATEGORY_BOGUS)"),
                  encoding="utf-8")
    assert any("cannot verify the metadata" in e for e in _errors(oct_file, app))


def test_zero_guid_is_only_a_warning(app, tmp_path):
    md = app / "src" / "app_metadata.h"
    md.write_text(md.read_text(encoding="utf-8").replace("0x8899AABBCCDDEEFFULL", "0x0000000000000000"),
                  encoding="utf-8")
    out = build_oct(app, app / "out" / "app_vfy.bin", tmp_path / "zero.oct")
    errors, warnings, _ = verify_oct(out, app)
    assert errors == [] and any("APP_GUID1 is 0" in w for w in warnings)


def test_test_category_macro_is_known(app, tmp_path):
    md = app / "src" / "app_metadata.h"
    md.write_text(md.read_text(encoding="utf-8").replace("(APP_CATEGORY_GAME)", "(APP_CATEGORY_TEST)"),
                  encoding="utf-8")
    assert pack_beta.read_app_defines(app / "src" / "app.h")["categories"] == 1 << 6
    out = build_oct(app, app / "out" / "app_vfy.bin", tmp_path / "test.oct")
    assert _errors(out, app) == []


# ── octpack-info JSON path (header with engine-answered offsets) ───────────────

def _octpack_info(oct_file) -> dict:
    blob = oct_file.read_bytes()
    header = read_oct_header(blob)
    return {"header": header, "assets": read_oct_assets(blob, header)}


def test_octpack_info_header_is_used_and_checked(oct_file, app, tmp_path):
    info = _octpack_info(oct_file)
    assert _errors(oct_file, app, info=info) == []
    info["header"]["title"] = "Something else"
    info["assets"] = [a for a in info["assets"] if a["name"] != "ico"]
    errors = _errors(oct_file, app, info=info)
    assert any("title" in e for e in errors) and any("MAP 'ico'" in e for e in errors)


# ── CLI (what build_device runs) ──────────────────────────────────────────────

def test_cli_verify_ok_prints_version(oct_file, app, capsys):
    rc = pack_beta.main(["--verify-oct", str(oct_file), "--app-dir", str(app)])
    out = capsys.readouterr().out
    assert rc == 0 and "VERIFY OK" in out and "VERSION=1.2.3" in out and "local header check" in out


def test_cli_verify_with_info_json(oct_file, app, tmp_path, capsys):
    info = tmp_path / "info.json"
    info.write_text("﻿" + json.dumps(_octpack_info(oct_file)), encoding="utf-8")   # PS 5.1 writes a BOM
    rc = pack_beta.main(["--verify-oct", str(oct_file), "--app-dir", str(app), "--info-json", str(info)])
    assert rc == 0 and "octpack-info" in capsys.readouterr().out


def test_cli_verify_failure_exit_1(oct_file, app, capsys):
    _patch(oct_file, 4, "<I", 1, fix_crc=False)
    rc = pack_beta.main(["--verify-oct", str(oct_file), "--app-dir", str(app)])
    out = capsys.readouterr().out
    assert rc == 1 and "VERIFY FAILED" in out and "ERROR:" in out


def test_cli_build_still_needs_code_and_out(app):
    with pytest.raises(SystemExit):
        pack_beta.main(["--build-oct", "--app-dir", str(app)])


# ── OCT_ASSETS_CAP: 5120 on octavios dev (older firmware: 2048) ───────────────

def test_assets_cap_is_the_dev_value():
    assert ASSETS_CAP == 5120 and ASSETS_CAP_OLD_FIRMWARE == 2048


def test_index_bin_accepts_exactly_the_cap_and_rejects_one_more():
    records = [(KIND_SPRITE, f"s{i}") for i in range(ASSETS_CAP)]
    assert len(read_index_bin_bytes(build_index_bin(records))) == ASSETS_CAP
    with pytest.raises(ValueError, match="5120"):
        build_index_bin(records + [(KIND_SPRITE, "one_more")])


def test_old_firmware_count_now_packs(tmp_path, capsys):
    """2049 records were refused before; every kind counts toward the cap."""
    app_dir = tmp_path / "app_big"
    sounds = [f"snd{i}" for i in range(ASSETS_CAP_OLD_FIRMWARE)]       # + zero + 1 pal + 1 sprite > 2048
    records = pack_beta.emit_beta_layout(app_dir, "app_big", palettes={0: [0, 1]},
                                         palette_sprites=[("dot", _legacy_blob(4, 4))], sounds=sounds)
    assert len(records) > ASSETS_CAP_OLD_FIRMWARE
    assert "needs dev firmware" in capsys.readouterr().out


def test_build_oct_rejects_an_index_over_the_cap(app, tmp_path):
    records = read_index_bin(app / "index.bin")
    filler = [(KIND_SPRITE, f"f{i}") for i in range(ASSETS_CAP - len(records) + 1)]
    blob = struct.pack("<i", len(records) + len(filler)) + b"".join(
        pack_beta.INDEX_RECORD.pack(k, n.encode()) for k, n in records + filler)
    (app / "index.bin").write_bytes(blob)
    with pytest.raises(ValueError, match="OCT_ASSETS_CAP"):
        build_oct(app, app / "out" / "app_vfy.bin", tmp_path / "x.oct")


def read_index_bin_bytes(blob: bytes) -> list:
    count, = struct.unpack_from("<i", blob, 0)
    return [pack_beta.INDEX_RECORD.unpack_from(blob, 4 + i * pack_beta.INDEX_RECORD.size) for i in range(count)]
