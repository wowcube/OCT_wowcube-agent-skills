"""Integration tests for scripts/new_app.(ps1|sh) and the SDK part of scripts/check_env.(ps1|sh).

The scaffolders run for real against the repo template (clone, rename, dev metadata, python pack) with the build
skipped, so no SDK, compiler or simulator is involved. PowerShell variants run on Windows only; the bash variants
wherever bash is available (Git Bash on Windows included).
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
HAS_PWSH = sys.platform == "win32" and shutil.which("powershell") is not None


def _bash_works() -> bool:
    """A usable bash, not Windows' System32 WSL launcher without a distribution (what PowerShell finds first)."""
    import subprocess
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


HAS_BASH = _bash_works()
META_KEYS = ("APP_VERSION", "APP_GUID1", "APP_TITLE", "APP_CATEGORIES", "APP_COLORS")


def _scaffold(kind: str, ws: Path, name: str, with_save: bool) -> subprocess.CompletedProcess:
    if kind == "ps1":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "new_app.ps1"),
               "-Name", name, "-Workspace", str(ws), "-SkipEnvCheck", "-SkipBuild"] + (["-WithSave"] if with_save else [])
    else:
        cmd = ["bash", str(SCRIPTS / "new_app.sh"), "--name", name, "--workspace", ws.as_posix(),
               "--skip-env-check", "--skip-build"] + (["--with-save"] if with_save else [])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def _index_has_map(index_bin: Path, name: str) -> bool:
    d = index_bin.read_bytes()
    n = struct.unpack_from("<i", d, 0)[0]
    return any(struct.unpack_from("<i", d, 4 + i * 28)[0] == 3 and d[8 + i * 28:32 + i * 28].split(b"\0")[0] == name.encode()
               for i in range(n))


KINDS = [pytest.param("ps1", marks=pytest.mark.skipif(not HAS_PWSH, reason="Windows PowerShell only")),
         pytest.param("sh", marks=pytest.mark.skipif(not HAS_BASH, reason="needs bash"))]


@pytest.mark.parametrize("kind", KINDS)
def test_scaffold_produces_dev_layout(tmp_path, kind):
    r = _scaffold(kind, tmp_path, "my_game", with_save=True)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    app = tmp_path / "app_my_game"
    src = app / "src"
    assert (app / "app_my_game.target").is_file()
    assert not list(app.rglob("*app_ai_template*")), "template name left in a file name"

    meta = (src / "app_metadata.h").read_text(encoding="utf-8-sig")
    guid = re.search(r"(?m)^\s*#\s*define\s+APP_GUID1\s+0x([0-9A-Fa-f]{16})", meta)
    assert guid and int(guid.group(1), 16) != 0, "APP_GUID1 must be a random non-zero 64-bit value"
    assert re.search(r'(?m)^\s*#\s*define\s+APP_TITLE\s+"My Game"', meta)
    assert "OCT_APP_SEMVER" in meta and re.search(r"(?m)^\s*#\s*define\s+APP_VERSION_PATCH\s+\d+", meta)
    assert re.search(r'(?m)^\s*#\s*include\s+"app_save\.h"', meta), "--with-save must enable the save area"
    assert re.search(r"(?m)^\s*#\s*define\s+SAVE_MAGIC\s+0x4D594731u", (src / "app_save.h").read_text(encoding="utf-8-sig")), "MYG1"

    app_h = (src / "app.h").read_text(encoding="utf-8-sig")
    assert re.search(r'(?m)^\s*#\s*include\s+"app_metadata\.h"', app_h)
    for k in META_KEYS:
        assert not re.search(rf"(?m)^\s*#\s*define\s+{k}\b", app_h), f"app.h must not define {k}"
    assert "app_my_game" in app_h and "app_ai_template" not in app_h
    for h in src.glob("*.h"):
        assert not re.search(r"(?m)^\s*#\s*define\s+SIM_SINGLE_THREAD\b", h.read_text(encoding="utf-8-sig")), h.name

    assert _index_has_map(app / "index.bin", "ico"), "launcher map 'ico' missing"
    ids = (src / "app_my_game_ids.h").read_text(encoding="utf-8")
    assert re.search(r"\bBMP_font_1_\d{5}\b", ids), "BMFont glyphs missing: labels would draw nothing"


@pytest.mark.skipif(not (HAS_PWSH and HAS_BASH), reason="needs both shells")
def test_scaffolds_get_different_guids(tmp_path):
    guids = []
    for kind in ("ps1", "sh"):
        ws = tmp_path / kind
        ws.mkdir()
        r = _scaffold(kind, ws, "twin", with_save=False)
        assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
        meta = (ws / "app_twin" / "src" / "app_metadata.h").read_text(encoding="utf-8-sig")
        guids.append(re.search(r"APP_GUID1\s+(0x[0-9A-Fa-f]+)", meta).group(1))
        assert re.search(r'(?m)^\s*//\s*#\s*include\s+"app_save\.h"', meta), "no save area unless asked"
    assert guids[0] != guids[1]


def _fake_sdk(root: Path, complete: bool) -> Path:
    oct_dir = root / "octavios"
    files = ["engine/oct_app_version.h", "octpacker/pyproject.toml", "tools/mcp/octavios_mcp.py",
             "sim/src/sim_mcp.h", "tools/new_app.ps1", "tools/new_app.sh"]
    if not complete:
        files.remove("octpacker/pyproject.toml")
    for f in files:
        (oct_dir / f).parent.mkdir(parents=True, exist_ok=True)
        (oct_dir / f).write_text("x", encoding="utf-8")
    tel = root / "telemetry" / "octavios_simulator" / "telemetry_sim.cpp"
    tel.parent.mkdir(parents=True)
    tel.write_text("x", encoding="utf-8")
    return oct_dir


def _check_env(kind: str, oct_dir: Path) -> str:
    if kind == "ps1":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "check_env.ps1"),
               "-Octavios", str(oct_dir), "-SkipMsvc"]
    else:
        cmd = ["bash", str(SCRIPTS / "check_env.sh"), "--octavios", oct_dir.as_posix()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_check_env_reports_dev_sdk_and_telemetry(tmp_path, kind):
    out = _check_env(kind, _fake_sdk(tmp_path, complete=True))
    assert re.search(r"\[ok\]\s+octavios dev", out), out
    assert re.search(r"\[ok\]\s+telemetry next to octavios", out), out


@pytest.mark.parametrize("kind", KINDS)
def test_check_env_flags_an_old_sdk(tmp_path, kind):
    out = _check_env(kind, _fake_sdk(tmp_path, complete=False))
    assert re.search(r"\[MISSING\]\s+octavios at .* older than dev 609d5ae", out), out
    assert "octpacker" in out
