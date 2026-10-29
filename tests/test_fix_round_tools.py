"""Fix round after the Codex pipeline review (code side), the smaller items:

- art.py `process --only <leaders>`: an incomplete family is fitted from the
  members that have a raw image (shared scale among them, "partial set"
  warning); a full run keeps refusing; a complete set is refitted whole;
- repack_app: an app with art/octpack.json goes to the official octpacker;
- sound_kit expands wildcards itself (PowerShell passes `*.mp3` literally);
- static safety invariants of check_env, build_device, run.ps1 and the
  template's save failure path.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "skills" / "cube_art-director" / "scripts"
sys.path.insert(0, str(ART))

import art  # noqa: E402
import repack_app  # noqa: E402
import sound_kit  # noqa: E402

_REAL_PACKAGED_PYTHON = repack_app.packaged_python


# ── art.py process --only: family leaders first ────────────────────────────────

def _raw(path: Path, box: tuple[int, int, int, int], colour=(30, 60, 200)):
    """A magenta-key raw image with one rectangular subject."""
    a = np.zeros((64, 64, 3), np.uint8)
    a[:] = (255, 0, 255)
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = colour
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a, "RGB").save(path)


@pytest.fixture
def hero_set(tmp_path):
    plans = tmp_path / "plans"
    plans.mkdir()
    spec = plans / "demo_assets.json"
    spec.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [
        {"name": f"hero_walk_0{i}", "size": [16, 16], "description": "d", "background": "key", "group": "hero",
         "anim": "hero_walk", "frame": i, "gen_prompt": f"A knight, frame {i}."} for i in range(3)]}),
        encoding="utf-8")
    ws = tmp_path / "assets_demo"
    return spec, ws


def test_process_only_fits_the_leaders_of_an_incomplete_family(hero_set, capsys):
    spec, ws = hero_set
    _raw(ws / "raw" / "hero_walk_00.png", (8, 8, 56, 56))
    rc = art.main(["process", str(spec), "--only", "hero_walk_00"])
    assert rc == 0
    assert "partial set: refit when the family is complete" in capsys.readouterr().err
    assert (ws / "art" / "hero_walk_00.png").is_file()
    assert not (ws / "art" / "hero_walk_01.png").exists()
    prov = json.loads((ws / "qa" / "provenance.json").read_text(encoding="utf-8"))
    assert prov["hero_walk_00"].get("partial_set") is True


def test_partial_members_share_one_scale(hero_set):
    spec, ws = hero_set
    _raw(ws / "raw" / "hero_walk_00.png", (8, 8, 56, 56))          # big subject
    _raw(ws / "raw" / "hero_walk_01.png", (24, 24, 40, 40))        # small subject: must stay smaller
    assert art.main(["process", str(spec), "--only", "hero_walk_00,hero_walk_01"]) == 0

    def area(name):
        return int((np.array(Image.open(ws / "art" / f"{name}.png"))[..., 3] > 0).sum())
    assert area("hero_walk_01") < area("hero_walk_00") / 4         # one shared scale, not fitted one by one


def test_full_run_still_refuses_an_incomplete_set(hero_set, capsys):
    spec, ws = hero_set
    _raw(ws / "raw" / "hero_walk_00.png", (8, 8, 56, 56))
    assert art.main(["process", str(spec)]) == 1
    assert "no raw image for hero_walk_01,hero_walk_02" in capsys.readouterr().err
    assert not (ws / "art" / "hero_walk_00.png").exists()


def test_complete_family_is_refitted_whole_and_clears_the_partial_mark(hero_set, capsys):
    spec, ws = hero_set
    _raw(ws / "raw" / "hero_walk_00.png", (8, 8, 56, 56))
    assert art.main(["process", str(spec), "--only", "hero_walk_00"]) == 0
    for i in (1, 2):
        _raw(ws / "raw" / f"hero_walk_0{i}.png", (10, 10, 50, 50))
    capsys.readouterr()
    assert art.main(["process", str(spec), "--only", "hero_walk_00"]) == 0
    assert "partial set" not in capsys.readouterr().err
    prov = json.loads((ws / "qa" / "provenance.json").read_text(encoding="utf-8"))
    assert all("partial_set" not in prov[f"hero_walk_0{i}"] for i in range(3))
    assert all((ws / "art" / f"hero_walk_0{i}.png").is_file() for i in range(3))


def test_single_asset_without_raw_is_still_a_problem(tmp_path):
    spec = tmp_path / "plans" / "demo_assets.json"
    spec.parent.mkdir()
    spec.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [
        {"name": "bg", "size": [16, 16], "description": "d", "background": "opaque", "gen_prompt": "A wall."}]}),
        encoding="utf-8")
    assert art.main(["process", str(spec), "--only", "bg"]) == 1


def test_cube_manifest_names_follow_the_packer_rules(tmp_path):
    from art_spec import Asset, Project, validate
    p = Project(root=tmp_path, name="t", bible=None, anchors=[], kind="cube-manifest", workspace=tmp_path / "ws",
                assets=[Asset(n, (8, 8), prompt="p") for n in ("1up", "ico_idle", "ahover", "hero")])
    errs = validate(p)
    assert sum("WowCube asset names" in e for e in errs) == 3
    p.kind = "art"                                                    # artist projects keep their own rules
    assert not any("WowCube" in e for e in validate(p))


# ── repack_app: art/octpack.json -> the official octpacker ────────────────────

@pytest.fixture(autouse=True)
def _ordinary_python(monkeypatch):
    """Tests decide whether the interpreter is a Microsoft Store (packaged) Python; the host's does not leak in."""
    monkeypatch.setattr(repack_app, "packaged_python", lambda: False)


