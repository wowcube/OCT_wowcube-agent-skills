"""Tests for build_pipeline.py.

Sprite generation is stubbed offline via the `stub_ai` fixture (no real
OpenRouter call); the Codex path is faked at `image_providers.codex_generate`
and Codex detection is switched off for every test here, so a logged-in Codex
on the test machine is never launched. Heavy integration (pack stage) runs
only when pytoshop AND psd-tools are importable; otherwise those tests skip.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import image_providers
from build_pipeline import find_script, _cli


@pytest.fixture(autouse=True)
def _no_real_codex(monkeypatch):
    monkeypatch.setenv(image_providers.NO_CODEX_ENV, "1")

    def _guard(argv, **kwargs):
        raise AssertionError(f"unexpected subprocess (Codex/art.py) in a pipeline test: {argv}")

    monkeypatch.setattr(image_providers, "_run", _guard)
    image_providers._codex_login_cache.clear()


@pytest.fixture
def codex_provider(monkeypatch):
    """Resolve the codex provider and fake the art.py delegation: the fake
    writes one final PNG per selected sprite into <workspace>/art and records
    every call. genimg must never be reached on this path."""
    import genimg
    from PIL import Image

    from manifest_schema import load_manifest

    monkeypatch.setattr(image_providers, "resolve_provider",
                        lambda: image_providers.ProviderConfig(provider="codex", cli="codex"))
    calls: list[dict] = []

    def _fake_generate(manifest_path, workspace, *, only=None, force=False, jobs=None):
        calls.append({"manifest": Path(manifest_path), "workspace": Path(workspace),
                      "only": only, "force": force, "jobs": jobs})
        art = Path(workspace) / "art"
        art.mkdir(parents=True, exist_ok=True)
        for s in load_manifest(manifest_path).sprites:
            if only is None or s.name in only:
                Image.new("RGBA", tuple(s.size), (0, 0, 0, 0)).save(art / f"{s.name}.png")

    def _no_genimg(*a, **k):
        raise AssertionError("the codex path must not call genimg per sprite")

    monkeypatch.setattr(image_providers, "codex_generate", _fake_generate)
    monkeypatch.setattr(genimg, "generate_image", _no_genimg)
    return calls


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


def test_generate_no_provider_configured_fails(tmp_path, tmp_manifest, minimal_manifest,
                                               monkeypatch, capsys):
    """No image provider from ANY config source stops the generate stage at
    the dep check, with a message naming all three sources + the placeholder
    fallback (mocked resolve_provider so host env/config files don't leak in)."""
    import image_providers
    monkeypatch.setattr(image_providers, "resolve_provider", lambda: None)
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 3
    err = capsys.readouterr().err
    assert "OPENROUTER_API_KEY" in err
    assert "IMAGE_API" in err
    assert "image_api.json" in err
    assert "placeholder" in err


def test_generate_any_configured_provider_passes(tmp_path, tmp_manifest, minimal_manifest,
                                                 monkeypatch, stub_ai, stub_ffmpeg):
    """A provider resolved from ANY source (not just OPENROUTER_API_KEY env)
    passes the dep check: key env removed, resolve_provider mocked to a
    non-openrouter config."""
    import image_providers
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        image_providers, "resolve_provider",
        lambda: image_providers.ProviderConfig(provider="openai", key="sk-x"))
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 0


def test_generate_invalid_provider_config_fails(tmp_path, tmp_manifest, minimal_manifest,
                                                monkeypatch, capsys):
    """A present-but-broken config (e.g. garbage IMAGE_API) is a dep error too."""
    import image_providers

    def boom():
        raise image_providers.UnknownProviderError("cannot identify an image provider")

    monkeypatch.setattr(image_providers, "resolve_provider", boom)
    manifest = tmp_manifest(minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest),
               "--workspace", str(tmp_path / "assets")])
    assert rc == 3
    assert "cannot identify an image provider" in capsys.readouterr().err


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


