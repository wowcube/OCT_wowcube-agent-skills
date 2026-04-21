"""Tests for manifest_schema.py."""
from __future__ import annotations

import pytest

from manifest_schema import (
    Manifest, Sprite, Sound,
    load_manifest, validate, ValidationError,
    NAME_RE,
)


def test_minimal_manifest_parses(tmp_manifest, minimal_manifest):
    path = tmp_manifest(minimal_manifest)
    m = load_manifest(path)
    assert isinstance(m, Manifest)
    assert m.game == "demo"
    assert m.schema_version == 1
    assert len(m.sprites) == 1
    assert m.sprites[0].name == "coin"
    assert m.sprites[0].size == (32, 32)
    assert m.sprites[0].flags.alpha is True
    assert len(m.sounds) == 1
    assert m.sounds[0].duration_ms == 200


def test_animation_manifest_parses(tmp_manifest, animation_manifest):
    path = tmp_manifest(animation_manifest)
    m = load_manifest(path)
    assert len(m.sprites) == 3
    assert [s.frame for s in m.sprites] == [0, 1, 2]
    for s in m.sprites:
        assert s.anim == "hero_idle"


def test_sound_default_duration(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [{"name": "s", "description": "d"}],
    }
    m = load_manifest(tmp_manifest(data))
    assert m.sounds[0].duration_ms == 500


def test_sprite_default_pivot_is_center(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": "x", "size": [64, 40], "description": "d"}],
        "sounds": [],
    }
    m = load_manifest(tmp_manifest(data))
    assert m.sprites[0].pivot == (32, 20)


# ── Name character set ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["Hero", "hero-idle", "hero idle", "hero!", "hero%x"])
def test_invalid_sprite_name_rejected(tmp_manifest, bad):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": bad, "size": [32, 32], "description": "d"}],
        "sounds": [],
    }
    m = load_manifest(tmp_manifest(data))
    errors = validate(m)
    assert any("name" in e.lower() for e in errors), f"expected name error for {bad!r}, got {errors}"


def test_invalid_sound_name_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [{"name": "SfxCoin", "description": "d"}],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert errors


# ── Reserved names ─────────────────────────────────────────────────────

@pytest.mark.parametrize("reserved", ["pal", "0", "icon", "bmp_none"])
def test_reserved_name_rejected(tmp_manifest, reserved):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": reserved, "size": [32, 32], "description": "d"}],
        "sounds": [],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("reserved" in e.lower() for e in errors)


# ── Size limits ────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_size", [[0, 32], [32, 0], [241, 32], [32, 241]])
def test_sprite_size_out_of_range(tmp_manifest, bad_size):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": "x", "size": bad_size, "description": "d"}],
        "sounds": [],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("size" in e.lower() for e in errors)


# ── Duplicates ─────────────────────────────────────────────────────────

def test_duplicate_sprite_names_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [
            {"name": "x", "size": [32, 32], "description": "a"},
            {"name": "x", "size": [32, 32], "description": "b"},
        ],
        "sounds": [],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("duplicate" in e.lower() for e in errors)


def test_duplicate_sound_names_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [
            {"name": "s", "description": "a"},
            {"name": "s", "description": "b"},
        ],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("duplicate" in e.lower() for e in errors)


# ── Sound duration ─────────────────────────────────────────────────────

def test_sound_duration_over_cap_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [{"name": "s", "description": "d", "duration_ms": 2001}],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("duration" in e.lower() for e in errors)


# ── Animation sequence ─────────────────────────────────────────────────

def test_animation_not_starting_at_00_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [
            {"name": "run_01", "size": [32, 32], "description": "d",
             "anim": "run", "frame": 1},
            {"name": "run_02", "size": [32, 32], "description": "d",
             "anim": "run", "frame": 2},
        ],
        "sounds": [],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("_00" in e for e in errors)


def test_animation_non_contiguous_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1,
        "sprites": [
            {"name": "run_00", "size": [32, 32], "description": "d",
             "anim": "run", "frame": 0},
            {"name": "run_02", "size": [32, 32], "description": "d",
             "anim": "run", "frame": 2},
        ],
        "sounds": [],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("contiguous" in e.lower() or "missing" in e.lower() for e in errors)


def test_valid_animation_passes(tmp_manifest, animation_manifest):
    errors = validate(load_manifest(tmp_manifest(animation_manifest)))
    assert errors == []


# ── Unknown event_type ─────────────────────────────────────────────────

def test_unknown_event_type_rejected(tmp_manifest):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [{"name": "s", "description": "d", "event_type": "explosion"}],
    }
    errors = validate(load_manifest(tmp_manifest(data)))
    assert any("event_type" in e for e in errors)


# ── Minimal valid ──────────────────────────────────────────────────────

def test_minimal_manifest_has_no_errors(tmp_manifest, minimal_manifest):
    errors = validate(load_manifest(tmp_manifest(minimal_manifest)))
    assert errors == []