def _psd_app(root: Path) -> Path:
    app = root / "app_psd"
    (app / "art").mkdir(parents=True)
    (app / "src").mkdir()
    (app / "app_psd.target").write_text("")
    (app / "art" / "octpack.json").write_text('{"assets": ["assets.psd"], "maps": ["ico.psd"]}')
    (app / "src" / "app.h").write_text("#define APP_VERSION 100\n", encoding="utf-8")
    (root / "assets_psd" / "art").mkdir(parents=True)           # even with a workspace next to it
    (root / "assets_psd" / "art" / "x.png").write_bytes(b"\x89PNG")
    return app


def _sdk(root: Path) -> Path:
    sdk = root / "octavios"
    (sdk / "octpacker").mkdir(parents=True)
    (sdk / "octpacker" / "pyproject.toml").write_text("[project]\nname='octpack'\n")
    return sdk


def test_octpack_json_dispatches_the_official_packer(tmp_path, monkeypatch):
    monkeypatch.setattr(repack_app, "_have", lambda exe: exe == "uv")
    app, sdk = _psd_app(tmp_path), _sdk(tmp_path)
    cmd, cwd = repack_app.detect_pack_command(app)
    assert cmd == ["uv", "run", "--frozen", "--project", str(sdk.resolve() / "octpacker"), "octpack-pack",
                   str(app.resolve()), "--engine", str(sdk.resolve())]
    assert cwd == app.resolve()


def test_octpack_json_needs_the_sdk_and_uv(tmp_path, monkeypatch):
    app = _psd_app(tmp_path)
    monkeypatch.setattr(repack_app, "_have", lambda exe: True)
    with pytest.raises(ValueError, match="octpacker"):
        repack_app.detect_pack_command(app)                       # no SDK next to the app
    other = _sdk(tmp_path / "elsewhere")
    assert "octpack-pack" in repack_app.detect_pack_command(app, octavios=other)[0]
    monkeypatch.setattr(repack_app, "_have", lambda exe: False)
    with pytest.raises(ValueError, match="uv"):
        repack_app.detect_pack_command(app, octavios=other)


def test_cli_runs_octpack_pack_then_bumps_and_builds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(repack_app, "_have", lambda exe: exe == "uv")
    app, sdk = _psd_app(tmp_path), _sdk(tmp_path)
    calls = []
    monkeypatch.setattr(repack_app, "_run", lambda cmd, *, cwd=None: (calls.append([str(c) for c in cmd]), 0)[1])
    assert repack_app._cli(["--app-dir", str(app), "--icon", str(tmp_path / "ignored.png")]) == 0
    assert calls[0][:2] == ["uv", "run"] and "octpack-pack" in calls[0]
    assert any("build_device" in c for c in calls[1])
    assert "#define APP_VERSION 101" in (app / "src" / "app.h").read_text(encoding="utf-8")
    assert "are ignored" in capsys.readouterr().out