def _writes_pal(workspace: Path, inner=None):
    """A fake `_run` for the pack stage: like the real pack.py, the pack.py
    call (re)creates <ws>/packed/pal.png - the stage clears <ws>/packed
    before it runs, so a pre-seeded one does not survive."""
    def fake(cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        if any(c.endswith("pack.py") for c in cmd):
            (workspace / "packed").mkdir(parents=True, exist_ok=True)
            (workspace / "packed" / "pal.png").write_bytes(b"x")
        return inner(cmd, cwd) if inner else 0
    return fake


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

    monkeypatch.setattr(build_pipeline, "_run", _writes_pal(workspace, fake_run))

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


def test_pack_moves_mp3s_not_in_the_manifest_out_of_sound_assets(tmp_path, monkeypatch, capsys):
    """The scaffold leaves the template's demo mp3s in sound/assets and every packer ships whatever lies there:
    with a manifest the pack stage moves the extras to sound/unused/ (read by no packer) before pack.py runs."""
    import json
    import build_pipeline
    from PIL import Image

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(workspace / "art" / "coin.png")
    (workspace / "wav" / "assets").mkdir(parents=True)
    (workspace / "wav" / "assets" / "sfx_coin.mp3").write_bytes(b"game")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    app_dir = tmp_path / "app_tiny"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "src" / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    (app_dir / "sound" / "assets").mkdir(parents=True)
    for n in ("digit_merge0", "digit_merge1"):
        (app_dir / "sound" / "assets" / f"{n}.mp3").write_bytes(b"template")
    manifest = tmp_path / "tiny_assets.json"
    manifest.write_text(json.dumps({
        "game": "tiny", "schema_version": 1,
        "sprites": [{"name": "coin", "size": [8, 8], "description": "coin", "gen_prompt": "a coin",
                     "background": "key"}],
        "sounds": [{"name": "sfx_coin", "description": "beep", "duration_ms": 200, "event_type": "pickup"}],
    }), encoding="utf-8")
    at_pack: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        if "--beta-app-dir" in cmd:
            at_pack.append(sorted(p.name for p in (app_dir / "sound" / "assets").glob("*.mp3")))
        return 0

    monkeypatch.setattr(build_pipeline, "_run", _writes_pal(workspace, fake_run))
    rc = build_pipeline._cli(["pack", "--game", "tiny", "--workspace", str(workspace),
                              "--src-dir", str(tmp_path / "src"), "--app-dir", str(app_dir),
                              "--manifest", str(manifest)])
    assert rc == 0
    assert at_pack == [["sfx_coin.mp3"]]
    assert sorted(p.name for p in (app_dir / "sound" / "unused").iterdir()) == ["digit_merge0.mp3", "digit_merge1.mp3"]
    assert "not in the manifest" in capsys.readouterr().err


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
    monkeypatch.setattr(build_pipeline, "_run", _writes_pal(
        workspace, lambda cmd, cwd=None: (calls.append([str(c) for c in cmd]), 0)[1]))

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
        "--app-dir", str(app_dir),
    ])
    assert rc == 0
    assert "--beta-app-dir" in calls[1]
    assert not (app_dir / "sound").exists()


