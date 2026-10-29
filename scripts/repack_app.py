"""One-command repack cycle for an existing app_<game> folder (spec §9, §10).

    python scripts/repack_app.py --app-dir <workspace>/app_<game>
                                 [--manifest <path>|auto] [--icon <path>|auto]
                                 [--skip-device] [--octavios <path>]
                                 [--out <path.oct>] [--builder auto|octpack|python]

The "I replaced the assets — rebuild" cycle in one command:

  1. repack the beta container, using the app's CANONICAL pack invocation
     auto-detected from what exists on disk (see detect_pack_command below)
     — the user never has to remember flags. An app with art/octpack.json
     (PSD-authored, the official workflow) is repacked by the SDK's
     octpacker: `uv run --frozen --project <octavios>/octpacker octpack-pack
     <app> --engine <octavios>`; every other shape by our pack.py /
     build_pipeline.py pack;
  2. bump the patch version (+1): APP_VERSION_PATCH in src/app_metadata.h
     (octavios dev layout), else the literal OCT_APP_SEMVER(...) or legacy
     integer in src/app.h — the cube's catalog compares versions on install,
     so an un-bumped rebuild may not apply over an already-installed app;
  3. unless --skip-device: device build via scripts/build_device.(ps1|sh)
     (octpack-build when available, python builder as fallback, ARM-embed
     verification) into <workspace>/dist/<app>.oct. No simulator is started.

Cross-platform single entry point; exits non-zero on any stage failure.
"""
from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACK_PY = SCRIPT_DIR / "pack.py"
BUILD_PIPELINE_PY = SCRIPT_DIR / "build_pipeline.py"

_VERSION_RE = re.compile(
    r"^(?P<pre>\s*#\s*define\s+APP_VERSION\s+)(?P<num>\d+)(?P<tail>.*)$",
    re.MULTILINE)


_PATCH_RE = re.compile(
    r"^(?P<pre>\s*#\s*define\s+APP_VERSION_PATCH\s+)(?P<num>\d+)(?P<tail>.*)$",
    re.MULTILINE)
_SEMVER_RE = re.compile(
    r"^(?P<pre>\s*#\s*define\s+APP_VERSION\s+OCT_APP_SEMVER\s*\(\s*(?P<ma>\d+)\s*,\s*(?P<mi>\d+)\s*,\s*)"
    r"(?P<num>\d+)(?P<tail>\s*\).*)$",
    re.MULTILINE)


def _rewrite(p: Path, text: str, has_bom: bool) -> None:
    p.write_bytes((codecs.BOM_UTF8 if has_bom else b"") + text.encode("utf-8"))


def bump_patch(app_h_path: str | Path) -> int:
    """+1 the app's patch version; return the new APP_VERSION value.

    Three layouts, newest first (the cube's catalog compares versions on
    install, so an un-bumped rebuild may not apply over an installed app):
      1. octavios dev: `#define APP_VERSION_PATCH <n>` in src/app_metadata.h
         (or app.h), APP_VERSION = OCT_APP_SEMVER(MAJOR, MINOR, PATCH);
      2. `#define APP_VERSION OCT_APP_SEMVER(<ma>, <mi>, <n>)` with literals;
      3. legacy `#define APP_VERSION <int>` (102 = v1.02): +1 on the integer.
    Semver fields are bytes: a patch of 255 cannot be bumped (raise; bump the
    minor by hand). Comment tails and the files' BOMs are preserved.
    """
    app_h = Path(app_h_path)
    for p in (app_h.parent / "app_metadata.h", app_h):
        if not p.is_file():
            continue
        raw = p.read_bytes()
        has_bom = raw.startswith(codecs.BOM_UTF8)
        text = raw.decode("utf-8-sig")
        m = _PATCH_RE.search(text)
        if m:
            patch = int(m.group("num")) + 1
            if patch > 255:
                raise ValueError(f"APP_VERSION_PATCH would exceed 255 in {p}: bump the minor version by hand")
            _rewrite(p, text[:m.start("num")] + str(patch) + text[m.end("num"):], has_bom)
            ma = re.search(r"^\s*#\s*define\s+APP_VERSION_MAJOR\s+(\d+)", text, re.M)
            mi = re.search(r"^\s*#\s*define\s+APP_VERSION_MINOR\s+(\d+)", text, re.M)
            return (1 << 24) | (int(ma.group(1)) if ma else 0) << 16 | (int(mi.group(1)) if mi else 0) << 8 | patch
        m = _SEMVER_RE.search(text)
        if m:
            patch = int(m.group("num")) + 1
            if patch > 255:
                raise ValueError(f"OCT_APP_SEMVER patch would exceed 255 in {p}: bump the minor version by hand")
            _rewrite(p, text[:m.start("num")] + str(patch) + text[m.end("num"):], has_bom)
            return (1 << 24) | int(m.group("ma")) << 16 | int(m.group("mi")) << 8 | patch
    p = app_h
    raw = p.read_bytes()
    has_bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f"no APP_VERSION_PATCH, OCT_APP_SEMVER(...) or '#define APP_VERSION <int>' in {p}")
    new_version = int(m.group("num")) + 1
    _rewrite(p, text[:m.start("num")] + str(new_version) + text[m.end("num"):], has_bom)
    return new_version


