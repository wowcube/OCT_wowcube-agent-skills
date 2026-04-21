"""Tests for gen_placeholders.py."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from manifest_schema import load_manifest
from gen_placeholders import generate


def _files(d: Path) -> set[str]:
    return {p.name for p in d.iterdir() if p.is_file()}


def test_creates_png_per_sprite_and_index_zero(tmp_manifest, minimal_manifest, tmp_path):
    manifest_path = tmp_manifest(minimal_manifest)
    out = tmp_path / "art"
    m = load_manifest(manifest_path)
    generate(m, out)
    assert _files(out) == {"0.png", "coin.png"}


def test_png_size_matches_manifest(tmp_manifest, minimal_manifest, tmp_path):
    out = tmp_path / "art"
    generate(load_manifest(tmp_manifest(minimal_manifest)), out)
    img = Image.open(out / "coin.png")
    assert img.size == (32, 32)
    assert img.mode == "RGBA"


def test_zero_png_is_transparent(tmp_manifest, minimal_manifest, tmp_path):
    out = tmp_path / "art"
    generate(load_manifest(tmp_manifest(minimal_manifest)), out)
    img = Image.open(out / "0.png")
    assert img.size == (1, 1)
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0


def test_animation_files_named_zero_padded(tmp_manifest, animation_manifest, tmp_path):
    out = tmp_path / "art"
    generate(load_manifest(tmp_manifest(animation_manifest)), out)
    names = _files(out) - {"0.png"}
    assert names == {"hero_idle_00.png", "hero_idle_01.png", "hero_idle_02.png"}


def test_deterministic_across_runs(tmp_manifest, minimal_manifest, tmp_path):
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    m = load_manifest(tmp_manifest(minimal_manifest))
    generate(m, out1)
    generate(m, out2)
    h1 = hashlib.md5((out1 / "coin.png").read_bytes()).hexdigest()
    h2 = hashlib.md5((out2 / "coin.png").read_bytes()).hexdigest()
    assert h1 == h2


def test_group_filter_only_regenerates_one_group(tmp_manifest, tmp_path):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [
            {"name": "hero_idle_00", "size": [32, 32], "description": "h0",
             "group": "hero", "anim": "hero_idle", "frame": 0},
            {"name": "coin", "size": [32, 32], "description": "c", "group": "pickup"},
        ],
        "sounds": [],
    }
    m = load_manifest(tmp_manifest(data))
    out = tmp_path / "art"
    generate(m, out)
    coin_bytes_a = (out / "coin.png").read_bytes()
    (out / "hero_idle_00.png").unlink()
    generate(m, out, group="hero")
    assert (out / "hero_idle_00.png").exists()
    assert (out / "coin.png").read_bytes() == coin_bytes_a


def test_fullsize_flag_fills_canvas(tmp_manifest, tmp_path):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": "bg", "size": [64, 64], "description": "sky",
                     "flags": {"fullsize": True, "bg": True}}],
        "sounds": [],
    }
    out = tmp_path / "art"
    generate(load_manifest(tmp_manifest(data)), out)
    img = Image.open(out / "bg.png")
    alphas = [img.getpixel((x, y))[3] for x in range(0, 64, 8) for y in range(0, 64, 8)]
    assert all(a > 0 for a in alphas)
