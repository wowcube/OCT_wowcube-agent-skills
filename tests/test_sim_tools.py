"""Tests for tools/sim_headless and tools/cube_upload: the patchers that turn a COPY of the octavios Windows
simulator into the hidden simulator and the windowless uploader, plus the safety invariants of their scripts.

The patch tables are exercised on synthetic source trees (every anchor written into its file), so no SDK is
needed. Set OCTAVIOS_DIR to an octavios dev checkout to also count the anchors in the real sources.
"""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hl = _load("hl_patch_under_test", TOOLS / "sim_headless" / "patch.py")
cu = _load("cu_patch_under_test", TOOLS / "cube_upload" / "patch.py")


def _synthetic_tree(root: Path, patches, crlf_files=()) -> None:
    """One file per patched name, holding every anchor of that file once, separated by filler."""
    by_file: dict[str, list[str]] = {}
    for fn, old, _new in patches:
        by_file.setdefault(fn, []).append(old)
    root.mkdir(parents=True, exist_ok=True)
    for fn, anchors in by_file.items():
        text = "// filler\n" + "\n// ---- filler ----\n".join(anchors) + "\n// end\n"
        if fn in crlf_files:
            text = text.replace("\n", "\r\n")
        (root / fn).write_bytes(text.encode("utf-8"))


@pytest.mark.parametrize("mod", [hl, cu], ids=["sim_headless", "cube_upload"])
def test_patch_tables_apply_once_each(tmp_path, mod):
    _synthetic_tree(tmp_path, mod.PATCHES)
    assert all(n == 1 for _f, _h, n in hl.count_anchors(str(tmp_path), mod.PATCHES))
    hl.apply_patches(str(tmp_path), mod.PATCHES)
    for fn, _old, new in mod.PATCHES:
        text = (tmp_path / fn).read_text(encoding="utf-8")
        assert new in text, f"{fn}: replacement missing"


def test_patches_keep_crlf_line_endings(tmp_path):
    crlf = {"sim_wrap_win.h", "sim.h"}
    _synthetic_tree(tmp_path, hl.PATCHES, crlf_files=crlf)
    hl.apply_patches(str(tmp_path), hl.PATCHES)
    for fn in crlf:
        raw = (tmp_path / fn).read_bytes()
        assert b"[HEADLESS]" in raw
        assert raw.count(b"\n") == raw.count(b"\r\n"), f"{fn}: a lone LF slipped into a CRLF file"


def test_missing_anchor_fails_loudly(tmp_path):
    _synthetic_tree(tmp_path, hl.PATCHES)
    p = tmp_path / "sim_pcm.h"
    p.write_text(p.read_text(encoding="utf-8").replace("waveOutOpen(", "waveOutOpen2("), encoding="utf-8")
    with pytest.raises(SystemExit, match="PATCH FAILED: sim_pcm.h"):
        hl.apply_patches(str(tmp_path), hl.PATCHES)


def test_engine_compat_is_optional(tmp_path):
    (tmp_path / "oct_mp3.h").write_text("#pragma once\n" + hl.ENGINE_COMPAT[0][1], encoding="utf-8")
    assert "patched" in hl.apply_compat(str(tmp_path))[0]
    text = (tmp_path / "oct_mp3.h").read_text(encoding="utf-8")
    assert "__declspec(noinline)" in text and "__attribute__((noinline))" in text
    assert "no fix needed" in hl.apply_compat(str(tmp_path))[0]   # already fixed: skipped, no error
    assert (tmp_path / "oct_mp3.h").read_text(encoding="utf-8") == text
    (tmp_path / "oct_mp3.h").write_text("#pragma once\n", encoding="utf-8")
    assert "needs no MSVC fix" in hl.apply_compat(str(tmp_path))[0]   # anchor gone upstream


def test_headless_patch_keeps_the_safety_switches():
    joined = "\n".join(new for _f, _o, new in hl.PATCHES)
    assert "if (!SIM_headless()) ShowWindow(WND, SW_NORMAL);" in joined           # never shown
    assert "WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE" in joined
    assert "SET.Idle = false; HL_init();" in joined                               # runs without activation
    assert "if (SIM_headless()) return 1;" in joined                              # no audio device
    assert "SIM_HEADLESS_OCT_OUT" in joined                                       # .oct only to an explicit path
    assert any(f == "sim_wrap_win.h" and "simMcp::Start(mcp_port);" in o and "simMcp::Start(mcp_port);" in n
               for f, o, n in hl.PATCHES), "the MCP socket must stay on in the hidden simulator"