def _version_str(value: int) -> str:
    """'1.2.3' for an OCT_APP_SEMVER value (scheme byte 1), the plain number for a legacy counter."""
    if (value >> 24) & 0xFF == 1:
        return f"{(value >> 16) & 0xFF}.{(value >> 8) & 0xFF}.{value & 0xFF}"
    return str(value)


def _app_name(app_dir: Path) -> str:
    """App name from the *.target marker (same rule as build_device);
    fall back to the folder name when no marker exists."""
    targets = sorted(app_dir.glob("*.target"))
    if targets:
        return targets[0].stem
    return app_dir.name


def _manifest_has_palette_sprites(manifest_path: Path) -> bool:
    """True when at least one sprite is palette-encoded (color != 'full').

    Plain JSON read on purpose: detection must not fail on schema details —
    pack.py itself validates the manifest properly right after.
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return True     # unreadable manifest: keep the palette build, let pack.py complain
    sprites = data.get("sprites") or []
    return any(s.get("color") != "full" for s in sprites)


def _have(exe: str) -> bool:
    return shutil.which(exe) is not None


def packaged_python() -> bool:
    """True when this interpreter runs inside a Microsoft Store (MSIX) package,
    e.g. the Store's Python 3.12. Every process it starts - grandchildren
    included - sees the package's private copy of AppData: uv then cannot find
    its managed Python, "ignores" the octpacker environment and rebuilds it
    (observed: it deleted a working offline venv). So uv is never started from
    such an interpreter; build_device runs with -NoUv instead."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        length = ctypes.c_uint32(0)
        # APPMODEL_ERROR_NO_PACKAGE (15700) = an ordinary desktop process
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) != 15700
    except (AttributeError, OSError):
        return False


STORE_PYTHON_NOTE = ("this python is the Microsoft Store build: programs it starts see a private copy of AppData, so "
                     "uv cannot find its managed Python and would rebuild the octpacker environment")


def default_octavios(app_dir: str | Path) -> Path:
    """The SDK build_device uses by default: <app>/../octavios."""
    return Path(app_dir).resolve().parent / "octavios"


def octpack_pack_command(app_dir: str | Path, octavios: str | Path | None = None) -> list[str]:
    """The official PSD-workflow repack of an app that has art/octpack.json:
    `uv run --frozen --project <octavios>/octpacker octpack-pack <app> --engine <octavios>`
    (octava_dev_tooling.md §2.3/2.5: sound conversion, PSD/font export, link
    -> art/packed, index.bin, src/<app>_ids.h). --frozen: never rewrite the
    SDK's uv.lock. Raises ValueError when the SDK or uv is missing."""
    app_dir = Path(app_dir).resolve()
    sdk = Path(octavios).resolve() if octavios else default_octavios(app_dir)
    project = sdk / "octpacker"
    if not (project / "pyproject.toml").is_file():
        raise ValueError(
            f"{app_dir / 'art' / 'octpack.json'} marks a PSD-authored app: it is packed by the official octpacker "
            f"(octpack-pack), which needs octavios dev with {project / 'pyproject.toml'} - pass --octavios <dir>")
    if not _have("uv"):
        raise ValueError("the official octpacker runs through uv, which is not on PATH (install it with the "
                         "user's approval: scripts/check_env.ps1 -Install / check_env.sh)")
    cmd = ["uv", "run", "--frozen", "--project", str(project), "octpack-pack", str(app_dir), "--engine", str(sdk)]
    if packaged_python():
        raise ValueError(f"{STORE_PYTHON_NOTE}. Run the official packer from a normal PowerShell instead: "
                         f"{' '.join(cmd)} - then build the device .oct there too (scripts\\build_device.ps1 "
                         f"-AppDir {app_dir}), or run this script with a python.org / uv-managed Python")
    return cmd


