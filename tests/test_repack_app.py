"""Tests for scripts/repack_app.py — the one-command repack cycle (spec §9, §10).

bump_patch is tested on handcrafted app.h files; invocation detection on tmp
app dirs with different on-disk shapes (manifest / icon / PSD / palette
sprites); the CLI stage order with a mocked runner; and the --skip-device
path end-to-end with a real pack.py run (no ARM toolchain involved).
"""
from __future__ import annotations

import codecs
import json
import sys
from pathlib import Path

import pytest

import repack_app
from repack_app import bump_patch, detect_pack_command, _cli


# ── bump_patch ──────────────────────────────────────────────────────────────

def test_bump_patch_preserves_comment_tail(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text(
        "#pragma once\n"
        "#define APP_VERSION 102 //v1.02 - dither notes, do not touch\n"
        '#define APP_TITLE "Demo"\n',
        encoding="utf-8")
    assert bump_patch(app_h) == 103
    text = app_h.read_text(encoding="utf-8")
    assert "#define APP_VERSION 103 //v1.02 - dither notes, do not touch\n" in text
    assert "#pragma once" in text and 'APP_TITLE "Demo"' in text


def test_bump_patch_without_comment(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text("#define APP_VERSION 100\n", encoding="utf-8")
    assert bump_patch(app_h) == 101
    assert app_h.read_text(encoding="utf-8") == "#define APP_VERSION 101\n"


def test_bump_patch_missing_define_raises(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text("#define APP_TITLE \"x\"\n", encoding="utf-8")
    with pytest.raises(ValueError, match="APP_VERSION"):
        bump_patch(app_h)


def test_bump_patch_preserves_bom(tmp_path):
    """Real app.h files carry a UTF-8 BOM; bumping must not strip it."""
    app_h = tmp_path / "app.h"
    app_h.write_bytes(codecs.BOM_UTF8 + b"#define APP_VERSION 199\n")
    assert bump_patch(app_h) == 200
    raw = app_h.read_bytes()
    assert raw.startswith(codecs.BOM_UTF8)
    assert b"APP_VERSION 200" in raw


def test_bump_patch_no_bom_stays_no_bom(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_bytes(b"#define APP_VERSION 1\n")
    bump_patch(app_h)
    assert not app_h.read_bytes().startswith(codecs.BOM_UTF8)


def test_bump_patch_repeated_runs_accumulate(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text("#define APP_VERSION 102 //v1.02\n", encoding="utf-8")
    assert bump_patch(app_h) == 103
    assert bump_patch(app_h) == 104


# ── invocation detection ────────────────────────────────────────────────────

FULL_SPRITE = {"name": "bg", "size": [16, 16], "description": "bg",
               "color": "full", "flags": {"alpha": False, "fullsize": False}}
PAL_SPRITE = {"name": "coin", "size": [8, 8], "description": "coin"}


def make_app(root: Path, name: str = "app_demo", *, sprites=None,
             manifest_names=("demo_assets.json",), icon=False,
             psd=False) -> Path:
    """Minimal on-disk app shape for detection tests (no real assets)."""
    app = root / name
    (app / "art" / "exported").mkdir(parents=True)
    (app / "src").mkdir()
    (app / f"{name}.target").write_text("")
    (app / "src" / "app.h").write_text("#define APP_VERSION 100\n",
                                       encoding="utf-8")
    if sprites is not None:
        (app / "plans").mkdir()
        for mname in manifest_names:
            (app / "plans" / mname).write_text(json.dumps(
                {"game": "demo", "schema_version": 1,
                 "sprites": sprites, "sounds": []}), encoding="utf-8")
    if icon:
        (app / "art" / "icon.png").write_bytes(b"\x89PNG-fake")
    if psd:
        (app / "art" / "assets.psd").write_bytes(b"8BPS-fake")
    return app


def test_detect_manifest_and_icon_included(tmp_path):
    app = make_app(tmp_path, sprites=[FULL_SPRITE], icon=True)
    cmd, cwd = detect_pack_command(app)
    assert cwd == app
    assert cmd[0] == sys.executable and cmd[1].endswith("pack.py")
    mi = cmd.index("--manifest")
    assert cmd[mi + 1] == str(app / "plans" / "demo_assets.json")
    ii = cmd.index("--icon")
    assert cmd[ii + 1] == str(app / "art" / "icon.png")
    # canonical constants
    ai = cmd.index("--app-name")
    assert cmd[ai + 1] == "app_demo"
    bi = cmd.index("--beta-app-dir")
    assert cmd[bi + 1] == str(app)
    ii = cmd.index("--ids-output")
    assert cmd[ii + 1] == str(Path("src") / "app_demo_ids.h")
    assert "--build-ids" in cmd
    assert "--assets" in cmd and cmd[cmd.index("--assets") + 1] == "assets"


def test_detect_no_manifest_no_icon(tmp_path):
    app = make_app(tmp_path)
    cmd, _cwd = detect_pack_command(app)
    assert "--manifest" not in cmd
    assert "--icon" not in cmd
    # legacy palette app: canonical invocation always builds the palette
    assert "--build-palette" in cmd


def test_detect_all_full_manifest_skips_build_palette(tmp_path):
    """gbhotel-shaped app: every sprite color=='full' -> no palette build."""
    app = make_app(tmp_path, sprites=[FULL_SPRITE])
    cmd, _cwd = detect_pack_command(app)
    assert "--build-palette" not in cmd


def test_detect_palette_sprites_keep_build_palette(tmp_path):
    app = make_app(tmp_path, sprites=[PAL_SPRITE, FULL_SPRITE])
    cmd, _cwd = detect_pack_command(app)
    assert "--build-palette" in cmd


def test_detect_export_only_with_psd(tmp_path):
    without = make_app(tmp_path, "app_nopsd")
    cmd, _ = detect_pack_command(without)
    assert "--export" not in cmd
    with_psd = make_app(tmp_path, "app_psd", psd=True)
    cmd, _ = detect_pack_command(with_psd)
    assert "--export" in cmd


def test_detect_multiple_manifests_rejected(tmp_path):
    app = make_app(tmp_path, sprites=[FULL_SPRITE],
                   manifest_names=("a_assets.json", "b_assets.json"))
    with pytest.raises(ValueError, match="--manifest"):
        detect_pack_command(app)


def test_detect_explicit_manifest_and_icon_override(tmp_path):
    app = make_app(tmp_path, sprites=[FULL_SPRITE],
                   manifest_names=("a_assets.json", "b_assets.json"))
    (app / "art" / "logo.png").write_bytes(b"\x89PNG-fake")
    manifest = app / "plans" / "b_assets.json"
    cmd, _ = detect_pack_command(app, manifest=manifest,
                                 icon=app / "art" / "logo.png")
    assert cmd[cmd.index("--manifest") + 1] == str(manifest)
    assert cmd[cmd.index("--icon") + 1] == str(app / "art" / "logo.png")


def test_detect_explicit_missing_paths_rejected(tmp_path):
    app = make_app(tmp_path)
    with pytest.raises(ValueError, match="manifest"):
        detect_pack_command(app, manifest=app / "plans" / "nope.json")
    with pytest.raises(ValueError, match="icon"):
        detect_pack_command(app, icon=app / "art" / "nope.png")


def test_detect_app_name_from_target_marker(tmp_path):
    app = make_app(tmp_path, "app_dirname")
    (app / "app_dirname.target").unlink()
    (app / "app_realname.target").write_text("")
    cmd, _ = detect_pack_command(app)
    assert cmd[cmd.index("--app-name") + 1] == "app_realname"


# ── pipeline-workspace shape (asset-builder Stage 3 output) ────────────────

def make_pipeline_app(root: Path, name: str = "app_demo", *, sprites=None,
                      icon=True) -> Path:
    """App built by build_pipeline.py: sprite PNGs live in assets/art/."""
    app = make_app(root, name, sprites=sprites, icon=icon, psd=True)
    (app / "assets" / "art").mkdir(parents=True)
    (app / "assets" / "art" / "hero.png").write_bytes(b"\x89PNG-fake")
    return app


def test_detect_pipeline_shape_uses_build_pipeline(tmp_path):
    """assets/art PNGs mark the asset-builder pipeline shape: repack must
    re-run the canonical build_pipeline pack invocation (re-atlases the
    workspace PNGs), NOT the scaffold pack.py call — that one would --export
    the template art/assets.psd over the real art."""
    app = make_pipeline_app(tmp_path, sprites=[PAL_SPRITE, FULL_SPRITE])
    cmd, cwd = detect_pack_command(app)
    assert cwd == app
    assert cmd[0] == sys.executable and cmd[1].endswith("build_pipeline.py")
    assert cmd[2] == "pack"
    assert cmd[cmd.index("--game") + 1] == "demo"
    assert cmd[cmd.index("--workspace") + 1] == "assets"
    assert cmd[cmd.index("--src-dir") + 1] == "src"
    assert cmd[cmd.index("--app-dir") + 1] == str(app)
    assert cmd[cmd.index("--manifest") + 1] == str(
        app / "plans" / "demo_assets.json")
    assert cmd[cmd.index("--icon") + 1] == str(app / "art" / "icon.png")
    assert "--export" not in cmd


def test_detect_pipeline_shape_game_from_target_marker(tmp_path):
    app = make_pipeline_app(tmp_path, "app_dirname", sprites=[PAL_SPRITE])
    (app / "app_dirname.target").unlink()
    (app / "app_realname.target").write_text("")
    cmd, _ = detect_pack_command(app)
    assert cmd[cmd.index("--game") + 1] == "realname"


def test_detect_pipeline_shape_without_manifest_or_icon(tmp_path):
    app = make_pipeline_app(tmp_path, icon=False)
    cmd, _ = detect_pack_command(app)
    assert cmd[1].endswith("build_pipeline.py")
    assert "--manifest" not in cmd
    assert "--icon" not in cmd


def test_detect_empty_assets_art_falls_back_to_pack_py(tmp_path):
    """assets/art exists but holds no PNGs -> not the pipeline shape."""
    app = make_app(tmp_path, sprites=[PAL_SPRITE], psd=True)
    (app / "assets" / "art").mkdir(parents=True)
    cmd, _ = detect_pack_command(app)
    assert cmd[1].endswith("pack.py")
    assert "--export" in cmd


def test_detect_pipeline_shape_multiple_manifests_rejected(tmp_path):
    app = make_pipeline_app(tmp_path, sprites=[PAL_SPRITE])
    (app / "plans" / "extra_assets.json").write_text(
        (app / "plans" / "demo_assets.json").read_text())
    with pytest.raises(ValueError, match="--manifest"):
        detect_pack_command(app)


# ── CLI stage order (mocked subprocess) ─────────────────────────────────────

@pytest.fixture
def run_recorder(monkeypatch):
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(cmd, *, cwd=None):
        calls.append(([str(c) for c in cmd], cwd))
        return 0

    monkeypatch.setattr(repack_app, "_run", fake_run)
    return calls


def test_cli_full_cycle_order(tmp_path, run_recorder):
    app = make_app(tmp_path, sprites=[FULL_SPRITE], icon=True)
    rc = _cli(["--app-dir", str(app)])
    assert rc == 0
    assert len(run_recorder) == 2
    pack_cmd, pack_cwd = run_recorder[0]
    assert pack_cmd[1].endswith("pack.py") and pack_cwd == app
    dev_cmd, _ = run_recorder[1]
    assert any("build_device" in c for c in dev_cmd)
    assert str(app) in dev_cmd
    # version bumped between pack and device build
    assert "#define APP_VERSION 101" in (app / "src" / "app.h").read_text(
        encoding="utf-8")


def test_cli_skip_device(tmp_path, run_recorder):
    app = make_app(tmp_path, sprites=[FULL_SPRITE])
    rc = _cli(["--app-dir", str(app), "--skip-device"])
    assert rc == 0
    assert len(run_recorder) == 1          # pack only, no device build
    assert "#define APP_VERSION 101" in (app / "src" / "app.h").read_text(
        encoding="utf-8")


def test_cli_pack_failure_stops_before_bump(tmp_path, monkeypatch):
    app = make_app(tmp_path, sprites=[FULL_SPRITE])
    monkeypatch.setattr(repack_app, "_run", lambda cmd, *, cwd=None: 9)
    rc = _cli(["--app-dir", str(app)])
    assert rc != 0
    assert "#define APP_VERSION 100" in (app / "src" / "app.h").read_text(
        encoding="utf-8")


def test_cli_device_failure_propagates(tmp_path, monkeypatch):
    app = make_app(tmp_path, sprites=[FULL_SPRITE])
    rcs = iter([0, 7])
    monkeypatch.setattr(repack_app, "_run",
                        lambda cmd, *, cwd=None: next(rcs))
    rc = _cli(["--app-dir", str(app)])
    assert rc != 0


def test_cli_detection_error_exits_2(tmp_path, run_recorder, capsys):
    app = make_app(tmp_path, sprites=[FULL_SPRITE],
                   manifest_names=("a_assets.json", "b_assets.json"))
    rc = _cli(["--app-dir", str(app)])
    assert rc == 2
    assert run_recorder == []
    assert "--manifest" in capsys.readouterr().err


def test_cli_missing_app_dir_exits_2(tmp_path):
    assert _cli(["--app-dir", str(tmp_path / "nope")]) == 2


# ── --skip-device end-to-end (real pack.py, no ARM) ─────────────────────────

def test_skip_device_end_to_end(tmp_path):
    """Tiny all-full-color app (gbhotel-shaped): real pack, bump, no device."""
    from PIL import Image

    app = tmp_path / "app_tiny"
    (app / "art" / "exported").mkdir(parents=True)
    (app / "src").mkdir()
    (app / "plans").mkdir()
    (app / "sound" / "assets").mkdir(parents=True)
    (app / "app_tiny.target").write_text("")
    (app / "src" / "app.h").write_text(
        "#define APP_VERSION 100 //v1.00\n", encoding="utf-8")
    (app / "sound" / "assets" / "blip.mp3").write_bytes(b"mp3")

    Image.new("RGB", (16, 16), (30, 60, 200)).save(
        app / "art" / "exported" / "bg.png")
    Image.new("RGB", (64, 64), (10, 200, 30)).save(app / "art" / "icon.png")

    (app / "plans" / "tiny_assets.json").write_text(json.dumps({
        "game": "tiny", "schema_version": 1,
        "sprites": [FULL_SPRITE],
        "sounds": [{"name": "blip", "description": "b"}],
    }), encoding="utf-8")

    rc = _cli(["--app-dir", str(app), "--skip-device"])
    assert rc == 0
    assert (app / "index.bin").is_file()
    assert (app / "art" / "packed" / "bg.raw").is_file()
    ids = (app / "src" / "app_tiny_ids.h").read_text(encoding="utf-8")
    assert "BMP_bg" in ids and "SND_blip" in ids
    assert "#define APP_VERSION 101 //v1.00" in (
        app / "src" / "app.h").read_text(encoding="utf-8")
