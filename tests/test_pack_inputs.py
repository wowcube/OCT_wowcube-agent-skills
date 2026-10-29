"""`build_pipeline.py pack` input handling and `pack-status`:

- an incomplete set (sprite PNG / sound mp3 / --icon missing) is refused
  BEFORE anything is written (exit 4);
- the intermediate <ws>/packed and <ws>/exported are cleared first, so a
  retired animation frame can never come back into index.bin;
- changed app fonts are synced into <ws>/fonts, stale atlas pages removed;
- a successful pack records <app>/.pack_inputs.json; `pack-status` exits 0
  while it matches the inputs and outputs, 1 when stale or missing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

import build_pipeline
from build_pipeline import PACK_INPUTS_FILE, _cli


@pytest.fixture(autouse=True)
def _deps_ok(monkeypatch):
    monkeypatch.setattr(build_pipeline, "_check_deps", lambda stage: [])


def _png(path: Path, colour=(200, 40, 40, 255), size=(8, 8)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, colour).save(path)
    return path


def _setup(tmp_path, sprites=("coin", "gem"), sounds=("blip",), with_pngs=None, ws_mp3s=None):
    ws = tmp_path / "assets_demo"
    app = tmp_path / "app_demo"
    (app / "src").mkdir(parents=True)
    manifest = tmp_path / "plans" / "demo_assets.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "game": "demo", "schema_version": 1,
        "sprites": [{"name": n, "size": [8, 8], "description": "d", "background": "key"} for n in sprites],
        "sounds": [{"name": n, "description": "d"} for n in sounds]}), encoding="utf-8")
    for n in (sprites if with_pngs is None else with_pngs):
        _png(ws / "art" / f"{n}.png")
    for n in (sounds if ws_mp3s is None else ws_mp3s):
        p = ws / "wav" / "assets" / f"{n}.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-mp3:" + n.encode())
    return ws, app, manifest


def _pack_args(ws, app, manifest, *extra):
    return ["pack", "--game", "demo", "--workspace", str(ws), "--src-dir", str(app / "src"),
            "--app-dir", str(app), "--manifest", str(manifest), *extra]


def _status_args(ws, app, manifest, *extra):
    return ["pack-status", "--game", "demo", "--workspace", str(ws), "--app-dir", str(app),
            "--manifest", str(manifest), *extra]


class FakeTools:
    """Stands in for build_psd.py + pack.py: records what the packed dir held
    when build_psd started and writes the outputs the real pack.py writes."""

    def __init__(self, ws: Path, app: Path, rc: int = 0, header_extra: str = ""):
        self.ws, self.app, self.rc, self.header_extra = ws, app, rc, header_extra
        self.calls: list[list[str]] = []
        self.packed_at_start: list[str] | None = None

    def __call__(self, cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        if any(c.endswith("build_psd.py") for c in cmd):
            packed = self.ws / "packed"
            self.packed_at_start = sorted(p.name for p in packed.iterdir()) if packed.is_dir() else []
            return 0
        if any(c.endswith("pack.py") for c in cmd):
            if self.rc:
                return self.rc
            (self.ws / "packed").mkdir(parents=True, exist_ok=True)
            (self.ws / "packed" / "pal.png").write_bytes(b"x")
            (self.ws / "app_demo_ids.h").write_text("enum BMP { BMP_none = 0, BMP_last};")
            (self.app / "src" / "app_demo_ids.h").write_text(
                f"enum BMP {{ BMP_none = 0, BMP_coin = 3, BMP_last}};{self.header_extra}")
            (self.app / "index.bin").write_bytes(b"\x01\x00\x00\x00" + b"zero".ljust(28, b"\0"))
        return 0


def _install(monkeypatch, tools):
    monkeypatch.setattr(build_pipeline, "_run", tools)
    return tools


# ── incomplete sets are refused before anything is written ───────────────────

def test_missing_sprite_png_refused_before_any_write(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path, with_pngs=["coin"])
    (ws / "packed").mkdir(parents=True)
    (ws / "packed" / "keep_me.png").write_bytes(b"x")
    (app / PACK_INPUTS_FILE).write_text("{}", encoding="utf-8")
    src = tmp_path / "fresh_src"
    tools = _install(monkeypatch, FakeTools(ws, app))
    args = _pack_args(ws, app, manifest)
    args[args.index("--src-dir") + 1] = str(src)
    assert _cli(args) == 4
    err = capsys.readouterr().err
    assert "incomplete asset set" in err and "sprite 'gem'" in err
    assert tools.calls == []                                   # build_psd / pack.py never ran
    assert not src.exists()                                    # nothing created
    assert (ws / "packed" / "keep_me.png").is_file()           # nothing cleared
    assert (app / PACK_INPUTS_FILE).read_text(encoding="utf-8") == "{}"


def test_missing_sound_refused(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path, ws_mp3s=[])
    tools = _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 4
    assert "sound 'blip'" in capsys.readouterr().err and tools.calls == []


def test_sound_already_in_the_app_is_enough(tmp_path, monkeypatch):
    ws, app, manifest = _setup(tmp_path, ws_mp3s=[])
    (app / "sound" / "assets").mkdir(parents=True)
    (app / "sound" / "assets" / "blip.mp3").write_bytes(b"recording")
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0


def test_missing_icon_refused(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    tools = _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest, "--icon", str(tmp_path / "nope.png"))) == 4
    assert "--icon" in capsys.readouterr().err and tools.calls == []


def test_missing_manifest_file_exit_2(tmp_path, monkeypatch):
    ws, app, manifest = _setup(tmp_path)
    tools = _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, tmp_path / "plans" / "other.json")) == 2
    assert tools.calls == []


def test_without_manifest_the_old_behaviour_stays(tmp_path, monkeypatch):
    ws, app, _manifest = _setup(tmp_path, with_pngs=["coin"])
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(["pack", "--game", "demo", "--workspace", str(ws), "--src-dir", str(app / "src"),
                 "--app-dir", str(app)]) == 0


def test_extra_art_pngs_are_reported(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    _png(ws / "art" / "old_frame_03.png")
    _png(ws / "art" / "0.png")
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    err = capsys.readouterr().err
    assert "old_frame_03" in err and "0," not in err


# ── intermediates ─────────────────────────────────────────────────────────────

def test_intermediates_are_cleared_before_packing(tmp_path, monkeypatch):
    ws, app, manifest = _setup(tmp_path)
    for d in ("packed", "exported"):
        _png(ws / d / "hero_walk_07.png")
        (ws / d / "sub").mkdir()
        (ws / d / "sub" / "x.raw").write_bytes(b"x")
    tools = _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    assert tools.packed_at_start == []
    assert not (ws / "exported" / "hero_walk_07.png").exists()
    assert not (ws / "packed" / "hero_walk_07.png").exists()


def test_the_apps_own_packed_dir_is_never_cleared(tmp_path, monkeypatch, capsys):
    app = tmp_path / "app_demo"
    ws = app / "art"                                           # odd but possible: <ws>/packed == <app>/art/packed
    _png(ws / "art" / "coin.png")
    _png(ws / "packed" / "keep.png")
    (app / "src").mkdir(parents=True)
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(["pack", "--game", "demo", "--workspace", str(ws), "--src-dir", str(app / "src"),
                 "--app-dir", str(app)]) == 0
    assert (app / "art" / "packed" / "keep.png").is_file()
    assert "not cleared" in capsys.readouterr().out


# ── fonts ─────────────────────────────────────────────────────────────────────

def test_changed_fonts_are_synced_and_stale_pages_removed(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    (app / "art").mkdir(parents=True)
    (app / "art" / "font_1.fnt").write_bytes(b"BMF\x03new")
    _png(app / "art" / "font_1_0.png", (1, 2, 3, 255))
    fonts = ws / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "font_1.fnt").write_bytes(b"BMF\x03old")
    _png(fonts / "font_1_0.png", (9, 9, 9, 255))
    _png(fonts / "font_1_1.png")                               # a page the re-exported font no longer has
    (fonts / "font_9.fnt").write_bytes(b"BMF\x03mine")         # only in the workspace: kept
    _install(monkeypatch, FakeTools(ws, app, header_extra=" BMP_font_1_00065 = 9,"))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    assert (fonts / "font_1.fnt").read_bytes() == b"BMF\x03new"
    assert (fonts / "font_1_0.png").read_bytes() == (app / "art" / "font_1_0.png").read_bytes()
    assert not (fonts / "font_1_1.png").exists()
    assert (fonts / "font_9.fnt").is_file()
    out = capsys.readouterr().out
    assert "new/changed font" in out and "stale font atlas page" in out and "font_9.fnt" in out


def test_font_sync_is_idempotent(tmp_path):
    app, ws = tmp_path / "app", tmp_path / "ws"
    (app / "art").mkdir(parents=True)
    (app / "art" / "font_1.fnt").write_bytes(b"BMF\x03")
    _png(app / "art" / "font_1_0.png")
    assert build_pipeline._sync_fonts(app, ws)[:2] == (2, 0)
    assert build_pipeline._sync_fonts(app, ws)[:2] == (0, 0)
    assert build_pipeline._copy_fonts(app, ws) == 0           # the old name still works


# ── .pack_inputs.json + pack-status ───────────────────────────────────────────

def test_pack_records_inputs_and_status_is_fresh(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    rec = json.loads((app / PACK_INPUTS_FILE).read_text(encoding="utf-8"))
    assert {"manifest", "ws/art/coin.png", "ws/art/gem.png", "ws/wav/assets/blip.mp3",
            "app/sound/assets/blip.mp3"} <= set(rec["inputs"])
    assert set(rec["outputs"]) == {"index.bin", "src/app_demo_ids.h"}
    capsys.readouterr()
    assert _cli(_status_args(ws, app, manifest)) == 0
    assert "FRESH" in capsys.readouterr().out


@pytest.mark.parametrize("change,expect", [
    (lambda ws, app, m: _png(ws / "art" / "coin.png", (1, 1, 1, 255)), "changed: ws/art/coin.png"),
    (lambda ws, app, m: _png(ws / "art" / "new.png"), "added:   ws/art/new.png"),
    (lambda ws, app, m: (ws / "art" / "gem.png").unlink(), "removed: ws/art/gem.png"),
    (lambda ws, app, m: (app / "sound" / "assets" / "boom.mp3").write_bytes(b"b"), "added:   app/sound/assets/boom.mp3"),
    (lambda ws, app, m: m.write_text(m.read_text(encoding="utf-8") + " ", encoding="utf-8"), "changed: manifest"),
    (lambda ws, app, m: (app / "index.bin").write_bytes(b"other"), "changed output: index.bin"),
    (lambda ws, app, m: (app / "art").mkdir() or (app / "art" / "font_2.fnt").write_bytes(b"f"), "added:   app/art/font_2.fnt"),
])
def test_pack_status_reports_what_changed(tmp_path, monkeypatch, capsys, change, expect):
    ws, app, manifest = _setup(tmp_path)
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    change(ws, app, manifest)
    capsys.readouterr()
    assert _cli(_status_args(ws, app, manifest)) == 1
    out = capsys.readouterr().out
    assert "STALE" in out and expect in out, out


def test_pack_status_without_record_is_stale(tmp_path, capsys):
    ws, app, manifest = _setup(tmp_path)
    assert _cli(_status_args(ws, app, manifest)) == 1
    assert "never packed" in capsys.readouterr().out


def test_a_failed_pack_leaves_no_record(tmp_path, monkeypatch):
    ws, app, manifest = _setup(tmp_path)
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    _install(monkeypatch, FakeTools(ws, app, rc=1))
    assert _cli(_pack_args(ws, app, manifest)) == 1
    assert not (app / PACK_INPUTS_FILE).exists()
    assert _cli(_status_args(ws, app, manifest)) == 1


def test_pack_status_follows_the_recorded_icon(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    icon = _png(tmp_path / "badge.png", (5, 5, 5, 255))
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest, "--icon", str(icon))) == 0
    assert _cli(_status_args(ws, app, manifest)) == 0          # no --icon: the recorded one is used
    _png(icon, (6, 6, 6, 255))
    capsys.readouterr()
    assert _cli(_status_args(ws, app, manifest)) == 1
    assert "changed: icon" in capsys.readouterr().out


def test_pack_status_auto_icon_appearing_is_a_change(tmp_path, monkeypatch, capsys):
    ws, app, manifest = _setup(tmp_path)
    _install(monkeypatch, FakeTools(ws, app))
    assert _cli(_pack_args(ws, app, manifest)) == 0
    _png(app / "art" / "icon.png")
    capsys.readouterr()
    assert _cli(_status_args(ws, app, manifest)) == 1
    assert "added:   icon" in capsys.readouterr().out


# ── the real packer: a retired frame never comes back ─────────────────────────

def _real_pack_deps() -> bool:
    try:
        import psd_tools  # noqa: F401
        import pytoshop  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _real_pack_deps(), reason="the real pack stage needs pytoshop + psd-tools")
def test_retired_animation_frame_is_not_packed_again(tmp_path, monkeypatch):
    monkeypatch.undo()                                         # real _check_deps, real subprocesses
    pack_beta = pytest.importorskip("pack_beta")
    ws = tmp_path / "assets_demo"
    app = tmp_path / "app_demo"
    (app / "src").mkdir(parents=True)
    frames = ["hero_walk_00", "hero_walk_01", "hero_walk_02"]

    def manifest_for(names):
        m = tmp_path / "plans" / "demo_assets.json"
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [
            {"name": n, "size": [16, 16], "description": "d", "background": "key", "anim": "hero_walk",
             "frame": i} for i, n in enumerate(names)], "sounds": []}), encoding="utf-8")
        return m

    for i, n in enumerate(frames):
        _png(ws / "art" / f"{n}.png", (40 * i + 20, 90, 200, 255), (16, 16))
    icon = _png(tmp_path / "icon.png", (10, 200, 30, 255), (32, 32))
    m = manifest_for(frames)
    assert _cli(_pack_args(ws, app, m, "--icon", str(icon))) == 0
    names = {n for _k, n in pack_beta.read_index_bin(app / "index.bin")}
    assert set(frames) <= names
    assert _cli(_status_args(ws, app, m)) == 0

    # retire frame 02: drop it from the manifest and from assets_<game>/art, repack
    (ws / "art" / "hero_walk_02.png").unlink()
    m = manifest_for(frames[:2])
    assert _cli(_status_args(ws, app, m)) == 1
    assert _cli(_pack_args(ws, app, m, "--icon", str(icon))) == 0
    names = {n for _k, n in pack_beta.read_index_bin(app / "index.bin")}
    assert "hero_walk_02" not in names and {"hero_walk_00", "hero_walk_01"} <= names
    assert "BMP_hero_walk_02" not in (app / "src" / "app_demo_ids.h").read_text(encoding="utf-8")
    assert _cli(_status_args(ws, app, m)) == 0