def detect_pack_command(app_dir: str | Path,
                        manifest: str | Path = "auto",
                        icon: str | Path = "auto",
                        octavios: str | Path | None = None,
                        ) -> tuple[list[str], Path]:
    """Assemble the app's canonical pack invocation from what's on disk.

    Returns (command, cwd). Checked first: **`art/octpack.json`** = an app
    authored in Photoshop for the official octpacker (STAGE3_ASSETS "PSD
    workflow"): repack with `octpack-pack` (octpack_pack_command; `octavios`
    defaults to <app>/../octavios), never with our pack.py - the two paths
    must not be mixed. --manifest/--icon do not apply to it. Otherwise three
    on-disk shapes exist:

    **Per-game workspace** (the current asset stage, cube_asset-builder) —
    `<root>/assets_<game>/art/*.png` next to `app_<game>/` (root = the app's
    parent, which also holds `plans/<game>_assets.json`): re-run the same
    `build_pipeline.py pack --game <game> --workspace assets_<game> ...` from
    <root>, so the art is re-atlased from the workspace PNGs.

    **Pipeline shape** — `assets/art/*.png` present: the app's art was built
    by the asset-builder pipeline (AI-generated or agent-drawn placeholder
    PNGs in the `assets/` workspace, atlased into `assets/assets.psd` by
    build_pipeline.py pack). The canonical invocation is that same
    `build_pipeline.py pack` command (re-atlases the workspace PNGs, then
    drives pack.py) — NOT the scaffold pack.py call, which would `--export`
    the template's untouched `art/assets.psd` over the real art and fail on
    any manifest full-color sprite.

    **Scaffold/legacy shape** — everything else mirrors the scaffold-time
    invocation (scripts/new_app.ps1 step 5) with these detection rules:

      *.target marker          -> --app-name (fallback: folder name)
      plans/*_assets.json      -> --manifest (exactly one match; several ->
                                  error asking for an explicit --manifest)
      art/icon.png             -> --icon
      art/*assets*.psd         -> --export (PSD workflow; PNG-only apps keep
                                  their art/exported PNGs untouched)
      palette sprites present  -> --build-palette (any manifest sprite with
                                  color != 'full', or no manifest at all —
                                  the legacy/scaffold shape; all-full apps
                                  like photo frames skip the palette build)

    Manifest and icon detection are shared by both shapes.
    """
    app_dir = Path(app_dir).resolve()
    app = _app_name(app_dir)
    game = app[4:] if app.startswith("app_") else app
    root = app_dir.parent

    # Official PSD workflow first: octpack.json decides, our packer never touches such an app
    if (app_dir / "art" / "octpack.json").is_file():
        return octpack_pack_command(app_dir, octavios), app_dir

    # --manifest: explicit path, or single <app>/plans/*_assets.json, or
    # <root>/plans/<game>_assets.json (the pipeline keeps plans/ next to the app), or omitted
    if str(manifest) == "auto":
        found = sorted((app_dir / "plans").glob("*_assets.json"))
        if len(found) > 1:
            names = ", ".join(p.name for p in found)
            raise ValueError(
                f"several manifests in {app_dir / 'plans'} ({names}) - "
                f"pass an explicit --manifest")
        if not found and (root / "plans" / f"{game}_assets.json").is_file():
            found = [root / "plans" / f"{game}_assets.json"]
        manifest_path = found[0] if found else None
    else:
        manifest_path = Path(manifest)
        if not manifest_path.is_file():
            raise ValueError(f"manifest not found: {manifest_path}")

    # --icon: explicit path, or art/icon.png, or omitted
    if str(icon) == "auto":
        icon_path = app_dir / "art" / "icon.png"
        if not icon_path.is_file():
            icon_path = None
    else:
        icon_path = Path(icon)
        if not icon_path.is_file():
            raise ValueError(f"icon not found: {icon_path}")

    # Per-game workspace next to the app (cube_asset-builder's canonical
    # command, run from <root>).
    workspace = root / f"assets_{game}"
    if sorted((workspace / "art").glob("*.png")):
        cmd = [sys.executable, str(BUILD_PIPELINE_PY), "pack",
               "--game", game,
               "--workspace", str(workspace),
               "--src-dir", str(app_dir / "src"),
               "--app-dir", str(app_dir)]
        if manifest_path is not None:
            cmd += ["--manifest", str(manifest_path)]
        if icon_path is not None:
            cmd += ["--icon", str(icon_path)]
        return cmd, root

    # Pipeline shape: sprite PNGs in the assets/ workspace -> re-run the
    # canonical build_pipeline.py pack invocation from the app dir.
    if sorted((app_dir / "assets" / "art").glob("*.png")):
        cmd = [sys.executable, str(BUILD_PIPELINE_PY), "pack",
               "--game", game,
               "--workspace", "assets",
               "--src-dir", "src",
               "--app-dir", str(app_dir)]
        if manifest_path is not None:
            cmd += ["--manifest", str(manifest_path)]
        if icon_path is not None:
            cmd += ["--icon", str(icon_path)]
        return cmd, app_dir

    cmd: list[str] = [sys.executable, str(PACK_PY)]
    if sorted((app_dir / "art").glob("*assets*.psd")):
        cmd.append("--export")
    if manifest_path is None or _manifest_has_palette_sprites(manifest_path):
        cmd.append("--build-palette")
    cmd += [
        "--build-ids",
        "--art-dir", "art",
        "--exported-dir", str(Path("art") / "exported"),
        "--packed-dir", str(Path("art") / "packed"),
        "--output-dir", str(Path("art") / "packed"),
        "--ids-output", str(Path("src") / f"{app}_ids.h"),
        "--assets", "assets",
        "--beta-app-dir", str(app_dir),
        "--app-name", app,
    ]
    if manifest_path is not None:
        cmd += ["--manifest", str(manifest_path)]
    if icon_path is not None:
        cmd += ["--icon", str(icon_path)]
    return cmd, app_dir


