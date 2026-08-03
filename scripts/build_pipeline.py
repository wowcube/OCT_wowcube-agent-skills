"""Pipeline driver for cube_asset-builder.

Two subcommands:
  generate  — validate manifest, generate AI sprite PNGs (from each sprite's
              gen_prompt) and synthesise WAV sound placeholders.
  pack      — build assets.psd then run pack.py to produce packed/ and _ids.h.

Designed to work identically in the dev repo layout and inside the
corporate-Claude package (where build_psd.py/pack.py are copied next to this
file). `find_script()` checks the scripts dir then walks up the ancestors.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from manifest_schema import ValidationError, load_manifest, validate
import gen_sprites
import gen_sounds
from genimg import API_KEY_ENV

SCRIPT_DIR = Path(__file__).resolve().parent


def find_script(name: str) -> Path:
    """Return absolute path to `name` in the package scripts/ dir or an ancestor.

    Package mode: scripts/<name> lives next to this file.
    Dev mode: <name> lives at the repo root somewhere above this file. The repo
    may be nested at any depth, so we walk every ancestor and return the first
    `<ancestor>/<name>` that exists.
    """
    local = SCRIPT_DIR / name
    if local.exists():
        return local
    for ancestor in SCRIPT_DIR.parents:
        for candidate in (ancestor / name, ancestor / "scripts" / name):
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        f"{name} not found near {SCRIPT_DIR} (checked {local}) "
        f"or in any ancestor directory (or its scripts/ subdir)"
    )


GENERATE_PY_DEPS = ("PIL", "numpy", "requests")
PACK_PY_DEPS = ("PIL", "numpy", "pytoshop", "psd_tools")


def _check_deps(stage: str) -> list[str]:
    """Return list of missing dependency messages. Empty = everything installed.

    `stage` is 'generate' or 'pack'. Generate needs PIL+numpy+requests and the
    OPENROUTER_API_KEY env var (AI sprites); pack needs PIL+numpy+pytoshop+psd_tools.
    """
    required = PACK_PY_DEPS if stage == "pack" else GENERATE_PY_DEPS
    missing: list[str] = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            pip_name = {"PIL": "Pillow", "psd_tools": "psd-tools"}.get(mod, mod)
            missing.append(f"python module {mod!r} - install with: pip install {pip_name}")
    if stage == "generate" and not os.environ.get(API_KEY_ENV):
        missing.append(
            f"environment variable {API_KEY_ENV} - AI sprite generation needs "
            f"an OpenRouter key: `export {API_KEY_ENV}=sk-or-...`"
        )
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
    wav_dir = workspace / "wav"

    print(f"Generating AI sprites -> {art_dir}")
    try:
        png_paths = gen_sprites.generate(manifest, art_dir, group=args.group)
    except (gen_sprites.genimg.ImageGenError, ValueError) as e:
        print(f"ERROR: sprite generation failed: {e}", file=sys.stderr)
        return 6

    # beta mp3s (22050 Hz mono CBR 32k) are what the beta simulator actually
    # loads; encode them whenever ffmpeg is around, or unconditionally when
    # --mp3 forces it (then a missing ffmpeg is a hard error, not a skip)
    want_mp3 = args.mp3 or shutil.which("ffmpeg") is not None
    mp3_note = f" (+ mp3 -> {wav_dir / 'assets'})" if want_mp3 else ""
    print(f"Generating sounds     -> {wav_dir}{mp3_note}")
    try:
        wav_paths = gen_sounds.generate(manifest, wav_dir, group=args.group,
                                        encode_mp3=want_mp3)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        # RuntimeError = ffmpeg missing; CalledProcessError = ffmpeg present
        # but the mp3 encode itself failed. Same exit either way.
        print(f"ERROR: sound encoding failed: {e}", file=sys.stderr)
        return 7

    groups: set[str] = set()
    for s in manifest.sprites:
        groups.add(s.group or gen_sprites._derived_group(s))
    for snd in manifest.sounds:
        groups.add(snd.group or snd.name)

    print("=" * 60)
    print(f"  {len(png_paths)} PNG(s), {len(wav_paths)} WAV(s)")
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
    pack_cmd = [
        sys.executable, str(pack_py),
        "--export",
        "--build-palette",
        "--build-ids",
        "--emit-raw",
        "--art-dir", str(workspace),
        "--exported-dir", str(exported_dir),
        "--packed-dir", str(packed_dir),
        "--output-dir", str(packed_dir),
        "--raw-dir", str(packed_dir),
        "--ids-output", str(ids_path),
        "--assets", "assets",
    ]
    if args.app_dir:
        app_dir = Path(args.app_dir)
        # the beta simulator loads sounds ONLY from <app_dir>/sound/assets/;
        # the generate stage encodes its beta mp3s into <workspace>/wav/assets/
        # (it doesn't know the app dir), so carry them over BEFORE pack.py
        # scans the app dir for KIND_SOUND records
        wav_assets = workspace / "wav" / "assets"
        mp3s = sorted(wav_assets.glob("*.mp3")) if wav_assets.is_dir() else []
        if mp3s:
            snd_assets = app_dir / "sound" / "assets"
            snd_assets.mkdir(parents=True, exist_ok=True)
            for mp3 in mp3s:
                shutil.copy2(mp3, snd_assets / mp3.name)
            print(f"  copied {len(mp3s)} beta mp3(s) -> {snd_assets}")
        # beta (octavios dev) container: index.bin + art/packed + kind-aware
        # src/app_<game>_ids.h, emitted into the app dir by pack.py
        pack_cmd += [
            "--beta-app-dir", str(app_dir),
            "--app-name", f"app_{args.game}",
        ]
        if args.manifest:
            pack_cmd += ["--manifest", str(args.manifest)]
    rc = _run(pack_cmd)
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
    if args.app_dir:
        # Beta mode: pack.py already emitted the canonical kind-aware header
        # (record index == asset id, SND_/MAP_ enums) into <app_dir>/src/.
        # The legacy workspace header uses a different numbering and has no
        # sound enum, so copying it over src/ would clobber the real one.
        beta_ids = Path(args.app_dir) / "src" / ids_path.name
        if not beta_ids.is_file() or beta_ids.stat().st_size == 0:
            print(f"ERROR: beta ids header missing or empty: {beta_ids}",
                  file=sys.stderr)
            return 5
        if dest_ids.resolve() != beta_ids.resolve():
            shutil.copy2(beta_ids, dest_ids)
        header = beta_ids.read_text(encoding="utf-8")
    else:
        shutil.copy2(ids_path, dest_ids)
        header = ids_path.read_text(encoding="utf-8")
    bmp_count = header.count("BMP_") - header.count("BMP_none") \
                - header.count("BMP_last") - header.count("BMP_0")

    raw_count = len(list(packed_dir.glob("*.raw")))

    print("=" * 60)
    print(f"  packed/pal.png       : ok")
    print(f"  packed/*.raw         : {raw_count} file(s) (sim/.oct assets)")
    print(f"  {ids_path.name:<20}: {bmp_count} BMP_* constants")
    print(f"  {dest_ids}: copied")
    print("=" * 60)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_pipeline",
        description="cube_asset-builder pipeline driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate AI sprites + WAV sounds from manifest")
    g.add_argument("--manifest", required=True, help="Path to <game>_assets.json")
    g.add_argument("--workspace", default="assets",
                   help="Workspace root (default: assets). PNGs -> <ws>/art, WAVs -> <ws>/wav.")
    g.add_argument("--group", default=None,
                   help="Only regenerate one group (sprites + sounds)")
    g.add_argument("--mp3", action="store_true",
                   help="Require beta mp3 encoding (fail if ffmpeg is missing; "
                        "without this flag mp3s are encoded only when ffmpeg "
                        "is on PATH)")
    g.set_defaults(func=do_generate)

    k = sub.add_parser("pack", help="Build PSD + run pack.py + copy ids to src/")
    k.add_argument("--game", required=True, help="Game name (used in _ids.h filename)")
    k.add_argument("--workspace", default="assets", help="Workspace root (default: assets)")
    k.add_argument("--src-dir", default="src", help="Target dir for the ids header")
    k.add_argument("--app-dir", default=None,
                   help="Beta app root (app_<game>/). When set, pack.py also "
                        "emits the beta container there: index.bin, "
                        "art/packed/*.{raw,pal}, launcher icon maps, and a "
                        "kind-aware src/app_<game>_ids.h")
    k.add_argument("--manifest", default=None,
                   help="Path to plans/<game>_assets.json, so color=='full' "
                        "sprites are RAW565-encoded in the beta container")
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
