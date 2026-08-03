"""Tests for build_pipeline.py.

Sprite generation is stubbed offline via the `stub_ai` fixture (no real
OpenRouter call). Heavy integration (pack stage) runs only when pytoshop AND
psd-tools are importable; otherwise those tests skip.
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


@pytest.fixture
def stub_ffmpeg(monkeypatch):
    """Make the beta-mp3 path deterministic and offline.

    shutil.which('ffmpeg') always 'finds' it (so do_generate opts into
    encode_mp3 regardless of the host machine) and encode_beta_mp3 writes a
    fake mp3 instead of shelling out — tests never require real ffmpeg.
    """
    import shutil as _shutil

    import gen_sounds

    real_which = _shutil.which
    monkeypatch.setattr(
        _shutil, "which",
        lambda name, *a, **kw: ("ffmpeg" if name == "ffmpeg"
                                else real_which(name, *a, **kw)))

    def _fake_encode(wav_path, assets_dir):
        wav_path = Path(wav_path)
        assets_dir = Path(assets_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)
        out = assets_dir / (wav_path.stem + ".mp3")
        out.write_bytes(b"fake-beta-mp3:" + wav_path.stem.encode())
        return out

    monkeypatch.setattr(gen_sounds, "encode_beta_mp3", _fake_encode)
    return _fake_encode


@pytest.fixture
def no_ffmpeg(monkeypatch):
    """The opposite: shutil.which never finds ffmpeg."""
    import shutil as _shutil

    real_which = _shutil.which
    monkeypatch.setattr(
        _shutil, "which",
        lambda name, *a, **kw: (None if name == "ffmpeg"
                                else real_which(name, *a, **kw)))


def test_find_script_returns_repo_root_copy_in_dev():
    """In the dev layout, find_script('build_psd.py') must resolve to repo root."""
    p = find_script("build_psd.py")
    assert p.name == "build_psd.py"
    assert p.exists()


def test_find_script_raises_for_missing_name():
    with pytest.raises(FileNotFoundError):
        find_script("definitely_not_a_real_script.py")


def test_generate_stage_runs(tmp_path, tmp_manifest, minimal_manifest, stub_ai, stub_ffmpeg):
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
    assert (project / "assets" / "wav" / "sfx_coin.wav").exists()
    # ffmpeg "available" (stubbed) -> beta mp3s land next to the WAVs
    assert (project / "assets" / "wav" / "assets" / "sfx_coin.mp3").exists()


def test_generate_skips_mp3_without_ffmpeg(tmp_path, tmp_manifest, minimal_manifest,
                                           stub_ai, no_ffmpeg):
    """No ffmpeg and no --mp3 flag: WAVs are written, mp3 encoding is skipped."""
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 0
    assert (tmp_path / "assets" / "wav" / "sfx_coin.wav").exists()
    assert not (tmp_path / "assets" / "wav" / "assets").exists()


def test_generate_mp3_flag_fails_without_ffmpeg(tmp_path, tmp_manifest, minimal_manifest,
                                                stub_ai, no_ffmpeg):
    """--mp3 makes a missing ffmpeg a hard error with its own exit code."""
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets"), "--mp3"])
    assert rc == 7


def test_generate_rejects_invalid_manifest(tmp_path, tmp_manifest, stub_ai):
    bad = {
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": "BadName", "size": [32, 32], "description": "x"}],
        "sounds": [],
    }
    manifest = tmp_manifest(bad)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 2


def test_generate_missing_api_key_fails(tmp_path, tmp_manifest, minimal_manifest, monkeypatch):
    """Without OPENROUTER_API_KEY the generate stage stops at the dep check."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 3


@pytest.mark.slow
def test_pack_stage_end_to_end(tmp_path, tmp_manifest, minimal_manifest, stub_ai, stub_ffmpeg):
    if not _deps_available():
        pytest.skip("pack stage needs pytoshop + psd-tools")
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


def test_acceptance_criteria_e2e(tmp_path, tmp_manifest, stub_ai, stub_ffmpeg):
    """Covers all four acceptance criteria from the spec §12."""
    if not _deps_for_e2e():
        pytest.skip("acceptance test needs pytoshop + psd-tools")

    manifest_data = {
        "game": "mini",
        "schema_version": 1,
        "sprites": [
            {"name": "hero_idle_00", "size": [32, 32], "description": "round blue hero",
             "gen_prompt": "Pixel-art round blue hero, idle frame 0, 32x32, transparent bg",
             "group": "hero", "anim": "hero_idle", "frame": 0},
            {"name": "hero_idle_01", "size": [32, 32], "description": "mid bounce",
             "gen_prompt": "Pixel-art round blue hero, idle frame 1, 32x32, transparent bg",
             "group": "hero", "anim": "hero_idle", "frame": 1},
            {"name": "coin", "size": [16, 16], "description": "shiny yellow coin",
             "gen_prompt": "Pixel-art shiny yellow coin, 16x16, transparent bg",
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
    assert (workspace / "wav" / "sfx_coin.wav").exists()

    rc = _cli(["pack", "--game", "mini", "--workspace", str(workspace),
               "--src-dir", str(src_dir)])
    assert rc == 0
    assert (workspace / "packed" / "pal.png").exists()
    assert (src_dir / "app_mini_ids.h").exists()

    header = (src_dir / "app_mini_ids.h").read_text()
    for constant in ("BMP_coin", "BMP_hero_idle_00", "BMP_hero_idle_01",
                     "BMP_hero_idle", "BMP_hero_idle_end"):
        assert constant in header, f"missing {constant} in _ids.h"

    wav_hashes_1 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace / "wav").glob("*.wav")}

    workspace2 = project / "assets2"
    rc = _cli(["generate", "--manifest", str(manifest_path),
               "--workspace", str(workspace2)])
    assert rc == 0
    wav_hashes_2 = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                    for p in (workspace2 / "wav").glob("*.wav")}
    # Sounds are deterministic (pure synthesis); AI sprites are not, so only
    # the WAVs are hash-compared across runs.
    assert wav_hashes_1 == wav_hashes_2


