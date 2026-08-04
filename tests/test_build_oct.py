"""Tests for pack_beta.build_oct — the pure-python .oct pack assembler.

Layout ground truth is the beta simulator's SIM_build_pack (octavios/sim/
src/sim.h) and engine/oct_pack.h: 232-byte octPackHeader_t, 84-byte
octAssetDesc_t table in index.bin id order, 4-byte-aligned payloads, ARM
code as the final chunk, CRC32 over bytes 8..Size stored at offset 4.

Fixtures synthesize a tiny app dir with the pack_beta emit primitives (the
same shapes tests/test_beta_emit.py uses), so no real toolchain output is
needed. The byte-for-byte comparison against a real simulator-built .oct is
a manual E2E step (see the part-2 plan, Task 2), not a pytest.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image

import pack_beta
from pack_beta import (
    KIND_SPRITE, KIND_SOUND, KIND_PAL, KIND_MAP,
    OCT_FLAG_FULLSIZE,
    OCT_HEADER_SIZE, OCT_DESC_SIZE, BMP_SIZE,
    build_oct, extract_gnu_build_id, read_app_defines, read_index_bin,
)

PAL_A = [0x0000, 0xF800, 0x07E0, 0x001F]
CODE = bytes(range(256)) * 5 + b"\x7f"          # odd length on purpose
GUID = 0xDEADBEEF12345678
BUILD_ID = bytes(range(0xA0, 0xB4))             # 20 bytes


def legacy_sprite_blob(w: int, h: int, pidx: int) -> bytes:
    """Minimal legacy packed-sprite blob (same shape test_beta_emit uses)."""
    payload = bytes(((h + 3) // 4) * 4) + b"\x12\x34\x56\x78" * w
    hdr = b"".join((
        struct.pack("<I", len(payload)),
        struct.pack("<ff", 3.5, 4.5),
        struct.pack("<ffff", 0.0, 0.0, 0.0, 0.0),
        struct.pack("<I", 0),
        struct.pack("<I", (7 << 8) | 4),
        struct.pack("<hh", w, h),
        struct.pack("<h", 0),
        struct.pack("<BB", 0, 0),
        struct.pack("<BB", 0, pidx),
        struct.pack("<bb", 0, 1),
    ))
    return hdr + payload


def make_elf_with_build_id(build_id: bytes) -> bytes:
    """Little-endian ELF32 whose single SHT_NOTE section carries the GNU
    build-id, matching what SIM_extract_gnu_build_id parses."""
    note = struct.pack("<III", 4, len(build_id), 3) + b"GNU\0" + build_id
    shdr = bytearray(40)
    struct.pack_into("<I", shdr, 4, 7)              # sh_type = SHT_NOTE
    struct.pack_into("<I", shdr, 16, 92)            # sh_offset
    struct.pack_into("<I", shdr, 20, len(note))     # sh_size
    ehdr = bytearray(52)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 1                                     # ELFCLASS32
    ehdr[5] = 1                                     # ELFDATA2LSB
    struct.pack_into("<I", ehdr, 32, 52)            # e_shoff
    struct.pack_into("<H", ehdr, 46, 40)            # e_shentsize
    struct.pack_into("<H", ehdr, 48, 1)             # e_shnum
    return bytes(ehdr) + bytes(shdr) + note


@pytest.fixture
def app(tmp_path):
    """Tiny but complete beta app dir: pal, icon+maps, sprites, a sound,
    an ARM code blob and an ELF carrying a known build-id."""
    app_dir = tmp_path / "app_tiny"
    (app_dir / "sound" / "assets").mkdir(parents=True)
    (app_dir / "sound" / "assets" / "blip.mp3").write_bytes(b"ID3-fake-mp3!")

    icon = tmp_path / "icon.png"
    Image.new("RGB", (64, 64), (10, 200, 30)).save(icon)
    gem = tmp_path / "gem.png"
    Image.new("RGB", (16, 8), (255, 0, 0)).save(gem)

    pack_beta.emit_beta_layout(
        app_dir, "app_tiny",
        palettes={0: PAL_A},
        palette_sprites=[("coin_00", legacy_sprite_blob(8, 4, 0)),
                         ("coin_01", legacy_sprite_blob(8, 4, 0))],
        full_sprites=[("gem", gem, (16, 8), OCT_FLAG_FULLSIZE)],
        icon=icon, icon_side=16,
    )

    out = app_dir / "out"
    out.mkdir()
    (out / "app_tiny.bin").write_bytes(CODE)
    (out / "app_tiny.elf").write_bytes(make_elf_with_build_id(BUILD_ID))
    return app_dir


def built(app_dir, **kwargs):
    kwargs.setdefault("title", "TINY")
    kwargs.setdefault("guid1", GUID)
    kwargs.setdefault("app_version", 7)
    out = app_dir / "pack" / "app_tiny.oct"
    path = build_oct(app_dir, app_dir / "out" / "app_tiny.bin", out, **kwargs)
    assert path == out
    return path.read_bytes()


# ── header ───────────────────────────────────────────────────────────────────

def test_header_fields(app):
    d = built(app, categories=3, colors=0x11223344)
    assert d[0:4] == bytes((0xCC, 0x00, 0x00, 0xBB))
    assert struct.unpack_from("<I", d, 8)[0] == 4          # FormatVersion
    assert d[12:16] == b"\0\0\0\0"                          # struct padding
    assert struct.unpack_from("<Q", d, 16)[0] == GUID       # Guid1
    assert struct.unpack_from("<Q", d, 24)[0] == 0          # Guid2
    assert struct.unpack_from("<I", d, 32)[0] == 7          # AppVersion
    assert struct.unpack_from("<I", d, 36)[0] == 2          # EngineVersion
    assert struct.unpack_from("<I", d, 40)[0] == 0          # Features
    assert struct.unpack_from("<I", d, 44)[0] == 3          # Categories
    assert struct.unpack_from("<I", d, 48)[0] == 0          # BuildDateTime
    assert struct.unpack_from("<I", d, 52)[0] == len(d)     # Size
    assert d[56:136] == b"TINY" + b"\0" * 76                # Title[80]
    assert struct.unpack_from("<I", d, 136)[0] == 0x11223344  # Colors
    records = read_index_bin(app / "index.bin")
    assert struct.unpack_from("<II", d, 148) == (OCT_HEADER_SIZE, len(records))
    assert struct.unpack_from("<II", d, 156) == (OCT_HEADER_SIZE, 0)  # sounds
    assert d[164:184] == BUILD_ID                           # from the ELF
    assert d[184:228] == bytes(44)                          # Reserved


def test_crc_covers_bytes_8_to_size(app):
    d = built(app)
    size = struct.unpack_from("<I", d, 52)[0]
    assert struct.unpack_from("<I", d, 4)[0] == zlib.crc32(d[8:size]) & 0xFFFFFFFF


def test_title_truncated_to_79_bytes(app):
    d = built(app, title="X" * 200)
    assert d[56:136] == b"X" * 79 + b"\0"


def test_deterministic(app):
    assert built(app) == built(app)


# ── descriptors + payloads ───────────────────────────────────────────────────

def test_descriptor_table(app):
    d = built(app)
    records = read_index_bin(app / "index.bin")
    cursor = (OCT_HEADER_SIZE + OCT_DESC_SIZE * len(records) + 3) & ~3
    for i, (kind, name) in enumerate(records):
        desc = d[OCT_HEADER_SIZE + i * OCT_DESC_SIZE:][:OCT_DESC_SIZE]
        assert desc[:24].rstrip(b"\0").decode() == name
        offset, size = struct.unpack_from("<II", desc, 24)
        assert offset == cursor and offset % 4 == 0
        assert desc[32] == kind
        assert desc[33:36] == b"\0\0\0"                 # Flags, ExtId, Reserved
        src = {KIND_SOUND: app / "sound" / "assets" / f"{name}.mp3",
               KIND_PAL: app / "art" / "packed" / f"{name}.pal"}.get(
                   kind, app / "art" / "packed" / f"{name}.raw")
        blob = src.read_bytes()
        assert size == len(blob)
        assert d[offset:offset + size] == blob
        # sprites embed their octBmp_t so the engine can cull without the disk
        if kind == KIND_SPRITE:
            assert desc[36:36 + BMP_SIZE] == blob[:BMP_SIZE]
        else:
            assert desc[36:36 + BMP_SIZE] == bytes(BMP_SIZE)
        cursor = (cursor + size + 3) & ~3


def test_code_tail(app):
    d = built(app)
    code_offset, code_size = struct.unpack_from("<II", d, 140)
    assert code_size == len(CODE)
    assert code_offset % 4 == 0
    assert code_offset + code_size == len(d)
    assert d[code_offset:] == CODE


def test_short_sprite_payload_bmp_zero_padded(app):
    # the sim memcpys 48 bytes from a zeroed buffer, so a payload shorter
    # than octBmp_t yields a zero-padded desc.Bmp — mirror that, don't crash
    (app / "art" / "packed" / "gem.raw").write_bytes(b"\xAA" * 12)
    d = built(app)
    records = read_index_bin(app / "index.bin")
    i = [n for _k, n in records].index("gem")
    desc = d[OCT_HEADER_SIZE + i * OCT_DESC_SIZE:][:OCT_DESC_SIZE]
    assert desc[36:36 + BMP_SIZE] == b"\xAA" * 12 + bytes(BMP_SIZE - 12)


# ── app.h define fallback ────────────────────────────────────────────────────

APP_H = """\
#pragma once
#include "app_tiny.h"
#define APP_VERSION 102 //v1.02 - some comment
#define APP_TITLE "GRAND TINY"
#define APP_DIR "..\\\\app_tiny"
#define APP_GUID1 0xDF2CD5E85FF28AD8ULL
#define APP_CATEGORIES (APP_CATEGORY_GAME)
#define APP_COLORS 0x00000012
"""


def test_reads_defines_from_app_h(app):
    (app / "src").mkdir(exist_ok=True)
    (app / "src" / "app.h").write_text(APP_H, encoding="utf-8")
    out = app / "pack" / "app_tiny.oct"
    build_oct(app, app / "out" / "app_tiny.bin", out)
    d = out.read_bytes()
    assert struct.unpack_from("<Q", d, 16)[0] == 0xDF2CD5E85FF28AD8
    assert struct.unpack_from("<I", d, 32)[0] == 102
    assert struct.unpack_from("<I", d, 44)[0] == 0           # APP_CATEGORY_GAME
    assert d[56:136].rstrip(b"\0") == b"GRAND TINY"
    assert struct.unpack_from("<I", d, 136)[0] == 0x12


def test_kwargs_override_app_h(app):
    (app / "src").mkdir(exist_ok=True)
    (app / "src" / "app.h").write_text(APP_H, encoding="utf-8")
    d = built(app)                                           # kwargs win
    assert struct.unpack_from("<Q", d, 16)[0] == GUID
    assert struct.unpack_from("<I", d, 32)[0] == 7
    assert d[56:136].rstrip(b"\0") == b"TINY"


def test_read_app_defines_parses_category_expressions(tmp_path):
    h = tmp_path / "app.h"
    h.write_text("#define APP_CATEGORIES (APP_CATEGORY_LAUNCHER | "
                 "APP_CATEGORY_SCREENSAVER)\n#define APP_VERSION 3\n",
                 encoding="utf-8")
    defines = read_app_defines(h)
    assert defines["categories"] == (1 << 0) | (1 << 2)
    assert defines["app_version"] == 3


def test_read_app_defines_bom_and_suffixes(tmp_path):
    # real app.h files carry a UTF-8 BOM and ULL/u literal suffixes
    h = tmp_path / "app.h"
    h.write_bytes("﻿#define APP_GUID1 0xF886130CD255789DULL\n"
                  "#define APP_COLORS 0u\n".encode("utf-8"))
    defines = read_app_defines(h)
    assert defines["guid1"] == 0xF886130CD255789D
    assert defines["colors"] == 0


def test_unknown_category_macro_rejected(tmp_path):
    h = tmp_path / "app.h"
    h.write_text("#define APP_CATEGORIES (APP_CATEGORY_BOGUS)\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="APP_CATEGORY_BOGUS"):
        read_app_defines(h)


def test_missing_required_defines_raise(app):
    # no src/app.h and no kwargs: guid/version/title have no source
    with pytest.raises(ValueError, match="APP_GUID1"):
        build_oct(app, app / "out" / "app_tiny.bin",
                  app / "pack" / "app_tiny.oct")


# ── error paths ──────────────────────────────────────────────────────────────

def test_missing_index_bin(app):
    (app / "index.bin").unlink()
    with pytest.raises(ValueError, match="index.bin"):
        built(app)


def test_missing_payload_file(app):
    (app / "art" / "packed" / "gem.raw").unlink()
    with pytest.raises(ValueError, match="gem.raw"):
        built(app)


def test_empty_payload_file(app):
    (app / "art" / "packed" / "gem.raw").write_bytes(b"")
    with pytest.raises(ValueError, match="gem.raw"):
        built(app)


def test_missing_code_bin(app):
    (app / "out" / "app_tiny.bin").unlink()
    with pytest.raises(ValueError, match="app_tiny.bin"):
        built(app)


def test_empty_code_bin(app):
    (app / "out" / "app_tiny.bin").write_bytes(b"")
    with pytest.raises(ValueError, match="app_tiny.bin"):
        built(app)


def test_unknown_asset_kind_rejected(app):
    records = read_index_bin(app / "index.bin")
    blob = bytearray((app / "index.bin").read_bytes())
    struct.pack_into("<i", blob, 4, 9)          # kind of record 0 -> bogus
    (app / "index.bin").write_bytes(blob)
    with pytest.raises(ValueError, match="kind"):
        built(app)
    assert records                               # fixture really had records


# ── GNU build-id ─────────────────────────────────────────────────────────────

def test_build_id_zero_without_elf(app):
    (app / "out" / "app_tiny.elf").unlink()
    d = built(app)
    assert d[164:184] == bytes(20)


def test_build_id_zero_on_malformed_elf(app):
    (app / "out" / "app_tiny.elf").write_bytes(b"\x7fELF-not-really")
    d = built(app)
    assert d[164:184] == bytes(20)


def test_extract_gnu_build_id_roundtrip():
    assert extract_gnu_build_id(make_elf_with_build_id(BUILD_ID)) == BUILD_ID
    assert extract_gnu_build_id(b"") is None
    assert extract_gnu_build_id(b"\x7fELF" + bytes(60)) is None


# ── CLI entry ────────────────────────────────────────────────────────────────

def test_cli_build_oct(app, capsys):
    out = app / "pack" / "cli.oct"
    rc = pack_beta.main(["--build-oct",
                         "--app-dir", str(app),
                         "--code", str(app / "out" / "app_tiny.bin"),
                         "--out", str(out),
                         "--title", "TINY", "--guid", hex(GUID),
                         "--version", "7"])
    assert rc == 0
    d = out.read_bytes()
    assert d[0:4] == bytes((0xCC, 0x00, 0x00, 0xBB))
    assert d == built(app)                       # CLI == API, byte for byte
    assert str(out) in capsys.readouterr().out


def test_cli_error_is_clean_failure(app):
    (app / "index.bin").unlink()
    rc = pack_beta.main(["--build-oct",
                         "--app-dir", str(app),
                         "--code", str(app / "out" / "app_tiny.bin"),
                         "--out", str(app / "pack" / "cli.oct"),
                         "--title", "T", "--guid", "0x1", "--version", "1"])
    assert rc != 0
