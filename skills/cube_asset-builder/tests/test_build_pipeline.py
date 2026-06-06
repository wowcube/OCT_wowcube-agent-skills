"""Tests for build_pipeline.py.

Heavy integration (pack stage) runs only when ffmpeg AND pytoshop AND psd-tools
are importable. Otherwise those tests skip.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from build_pipeline import find_script, _cli


def _deps_available() -> bool:
    try:
        import pytoshop  # noqa: F401
        import psd_tools  # noqa: F401
        return True
    except ImportError:
        return False


def test_find_script_returns_repo_root_copy_in_dev():
    """In the dev layout, find_script('build_psd.py') must resolve to repo root."""
    p = find_script("build_psd.py")
    assert p.name == "build_psd.py"
    assert p.exists()


def test_find_script_raises_for_missing_name():
    with pytest.raises(FileNotFoundError):
        find_script("definitely_not_a_real_script.py")


def test_generate_stage_runs(tmp_path, tmp_manifest, minimal_manifest, ffmpeg_available):
    if not ffmpeg_available:
        pytest.skip("ffmpeg required for generate stage")
    manifest = tmp_manifest(minimal_manifest)
    project = tmp_path / "project"
    project.mkdir()
    game_dir = project / "plans" / "demo"
    game_dir.mkdir(parents=True)
    target_manifest = game_dir / "demo_assets.json"
    target_manifest.write_text(manifest.read_text(), encoding="utf-8")

    rc = _cli(["generate", "--manifest", str(target_manifest),
               "--workspace", str(project / "assets")])
    assert rc == 0
    assert (project / "assets" / "art" / "coin.png").exists()
    assert (project / "assets" / "mp3" / "sfx_coin.mp3").exists()


def test_generate_rejects_invalid_manifest(tmp_path, tmp_manifest, ffmpeg_available):
    if not ffmpeg_available:
        pytest.skip("generate runs _check_deps first; need ffmpeg to reach validation path")
    bad = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": "BadName", "size": [32, 32], "description": "x"}],
        "sounds": [],
    }
    manifest = tmp_manifest(bad)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 2


@pytest.mark.slow
def test_pack_stage_end_to_end(tmp_path, tmp_manifest, minimal_manifest, ffmpeg_available):
    if not (ffmpeg_available and _deps_available()):
        pytest.skip("pack stage needs ffmpeg + pytoshop + psd-tools")
    manifest = tmp_manifest(minimal_manifest)
    project = tmp_path / "project"
    project.mkdir()

    rc_gen = _cli(["generate", "--manifest", str(manifest),
                   "--workspace", str(project / "assets")])
    assert rc_gen == 0

    rc_pack = _cli(["pack", "--game", "demo",
                    "--workspace", str(project / "assets"),
                    "--src-dir", str(project / "src")])
    assert rc_pack == 0
    assert (project / "assets" / "packed" / "pal.png").exists()
    assert (project / "src" / "app_demo_ids.h").exists()
    header = (project / "src" / "app_demo_ids.h").read_text()
    assert "BMP_coin" in header


def _deps_for_e2e() -> bool:
    try:
        import pytoshop  # noqa: F401
        import psd_tools  # noqa: F401
        return True
    except ImportError:
        return False


def test_acceptance_criteria_e2e(tmp_path, tmp_manifest, ffmpeg_available):
    """Covers all four acceptance criteria from the spec §12."""
    if not (ffmpeg_available and _deps_for_e2e()):
        pytest.skip("acceptance test needs ffmpeg + pytoshop + psd-tools")

    manifest_data = {
        "game": "mini",
        "schema_version": 1,
        "sprites": [
            {"name": "hero_idle_00", "size": [32, 32], "description": "round blue hero",
             "group": "hero", "anim": "hero_idle", "frame": 0},
            {"name": "hero_idle_01", "size": [32, 32], "description": "mid bounce",
             "group": "hero", "anim": "hero_idle", "frame": 1},
            {"name": "coin", "size": [16, 16], "description": "shiny yellow coin",
             "group": "pickup"},
        ],
        "sounds": [
            {"name": "sfx_coin", "description": "beep", "duration_ms": 200,
             "event_type": "pickup", "group": "ui"},
        ],
    }
    manifest_path = tmp_manifest(manifest_data)
    project = tmp_path / "project"
    project.mkdir()
    workspace = project / "assets"
    src_dir = project / "src"

    rc = _cli(["generate", "--manifest", str(manifest_path),
               "--workspace", str(workspace)])
    assert rc == 0
    for fname in ("0.png", "hero_idle_00.png", "hero_idle_01.png", "coin.png"):
        assert (workspace / "art" / fname).exists(), fname
    assert (workspace / "mp3" / "sfx_coin.mp3").exists()

    rc = _cli(["pack", "--game", "mini", "--workspace", str(workspace),
               "--src-dir", str(src_dir)])
    assert rc == 0
    assert (workspace / "packed" / "pal.png").exists()
    assert (src_dir / "app_mini_ids.h").exists()

    header = (src_dir / "app_mini_ids.h").read_text()
    for constant in ("BMP_coin", "BMP_hero_idle_00", "BMP_hero_idle_01",
                     "BMP_hero_idle", "BMP_hero_idle_end"):
        assert constant in header, f"missing {constant} in _ids.h"

    png_hashes_1 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace / "art").glob("*.png")}
    mp3_hashes_1 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace / "mp3").glob("*.mp3")}

    workspace2 = project / "assets2"
    rc = _cli(["generate", "--manifest", str(manifest_path),
               "--workspace", str(workspace2)])
    assert rc == 0
    png_hashes_2 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace2 / "art").glob("*.png")}
    mp3_hashes_2 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace2 / "mp3").glob("*.mp3")}
    assert png_hashes_1 == png_hashes_2
    assert mp3_hashes_1 == mp3_hashes_2