def test_upload_patch_specifics():
    joined = "\n".join(new for _f, _o, new in cu.PATCHES)
    assert "BLOB_FLAG_LONG_CHUNK_TIMEOUT" in joined and "OCT_CHUNK_CAP" in joined
    assert "CUBE_UPLOAD_MAC" in joined and "CUBE_UPLOAD_PATH" in joined
    assert "upload_result.txt" not in joined or "CU_write_result" in joined
    assert "simMcp::Start" not in joined                                          # no control socket
    assert "BtPreferredAddr.ullLong = 0; BtPreferredName[0] = 0;" not in joined   # the headless BT wipe is not shared
    keys = [(f, o) for f, o, _n in cu.PATCHES]
    assert len(keys) == len(set(keys)), "duplicate anchors in the upload patch"


def _scripts(*globs):
    out = []
    for g in globs:
        out += list(TOOLS.glob(g))
    return out


def test_tool_scripts_kill_only_by_pid_and_never_inject_input():
    for p in _scripts("*/*.ps1", "*/*.py", "*/hl_src/*", "*/cu_src/*"):
        text = p.read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"Stop-Process\s+(-Name|-ProcessName)|taskkill\s+/IM|pkill|killall", text, re.I), p
        assert not re.search(r"\b(SendInput|keybd_event|mouse_event|SetForegroundWindow)\b", text), p
    launcher = (TOOLS / "sim_headless" / "hidden_launch.ps1").read_text(encoding="utf-8")
    assert "Start-Sleep -Milliseconds 50" in launcher
    # kills go only through the handle held on the process we started (PID reuse-safe), never a bare PID or a name
    code = "\n".join(line for line in launcher.splitlines() if not line.lstrip().startswith("#"))
    assert "Stop-Process" not in code and "$p.Kill()" in code and "held[pi.pid] = pi.hp" in code
    for p in _scripts("*/*.ps1"):
        body = "\n".join(line for line in p.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))
        assert not re.search(r"Stop-Process\s+-Id", body), f"bare-PID kill in {p.name}"


def test_uploader_has_no_personal_defaults():
    """No device address, name or personal path may ship: -Mac and -Oct are mandatory, examples are placeholders."""
    text = (TOOLS / "cube_upload" / "run_upload.ps1").read_text(encoding="utf-8")
    assert not re.search(r"\$Mac\s*=", text) and not re.search(r"\$Oct\s*=\s*['\"]", text)
    placeholder_free = re.sub(r"(?i)AA[:-]?BB[:-]?CC[:-]?DD[:-]?EE[:-]?FF", "", text)
    for p in [q for q in (*TOOLS.glob("cube_upload/*"), *TOOLS.glob("cube_upload/cu_src/*")) if q.is_file()]:
        body = re.sub(r"(?i)AA[:-]?BB[:-]?CC[:-]?DD[:-]?EE[:-]?FF", "", p.read_text(encoding="utf-8", errors="replace"))
        assert not re.search(r"(?i)\b(0x)?[0-9a-f]{12}\b|\b[0-9a-f]{2}([:-][0-9a-f]{2}){5}\b", body), f"device address in {p.name}"
        assert not re.search(r"(?i)\bWow_[a-z]+_[a-z]+_\d\b|C:\\Users\\", body), f"personal name/path in {p.name}"
    assert placeholder_free


@pytest.mark.skipif(not os.environ.get("OCTAVIOS_DIR"), reason="set OCTAVIOS_DIR to an octavios dev checkout")
@pytest.mark.parametrize("mod", [hl, cu], ids=["sim_headless", "cube_upload"])
def test_anchors_match_real_octavios(mod):
    src = Path(os.environ["OCTAVIOS_DIR"]) / "sim" / "src"
    bad = [(f, h, n) for f, h, n in hl.count_anchors(str(src), mod.PATCHES) if n != 1]
    assert not bad, bad


