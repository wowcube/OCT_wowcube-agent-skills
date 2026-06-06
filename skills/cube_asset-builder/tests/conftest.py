"""Shared pytest fixtures for cube_asset-builder tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest


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
