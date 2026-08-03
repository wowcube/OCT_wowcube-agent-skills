"""Golden-reference tests for the beta (octavios dev) asset-container primitives.

Fixtures in tests/golden/ were copied verbatim from the real beta toolchain
output (`..\\app_hulk\\app_hulk\\`, produced by utils.exe) so these tests pin
scripts/pack_beta.py's binary layouts against ground truth rather than
against our own assumptions.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

import pack_beta

GOLDEN = Path(__file__).parent / "golden"


def test_index_bin_roundtrip():
    records = pack_beta.read_index_bin(GOLDEN / "index.bin")
    assert len(records) == 1027
    assert records[0] == (pack_beta.KIND_SPRITE, "zero")
    assert records[1] == (pack_beta.KIND_PAL, "5")
    assert records[2] == (pack_beta.KIND_MAP, "ico")
    blob = pack_beta.build_index_bin(records)
    assert blob == (GOLDEN / "index.bin").read_bytes()


def test_bmp_header_parse_golden():
    hdr = pack_beta.parse_bmp_header((GOLDEN / "ahover_00.raw").read_bytes())
    assert (hdr.pidx, hdr.seq, hdr.w, hdr.h) == (8, 11, 74, 67)
    assert hdr.compression == 0x706  # SymbolBitness=6, OffsetBitness=7


def test_bmp_header_build_is_48_bytes():
    blob = pack_beta.build_bmp_header(w=74, h=67, flags=0, pidx=8, seq=11,
                                       compression=0x706, pivot=(73.5, 65.5), rate=1)
    assert len(blob) == 48
    hdr = pack_beta.parse_bmp_header(blob)
    assert (hdr.pidx, hdr.seq, hdr.w, hdr.h, hdr.compression) == (8, 11, 74, 67, 0x706)


def test_pal_roundtrip_golden():
    colors = pack_beta.read_pal(GOLDEN / "5.pal")
    assert len(colors) == 64
    assert colors[0] == 0x0000          # index 0 = transparent
    assert pack_beta.build_pal(colors) == (GOLDEN / "5.pal").read_bytes()


def test_map_raw_golden():
    blob = (GOLDEN / "ahover.raw").read_bytes()
    version, count = struct.unpack_from("<ii", blob, 0)
    assert (version, count, len(blob)) == (1, 1, 36)