# --- seams.py: thin background lines on screen edges -------------------------------------------------------------

seams = _load("seams_under_test", TOOLS / "sim_headless" / "seams.py")


def _cross_frame(screen_fn):
    """A synthetic unfolded-cross frame: screen_fn(face, sy, sx) returns a 240x240x3 int array."""
    import numpy as np
    w = 4 * seams.FACE + 3 * seams.FACEGAP
    h = 3 * seams.FACE + 2 * seams.FACEGAP
    img = np.full((h, w, 3), 40, dtype=int)
    for face, (c, r) in seams.CROSS.items():
        for sy in (0, 1):
            for sx in (0, 1):
                x0 = c * (seams.FACE + seams.FACEGAP) + sx * (seams.SIDE + seams.SCRGAP)
                y0 = r * (seams.FACE + seams.FACEGAP) + sy * (seams.SIDE + seams.SCRGAP)
                img[y0:y0 + 240, x0:x0 + 240] = screen_fn(face, sy, sx)
    return img


def _picture(seed):
    import numpy as np
    return np.random.default_rng(seed).integers(0, 256, size=(240, 240, 3))


def test_seams_found_on_inner_edges_only_where_drawn():
    bg = (8, 16, 49)

    def screen(face, sy, sx):
        s = _picture(sy * 2 + sx)
        if face == "FRONT" and sy == 0:
            s[-2:, :] = bg                       # 2-px line at the bottom of the top row: the +-120 artifact
        return s
    found = seams.find_seams(_cross_frame(screen))
    assert sorted((label, edge, width) for label, edge, width, _c in found) == [
        ("FRONT r0c0", "bottom", 2), ("FRONT r0c1", "bottom", 2)]
    assert found[0][3] == bg


def test_seams_ignore_clean_pictures_wide_bands_and_empty_screens():
    def screen(face, sy, sx):
        s = _picture(7)
        if face == "TOP":
            s[:12, :] = (10, 20, 30)               # a 12-px uniform sky band is part of the picture
        if face == "BOTTOM":
            s[:, :] = (8, 16, 49)                  # an empty screen
        return s
    assert seams.find_seams(_cross_frame(screen)) == []


def test_seams_cli_exit_codes(tmp_path):
    import numpy as np
    from PIL import Image

    def screen(face, sy, sx):
        s = _picture(3)
        s[:, :1] = 0                               # 1-px line on the left: the fullsize variant
        return s
    bad = tmp_path / "bad.png"
    Image.fromarray(_cross_frame(screen).astype(np.uint8)).save(bad)
    clean = tmp_path / "clean.png"
    Image.fromarray(_cross_frame(lambda f, y, x: _picture(5)).astype(np.uint8)).save(clean)
    assert seams.main([str(bad)]) == 1
    assert seams.main([str(clean)]) == 0
    assert seams.main([str(tmp_path / "missing.png")]) == 2


def test_run_reports_seams_without_changing_its_exit_code():
    run = (TOOLS / "sim_headless" / "run.ps1").read_text(encoding="utf-8")
    assert "seams.py" in run and "--face" in run


def test_mcp_client_takes_bare_commands_as_documented():
    """The documented `mcp.ps1 -Port 8177 ping info` once bound "ping" to -TimeoutSec (a type error)."""
    import shutil
    import subprocess
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("no PowerShell")
    script = TOOLS / "sim_headless" / "mcp.ps1"
    r = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Port", "1", "ping", "info"],
                       capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    assert "Cannot convert" not in out and "is a simulator listening on 127.0.0.1:1?" in out, out
    assert r.returncode == 1


def test_seams_found_on_a_solid_colour_picture():
    """A flat full-screen picture placed at +-120 is ~98 % one colour: the seam must still be reported."""
    import numpy as np

    def screen(face, sy, sx):
        s = np.zeros((240, 240, 3), dtype=int)
        s[:, :] = (200, 120, 40)
        if face == "LEFT" and sx == 0:
            s[:, -2:] = (8, 16, 49)
        return s
    found = seams.find_seams(_cross_frame(screen))
    assert sorted((label, edge, width) for label, edge, width, _c in found) == [
        ("LEFT r0c0", "right", 2), ("LEFT r1c0", "right", 2)]
