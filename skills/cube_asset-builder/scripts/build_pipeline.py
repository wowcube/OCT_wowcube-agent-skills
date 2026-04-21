"""Pipeline driver for cube_asset-builder.

Two subcommands:
  generate  — validate manifest, render PNG placeholders and MP3 placeholders.
  pack      — build assets.psd then run pack.py to produce packed/ and _ids.h.

Designed to work identically in the dev repo layout and inside the
corporate-Claude package (where build_psd.py/pack.py are copied next to this
file). `find_script()` walks two candidate locations.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from manifest_schema import ValidationError, load_manifest, validate
import gen_placeholders
import gen_sounds

SCRIPT_DIR = Path(__file__).resolve().parent


def find_script(name: str) -> Path:
    """Return absolute path to `name` in the package scripts/ dir or at repo root.

    Package mode: scripts/<name> lives next to this file.
    Dev mode: <name> lives at the repo root, 4 levels up from this file:
      <repo>/OCT_wowcube-agent-skills/skills/cube_asset-builder/scripts/build_pipeline.py
      -> repo = SCRIPT_DIR.parent.parent.parent.parent
    """
    local = SCRIPT_DIR / name
    if local.exists():
        return local
    repo_root = SCRIPT_DIR.parent.parent.parent.parent
    remote = repo_root / name
    if remote.exists():
        return remote
    raise FileNotFoundError(
        f"{name} not found near {SCRIPT_DIR} (checked {local}) "
        f"and not at {remote}"
    )


GENERATE_PY_DEPS = ("PIL", "numpy")
PACK_PY_DEPS = ("PIL", "numpy", "pytoshop", "psd_tools")


def _check_deps(stage: str) -> list[str]:
    """Return list of missing dependency messages. Empty = everything installed.

    `stage` is 'generate' or 'pack'. Generate needs PIL+numpy+ffmpeg; pack also
    needs pytoshop and psd_tools.
    """
    required = PACK_PY_DEPS if stage == "pack" else GENERATE_PY_DEPS
    missing: list[str] = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            pip_name = {"PIL": "Pillow", "psd_tools": "psd-tools"}.get(mod, mod)
            missing.append(f"python module {mod!r} - install with: pip install {pip_name}")
    if not shutil.which("ffmpeg"):
        missing.append("binary 'ffmpeg' on PATH - see https://ffmpeg.org/download.html")
    return missing


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    return proc.returncode


def do_generate(args: argparse.Namespace) -> int:
    deps = _check_deps("generate")
    if deps:
        print("ERROR: missing dependencies:", file=sys.stderr)
        for d in deps:
            print(f"  - {d}", file=sys.stderr)
        return 3

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    manifest = load_manifest(manifest_path)
    errors = validate(manifest)
    if errors:
        print(f"ERROR: manifest validation failed ({len(errors)} issue(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    workspace = Path(args.workspace)
    art_dir = workspace / "art"
    mp3_dir = workspace / "mp3"

    print(f"Generating placeholders -> {art_dir}")
    png_paths = gen_placeholders.generate(manifest, art_dir, group=args.group)

    print(f"Generating sounds        -> {mp3_dir}")
    mp3_paths = gen_sounds.generate(manifest, mp3_dir, group=args.group)

    groups: set[str] = set()
    for s in manifest.sprites:
        groups.add(s.group or gen_placeholders._derived_group(s))
    for snd in manifest.sounds:
        groups.add(snd.group or snd.name)

    print("=" * 60)
    print(f"  {len(png_paths)} PNG(s), {len(mp3_paths)} MP3(s)")
    print(f"  groups: {sorted(groups)}")
    print("=" * 60)
    return 0


def do_pack(args: argparse.Namespace) -> int:
    deps = _check_deps("pack")
    if deps:
        print("ERROR: missing dependencies:", file=sys.stderr)
        for d in deps:
            print(f"  - {d}", file=sys.stderr)
        return 3

    workspace = Path(args.workspace)
    src_dir = Path(args.src_dir)
    src_dir.mkdir(parents=True, exist_ok=True)

    art_dir = workspace / "art"
    psd_path = workspace / "assets.psd"
    exported_dir = workspace / "exported"
    packed_dir = workspace / "packed"
    ids_path = workspace / f"app_{args.game}_ids.h"

    if not art_dir.exists() or not any(art_dir.glob("*.png")):
        print(f"ERROR: no PNGs found in {art_dir}. Run 'generate' first.",
              file=sys.stderr)
        return 4

    build_psd_py = find_script("build_psd.py")
    pack_py = find_script("pack.py")

    print("=== Stage: build_psd ===")
    rc = _run([
        sys.executable, str(build_psd_py),
        str(art_dir), str(psd_path),
        "--padding", "2",
        "--bg-color", "#FF00FF",
    ])
    if rc != 0:
        return rc

    print("=== Stage: pack ===")
    rc = _run([
        sys.executable, str(pack_py),
        "--export",
        "--build-palette",
        "--build-ids",
        "--art-dir", str(workspace),
        "--exported-dir", str(exported_dir),
        "--packed-dir", str(packed_dir),
        "--output-dir", str(packed_dir),
        "--ids-output", str(ids_path),
        "--assets", "assets",
    ])
    if rc != 0:
        return rc

    pal_png = packed_dir / "pal.png"
    if not pal_png.exists():
        print(f"ERROR: expected {pal_png} was not produced.", file=sys.stderr)
        return 5
    if not ids_path.exists() or ids_path.stat().st_size == 0:
        print(f"ERROR: {ids_path} missing or empty.", file=sys.stderr)
        return 5

    dest_ids = src_dir / ids_path.name
    shutil.copy2(ids_path, dest_ids)

    header = ids_path.read_text(encoding="utf-8")
    bmp_count = header.count("BMP_") - header.count("BMP_none") \
                - header.count("BMP_last") - header.count("BMP_0")

    print("=" * 60)
    print(f"  packed/pal.png       : ok")
    print(f"  {ids_path.name:<20}: {bmp_count} BMP_* constants")
    print(f"  {dest_ids}: copied")
    print("=" * 60)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_pipeline",
        description="cube_asset-builder pipeline driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Render placeholders from manifest")
    g.add_argument("--manifest", required=True, help="Path to <game>_assets.json")
    g.add_argument("--workspace", default="assets",
                   help="Workspace root (default: assets). PNGs -> <ws>/art, MP3s -> <ws>/mp3.")
    g.add_argument("--group", default=None,
                   help="Only regenerate one group (sprites + sounds)")
    g.set_defaults(func=do_generate)

    k = sub.add_parser("pack", help="Build PSD + run pack.py + copy ids to src/")
    k.add_argument("--game", required=True, help="Game name (used in _ids.h filename)")
    k.add_argument("--workspace", default="assets", help="Workspace root (default: assets)")
    k.add_argument("--src-dir", default="src", help="Target dir for the ids header")
    k.set_defaults(func=do_pack)

    return p


def _cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def main() -> int:
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
