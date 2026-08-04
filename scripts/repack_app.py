"""One-command repack cycle for an existing app_<game> folder (spec §9, §10).

    python scripts/repack_app.py --app-dir <workspace>/app_<game>
                                 [--manifest <path>|auto] [--icon <path>|auto]
                                 [--skip-device] [--octavios <path>]

The "I replaced the assets — rebuild" cycle in one command:

  1. repack the beta container via pack.py, using the app's CANONICAL pack
     invocation auto-detected from what exists on disk (see
     detect_pack_command below) — the user never has to remember flags;
  2. bump the APP_VERSION patch digit (+1) in src/app.h — the cube's catalog
     compares versions on install, so an un-bumped rebuild may not apply
     over an already-installed app (spec §9);
  3. unless --skip-device: full device build via scripts/build_device.(ps1|sh)
     (ARM cmake+ninja, python .oct pack, ARM-embed tail verification).

Cross-platform single entry point; exits non-zero on any stage failure.
"""
from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACK_PY = SCRIPT_DIR / "pack.py"

_VERSION_RE = re.compile(
    r"^(?P<pre>\s*#\s*define\s+APP_VERSION\s+)(?P<num>\d+)(?P<tail>.*)$",
    re.MULTILINE)


def bump_patch(app_h_path: str | Path) -> int:
    """+1 the integer in `#define APP_VERSION <int>`; return the new value.

    APP_VERSION encodes v<major>.<minor><patch> as one int (102 = v1.02), so
    +1 bumps ONLY the patch digit; minor/major are just higher digits of the
    same int and are never changed here (they need an explicit user edit).
    The rest of the line (comment tail) and the file's BOM are preserved —
    real app.h files carry a UTF-8 BOM.
    """
    p = Path(app_h_path)
    raw = p.read_bytes()
    has_bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f"no '#define APP_VERSION <int>' line in {p}")
    new_version = int(m.group("num")) + 1
    text = text[:m.start("num")] + str(new_version) + text[m.end("num"):]
    p.write_bytes((codecs.BOM_UTF8 if has_bom else b"")
                  + text.encode("utf-8"))
    return new_version


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


def detect_pack_command(app_dir: str | Path,
                        manifest: str | Path = "auto",
                        icon: str | Path = "auto",
                        ) -> tuple[list[str], Path]:
    """Assemble the app's canonical pack.py invocation from what's on disk.

    Returns (command, cwd). The command mirrors the scaffold-time invocation
    (scripts/new_app.ps1 step 5) with these on-disk detection rules:

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
    """
    app_dir = Path(app_dir).resolve()
    app = _app_name(app_dir)

    # --manifest: explicit path, or single plans/*_assets.json, or omitted
    if str(manifest) == "auto":
        found = sorted((app_dir / "plans").glob("*_assets.json"))
        if len(found) > 1:
            names = ", ".join(p.name for p in found)
            raise ValueError(
                f"several manifests in {app_dir / 'plans'} ({names}) - "
                f"pass an explicit --manifest")
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


def build_device_command(app_dir: Path, octavios: str | None = None) -> list[str]:
    """Platform-specific invocation of scripts/build_device.(ps1|sh).

    The device stage deliberately INVOKES the build_device script instead of
    reimplementing it: that script is the single source of truth for the ARM
    cmake+ninja build, the python .oct pack, and the ARM-embed tail
    verification — duplicating that logic here would inevitably drift.
    """
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(SCRIPT_DIR / "build_device.ps1"),
               "-AppDir", str(app_dir)]
        if octavios:
            cmd += ["-OctaviOS", octavios]
    else:
        cmd = ["bash", str(SCRIPT_DIR / "build_device.sh"),
               "--app-dir", str(app_dir)]
        if octavios:
            cmd += ["--octavios", octavios]
    return cmd


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
                        help="octavios SDK path, forwarded to build_device "
                             "(default: <app-dir>/../octavios)")
    args = parser.parse_args(argv)

    app_dir = Path(args.app_dir)
    if not app_dir.is_dir():
        print(f"ERROR: app folder not found: {app_dir}", file=sys.stderr)
        return 2
    app_dir = app_dir.resolve()

    # --- 1. repack the beta container (canonical invocation from disk) -----
    try:
        pack_cmd, cwd = detect_pack_command(app_dir, args.manifest, args.icon)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print("==> Repacking beta container (pack.py)")
    rc = _run(pack_cmd, cwd=cwd)
    if rc != 0:
        print(f"ERROR: asset repack failed (pack.py exit {rc})", file=sys.stderr)
        return rc or 1

    # --- 2. auto patch-bump (spec §9: every new device .oct bumps +1) ------
    app_h = app_dir / "src" / "app.h"
    try:
        new_version = bump_patch(app_h)
    except (OSError, ValueError) as e:
        print(f"ERROR: version bump failed: {e}", file=sys.stderr)
        return 2
    print(f"==> APP_VERSION bumped to {new_version} in {app_h}")

    # --- 3. device build (ARM + python .oct + tail verification) -----------
    app = _app_name(app_dir)
    oct_path = app_dir / f"{app}.oct"
    if args.skip_device:
        print()
        print("REPACK DONE (device build skipped):")
        print(f"  APP_VERSION = {new_version}")
        print(f"  no new .oct was built - any existing {oct_path} is STALE; "
              f"re-run without --skip-device to ship.")
        return 0

    print("==> Device build (scripts/build_device)")
    rc = _run(build_device_command(app_dir, args.octavios))
    if rc != 0:
        print(f"ERROR: device build failed (exit {rc})", file=sys.stderr)
        return rc or 1

    print()
    print("REPACK COMPLETE:")
    print(f"  {oct_path}")
    print(f"  APP_VERSION = {new_version}")
    return 0


def main() -> int:
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
