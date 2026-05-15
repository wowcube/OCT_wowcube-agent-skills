"""Pipeline driver for cube_asset-builder.

Two subcommands:
  generate  - validate manifest and render MP3 placeholders for every sound.
              Sprite PNGs are NOT produced here; they are rendered upstream by
              canvas-design (driven by cube_asset-prompter) and must already be
              present in <workspace>/art/ before `pack` runs.
  pack      - build assets.psd at the workspace root, then run pack.py to
              produce packed/ and _ids.h from the sprite PNGs in <workspace>/art/.

`build_psd.py` and `pack.py` are vendored into this skill's `scripts/` folder
and resolved via `find_script()`.
"""
from __future__ import annotations

import argparse
import enum
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from manifest_schema import (
    SchemaMigrationError,
    ValidationError,
    load_manifest,
    validate,
)
import gen_sounds

SCRIPT_DIR = Path(__file__).resolve().parent

# Pipeline state file dropped in the workspace between generate and pack so
# interrupted sessions (or a cold-boot Claude) can detect resumable work.
PIPELINE_STATE_FILE = ".pipeline_state.json"

# Workspace layout. Kept here so every function builds paths the same way.
ART_SUBDIR = "art"           # source PNGs (and the packed PSD)
MP3_SUBDIR = "mp3"           # source sound placeholders
EXPORTED_SUBDIR = "exported" # PSD layers exported by psd-tools
PACKED_SUBDIR = "packed"     # final packed atlas + palette
PSD_FILENAME = "assets.psd"  # keep stem == --assets argument for pack.py

logger = logging.getLogger("cube_asset_builder")


def _configure_logging(verbose: bool = False) -> None:
    """Route INFO to stdout and WARNING+ to stderr; idempotent across calls."""
    if logger.handlers:
        return
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    out = logging.StreamHandler(sys.stdout)
    out.setLevel(logging.DEBUG if verbose else logging.INFO)
    out.addFilter(lambda rec: rec.levelno < logging.WARNING)
    out.setFormatter(logging.Formatter("%(message)s"))
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    err.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(out)
    logger.addHandler(err)
    logger.propagate = False


class Stage(enum.Enum):
    """Pipeline stage identifier. Replaces magic 'generate'/'pack' strings."""
    GENERATE = "generate"
    PACK = "pack"


# Regex for counting BMP_* entries emitted by pack.py into _ids.h.
# pack.py produces `enum BMP { BMP_name = N, ... };` - match each BMP_<name>
# that has an '=' assignment so stray references in comments are ignored.
BMP_DEFINE_RE = re.compile(r"\bBMP_([A-Za-z0-9_]+)\s*=", re.MULTILINE)
# Service identifiers produced by pack.py that are not real sprite entries.
# `pal` is pack.py's palette output; the others are standard sentinel entries.
BMP_SERVICE_IDS = frozenset({"none", "last", "0", "pal"})


def find_script(name: str) -> Path:
    """Return absolute path to `name` vendored inside this skill's scripts/ dir.

    `build_psd.py` and `pack.py` live next to this file. The lookup used to
    also walk up to a repo root, but vendoring makes the skill self-contained
    and removes the fragile `.parent.parent.parent.parent` path arithmetic.
    """
    local = SCRIPT_DIR / name
    if local.exists():
        return local
    raise FileNotFoundError(
        f"{name} not found in skill scripts/ directory ({SCRIPT_DIR}). "
        f"Expected it to be vendored alongside build_pipeline.py."
    )


# Generate stage now only synthesises MP3 placeholders, so numpy + ffmpeg are
# the only runtime deps. PIL is no longer needed here — sprite PNGs are
# produced upstream by canvas-design.
GENERATE_PY_DEPS = ("numpy",)
PACK_PY_DEPS = ("PIL", "numpy", "pytoshop", "psd_tools")


