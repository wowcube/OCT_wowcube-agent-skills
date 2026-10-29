"""Pipeline driver for cube_asset-builder.

Subcommands:
  validate    — provider-free manifest check (schema, names, tiers,
                `background`, `launcher_icon`, the Codex prompt rules a regex
                can check, `_panoramas`). Exit 0 ok, 2 errors. Never
                generates, never starts a provider, never touches the
                network: gates and smoke checks use THIS, not `generate`.
  generate    — validate manifest, generate the sprite PNGs and placeholder
                sounds into the per-game workspace (default assets_<game>/
                next to plans/). Sprites: with the default provider (a Codex
                CLI logged in with ChatGPT) the whole manifest is delegated to
                cube_art-director's art.py (`gen` + `process`: style lock,
                chroma-key backdrop, shared scale per set, colour lock); with
                a paid API key, one genimg call per sprite. Sounds:
                synthesised placeholders for every sound that has no sourced
                mp3 yet.
  pack        — build assets.psd then run pack.py to produce packed/ and
                _ids.h. With --manifest it first refuses an incomplete set
                (every sprite needs <ws>/art/<name>.png, with --app-dir every
                sound an mp3 in <ws>/wav/assets or <app>/sound/assets) before
                writing anything; it always clears the intermediate
                <ws>/packed and <ws>/exported first, syncs changed app fonts
                into <ws>/fonts and, with --app-dir, records the sha1 of every
                input in <app>/.pack_inputs.json.
  pack-status — exit 0 when <app>/.pack_inputs.json matches the current
                inputs (and the pack outputs are still the ones it wrote),
                1 when stale or missing; prints what changed.

Designed to work identically in the dev repo layout and inside the
corporate-Claude package (where build_psd.py/pack.py are copied next to this
file). `find_script()` checks the scripts dir then walks up the ancestors.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from manifest_schema import ValidationError, check_manifest_file, load_manifest, validate
import gen_sprites
import gen_sounds
import image_providers

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


def _resolve_image_provider():
    """(ProviderConfig, None) or (None, error message) for the generate stage.
    Codex first; a paid key from the environment/config file only with the
    opt-in (WOWCUBE_ALLOW_PAID_IMAGES=1 or `generate --allow-paid`)."""
    try:
        provider = image_providers.resolve_provider()
    except image_providers.PaidProviderNotAllowed as e:
        return None, str(e)
    except image_providers.ImageGenError as e:
        return None, f"image provider config is invalid: {e}"
    if provider is None:
        return None, (
            "image provider - AI sprite generation needs a Codex CLI logged in "
            "with the user's ChatGPT account (the default, no key: install "
            "Codex, the user runs `codex login`) or a paid-API key via any of: "
            "the OPENROUTER_API_KEY env var, the IMAGE_API env var (bare "
            f"key/URL or JSON), or {image_providers.CONFIG_PATH}. With none "
            "configured the asset builder falls back to agent-drawn placeholder "
            "art (temporary, never accepted as final)."
        )
    return provider, None


def _check_deps(stage: str) -> list[str]:
    """Return list of missing dependency messages. Empty = everything installed.

    `stage` is 'generate' or 'pack'. Generate needs PIL+numpy+requests and an
    image provider from the image_providers chain (a logged-in Codex CLI ->
    OPENROUTER_API_KEY env -> IMAGE_API env -> ~/.wowcube/image_api.json);
    pack needs PIL+numpy+pytoshop+psd_tools.
    """
    required = PACK_PY_DEPS if stage == "pack" else GENERATE_PY_DEPS
    missing: list[str] = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            pip_name = {"PIL": "Pillow", "psd_tools": "psd-tools"}.get(mod, mod)
            missing.append(f"python module {mod!r} - install with: pip install {pip_name}")
    if stage == "generate":
        _, err = _resolve_image_provider()
        if err:
            missing.append(err)
    return missing


def _run(cmd: list[str], *, cwd: Path | None = None) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    return proc.returncode


def do_validate(args: argparse.Namespace) -> int:
    """Provider-free manifest gate: reads the JSON file and nothing else."""
    path = Path(args.manifest)
    errors, warnings, manifest = check_manifest_file(path)
    print(f"validate: {path}")
    for e in errors:
        print(f"  ERROR: {e}")
    for w in warnings:
        print(f"  WARNING: {w}")
    counts = (f"{len(manifest.sprites)} sprite(s), {len(manifest.sounds)} sound(s)"
              if manifest is not None else "not parsed")
    if errors:
        print(f"INVALID: {len(errors)} error(s), {len(warnings)} warning(s) ({counts}) - fix the manifest "
              f"(Stage 2) before generating or packing")
        return 2
    print(f"OK: manifest valid ({counts}{f', {len(warnings)} warning(s)' if warnings else ''})")
    return 0


def do_generate(args: argparse.Namespace) -> int:
    """`--allow-paid` is the opt-in for a paid image API, for this run only
    (it sets WOWCUBE_ALLOW_PAID_IMAGES while generating, then restores it)."""
    if getattr(args, "allow_paid", False) and not image_providers.paid_allowed():
        os.environ[image_providers.ALLOW_PAID_ENV] = "1"
        try:
            return _do_generate(args)
        finally:
            os.environ.pop(image_providers.ALLOW_PAID_ENV, None)
    return _do_generate(args)


def _do_generate(args: argparse.Namespace) -> int:
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

    provider, err = _resolve_image_provider()
    if provider is None:          # resolved a moment ago in _check_deps; be safe anyway
        print(f"ERROR: {err}", file=sys.stderr)
        return 3

    workspace = (Path(args.workspace) if args.workspace
                 else gen_sprites.default_workspace(manifest_path, manifest.game))
    art_dir = workspace / "art"
    wav_dir = workspace / "wav"
    codex = provider.provider == image_providers.CODEX_PROVIDER

    try:
        if codex:
            print(f"Generating sprites with Codex (cube_art-director art.py) -> {art_dir}")
            png_paths = gen_sprites.generate_codex(manifest_path, workspace, manifest=manifest,
                                                   group=args.group, force=args.force, jobs=args.jobs)
        elif image_providers.is_free_local(provider):
            print(f"Generating AI sprites with the local Stable Diffusion at {provider.base_url} "
                  f"(this machine, no paid opt-in needed) -> {art_dir}")
            png_paths = gen_sprites.generate(manifest, art_dir, group=args.group,
                                             style=gen_sprites.manifest_style(manifest_path))
        else:
            print(f"Generating AI sprites with the PAID {provider.provider} API (opted in: "
                  f"{image_providers.ALLOW_PAID_ENV}=1 / --allow-paid) -> {art_dir}")
            png_paths = gen_sprites.generate(manifest, art_dir, group=args.group,
                                             style=gen_sprites.manifest_style(manifest_path))
    except (image_providers.ImageGenError, ValueError) as e:
        print(f"ERROR: sprite generation failed: {e}", file=sys.stderr)
        return 6

    # beta mp3s (22050 Hz mono CBR 32k) are what the beta simulator actually
    # loads; encode them whenever ffmpeg is around, or unconditionally when
    # --mp3 forces it (then a missing ffmpeg is a hard error, not a skip)
    want_mp3 = args.mp3 or shutil.which("ffmpeg") is not None
    mp3_note = f" (+ mp3 -> {wav_dir / 'assets'})" if want_mp3 else ""
    print(f"Placeholder sounds    -> {wav_dir}{mp3_note}")
    kept: list[str] = []
    unverified: list[str] = []
    try:
        wav_paths = gen_sounds.generate(manifest, wav_dir, group=args.group,
                                        encode_mp3=want_mp3, kept=kept, unverified=unverified)
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as e:
        # RuntimeError = ffmpeg missing; CalledProcessError = ffmpeg present
        # but the mp3 encode itself failed; ValueError = two manifest sound
        # names collide once normalised to SND_ ids. Same exit either way.
        print(f"ERROR: sound encoding failed: {e}", file=sys.stderr)
        return 7

    groups: set[str] = set()
    for s in manifest.sprites:
        groups.add(s.group or gen_sprites._derived_group(s))
    for snd in manifest.sounds:
        groups.add(snd.group or snd.name)

    print("=" * 60)
    print(f"  {len(png_paths)} PNG(s) ({'codex via art.py' if codex else provider.provider}), "
          f"{len(wav_paths)} placeholder WAV(s), {len(kept)} sourced sound(s) kept")
    if unverified:
        print("  " + gen_sounds.unverified_warning(wav_dir, unverified))
    print(f"  workspace: {workspace}")
    print(f"  groups: {sorted(groups)}")
    if codex:
        print(f"  next: strict QA loop -> python skills/cube_art-director/scripts/art.py qa "
              f"{manifest_path} --workspace {workspace}")
    print("=" * 60)
    return 0


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ICON = REPO_ROOT / "templates" / "app_ai_template" / "art" / "icon.png"


def _sync_fonts(app_dir: Path, workspace: Path) -> tuple[int, int, list[str]]:
    """BMFont glyphs are packed only when font_*.fnt + their atlas PNGs sit in
    <workspace>/fonts. A scaffolded app keeps them in app_<game>/art, so
    mirror them over; without them every OCT_label_set silently draws
    nothing. A font that changed in the app (new .fnt, re-exported atlas) is
    copied again, and atlas pages the app no longer has
    (<stem>_<page>.png) are removed, so a stale page can never be packed.

    Returns (files copied, stale pages removed, workspace-only fonts). Fonts
    that exist only in <workspace>/fonts are left alone (reported)."""
    fonts = sorted((app_dir / "art").glob("font_*.fnt"))
    if not fonts:
        return 0, 0, []
    dst = workspace / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    copied = removed = 0
    for f in fonts:
        pages = sorted(f.parent.glob(f"{f.stem}_*.png"))
        for src in [f, *pages]:
            target = dst / src.name
            if not target.is_file() or target.read_bytes() != src.read_bytes():
                shutil.copy2(src, target)
                copied += 1
        keep = {p.name for p in pages}
        page_re = re.compile(rf"^{re.escape(f.stem)}_\d+\.png$")
        for old in sorted(dst.glob(f"{f.stem}_*.png")):
            if old.name not in keep and page_re.match(old.name):
                old.unlink()
                removed += 1
    app_stems = {f.stem for f in fonts}
    extra = sorted(p.name for p in dst.glob("*.fnt") if p.stem not in app_stems)
    return copied, removed, extra


def _copy_fonts(app_dir: Path, workspace: Path) -> int:
    """Kept for callers of the old name: syncs and returns the files copied."""
    return _sync_fonts(app_dir, workspace)[0]


def _clear_intermediate(d: Path) -> int:
    """Empty one intermediate build folder (<ws>/packed or <ws>/exported):
    pack.py emits EVERY PNG left in the packed-output folder, so a retired
    frame from an earlier run would otherwise come back indexed and chained.
    Returns the number of entries removed."""
    if not d.is_dir():
        return 0
    n = 0
    for p in sorted(d.iterdir()):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
        n += 1
    return n


PACK_INPUTS_FILE = ".pack_inputs.json"
PACK_INPUTS_VERSION = 1


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _auto_icon(workspace: Path, app_dir: Path) -> Path | None:
    """The icon pack.py picks when no --icon is given (same order)."""
    for cand in (workspace / "icon.png", app_dir / "icon.png", app_dir / "art" / "icon.png"):
        if cand.is_file():
            return cand
    return None


def pack_inputs(workspace: Path, app_dir: Path, manifest: Path | None, icon: Path | None) -> dict[str, str]:
    """sha1 of every file a pack reads: the manifest, every PNG in <ws>/art
    (and <ws>/overrides), the sounds (<ws>/wav/assets and <app>/sound/assets),
    the fonts (<app>/art/font_* and the <ws>/fonts mirror) and the launcher
    icon. Keys are stable labels (ws/..., app/...), so a moved workspace
    still compares."""
    files: dict[str, str] = {}
    if manifest is not None and Path(manifest).is_file():
        files["manifest"] = _sha1(Path(manifest))
    groups = (
        ("ws/art", workspace / "art", ("*.png",)),
        ("ws/overrides", workspace / "overrides", ("*.png",)),
        ("ws/wav/assets", workspace / "wav" / "assets", ("*.mp3",)),
        ("ws/fonts", workspace / "fonts", ("*.fnt", "*.png")),
        ("app/sound/assets", app_dir / "sound" / "assets", ("*.mp3",)),
        ("app/art", app_dir / "art", ("font_*.fnt", "font_*.png")),
    )
    for label, folder, patterns in groups:
        if not folder.is_dir():
            continue
        for pattern in patterns:
            for p in sorted(folder.glob(pattern)):
                if p.is_file():
                    files[f"{label}/{p.name}"] = _sha1(p)
    if icon is not None and Path(icon).is_file():
        files["icon"] = _sha1(Path(icon))
    return files


def pack_outputs(app_dir: Path, game: str) -> dict[str, str]:
    """sha1 of the outputs the pack-status record vouches for."""
    out: dict[str, str] = {}
    for rel in ("index.bin", f"src/app_{game}_ids.h"):
        p = app_dir / rel
        if p.is_file():
            out[rel] = _sha1(p)
    return out


def _compare(label: str, recorded: dict, current: dict) -> list[str]:
    lines = []
    for k in sorted(set(recorded) | set(current)):
        if k not in current:
            lines.append(f"  removed{label}: {k}")
        elif k not in recorded:
            lines.append(f"  added{label}:   {k}")
        elif recorded[k] != current[k]:
            lines.append(f"  changed{label}: {k}")
    return lines


def pack_status(game: str, workspace: Path, app_dir: Path, manifest: Path | None,
                icon: Path | None = None) -> tuple[bool, list[str]]:
    """(fresh, report lines) for <app>/.pack_inputs.json against the current inputs."""
    rec_path = Path(app_dir) / PACK_INPUTS_FILE
    if not rec_path.is_file():
        return False, [f"no {rec_path}: never packed by `build_pipeline.py pack --app-dir`, or the last pack "
                       f"failed"]
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        recorded_in, recorded_out = dict(rec["inputs"]), dict(rec.get("outputs", {}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, [f"{rec_path} unreadable ({exc})"]
    if manifest is not None and not Path(manifest).is_file():
        return False, [f"manifest not found: {manifest}"]
    if icon is None and rec.get("icon_arg"):
        icon = Path(rec["icon_arg"])        # the explicit --icon of the recorded pack
    if icon is None:
        icon = _auto_icon(Path(workspace), Path(app_dir))
    current_in = pack_inputs(Path(workspace), Path(app_dir), manifest, icon)
    lines = _compare("", recorded_in, current_in)
    lines += _compare(" output", recorded_out, pack_outputs(Path(app_dir), game))
    if rec.get("game") not in (None, game):
        lines.append(f"  game: recorded {rec.get('game')!r}, asked {game!r}")
    return not lines, lines


def _center_pivots(manifest, app_dir: Path) -> int:
    """Write utils.exe-style on-screen pivots into every manifest sprite's
    packed header (offset 4: PivotX/PivotY floats; offset 36: w, h). A regular
    sprite is drawn x2, so its authored pivot p maps to 2p - 0.5 on screen; a
    fullsize sprite (1:1) to p - 0.5. The PNG/PSD route otherwise leaves some
    animation frames and full-color sprites off centre."""
    import struct
    fixed = 0
    for s in manifest.sprites:
        raw = app_dir / "art" / "packed" / f"{s.name}.raw"
        if not raw.is_file():
            continue
        b = bytearray(raw.read_bytes())
        w, h = struct.unpack_from("<hh", b, 36)
        k = 1.0 if s.flags.fullsize else 2.0
        aw, ah = s.size
        if tuple(s.pivot) == (aw // 2, ah // 2):       # default = centred, exact for odd sizes too
            px, py = ((w - 1) / 2.0, (h - 1) / 2.0) if s.flags.fullsize else (w - 0.5, h - 0.5)
        else:
            px, py = s.pivot[0] * k - 0.5, s.pivot[1] * k - 0.5
        if struct.unpack_from("<ff", b, 4) != (px, py):
            struct.pack_into("<ff", b, 4, px, py)
            raw.write_bytes(bytes(b))
            fixed += 1
    return fixed


def do_pack(args: argparse.Namespace) -> int:
    deps = _check_deps("pack")
    if deps:
        print("ERROR: missing dependencies:", file=sys.stderr)
        for d in deps:
            print(f"  - {d}", file=sys.stderr)
        return 3

    workspace = Path(args.workspace)
    src_dir = Path(args.src_dir)

    art_dir = workspace / "art"
    psd_path = workspace / "assets.psd"
    exported_dir = workspace / "exported"
    packed_dir = workspace / "packed"
    ids_path = workspace / f"app_{args.game}_ids.h"
    app_dir = Path(args.app_dir) if args.app_dir else None

    # ── refuse an incomplete set BEFORE anything is written ─────────────────
    manifest = None
    if args.manifest:
        if not Path(args.manifest).is_file():
            print(f"ERROR: manifest not found: {args.manifest}", file=sys.stderr)
            return 2
        try:
            manifest = load_manifest(args.manifest)
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"ERROR: manifest unreadable: {args.manifest}: {e!r}", file=sys.stderr)
            return 2

    if not art_dir.exists() or not any(art_dir.glob("*.png")):
        print(f"ERROR: no PNGs found in {art_dir}. Run 'generate' first.",
              file=sys.stderr)
        return 4

    missing: list[str] = []
    if manifest is not None:
        for s in manifest.sprites:
            if not (art_dir / f"{s.name}.png").is_file():
                missing.append(f"sprite {s.name!r}: no {art_dir / (s.name + '.png')}")
        if app_dir is not None:
            for snd in manifest.sounds:
                ws_mp3 = workspace / "wav" / "assets" / f"{snd.name}.mp3"
                app_mp3 = app_dir / "sound" / "assets" / f"{snd.name}.mp3"
                if not (ws_mp3.is_file() or app_mp3.is_file()):
                    missing.append(f"sound {snd.name!r}: no {ws_mp3} or {app_mp3}")
    if args.icon and not Path(args.icon).is_file():
        missing.append(f"launcher icon: --icon {args.icon} not found")
    if missing:
        print(f"ERROR: incomplete asset set - {len(missing)} input(s) missing; nothing was packed or written "
              f"(a partial set is never packed):", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 4
    if manifest is not None:
        extra = sorted(p.stem for p in art_dir.glob("*.png")
                       if p.stem not in {s.name for s in manifest.sprites} and p.stem != "0")
        if extra:
            print(f"WARNING: {len(extra)} PNG(s) in {art_dir} are not manifest sprites and will be packed too: "
                  f"{', '.join(extra[:8])}{' ...' if len(extra) > 8 else ''} (delete retired ones)",
                  file=sys.stderr)

    build_psd_py = find_script("build_psd.py")
    pack_py = find_script("pack.py")

    src_dir.mkdir(parents=True, exist_ok=True)
    if app_dir is not None:
        # a pack in progress vouches for nothing: pack-status says "stale" until this run succeeds
        (app_dir / PACK_INPUTS_FILE).unlink(missing_ok=True)

    # ── clean intermediates: every output below is rebuilt from the inputs ─
    for d in (packed_dir, exported_dir):
        if app_dir is not None and d.resolve() == (app_dir / "art" / "packed").resolve():
            print(f"  NOTE: {d} is the app's own art/packed - not cleared")
            continue
        n = _clear_intermediate(d)
        if n:
            print(f"  cleared {n} stale entr{'y' if n == 1 else 'ies'} from {d}")

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
    if app_dir is not None:
        n_fonts, n_stale, ws_only = _sync_fonts(app_dir, workspace)
        if n_fonts:
            print(f"  copied {n_fonts} new/changed font file(s) -> {workspace / 'fonts'}")
        if n_stale:
            print(f"  removed {n_stale} stale font atlas page(s) from {workspace / 'fonts'}")
        if ws_only:
            print(f"  NOTE: {', '.join(ws_only)} exist only in {workspace / 'fonts'} (not in the app's art/): "
                  f"still packed")
        if not args.icon:
            icon = app_dir / "art" / "icon.png"
            if icon.is_file() and TEMPLATE_ICON.is_file() and icon.read_bytes() == TEMPLATE_ICON.read_bytes():
                print("WARNING: app_<game>/art/icon.png is still the TEMPLATE icon - generate the game's "
                      "launcher icon (160x160 RGBA flat-top hexagon badge) and pass --icon", file=sys.stderr)
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
        if manifest is not None:
            # ship exactly the manifest's sounds: the scaffold copies the template's demo mp3s into
            # sound/assets and every packer packs whatever lies there. sound/unused/ is read by no packer
            # (pack.py and octpack-link read sound/assets, octpack's converter only sound/'s own files).
            wanted = {snd.name for snd in manifest.sounds}
            snd_assets = app_dir / "sound" / "assets"
            extra_mp3 = sorted(p for p in snd_assets.glob("*.mp3") if p.stem not in wanted) \
                if snd_assets.is_dir() else []
            if extra_mp3:
                unused = app_dir / "sound" / "unused"
                unused.mkdir(parents=True, exist_ok=True)
                for p in extra_mp3:
                    shutil.move(str(p), str(unused / p.name))
                print(f"WARNING: moved {len(extra_mp3)} mp3(s) not in the manifest out of {snd_assets} -> "
                      f"{unused} (they would ship): {', '.join(p.stem for p in extra_mp3)}", file=sys.stderr)
        # beta (octavios dev) container: index.bin + art/packed + kind-aware
        # src/app_<game>_ids.h, emitted into the app dir by pack.py
        pack_cmd += [
            "--beta-app-dir", str(app_dir),
            "--app-name", f"app_{args.game}",
        ]
        if args.manifest:
            pack_cmd += ["--manifest", str(args.manifest)]
        if args.icon:
            pack_cmd += ["--icon", str(args.icon)]
    rc = _run(pack_cmd)
    if rc != 0:
        return rc

    pal_png = packed_dir / "pal.png"
    needs_palette = manifest is None or any(sp.color != "full" for sp in manifest.sprites)
    if needs_palette and not pal_png.exists():
        print(f"ERROR: expected {pal_png} was not produced.", file=sys.stderr)
        return 5
    if not ids_path.exists() or ids_path.stat().st_size == 0:
        print(f"ERROR: {ids_path} missing or empty.", file=sys.stderr)
        return 5

    if args.app_dir and manifest is not None:
        fixed = _center_pivots(manifest, Path(args.app_dir))
        if fixed:
            print(f"  pivots centred on {fixed} sprite(s)")
        fonts = list((Path(args.app_dir) / "art").glob("font_*.fnt"))
        beta_hdr = Path(args.app_dir) / "src" / ids_path.name
        if fonts and beta_hdr.is_file() and "font_" not in beta_hdr.read_text(encoding="utf-8").lower():
            print(f"ERROR: {len(fonts)} BMFont(s) in app art/ but no font_ glyphs in {beta_hdr.name}: "
                  f"labels would draw nothing", file=sys.stderr)
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

    if args.app_dir:
        # Beta mode: these *.raw live in the legacy workspace copy only; the
        # sim actually loads <app_dir>/art/packed/*.raw (copied there by
        # pack.py's --beta-app-dir handling above), not this workspace path.
        raw_label = "legacy workspace copies; the sim loads <app_dir>/art/packed"
    else:
        raw_label = "sim/.oct assets"
    print("=" * 60)
    print(f"  packed/pal.png       : ok")
    print(f"  packed/*.raw         : {raw_count} file(s) ({raw_label})")
    print(f"  {ids_path.name:<20}: {bmp_count} BMP_* constants")
    print(f"  {dest_ids}: copied")
    if app_dir is not None:
        manifest_path = Path(args.manifest) if args.manifest else None
        icon_used = Path(args.icon) if args.icon else _auto_icon(workspace, app_dir)
        record = {
            "version": PACK_INPUTS_VERSION,
            "packer": "build_pipeline.py pack",
            "packed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "game": args.game,
            "workspace": str(workspace.resolve()),
            "app_dir": str(app_dir.resolve()),
            "manifest": str(manifest_path.resolve()) if manifest_path else None,
            "icon": str(icon_used.resolve()) if icon_used else None,
            "icon_arg": str(Path(args.icon).resolve()) if args.icon else None,
            "inputs": pack_inputs(workspace, app_dir, manifest_path, icon_used),
            "outputs": pack_outputs(app_dir, args.game),
        }
        (app_dir / PACK_INPUTS_FILE).write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
        print(f"  {PACK_INPUTS_FILE:<20}: {len(record['inputs'])} input(s) recorded (pack-status compares them)")
    print("=" * 60)
    return 0


def do_pack_status(args: argparse.Namespace) -> int:
    fresh, lines = pack_status(args.game, Path(args.workspace), Path(args.app_dir),
                               Path(args.manifest) if args.manifest else None,
                               Path(args.icon) if args.icon else None)
    rec = Path(args.app_dir) / PACK_INPUTS_FILE
    if fresh:
        print(f"pack-status: FRESH - {rec} matches the current inputs and outputs")
        return 0
    print(f"pack-status: STALE - repack (build_pipeline.py pack ...); {len(lines)} difference(s):")
    for line in lines:
        print(line if line.startswith("  ") else f"  {line}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_pipeline",
        description="cube_asset-builder pipeline driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Provider-free manifest check (schema, names, tiers, background, "
                                        "launcher_icon, Codex prompt rules); exit 0 ok, 2 errors. Never "
                                        "generates, never touches the network")
    v.add_argument("--manifest", required=True, help="Path to plans/<game>_assets.json")
    v.set_defaults(func=do_validate)

    g = sub.add_parser("generate", help="Generate sprites (Codex via art.py, or a paid API) + "
                                        "placeholder sounds from the manifest")
    g.add_argument("--manifest", required=True, help="Path to plans/<game>_assets.json")
    g.add_argument("--workspace", default=None,
                   help="Per-game workspace (default: assets_<game>/ next to plans/, the folder "
                        "cube_art-director uses). PNGs -> <ws>/art, sounds -> <ws>/wav.")
    g.add_argument("--group", default=None,
                   help="Only regenerate one group (sprites + sounds)")
    g.add_argument("--force", action="store_true",
                   help="Codex: redraw sprites that already have a raw image (default: draw only "
                        "what is missing)")
    g.add_argument("--jobs", type=int, default=3,
                   help="Codex: parallel Codex runs (default 3)")
    g.add_argument("--mp3", action="store_true",
                   help="Require beta mp3 encoding (fail if ffmpeg is missing; "
                        "without this flag mp3s are encoded only when ffmpeg "
                        "is on PATH)")
    g.add_argument("--allow-paid", action="store_true",
                   help="Opt in to a PAID image API (OPENROUTER_API_KEY / IMAGE_API / ~/.wowcube/image_api.json) "
                        "when no Codex CLI is logged in - only after the user agreed to pay per image. Same as "
                        "WOWCUBE_ALLOW_PAID_IMAGES=1. Without it an inherited key is never used")
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
    k.add_argument("--icon", default=None,
                   help="Launcher icon PNG forwarded to pack.py's beta emit "
                        "(default: pack.py auto-detects <app-dir>/art/icon.png)")
    k.set_defaults(func=do_pack)

    s = sub.add_parser("pack-status", help="Exit 0 when <app>/.pack_inputs.json matches the current inputs "
                                           "(manifest, PNGs, mp3s, fonts, icon) and outputs, 1 when stale or "
                                           "missing; prints what changed")
    s.add_argument("--game", required=True, help="Game name (the ids header is src/app_<game>_ids.h)")
    s.add_argument("--workspace", required=True, help="The workspace the pack used (assets_<game>)")
    s.add_argument("--app-dir", required=True, help="The app the pack wrote (app_<game>)")
    s.add_argument("--manifest", default=None, help="The manifest the pack used (plans/<game>_assets.json)")
    s.add_argument("--icon", default=None,
                   help="The launcher icon (default: the --icon of the recorded pack, else the auto-detected one)")
    s.set_defaults(func=do_pack_status)

    return p


def _cli(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def main() -> int:
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
