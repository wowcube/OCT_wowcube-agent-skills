"""Shared pytest fixtures for cube_asset-builder tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

# Stub-PNG sizing defaults. Real sprites come from canvas-design upstream in
# production; tests fake them with small RGBA rectangles matching the manifest.
STUB_FILL_RGBA = (200, 100, 50, 255)
STUB_FALLBACK_SIZE = (16, 16)


@pytest.fixture
def tmp_manifest(tmp_path: Path):
    """Factory: write a manifest dict to a JSON file in tmp_path and return the path."""
    def _write(data: dict, name: str = "manifest.json") -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p
    return _write


@pytest.fixture
def minimal_manifest() -> dict:
    """Smallest valid manifest: one sprite, one sound."""
    return {
        "game": "demo",
        "schema_version": 1,
        "sprites": [
            {"name": "coin", "size": [32, 32], "description": "yellow coin"},
        ],
        "sounds": [
            {"name": "sfx_coin", "description": "beep", "duration_ms": 200},
        ],
    }


@pytest.fixture
def animation_manifest() -> dict:
    """Manifest with a valid zero-padded animation."""
    return {
        "game": "demo",
        "schema_version": 1,
        "sprites": [
            {"name": "hero_idle_00", "size": [32, 32], "description": "hero f0",
             "group": "hero", "anim": "hero_idle", "frame": 0},
            {"name": "hero_idle_01", "size": [32, 32], "description": "hero f1",
             "group": "hero", "anim": "hero_idle", "frame": 1},
            {"name": "hero_idle_02", "size": [32, 32], "description": "hero f2",
             "group": "hero", "anim": "hero_idle", "frame": 2},
        ],
        "sounds": [],
    }


@pytest.fixture
def ffmpeg_available() -> bool:
    """True if ffmpeg is on PATH; tests that need MP3 encoding skip otherwise."""
    return shutil.which("ffmpeg") is not None


@pytest.fixture
def populate_art_pngs():
    """Factory: write stub RGBA PNGs for every sprite in a manifest dict.

    Mirrors the production contract where `assets/art/<name>.png` is produced
    upstream by `canvas-design`. Tests use this to pre-seed the workspace so
    the pack stage has inputs to consume.
    """
    def _populate(manifest_dict: dict, art_dir: Path) -> list[Path]:
        from PIL import Image  # local import: only tests that pack depend on PIL

        art_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for sprite in manifest_dict.get("sprites", []):
            size = tuple(sprite.get("size", STUB_FALLBACK_SIZE))
            img = Image.new("RGBA", size, STUB_FILL_RGBA)
            out = art_dir / f"{sprite['name']}.png"
            img.save(out)
            written.append(out)
        return written
    return _populate
