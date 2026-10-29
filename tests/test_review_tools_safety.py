"""Review fixes for the template, the hidden-simulator / uploader tools and the build scripts.

Covers: work-dir guards and ASCII (8.3) paths for the MSVC builds, PID-safe stops, crash handling under
-AllowEarlyStop, the uploader's shared-patch selection, check_env under ErrorActionPreference=Stop, the absolute
octpacker venv path, the X11-forced Linux smoke run, and the template/skeleton save + playfield rules.
PowerShell cases run on Windows only; bash cases wherever a working bash exists.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
SCRIPTS = REPO / "scripts"
HAS_PWSH = sys.platform == "win32" and shutil.which("powershell") is not None
pwsh_only = pytest.mark.skipif(not HAS_PWSH, reason="Windows PowerShell only")


def _bash_works() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


bash_only = pytest.mark.skipif(not _bash_works(), reason="needs bash")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _ps(script: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, timeout=180, cwd=cwd)


def _q(p) -> str:
    return "'" + str(p).replace("'", "''") + "'"


# --- 7: -WorkDir guard ------------------------------------------------------------------------------------

@pwsh_only
def test_unsafe_workdirs_are_refused(tmp_path):
    ws = tmp_path / "ws"
    app, octv, tel = ws / "app_x", ws / "octavios", ws / "telemetry"
    for d in (app / "src", octv / "sim" / "src", tel):
        d.mkdir(parents=True)
    safe = ws / ".sim_headless" / "app_x"
    lib = TOOLS / "sim_headless" / "safe_paths.ps1"
    cases = {"ws": ws, "app": app, "appsrc": app / "src", "oct": octv, "octsim": octv / "sim", "tel": tel,
             "root": Path(str(tmp_path.anchor)), "home": Path(os.path.expanduser("~")), "safe": safe}
    lines = [f". {_q(lib)}", f"$prot = @({_q(app)}, {_q(octv)}, {_q(tel)})"]
    for k, v in cases.items():
        lines.append(f"$w = Test-UnsafeWorkDir -WorkDir {_q(v)} -Protect $prot; "
                     f"'{k}=' + $(if ($w) {{ 'REFUSED' }} else {{ 'ok' }})")
    r = _ps("\n".join(lines))
    out = dict(line.split("=", 1) for line in r.stdout.split() if "=" in line)
    assert out.pop("safe") == "ok", r.stdout + r.stderr
    assert set(out.values()) == {"REFUSED"}, out


def test_build_scripts_check_the_workdir_before_creating_it():
    for rel in ("tools/sim_headless/build.ps1", "tools/cube_upload/build.ps1"):
        text = _read(rel)
        assert "safe_paths.ps1" in text
        guard = text.index("Test-UnsafeWorkDir")
        assert guard < text.index("New-Item -ItemType Directory -Force -Path $WorkDir"), rel
        assert guard < text.index("& $python (Join-Path $PSScriptRoot 'patch.py')"), rel
        assert "Get-AsciiPath -Path $WorkDir" in text and "Get-AsciiPath -Path $Telemetry" in text, rel


# --- 8: non-ASCII paths ------------------------------------------------------------------------------------

@pwsh_only
def test_ascii_paths_pass_and_cyrillic_paths_become_short_or_fail_clearly(tmp_path):
    cyr = tmp_path / "\u0418\u0433\u043e\u0440\u044c"   # a Cyrillic folder name
    cyr.mkdir()
    lib = TOOLS / "sim_headless" / "safe_paths.ps1"
    script = (f". {_q(lib)}\n"
              f"'plain=' + (Get-AsciiPath -Path {_q(tmp_path)})\n"
              f"try {{ $s = Get-AsciiPath -Path {_q(cyr)} -What 'work dir'; 'cyr=' + $s }} "
              f"catch {{ 'err=' + $_.Exception.Message }}")
    # the Cyrillic path goes through a UTF-8 script file: -Command on PS 5.1 would mangle it in the ANSI code page
    sf = tmp_path / "t.ps1"
    sf.write_text(script, encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(sf)],
                       capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    out = r.stdout
    assert f"plain={tmp_path}" in out, out + r.stderr
    m = re.search(r"^cyr=(.*)$", out, re.M)
    if m:   # the volume keeps 8.3 names: an ASCII alias of the same folder
        short = m.group(1).strip()
        assert short.isascii() and os.path.samefile(short, cyr)
    else:
        assert "non-ASCII" in out and "Latin letters only" in out, out + r.stderr


def test_run_scripts_pass_ascii_paths_to_the_ansi_simulator():
    run = _read("tools/sim_headless/run.ps1")
    assert "Get-AsciiPath -Path $OutDir" in run and "-OctOut folder" in run
    up = _read("tools/cube_upload/run_upload.ps1")
    assert "Get-AsciiPath -Path $Oct" in up and "safe_paths.ps1" in up


# --- 7: PID reuse ----------------------------------------------------------------------------------------------

@pwsh_only
def test_stop_owned_process_never_touches_a_foreign_pid():
    lib = TOOLS / "sim_headless" / "hidden_launch.ps1"
    r = _ps(f". {_q(lib)}\n"
            f"Stop-OwnedProcess -ProcessId $PID -Exe 'C:\\nowhere\\sim_headless.exe'\n"
            f"Stop-OwnedProcess -ProcessId $PID -Exe (Get-Process -Id $PID).Path -StartTime '2001-01-01T00:00:00Z'\n"
            f"'alive'")
    lines = r.stdout.splitlines()
    assert lines[0].startswith("mismatch") and lines[1].startswith("mismatch"), r.stdout + r.stderr
    assert lines[-1] == "alive"


@pwsh_only
def test_watch_reports_the_exit_code_of_its_own_hidden_process(tmp_path):
    lib = TOOLS / "sim_headless" / "hidden_launch.ps1"
    cmd = Path(os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"))
    r = _ps(f". {_q(lib)}\n"
            f"$id = Start-HiddenProcess -Exe {_q(cmd)} -WorkDir {_q(tmp_path)} -Arguments '/d /c exit 3'\n"
            f"$w = Watch-HiddenProcess -ProcessId $id -TimeoutSec 30 -Exe {_q(cmd)}\n"
            f"'exit=' + $w.Exit + ' visible=' + $w.MaxVisible")
    assert "exit=3 visible=0" in r.stdout, r.stdout + r.stderr


def test_kills_go_through_the_held_handle_and_stop_ps1_checks_identity():
    launcher = _read("tools/sim_headless/hidden_launch.ps1")
    code = "\n".join(line for line in launcher.splitlines() if not line.lstrip().startswith("#"))
    assert "Stop-Process" not in code                          # no bare-PID kill left
    assert code.count("$p.Kill()") >= 3                        # visible, timeout, Stop-OwnedProcess
    assert "held[pi.pid] = pi.hp" in code and "Release($ProcessId)" in code
    stop = _read("tools/sim_headless/stop.ps1")
    assert "Stop-OwnedProcess" in stop and "start_time" in stop
    run = _read("tools/sim_headless/run.ps1")
    assert "start_time = $procStart" in run and "-Exe $Exe" in run
    assert "Stop-Process -Id $procId" not in run


# --- 6: crashes under -AllowEarlyStop -----------------------------------------------------------------------

def test_allow_early_stop_never_accepts_a_crash():
    run = _read("tools/sim_headless/run.ps1")
    crash = run.index("Fail 5 \"the simulator crashed")
    early = run.index("if ($AllowEarlyStop -and")
    assert crash < early                                          # crash verdict first, in every mode
    assert "$r.Exit -lt -1" in run and "$r.Exit -eq 99" in run    # NTSTATUS codes and the marker exit
    assert "$r.Exit -in @(-1, 0, 1)" in run                       # only a kill's codes pass as an early stop


# --- 12: uploader patch selection --------------------------------------------------------------------------

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upload_shared_picks_select_exactly_one_patch_each():
    cu = _load("cu_patch_review", TOOLS / "cube_upload" / "patch.py")
    hl = cu.hl
    for fn, needle in cu._SHARED_PICKS:
        hits = [p for p in hl.PATCHES if p[0] == fn and (needle is None or needle in p[1])]
        assert (len(hits) == 1) if needle else hits, (fn, needle)
    assert len(cu._SHARED) == len({(f, o) for f, o, _n in cu._SHARED})
    doubled = hl.PATCHES + [p for p in hl.PATCHES if "switch(message)" in p[1]]
    with pytest.raises(SystemExit, match="selects 2 headless patches"):
        cu.pick_shared(doubled)
    gone = [p for p in hl.PATCHES if "CreateWindowExA" not in p[1]]
    with pytest.raises(SystemExit, match="selects 0 headless patches"):
        cu.pick_shared(gone)


# --- 9: check_env under ErrorActionPreference=Stop ----------------------------------------------------------

@pwsh_only
def test_check_env_survives_a_caller_with_stop(tmp_path):
    oct_dir = tmp_path / "octavios"
    (oct_dir / "engine").mkdir(parents=True)
    (oct_dir / ".git").mkdir()        # a broken clone: git writes to stderr
    r = _ps(f"$ErrorActionPreference = 'Stop'\n"
            f"& {_q(SCRIPTS / 'check_env.ps1')} -Octavios {_q(oct_dir)} -Workspace {_q(tmp_path)} -SkipMsvc\n"
            f"'EXIT=' + $LASTEXITCODE")
    assert "NativeCommandError" not in r.stdout + r.stderr, r.stdout + r.stderr
    assert re.search(r"EXIT=2", r.stdout), r.stdout + r.stderr


# --- 10: relative octpacker venv ---------------------------------------------------------------------------

def _fake_build_tree(root: Path) -> tuple[Path, Path]:
    ws = root / "ws"
    app = ws / "app_x"
    (app / "src").mkdir(parents=True)
    (app / "app_x.target").write_text("", encoding="utf-8")
    (app / "index.bin").write_bytes(b"\0" * 4)
    (app / "src" / "app_metadata.h").write_text("", encoding="utf-8")
    octv = ws / "octavios"
    (octv / "apps").mkdir(parents=True)
    (octv / "apps" / "CMakeLists.txt").write_text("", encoding="utf-8")
    (octv / "octpacker").mkdir()
    (octv / "octpacker" / "pyproject.toml").write_text("", encoding="utf-8")
    return app, octv


@bash_only
def test_build_device_sh_makes_a_relative_uv_env_absolute(tmp_path):
    app, octv = _fake_build_tree(tmp_path)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "uv").write_text('#!/usr/bin/env bash\necho "UVENV=$UV_PROJECT_ENVIRONMENT"\nexit 1\n', encoding="utf-8", newline="\n")
    caller = tmp_path / "caller"
    caller.mkdir()
    script = (SCRIPTS / "build_device.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
    (tmp_path / "bd.sh").write_text(script, encoding="utf-8", newline="\n")
    # PATH gets the bash form of fakebin (cd + pwd): a "C:/..." entry would split at the colon and miss the fake uv
    r = subprocess.run(["bash", "-c", 'F="$(cd ../fakebin && pwd)"; chmod +x "$F/uv"; export PATH="$F:$PATH"; '
                        'command -v uv | grep -q fakebin || { echo "fake uv not first on PATH"; exit 9; }; '
                        f'bash "{(tmp_path / "bd.sh").as_posix()}" --app-dir "{app.as_posix()}" '
                        f'--octavios "{octv.as_posix()}" --builder octpack --uv-env rel_venv'],
                       capture_output=True, text=True, timeout=120, cwd=caller)
    m = re.search(r"UVENV=(.*)", r.stdout)
    assert m, r.stdout + r.stderr
    env = m.group(1).strip()
    assert env.endswith("/rel_venv") and env != "rel_venv"
    assert "octpacker" not in env
    assert env.rsplit("/", 2)[-2] == "caller"                     # the caller's cwd, not octpacker/


@pwsh_only
def test_build_device_ps1_resolves_uv_env_from_the_ps_location(tmp_path):
    app, octv = _fake_build_tree(tmp_path)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "uv.cmd").write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")
    caller = tmp_path / "caller"
    caller.mkdir()
    r = _ps(f"$env:PATH = {_q(fake)} + ';' + $env:PATH; Set-Location {_q(caller)}\n"
            f"& {_q(SCRIPTS / 'build_device.ps1')} -AppDir {_q(app)} -OctaviOS {_q(octv)} -Builder octpack -UvEnv rel_venv",
            cwd=tmp_path)
    m = re.search(r"octpacker environment: (.*?) \(", r.stdout)
    assert m, r.stdout + r.stderr
    assert Path(m.group(1)) == caller / "rel_venv"


# --- 11: Linux smoke run on Wayland ------------------------------------------------------------------------

def test_linux_smoke_run_forces_x11():
    sh = _read("scripts/new_app.sh")
    block = sh[sh.index("Hidden smoke run"):sh.index("PGID=$!")]
    assert "env -u WAYLAND_DISPLAY" in block and "SDL_VIDEODRIVER=x11" in block
    assert block.index("env -u WAYLAND_DISPLAY") < block.index("setsid xvfb-run")


# --- 1-5: template and skeleton ----------------------------------------------------------------------------

def _code(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def test_template_never_overwrites_an_unknown_save_version():
    src = _read("templates/app_ai_template/src/app_ai_template.h")
    body = src[src.index("void saveLoad(void) {"):src.index("// Util: copy this code if the game keeps a save\nvoid saveDefaults")]
    code = _code(body)
    assert "vars.save.valid = (got >= 0)" not in code
    tail = code[code.rindex("} else {"):]
    assert "saveDefaults();" in tail and "vars.save.valid = false;" in tail      # unknown/newer layout: preserved
    assert "newer" in body and "never write over it" in body


def test_skeleton_on_save_writes_the_games_record():
    sk = _read("src/app_structure_example.h").replace("\r\n", "\n")
    on_save = _code(sk[sk.index("OCT_CALLBACK void on_save()"):sk.index("#ifdef APP_HAS_ON_SAVE_SYNCED")])
    assert "memset(&rec" not in on_save and "saveRecord_t rec;" not in on_save
    assert "if (!vars.save.valid) return;" in on_save
    assert "OCT_save_write(&vars.save.rec" in on_save
    assert "saveRecord_t rec;" in sk[sk.index("typedef struct {\n#ifdef APP_SAVE_SIZE"):]
    assert "saveLoad();" in _code(sk[sk.index("OCT_CALLBACK void on_init()"):sk.index("OCT_CALLBACK void on_tick()")])


@pytest.mark.parametrize("rel", ["templates/app_ai_template/src/app_ai_template.h", "src/app_structure_example.h"])
def test_playfield_uses_the_engines_top_hysteresis(rel):
    src = _read(rel).replace("\r\n", "\n")
    pf = _code(src[src.index("int32_t playfieldPlane(void) {"):])
    pf = pf[:pf.index("\n}\n")]
    assert "topWithHysteresis(&vars.heldTop)" in pf and "OCT_TM_top_side()" not in pf
    assert src.index("static inline int32_t topWithHysteresis") < src.index("int32_t playfieldPlane(void) {")
    assert "vars.heldTop = -1;" in _code(src)


def test_tap_quad_does_not_trust_a_zero_quad_on_old_firmware():
    src = _read("templates/app_ai_template/src/app_ai_template.h")
    fn = _code(src[src.index("int32_t appTapQuad(int32_t tapid) {"):])
    fn = fn[:fn.index("\n}\n")]
    assert "vars.tapQuadReal" in fn and "OCT_cube_pose" in fn
    assert fn.index("tapQuadReal") < fn.index("/ OCT_QUADS_AT_PLANE != tapid")


def test_save_record_size_limits_are_asserted():
    h = _code(_read("templates/app_ai_template/src/app_save.h"))
    assert "uint16_t size;" in h                                   # the dev wire header stays 8 bytes
    assert re.search(r"static_assert\(sizeof\(saveRecord_t\) <= 0xFFFFu", h)
    assert re.search(r"static_assert\(APP_SAVE_SIZE <= 0x80000u", h)