def _check_deps(stage: Stage) -> list[str]:
    """Return list of missing dependency messages. Empty = everything installed.

    Generate stage needs numpy + ffmpeg (for sounds); pack stage additionally
    needs PIL + pytoshop + psd_tools (for PSD assembly and atlas packing).
    """
    required = PACK_PY_DEPS if stage is Stage.PACK else GENERATE_PY_DEPS
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
    logger.info("  $ %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    return proc.returncode


def _write_pipeline_state(workspace: Path, state: dict) -> None:
    """Persist pipeline state so a later `pack` knows what the user approved."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / PIPELINE_STATE_FILE).write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8",
    )


def _read_pipeline_state(workspace: Path) -> dict | None:
    """Return parsed pipeline state dict, or None if it does not exist."""
    p = workspace / PIPELINE_STATE_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("pipeline state file corrupted: %s", p)
        return None


def do_generate(args: argparse.Namespace) -> int:
    deps = _check_deps(Stage.GENERATE)
    if deps:
        logger.error("missing dependencies:")
        for d in deps:
            logger.error("  - %s", d)
        return 3

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.error("manifest not found: %s", manifest_path)
        return 2

    try:
        manifest = load_manifest(manifest_path)
    except SchemaMigrationError as exc:
        logger.error("schema migration failed: %s", exc)
        return 2
    errors = validate(manifest)
    if errors:
        logger.error("manifest validation failed (%d issue(s)):", len(errors))
        for e in errors:
            logger.error("  - %s", e)
        return 2

    workspace = Path(args.workspace)
    art_dir = workspace / ART_SUBDIR
    mp3_dir = workspace / MP3_SUBDIR

    # Ensure the workspace layout exists before generators try to write files.
    # On read-only or unusual mounts the generators would otherwise fail with
    # a confusing FileNotFoundError from ffmpeg.
    workspace.mkdir(parents=True, exist_ok=True)
    art_dir.mkdir(parents=True, exist_ok=True)
    mp3_dir.mkdir(parents=True, exist_ok=True)

    # Sprite PNGs are produced upstream by canvas-design (driven by
    # cube_asset-prompter). We do not render them here, but we DO report how
    # many of the manifest's sprites are already on disk so the user sees the
    # gap before running `pack`.
    expected_sprite_names = {s.name for s in manifest.sprites}
    if args.group is not None:
        expected_sprite_names = {
            s.name for s in manifest.sprites if s.derived_group() == args.group
        }
    existing_pngs = {p.stem for p in art_dir.glob("*.png")}
    missing_pngs = sorted(expected_sprite_names - existing_pngs)
    found_sprites = len(expected_sprite_names) - len(missing_pngs)

    logger.info("Checking sprite PNGs    -> %s", art_dir)
    logger.info("  %d/%d manifest sprites already present",
                found_sprites, len(expected_sprite_names))
    if missing_pngs:
        logger.warning(
            "%d sprite PNG(s) missing from %s; render them via "
            "cube_asset-prompter + canvas-design before running `pack`",
            len(missing_pngs), art_dir,
        )
        for name in missing_pngs:
            logger.warning("  - %s.png", name)

    logger.info("Generating sounds       -> %s", mp3_dir)
    mp3_paths = gen_sounds.generate(manifest, mp3_dir, group=args.group)

    groups: set[str] = set()
    for s in manifest.sprites:
        groups.add(s.derived_group())
    for snd in manifest.sounds:
        groups.add(snd.derived_group())

    _write_pipeline_state(workspace, {
        "stage": Stage.GENERATE.value,
        "game": manifest.game,
        "manifest": str(manifest_path),
        "group": args.group,
        "sprite_expected": len(expected_sprite_names),
        "sprite_found": found_sprites,
        "sprite_missing": missing_pngs,
        "mp3_count": len(mp3_paths),
        "groups": sorted(groups),
        "user_approved": False,
    })

    logger.info("=" * 60)
    logger.info("  sprites: %d/%d present in art/ (upstream-provided)",
                found_sprites, len(expected_sprite_names))
    logger.info("  sounds : %d MP3(s) generated", len(mp3_paths))
    logger.info("  groups : %s", sorted(groups))
    logger.info("=" * 60)
    return 0


def do_pack(args: argparse.Namespace) -> int:
    deps = _check_deps(Stage.PACK)
    if deps:
        logger.error("missing dependencies:")
        for d in deps:
            logger.error("  - %s", d)
        return 3

    workspace = Path(args.workspace)
    src_dir = Path(args.src_dir)
    src_dir.mkdir(parents=True, exist_ok=True)

    art_dir = workspace / ART_SUBDIR
    # PSD lives at the workspace root. pack.py resolves the PSD as
    # "{--art-dir}/{--assets}.psd", so --art-dir is the workspace itself.
    psd_path = workspace / PSD_FILENAME
    exported_dir = workspace / EXPORTED_SUBDIR
    packed_dir = workspace / PACKED_SUBDIR
    ids_path = workspace / f"app_{args.game}_ids.h"

    if not art_dir.exists() or not any(art_dir.glob("*.png")):
        logger.error(
            "no PNGs found in %s. Sprite PNGs are produced upstream by "
            "canvas-design (via cube_asset-prompter). Render them first, "
            "then re-run `pack`.", art_dir,
        )
        return 4

    # Make sure every output directory exists before the child processes run.
    # build_psd / pack.py do not create their own output folders.
    art_dir.mkdir(parents=True, exist_ok=True)
    exported_dir.mkdir(parents=True, exist_ok=True)
    packed_dir.mkdir(parents=True, exist_ok=True)

    # Warn (but don't block) when generate stage never ran in this workspace
    # or the user never confirmed review.
    state = _read_pipeline_state(workspace)
    if state is None:
        logger.warning(
            "no %s in %s; proceeding without a generate record",
            PIPELINE_STATE_FILE, workspace,
        )
    elif not state.get("user_approved") and not args.force:
        logger.error(
            "pipeline state says user has not approved generated assets. "
            "Re-run after review, or pass --force to skip the gate.",
        )
        return 6

    build_psd_py = find_script("build_psd.py")
    pack_py = find_script("pack.py")

    logger.info("=== Stage: build_psd ===")
    rc = _run([
        sys.executable, str(build_psd_py),
        str(art_dir), str(psd_path),
        "--padding", "2",
        "--bg-color", "#FF00FF",
    ])
    if rc != 0:
        return rc

    logger.info("=== Stage: pack ===")
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
        "--assets", Path(PSD_FILENAME).stem,
    ])
    if rc != 0:
        return rc

    pal_png = packed_dir / "pal.png"
    if not pal_png.exists():
        logger.error("expected %s was not produced.", pal_png)
        return 5
    if not ids_path.exists() or ids_path.stat().st_size == 0:
        logger.error("%s missing or empty.", ids_path)
        return 5

    dest_ids = src_dir / ids_path.name
    shutil.copy2(ids_path, dest_ids)

    header = ids_path.read_text(encoding="utf-8")
    # Count only real BMP_* defines; skip service aliases like BMP_none/last/0.
    bmp_ids = {m.group(1) for m in BMP_DEFINE_RE.finditer(header)}
    bmp_count = len(bmp_ids - BMP_SERVICE_IDS)

    # Mark pipeline state as packed so a retry knows the previous run succeeded.
    _write_pipeline_state(workspace, {
        **(state or {}),
        "stage": Stage.PACK.value,
        "bmp_count": bmp_count,
        "ids_header": str(dest_ids),
        "psd_path": str(psd_path),
        "exported_dir": str(exported_dir),
        "packed_dir": str(packed_dir),
    })

    logger.info("=" * 60)
    logger.info("  %-20s: ok", "packed/pal.png")
    logger.info("  %-20s: %d BMP_* constants", ids_path.name, bmp_count)
    logger.info("  %s: copied", dest_ids)
    logger.info("  %-20s: %s", "assets.psd", psd_path)
    logger.info("  %-20s: %s", "exported/", exported_dir)
    logger.info("=" * 60)
    return 0


def do_validate(args: argparse.Namespace) -> int:
    """Quick manifest check without rendering anything.

    Useful while editing the manifest by hand: rc=0 when clean, rc=2 otherwise.
    """
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.error("manifest not found: %s", manifest_path)
        return 2
    try:
        manifest = load_manifest(manifest_path)
    except SchemaMigrationError as exc:
        logger.error("schema migration failed: %s", exc)
        return 2
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("cannot parse manifest: %s", exc)
        return 2
    errors = validate(manifest)
    if errors:
        logger.error("manifest validation failed (%d issue(s)):", len(errors))
        for e in errors:
            logger.error("  - %s", e)
        return 2
    logger.info("OK: %d sprite(s), %d sound(s)",
                len(manifest.sprites), len(manifest.sounds))
    return 0


def do_approve(args: argparse.Namespace) -> int:
    """Mark the workspace as user-approved after visual/audio review."""
    workspace = Path(args.workspace)
    state = _read_pipeline_state(workspace)
    if state is None:
        logger.error(
            "no %s in %s; run 'generate' first.",
            PIPELINE_STATE_FILE, workspace,
        )
        return 4
    state["user_approved"] = True
    _write_pipeline_state(workspace, state)
    logger.info("Workspace %s approved. Run 'pack' next.", workspace)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_pipeline",
        description="cube_asset-builder pipeline driver")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Enable DEBUG-level logging")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate manifest without rendering")
    v.add_argument("--manifest", required=True, help="Path to <game>_assets.json")
    v.set_defaults(func=do_validate)

    g = sub.add_parser(
        "generate",
        help="Synthesise sound placeholders from manifest and report sprite-PNG gap.",
    )
    g.add_argument("--manifest", required=True, help="Path to <game>_assets.json")
    g.add_argument("--workspace", default="assets",
                   help="Workspace root (default: assets). MP3s -> <ws>/mp3. "
                        "Sprite PNGs are expected to already live in <ws>/art "
                        "(produced upstream by canvas-design).")
    g.add_argument("--group", default=None,
                   help="Only regenerate sounds for one group; sprite-gap "
                        "reporting is also scoped to this group.")
    g.set_defaults(func=do_generate)

    a = sub.add_parser("approve",
                       help="Mark workspace as user-approved (gate for pack)")
    a.add_argument("--workspace", default="assets", help="Workspace root")
    a.set_defaults(func=do_approve)

    k = sub.add_parser("pack", help="Build PSD + run pack.py + copy ids to src/")
    k.add_argument("--game", required=True, help="Game name (used in _ids.h filename)")
    k.add_argument("--workspace", default="assets", help="Workspace root (default: assets)")
    k.add_argument("--src-dir", default="src", help="Target dir for the ids header")
    k.add_argument("--force", action="store_true",
                   help="Bypass the approve gate (use only when running unattended)")
    k.set_defaults(func=do_pack)

    return p


def _cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbose=getattr(args, "verbose", False))
    return args.func(args)


def main() -> int:
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