def ensure_art_fonts(app_dir: str | Path) -> int:
    """pack.py exports BMFont glyphs only from <art-dir>/fonts/; scaffolded apps keep font_*.fnt and their
    atlas PNGs in art/. Copy them over (like build_pipeline does for assets_<game>/fonts) so a direct
    pack.py repack keeps the glyphs - without them every OCT_label_set draws nothing. Returns files copied."""
    art = Path(app_dir) / "art"
    files = sorted(p for p in art.glob("font_*") if p.is_file() and p.suffix.lower() in (".fnt", ".png"))
    if not files:
        return 0
    dst = art / "fonts"
    dst.mkdir(exist_ok=True)
    n = 0
    for p in files:
        target = dst / p.name
        if not target.is_file() or target.read_bytes() != p.read_bytes():
            shutil.copy2(p, target)
            n += 1
    return n


def default_oct_path(app_dir: str | Path) -> Path:
    """Where build_device writes the deliverable: <workspace>/dist/<app>.oct
    (the Windows simulator rewrites <app>/<app>.oct on every launch)."""
    app_dir = Path(app_dir).resolve()
    return app_dir.parent / "dist" / f"{_app_name(app_dir)}.oct"


def build_device_command(app_dir: Path, octavios: str | None = None,
                         out: str | Path | None = None,
                         builder: str = "auto", no_uv: bool = False) -> list[str]:
    """Platform-specific invocation of scripts/build_device.(ps1|sh).

    The device stage deliberately INVOKES the build_device script instead of
    reimplementing it: that script is the single source of truth for the
    octpack-build / python-builder choice, the ARM build and the .oct
    verification — duplicating that logic here would inevitably drift.
    `no_uv` (-NoUv / --no-uv): never start uv (python builder + the local
    header check) - set when this interpreter is a Store Python.
    """
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(SCRIPT_DIR / "build_device.ps1"),
               "-AppDir", str(app_dir)]
        if octavios:
            cmd += ["-OctaviOS", octavios]
        if out:
            cmd += ["-Out", str(out)]
        if builder != "auto":
            cmd += ["-Builder", builder]
        if no_uv:
            cmd += ["-NoUv"]
    else:
        cmd = ["bash", str(SCRIPT_DIR / "build_device.sh"),
               "--app-dir", str(app_dir)]
        if octavios:
            cmd += ["--octavios", octavios]
        if out:
            cmd += ["--out", str(out)]
        if builder != "auto":
            cmd += ["--builder", builder]
        if no_uv:
            cmd += ["--no-uv"]
    return cmd


