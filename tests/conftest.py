"""Shared pytest fixtures for cube_asset-builder tests."""
from __future__ import annotations

import json
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
            {"name": "coin", "size": [32, 32], "description": "yellow coin",
             "gen_prompt": "Pixel-art gold coin, 32x32, transparent background"},
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
             "gen_prompt": "Pixel-art hero idle frame 0, 32x32, transparent bg",
             "group": "hero", "anim": "hero_idle", "frame": 0},
            {"name": "hero_idle_01", "size": [32, 32], "description": "hero f1",
             "gen_prompt": "Pixel-art hero idle frame 1, 32x32, transparent bg",
             "group": "hero", "anim": "hero_idle", "frame": 1},
            {"name": "hero_idle_02", "size": [32, 32], "description": "hero f2",
             "gen_prompt": "Pixel-art hero idle frame 2, 32x32, transparent bg",
             "group": "hero", "anim": "hero_idle", "frame": 2},
        ],
        "sounds": [],
    }


@pytest.fixture
def stub_ai(monkeypatch):
    """Run the sprite pipeline offline.

    Patches `genimg.generate_image` to write a deterministic solid-colour PNG
    of the requested size (so same input -> same bytes across runs), and sets a
    dummy OPENROUTER_API_KEY so `_check_deps` passes without a real key.
    """
    import genimg
    from PIL import Image

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def _fake(prompt, out_path, *, size=None, reference=None):
        w, h = size if size else (64, 64)
        img = Image.new("RGBA", (int(w), int(h)), (180, 60, 120, 255))
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="PNG")
        return out_path

    monkeypatch.setattr(genimg, "generate_image", _fake)
    return _fake