def test_pack_copies_beta_mp3s_to_app_dir(tmp_path, monkeypatch):
    """With --app-dir, the pack stage carries <workspace>/wav/assets/*.mp3 to
    <app_dir>/sound/assets/ BEFORE invoking pack.py, so emit_beta_layout's
    sound scan picks them up (the beta sim loads sounds only from there)."""
    import build_pipeline
    from PIL import Image

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    packed = workspace / "packed"
    packed.mkdir()
    (packed / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    (workspace / "wav" / "assets").mkdir(parents=True)
    (workspace / "wav" / "assets" / "blip.mp3").write_bytes(b"fake-beta-mp3:blip")

    app_dir = tmp_path / "app_tiny"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "src" / "app_tiny_ids.h").write_text(
        "enum BMP { BMP_none = 0, BMP_last};")
    mp3_present_at_pack: list[bool] = []

    def fake_run(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        if "--beta-app-dir" in cmd:
            mp3_present_at_pack.append(
                (app_dir / "sound" / "assets" / "blip.mp3").is_file())
        return 0

    monkeypatch.setattr(build_pipeline, "_run", fake_run)

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
        "--app-dir", str(app_dir),
    ])
    assert rc == 0
    copied = app_dir / "sound" / "assets" / "blip.mp3"
    assert copied.read_bytes() == b"fake-beta-mp3:blip"
    # the copy happened before pack.py was invoked, not after
    assert mp3_present_at_pack == [True]


def test_pack_without_mp3s_still_passes_beta_args(tmp_path, monkeypatch):
    """No wav/assets dir at all: the pack stage must not trip over it."""
    import build_pipeline
    from PIL import Image

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    packed = workspace / "packed"
    packed.mkdir()
    (packed / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    app_dir = tmp_path / "app_tiny"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "src" / "app_tiny_ids.h").write_text(
        "enum BMP { BMP_none = 0, BMP_last};")

    calls: list[list[str]] = []
    monkeypatch.setattr(build_pipeline, "_run",
                        lambda cmd, cwd=None: (calls.append([str(c) for c in cmd]), 0)[1])

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
        "--app-dir", str(app_dir),
    ])
    assert rc == 0
    assert "--beta-app-dir" in calls[1]
    assert not (app_dir / "sound").exists()


def test_pack_app_dir_keeps_beta_ids_header(tmp_path, monkeypatch):
    """With --app-dir, the kind-aware beta header pack.py emitted into
    <app_dir>/src/ is canonical: the legacy workspace header (different
    numbering, no SND_ enum) must NOT clobber it, and a distinct --src-dir
    receives a copy of the BETA header, not the legacy one."""
    import build_pipeline
    from PIL import Image

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    (workspace / "packed").mkdir()
    (workspace / "packed" / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text(
        "enum BMP { BMP_none = 0, BMP_legacy = 1, BMP_last};")

    app_dir = tmp_path / "app_tiny"
    (app_dir / "src").mkdir(parents=True)
    beta_text = ("enum BMP { BMP_none = 0, BMP_hero = 19, BMP_last};\n"
                 "enum SND { SND_none = 0, SND_blip = 40, SND_last};\n")
    (app_dir / "src" / "app_tiny_ids.h").write_text(beta_text)

    monkeypatch.setattr(build_pipeline, "_run", lambda cmd, cwd=None: 0)

    src_dir = tmp_path / "other_src"
    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(src_dir),
        "--app-dir", str(app_dir),
    ])
    assert rc == 0
    assert (app_dir / "src" / "app_tiny_ids.h").read_text() == beta_text
    assert (src_dir / "app_tiny_ids.h").read_text() == beta_text

    # the common case: --src-dir IS <app_dir>/src -- must also survive
    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(app_dir / "src"),
        "--app-dir", str(app_dir),
    ])
    assert rc == 0
    assert (app_dir / "src" / "app_tiny_ids.h").read_text() == beta_text
