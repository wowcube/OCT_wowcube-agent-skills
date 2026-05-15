"""Tests for build_pipeline.py.

Heavy integration (pack stage) runs only when ffmpeg AND pytoshop AND psd-tools
are importable. Otherwise those tests skip.

Sprite PNGs are produced upstream by canvas-design in production; these tests
fake them via the `populate_art_pngs` fixture before exercising the pack stage.
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


def test_find_script_resolves_vendored_scripts():
    """build_psd.py and pack.py are vendored in the skill's scripts/ dir."""
    for name in ("build_psd.py", "pack.py"):
        p = find_script(name)
        assert p.name == name
        assert p.exists()
        assert p.parent.name == "scripts"


def test_find_script_raises_for_missing_name():
    with pytest.raises(FileNotFoundError):
        find_script("definitely_not_a_real_script.py")


def test_generate_stage_emits_sounds_only(
    tmp_path, tmp_manifest, minimal_manifest, ffmpeg_available
):
    """Generate is now sounds-only; sprite PNGs are not produced here."""
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
    # Sound was synthesised by this skill.
    assert (project / "assets" / "mp3" / "sfx_coin.mp3").exists()
    # Sprite PNG must NOT be generated here; it is an upstream artefact.
    assert not (project / "assets" / "art" / "coin.png").exists()


def test_generate_reports_sprite_gap_in_state(
    tmp_path, tmp_manifest, minimal_manifest, ffmpeg_available
):
    """Missing upstream PNGs are reported in `.pipeline_state.json` as warnings."""
    if not ffmpeg_available:
        pytest.skip("ffmpeg required for generate stage")
    import json as _json

    manifest = tmp_manifest(minimal_manifest)
    workspace = tmp_path / "assets"

    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(workspace)])
    assert rc == 0

    state = _json.loads((workspace / ".pipeline_state.json").read_text())
    assert state["sprite_expected"] == 1
    assert state["sprite_found"] == 0
    assert state["sprite_missing"] == ["coin"]
    assert state["mp3_count"] == 1


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


def test_pack_errors_when_art_dir_empty(
    tmp_path, tmp_manifest, minimal_manifest, ffmpeg_available
):
    """pack must refuse to run if upstream didn't provide any sprite PNGs."""
    if not (ffmpeg_available and _deps_available()):
        pytest.skip("pack stage needs ffmpeg + pytoshop + psd-tools")
    manifest = tmp_manifest(minimal_manifest)
    project = tmp_path / "project"
    project.mkdir()

    rc_gen = _cli(["generate", "--manifest", str(manifest),
                   "--workspace", str(project / "assets")])
    assert rc_gen == 0

    # Approve but do NOT populate assets/art/ — pack should bail with rc=4.
    rc_approve = _cli(["approve", "--workspace", str(project / "assets")])
    assert rc_approve == 0

    rc_pack = _cli(["pack", "--game", "demo",
                    "--workspace", str(project / "assets"),
                    "--src-dir", str(project / "src")])
    assert rc_pack == 4


@pytest.mark.slow
def test_pack_stage_end_to_end(
    tmp_path, tmp_manifest, minimal_manifest, populate_art_pngs, ffmpeg_available
):
    if not (ffmpeg_available and _deps_available()):
        pytest.skip("pack stage needs ffmpeg + pytoshop + psd-tools")
    manifest = tmp_manifest(minimal_manifest)
    project = tmp_path / "project"
    project.mkdir()
    workspace = project / "assets"

    rc_gen = _cli(["generate", "--manifest", str(manifest),
                   "--workspace", str(workspace)])
    assert rc_gen == 0

    # Pretend canvas-design already produced the sprite PNGs upstream.
    populate_art_pngs(minimal_manifest, workspace / "art")

    rc_pack = _cli(["pack", "--game", "demo",
                    "--workspace", str(workspace),
                    "--src-dir", str(project / "src"),
                    "--force"])
    assert rc_pack == 0
    assert (workspace / "packed" / "pal.png").exists()
    assert (project / "src" / "app_demo_ids.h").exists()
    header = (project / "src" / "app_demo_ids.h").read_text()
    assert "BMP_coin" in header


def test_acceptance_criteria_e2e(
    tmp_path, tmp_manifest, populate_art_pngs, ffmpeg_available
):
    """End-to-end: sprite PNGs come from upstream, sounds from this skill, pack emits atlas + _ids.h."""
    if not (ffmpeg_available and _deps_available()):
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
    # No sprites produced by generate.
    assert not any((workspace / "art").glob("*.png"))
    assert (workspace / "mp3" / "sfx_coin.mp3").exists()

    # Seed upstream-provided PNGs.
    populate_art_pngs(manifest_data, workspace / "art")
    for fname in ("hero_idle_00.png", "hero_idle_01.png", "coin.png"):
        assert (workspace / "art" / fname).exists(), fname

    rc = _cli(["pack", "--game", "mini", "--workspace", str(workspace),
               "--src-dir", str(src_dir), "--force"])
    assert rc == 0
    assert (workspace / "packed" / "pal.png").exists()
    assert (src_dir / "app_mini_ids.h").exists()

    header = (src_dir / "app_mini_ids.h").read_text()
    for constant in ("BMP_coin", "BMP_hero_idle_00", "BMP_hero_idle_01",
                     "BMP_hero_idle", "BMP_hero_idle_end"):
        assert constant in header, f"missing {constant} in _ids.h"

    # MP3 placeholder determinism still holds (this skill owns sounds).
    mp3_hashes_1 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace / "mp3").glob("*.mp3")}

    workspace2 = project / "assets2"
    rc = _cli(["generate", "--manifest", str(manifest_path),
               "--workspace", str(workspace2)])
    assert rc == 0
    mp3_hashes_2 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace2 / "mp3").glob("*.mp3")}
    assert mp3_hashes_1 == mp3_hashes_2