def test_store_python_never_starts_uv(tmp_path, monkeypatch, capsys):
    """A Store (MSIX) Python's children see a private AppData: uv rebuilt the octpacker venv from there once.
    The official packer is refused with the exact command for a normal shell; the device stage gets -NoUv."""
    monkeypatch.setattr(repack_app, "packaged_python", lambda: True)
    monkeypatch.setattr(repack_app, "_have", lambda exe: exe == "uv")
    app, _sdk_dir = _psd_app(tmp_path), _sdk(tmp_path)
    with pytest.raises(ValueError, match="Microsoft Store") as e:
        repack_app.detect_pack_command(app)
    assert "octpack-pack" in str(e.value) and "normal PowerShell" in str(e.value)

    ai_app = _psd_app(tmp_path / "ai")
    (ai_app / "art" / "octpack.json").unlink()
    calls = []
    monkeypatch.setattr(repack_app, "_run", lambda cmd, *, cwd=None: (calls.append([str(c) for c in cmd]), 0)[1])
    assert repack_app._cli(["--app-dir", str(ai_app)]) == 0
    no_uv_flag = "-NoUv" if sys.platform == "win32" else "--no-uv"
    assert no_uv_flag in calls[1] and "uv" not in calls[0][:1]
    assert "without uv" in capsys.readouterr().out
    assert repack_app._cli(["--app-dir", str(ai_app), "--builder", "octpack"]) == 2


def test_build_device_command_no_uv_flag(tmp_path):
    flag = "-NoUv" if sys.platform == "win32" else "--no-uv"
    assert flag in repack_app.build_device_command(tmp_path / "app_demo", no_uv=True)
    assert flag not in repack_app.build_device_command(tmp_path / "app_demo")


def test_packaged_python_probe_answers_a_bool(monkeypatch):
    result = _REAL_PACKAGED_PYTHON()
    assert isinstance(result, bool)
    if sys.platform != "win32":
        assert result is False
    monkeypatch.setattr(repack_app.os, "name", "posix")
    assert _REAL_PACKAGED_PYTHON() is False


def test_build_device_ps1_gates_every_uv_call_on_no_uv():
    text = _read("scripts/build_device.ps1")
    assert "[switch] $NoUv" in text and "WOWCUBE_NO_UV" in text
    assert "$useUv = (Have 'uv') -and -not $NoUv" in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert code.count("(Have 'uv')") == 1                      # only the $useUv line asks for uv directly
    sh = _read("scripts/build_device.sh")
    assert "--no-uv)" in sh and sh.count("have uv") == 1


def test_ai_art_apps_keep_the_python_packer(tmp_path):
    """new_app renames the template's octpack.json away: an AI-art app is never sent to octpack-pack."""
    app = _psd_app(tmp_path)
    (app / "art" / "octpack.json").rename(app / "art" / "octpack.json.template")
    cmd, _cwd = repack_app.detect_pack_command(app)
    assert "octpack-pack" not in cmd and cmd[1].endswith("build_pipeline.py")


# ── sound_kit: wildcards expanded in python ──────────────────────────────────

def test_sound_kit_expands_wildcards_itself(tmp_path):
    for n in ("b.mp3", "a.mp3", "c.wav"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "take [1].wav").write_bytes(b"x")
    got = sound_kit.expand_files([str(tmp_path / "*.mp3"), str(tmp_path / "take [1].wav"), str(tmp_path / "c.wav")])
    assert [Path(g).name for g in got] == ["a.mp3", "b.mp3", "take [1].wav", "c.wav"]
    with pytest.raises(SystemExit, match="no file matches"):
        sound_kit.expand_files([str(tmp_path / "*.ogg")])


def test_sound_kit_main_receives_expanded_files(tmp_path, monkeypatch):
    for n in ("x.mp3", "y.mp3"):
        (tmp_path / n).write_bytes(b"x")
    seen = []
    monkeypatch.setattr(sound_kit, "cmd_inspect", lambda args: seen.extend(args.files) or 0)
    assert sound_kit.main(["inspect", str(tmp_path / "*.mp3")]) == 0
    assert [Path(s).name for s in seen] == ["x.mp3", "y.mp3"]


# ── static invariants of the scripts ─────────────────────────────────────────

def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _code_lines(text: str) -> str:
    """PowerShell source without the <# help #> block and # comments."""
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_check_env_installs_are_quiet_and_never_pipe_to_a_shell():
    ps = _code_lines(_read("scripts/check_env.ps1"))
    msvc = re.search(r"^\$MSVC_ARGS\s*=\s*'([^']*)'", ps, re.M).group(1)
    assert "--passive" not in ps and "--quiet" in msvc and "--norestart" in msvc
    for line in re.findall(r"^\s*winget install .*$", ps, re.M):
        assert "--silent" in line or "--override" in line
    sh = "\n".join(line for line in _read("scripts/check_env.sh").splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"curl[^\n|]*\|\s*(ba)?sh", sh) and not re.search(r"wget[^\n|]*\|\s*(ba)?sh", sh)
    assert "pipx install uv" in sh