def test_pack_forwards_icon_to_pack_py(tmp_path, monkeypatch):
    """--icon is passed through to pack.py alongside the beta args, so
    repack_app's detected icon reaches the beta emit (launcher ico/ahover)."""
    import build_pipeline
    from PIL import Image

    workspace = tmp_path / "assets"
    (workspace / "art").mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(workspace / "art" / "x.png")
    (workspace / "packed").mkdir()
    (workspace / "packed" / "pal.png").write_bytes(b"x")
    (workspace / "app_tiny_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
    app_dir = tmp_path / "app_tiny"
    (app_dir / "src").mkdir(parents=True)
    (app_dir / "src" / "app_tiny_ids.h").write_text(
        "enum BMP { BMP_none = 0, BMP_last};")
    icon = tmp_path / "icon.png"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(icon)

    calls: list[list[str]] = []
    monkeypatch.setattr(build_pipeline, "_run", _writes_pal(
        workspace, lambda cmd, cwd=None: (calls.append([str(c) for c in cmd]), 0)[1]))

    rc = build_pipeline._cli([
        "pack", "--game", "tiny",
        "--workspace", str(workspace),
        "--src-dir", str(tmp_path / "src"),
        "--app-dir", str(app_dir),
        "--icon", str(icon),
    ])
    assert rc == 0
    pack_cmd = calls[1]
    assert pack_cmd[pack_cmd.index("--icon") + 1] == str(icon)


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

    monkeypatch.setattr(build_pipeline, "_run", _writes_pal(workspace))

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


# ── Codex provider: generate delegates to cube_art-director's art.py ─────────

def _plans_manifest(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "plans" / f"{data['game']}_assets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_generate_codex_delegates_to_art_director(tmp_path, minimal_manifest, codex_provider,
                                                  stub_ffmpeg, capsys):
    manifest = _plans_manifest(tmp_path, minimal_manifest)
    ws = tmp_path / "assets_demo"
    rc = _cli(["generate", "--manifest", str(manifest), "--workspace", str(ws)])
    assert rc == 0
    assert codex_provider == [{"manifest": manifest, "workspace": ws, "only": None,
                               "force": False, "jobs": 3}]
    assert (ws / "art" / "coin.png").exists()
    # sounds still get placeholders on the codex path
    assert (ws / "wav" / "sfx_coin.wav").exists()
    assert (ws / "wav" / "assets" / "sfx_coin.mp3").exists()
    out = capsys.readouterr().out
    assert "codex via art.py" in out and "art.py qa" in out


def test_generate_codex_default_workspace_is_assets_game(tmp_path, minimal_manifest,
                                                         codex_provider, no_ffmpeg):
    """No --workspace: the per-game folder next to plans/ that art.py also uses
    (never a shared assets/ folder)."""
    manifest = _plans_manifest(tmp_path, minimal_manifest)
    assert _cli(["generate", "--manifest", str(manifest)]) == 0
    assert codex_provider[0]["workspace"] == (tmp_path / "assets_demo").resolve()
    assert (tmp_path / "assets_demo" / "wav" / "sfx_coin.wav").exists()
    assert not (tmp_path / "assets").exists()


def test_generate_codex_group_force_jobs_and_seeded_refs(tmp_path, animation_manifest,
                                                         codex_provider, no_ffmpeg):
    data = dict(animation_manifest)
    data["sprites"] = animation_manifest["sprites"] + [
        {"name": "coin", "size": [16, 16], "description": "coin", "gen_prompt": "a coin",
         "group": "pickup"}]
    manifest = _plans_manifest(tmp_path, data)
    ws = tmp_path / "assets_demo"
    rc = _cli(["generate", "--manifest", str(manifest), "--workspace", str(ws),
               "--group", "hero", "--force", "--jobs", "5"])
    assert rc == 0
    call = codex_provider[0]
    assert call["only"] == ["hero_idle_00", "hero_idle_01", "hero_idle_02"]
    assert call["force"] is True and call["jobs"] == 5
    fixes = json.loads((ws / "fixes.json").read_text(encoding="utf-8"))
    assert fixes == {"hero_idle_01": {"text": "", "ref": "hero_idle_00"},
                     "hero_idle_02": {"text": "", "ref": "hero_idle_00"}}


def test_generate_codex_failure_is_exit_6(tmp_path, minimal_manifest, codex_provider,
                                          monkeypatch, capsys):
    def _fail(*a, **k):
        raise image_providers.ImageGenError("art.py gen failed (exit 1/0)")

    monkeypatch.setattr(image_providers, "codex_generate", _fail)
    manifest = _plans_manifest(tmp_path, minimal_manifest)
    rc = _cli(["generate", "--manifest", str(manifest), "--workspace", str(tmp_path / "ws")])
    assert rc == 6
    assert "art.py gen failed" in capsys.readouterr().err


def test_generate_keeps_a_sourced_sound(tmp_path, minimal_manifest, codex_provider,
                                        stub_ffmpeg, capsys):
    """A real recording built by sound_kit (or dropped in by the user) in
    <ws>/wav/assets is never replaced by a synthesised placeholder."""
    manifest = _plans_manifest(tmp_path, minimal_manifest)
    ws = tmp_path / "assets_demo"
    real = ws / "wav" / "assets" / "sfx_coin.mp3"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"real CC0 recording")
    assert _cli(["generate", "--manifest", str(manifest), "--workspace", str(ws)]) == 0
    assert real.read_bytes() == b"real CC0 recording"
    assert not (ws / "wav" / "sfx_coin.wav").exists()
    assert "1 sourced sound(s) kept" in capsys.readouterr().out


def test_generate_api_path_prefixes_the_manifest_style(tmp_path, minimal_manifest,
                                                       monkeypatch, no_ffmpeg):
    """Paid-API fallback: the per-game `_style` goes in front of every
    gen_prompt (art.py does that from STYLE.md on the Codex path)."""
    import genimg

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv(image_providers.ALLOW_PAID_ENV, "1")    # the paid fallback is opt-in
    prompts: list[str] = []

    def _fake(prompt, out_path, *, size=None, reference=None, cutout=False):
        from PIL import Image
        prompts.append(prompt)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", tuple(size)).save(out_path)
        return Path(out_path)

    monkeypatch.setattr(genimg, "generate_image", _fake)
    data = dict(minimal_manifest, _style="Style: flat vector, thick outlines.")
    manifest = _plans_manifest(tmp_path, data)
    assert _cli(["generate", "--manifest", str(manifest), "--workspace", str(tmp_path / "ws")]) == 0
    assert prompts and prompts[0].startswith("Style: flat vector, thick outlines.")
