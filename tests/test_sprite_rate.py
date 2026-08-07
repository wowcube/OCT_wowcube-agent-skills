"""``octBmp_t.Rate`` must survive the whole path: PSL -> header -> beta blob.

``Rate`` is the per-frame duration multiplier. ``oct_scene.h`` advances an
animation every ``bmp->Rate * spr->FrameRate`` ticks, so a sprite that reaches
the container with the default 1 instead of its declared multiplier plays back
at the raw frame rate.

The reference numbers come from ``OCT_ladybug`` built with the real
``psd.exe`` + ``utils.exe`` (and confirmed against the shipped
``app_ladybug.oct``, APP_VERSION 260): 493 sprites, of which 422 carry Rate 1,
36 carry 4, 30 carry 5 and 4 carry 10 -- and 66 of those 70 come from the
layer's Photoshop colour swatch alone, with no ``!rate`` marker anywhere in
the PSD. See ``test_layer_markers.py`` for the rule itself.

This file pins the plumbing, which is where all three previous regressions of
this shape actually happened: the value was parsed correctly and then dropped
before the bytes were written.
"""
from __future__ import annotations

import struct

import pytest

from config import (
    BMP_RATE_DEFAULT,
    HDR_OFF_FLAGS,
    HDR_OFF_RATE,
    SpriteFlag,
    layer_mark_of,
)
from pack_beta import BMP_SIZE, patch_palette_sprite
from pack_codec import build_header
from pack_psd import SpriteRecord, _write_records_psl

# The beta octBmp_t (oct_types.h) puts Rate at byte 45, right after Flags.
BETA_OFF_FLAGS = 44
BETA_OFF_RATE = 45


def test_build_header_writes_the_rate():
    hdr = build_header(8, 8, 4, 7, pidx=2, flags=0, rate=5)
    assert struct.unpack_from("<b", hdr, HDR_OFF_RATE)[0] == 5


def test_build_header_defaults_to_one():
    hdr = build_header(8, 8, 4, 7, pidx=2, flags=0)
    assert struct.unpack_from("<b", hdr, HDR_OFF_RATE)[0] == BMP_RATE_DEFAULT


@pytest.mark.parametrize("rate", [1, 4, 5, 10, 127])
def test_the_rate_survives_the_beta_conversion(rate):
    """patch_palette_sprite moves it from our intermediate slot (47) into the
    beta one (45) -- which is where a golden utils.exe .raw already keeps it."""
    hdr = build_header(8, 8, 4, 7, pidx=2, flags=int(SpriteFlag.ALPHA),
                       rate=rate)
    beta = patch_palette_sprite(hdr + b"payload", pal_id=17, seq_id=18)
    assert beta[BETA_OFF_RATE] == rate
    assert beta[BETA_OFF_FLAGS] == int(SpriteFlag.ALPHA)
    assert struct.unpack_from("<HH", beta, 0) == (17, 18)
    assert beta[46] == beta[47] == 0
    assert beta[BMP_SIZE:] == b"payload"


def test_flags_and_rate_do_not_collide():
    """They are adjacent bytes in both layouts; a packing slip shows up here."""
    hdr = build_header(8, 8, 4, 7, pidx=2,
                       flags=int(SpriteFlag.ALPHA | SpriteFlag.FULLSIZE),
                       rate=10)
    assert hdr[HDR_OFF_FLAGS] == 0x03
    assert struct.unpack_from("<b", hdr, HDR_OFF_RATE)[0] == 10


# ── the pack.py loader ──────────────────────────────────────────────────────

def _rec(name: str, markers=(), rate: int = 0, colour: int = 0) -> SpriteRecord:
    return SpriteRecord(
        id=1, name=name, group_id=0, kind=0, bmp="", x=0, y=0, w=4, h=4,
        layer_mark=layer_mark_of(colour), side=-1, side_cx=0, side_cy=0,
        png_name=name, is_marker=False, marker_number=0, sprite_number=0,
        type_name="", group_name="", rate=rate, markers=tuple(markers))


def _write(tmp_path, records, psl_type=1, stem="assets"):
    _write_records_psl(str(tmp_path / f"{stem}.psl"), records, psl_type)
    return tmp_path


def test_loader_reads_both_rate_sources(tmp_path):
    from pack import _load_sprite_rates_from_psls
    _write(tmp_path, [
        _rec("plain"),
        _rec("lb0_00", colour=3),                      # yellow  -> 4
        _rec("eat_00", colour=4),                      # green   -> 5
        _rec("pat_00", ("rate10",), rate=10),          # marker  -> 10
        _rec("both", ("rate10",), rate=10, colour=3),  # marker wins
    ])
    rates = _load_sprite_rates_from_psls(str(tmp_path))
    assert rates == {"plain": 1, "lb0_00": 4, "eat_00": 5,
                     "pat_00": 10, "both": 10}


def test_loader_ignores_map_psls(tmp_path):
    """octPlace_t.Rate is a different field with a different meaning (label
    alignment for text places); a map record must not set a sprite's Rate."""
    from pack import _load_sprite_rates_from_psls
    _write(tmp_path, [_rec("shared", colour=4)], psl_type=2, stem="hud")
    assert _load_sprite_rates_from_psls(str(tmp_path)) == {}


def test_loader_skips_marker_layers(tmp_path):
    """`=NN` markers have no name and no exported PNG."""
    from pack import _load_sprite_rates_from_psls
    marker = _rec("", colour=4)
    marker = SpriteRecord(**{**marker.__dict__, "is_marker": True,
                             "png_name": "", "name": "=20"})
    _write(tmp_path, [marker, _rec("real", colour=4)])
    assert _load_sprite_rates_from_psls(str(tmp_path)) == {"real": 5}