@pytest.mark.parametrize("rel", ["scripts/build_device.ps1", "scripts/build_device.sh"])
def test_build_device_verification_is_mandatory(rel):
    text = _read(rel)
    assert "header checks skipped" not in text
    assert "--verify-oct" in text and "--info-json" in text
    assert re.search(r"verification failed", text)


def test_run_ps1_only_passes_a_completed_timed_run():
    text = _read("tools/sim_headless/run.ps1")
    assert "[switch] $AllowEarlyStop" in text
    assert "Fail 7" in text and "headless_summary.txt" in text
    assert "before its timed exit (stopped by PID?)" not in text      # the old NOTE-then-exit-0 path is gone
    tail = text[text.index("Fail 4"):]
    assert tail.index("Fail 7") < tail.index("timed run completed")


def test_template_save_failure_path_keeps_modules_identical():
    src = _read("templates/app_ai_template/src/app_ai_template.h")
    begin = src[src.index("void saveBegin(void) {"):src.index("// Util: copy this code if the game keeps a save\nvoid saveLoad")]
    sync_branch = begin[begin.index("#if defined(APP_SAVE_SIZE) && defined(APP_HAS_ON_SAVE_SYNCED)"):begin.index("#elif")]
    code = "\n".join(line.split("//", 1)[0] for line in sync_branch.splitlines())
    assert "saveLoad()" not in code                                   # never read the own card on this path
    assert code.index("saveDefaults();") < code.index("OCT_save_sync(")
    assert code.index("vars.save.valid = false;") < code.index("OCT_save_sync(")
    synced = src[src.index("OCT_CALLBACK void on_save_synced"):]
    synced = synced[:synced.index("#endif\n}") if "#endif\n}" in synced else 2000]
    assert "saveDefaults();" in synced and "vars.save.valid = false;" in synced


def test_process_reruns_the_post_hook_on_every_run(hero_set):
    """fixes.json "@post": a reviewer's processing fix (here: paint pixel 0,0 red) is re-applied after every
    process run instead of being silently undone by it; provenance records the post-processed final."""
    spec, ws = hero_set
    for i in range(3):
        _raw(ws / "raw" / f"hero_walk_0{i}.png", (8, 8, 56, 56))
    (ws / "post.py").write_text(
        "import sys\nfrom pathlib import Path\nfrom PIL import Image\n"
        "out = Path(sys.argv[1])\n"
        "for n in sys.argv[2:]:\n"
        "    im = Image.open(out / f'{n}.png').convert('RGBA'); im.putpixel((0, 0), (255, 0, 0, 255)); im.save(out / f'{n}.png')\n",
        encoding="utf-8")
    (ws / "fixes.json").write_text(json.dumps({"@post": "post.py"}), encoding="utf-8")
    for _ in range(2):
        assert art.main(["process", str(spec)]) == 0
        for i in range(3):
            assert Image.open(ws / "art" / f"hero_walk_0{i}.png").convert("RGBA").getpixel((0, 0)) == (255, 0, 0, 255)
    prov = json.loads((ws / "qa" / "provenance.json").read_text(encoding="utf-8"))
    assert prov["hero_walk_00"]["post"] == "post.py"


def test_process_reports_a_missing_or_failing_post_hook(hero_set):
    spec, ws = hero_set
    for i in range(3):
        _raw(ws / "raw" / f"hero_walk_0{i}.png", (8, 8, 56, 56))
    (ws / "fixes.json").write_text(json.dumps({"@post": "nope.py"}), encoding="utf-8")
    assert art.main(["process", str(spec)]) == 1
    (ws / "bad.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    (ws / "fixes.json").write_text(json.dumps({"@post": "bad.py"}), encoding="utf-8")
    assert art.main(["process", str(spec)]) == 1


def test_octpacker_environment_defaults_to_the_workspace(tmp_path, monkeypatch):
    """uv must never create octavios/octpacker/.venv: the default environment is <workspace>/.uv_octpack_venv."""
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    app = tmp_path / "ws" / "app_x"
    app.mkdir(parents=True)
    assert Path(repack_app.uv_env_for(app)) == (tmp_path / "ws" / ".uv_octpack_venv").resolve()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "mine"))
    assert repack_app.uv_env_for(app) == str(tmp_path / "mine")
    ps1 = (REPO / "scripts" / "build_device.ps1").read_text(encoding="utf-8")
    sh = (REPO / "scripts" / "build_device.sh").read_text(encoding="utf-8")
    assert ".uv_octpack_venv" in ps1 and "$env:UV_PROJECT_ENVIRONMENT =" in ps1
    assert ".uv_octpack_venv" in sh and "export UV_PROJECT_ENVIRONMENT=" in sh