def uv_env_for(app_dir: str | Path) -> str:
    """octpacker's environment for uv: UV_PROJECT_ENVIRONMENT when set, else <workspace>/.uv_octpack_venv - never
    the SDK tree (uv would create octavios/octpacker/.venv). build_device.ps1/.sh use the same default."""
    return os.environ.get("UV_PROJECT_ENVIRONMENT") or str(Path(app_dir).resolve().parent / ".uv_octpack_venv")


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, cwd=cwd, text=True).returncode


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="repack_app",
        description="Repack an app's beta container, auto-bump the APP_VERSION "
                    "patch, and rebuild the device .oct - in one command.")
    parser.add_argument("--app-dir", required=True,
                        help="app_<game> folder to repack")
    parser.add_argument("--manifest", default="auto",
                        help="path to plans/<game>_assets.json "
                             "(default: auto-detect plans/*_assets.json)")
    parser.add_argument("--icon", default="auto",
                        help="launcher icon PNG (default: auto-detect art/icon.png)")
    parser.add_argument("--skip-device", action="store_true",
                        help="stop after repack + version bump (no ARM build, "
                             "no new .oct)")
    parser.add_argument("--octavios", default=None,
                        help="octavios SDK path, forwarded to build_device and used for octpack-pack "
                             "when the app has art/octpack.json (default: <app-dir>/../octavios)")
    parser.add_argument("--out", default=None,
                        help="device .oct path (default: <app-dir>/../dist/<app>.oct)")
    parser.add_argument("--builder", default="auto",
                        choices=("auto", "octpack", "python"),
                        help="forwarded to build_device (default: octpack-build "
                             "when available, else the python builder)")
    args = parser.parse_args(argv)

    app_dir = Path(args.app_dir)
    if not app_dir.is_dir():
        print(f"ERROR: app folder not found: {app_dir}", file=sys.stderr)
        return 2
    app_dir = app_dir.resolve()

    # --- 1. repack the beta container (canonical invocation from disk) -----
    try:
        pack_cmd, cwd = detect_pack_command(app_dir, args.manifest, args.icon, args.octavios)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    official = "octpack-pack" in pack_cmd
    os.environ["UV_PROJECT_ENVIRONMENT"] = uv_env_for(app_dir)   # inherited by octpack-pack and build_device
    packer = "octpack-pack (official PSD workflow, art/octpack.json)" if official else (
        Path(pack_cmd[1]).name if len(pack_cmd) > 1 else "packer")
    if official and (args.manifest != "auto" or args.icon != "auto"):
        print("NOTE: --manifest/--icon are ignored: art/octpack.json and its PSDs/!pack.txt define this app's pack")
    if packer == "pack.py" and ensure_art_fonts(app_dir):
        print("==> Staged art/font_* into art/fonts/ (pack.py exports glyphs from there)")
    print(f"==> Repacking beta container ({packer})")
    rc = _run(pack_cmd, cwd=cwd)
    if rc != 0:
        print(f"ERROR: asset repack failed ({packer} exit {rc})", file=sys.stderr)
        return rc or 1

    # --- 2. auto patch-bump (spec §9: every new device .oct bumps +1) ------
    app_h = app_dir / "src" / "app.h"
    try:
        new_version = bump_patch(app_h)
    except (OSError, ValueError) as e:
        print(f"ERROR: version bump failed: {e}", file=sys.stderr)
        return 2
    print(f"==> APP_VERSION bumped to {_version_str(new_version)} "
          f"({'src/app_metadata.h' if (app_h.parent / 'app_metadata.h').is_file() else app_h})")

    # --- 3. device build (octpack-build or python builder + verification) ---
    oct_path = Path(args.out).resolve() if args.out else default_oct_path(app_dir)
    if args.skip_device:
        print()
        print("REPACK DONE (device build skipped):")
        print(f"  APP_VERSION = {_version_str(new_version)}")
        print(f"  no new .oct was built - any existing {oct_path} is STALE; "
              f"re-run without --skip-device to ship.")
        return 0

    no_uv = packaged_python()
    if no_uv:
        if args.builder == "octpack":
            print(f"ERROR: --builder octpack runs through uv, but {STORE_PYTHON_NOTE}. Build from a normal "
                  f"PowerShell: scripts\\build_device.ps1 -AppDir {app_dir} -Builder octpack", file=sys.stderr)
            return 2
        print(f"NOTE: {STORE_PYTHON_NOTE}: the device build runs without uv (-NoUv: python builder + local "
              f".oct header check)")
    print("==> Device build (scripts/build_device)")
    rc = _run(build_device_command(app_dir, args.octavios, oct_path, args.builder, no_uv=no_uv))
    if rc != 0:
        print(f"ERROR: device build failed (exit {rc})", file=sys.stderr)
        return rc or 1

    print()
    print("REPACK COMPLETE:")
    print(f"  {oct_path}")
    print(f"  APP_VERSION = {_version_str(new_version)}")
    return 0


def main() -> int:
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
