#!/usr/bin/env python3
"""
WowCube Packed Sprite Encoder
=============================

Packs RGBA PNG sprites into the WowCube packed format (single-pixel-high
PNG strips with embedded header, scanline trims, and bit-packed RLE data).

Two operating modes:

  1. Re-pack (default): reads existing packed/ sprites for header metadata
     (pivot, flags, palette index, etc.) and re-encodes pixel data from
     the exported/ folder.  Use this after editing exported PNGs.

  2. Standalone: packs exported PNGs from scratch, generating headers and
     building a new palette.

Packed sprite format:
  - 48-byte header (octBmp_t without PackerSizes)
  - Scanline trim array (H bytes, aligned to multiple of 4)
  - Bit-packed texel stream (palette symbol + RLE length code)

Usage:
  python pack.py                                    # re-pack all (reuse existing palette)
  python pack.py exported/coin.png                  # re-pack one file
  python pack.py --build-palette                    # auto-build palette (try 16 colors first)
  python pack.py --build-palette --max-colors 64    # limit palette size
  python pack.py --build-palette --target-colors 16 # force exact palette size
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Required: pip install Pillow numpy")
    sys.exit(1)

from config import (
    DEFAULT_ASSET_NAME, DEFAULT_PALETTE_FILENAME,
    DEFAULT_QUALITY_THRESHOLD,
    HDR_OFF_COMPRESSION, HDR_OFF_PIDX, HDR_OFF_WIDTH,
    MAP_FILENAME_PREFIX,
    PALETTE_SPRITE_NAME,
    PLACEHOLDER_SPRITE_NAME,
    PLACEHOLDER_SPRITE_PIVOT,
    PSL_TYPE_ASSET,
    RESERVED_MAP_NAMES,
    SpriteFlag,
)

from pack_codec import (
    EncoderPalette,
    blob_to_packed_png,
    build_auto_palette,
    build_config_palettes,
    build_grouped_palettes,
    load_palette_for_encoding,
    pack_sprite,
    read_existing_header,
    save_palette_png,
)
from pack_psd import (
    _ensure_placeholder_sprite,
    emit_index_blocks,
    export_psd,
    generate_app_ids_h,
    is_name_declaration,
    normalize_layer_name,
    pack_maps,
    parse_psl,
)



# ─────────────────────────────────────────────────────────────────────────────
# Entry point — phases
# ─────────────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WowCube Packed Sprite Encoder")
    p.add_argument('files', nargs='*',
                   help='Exported PNGs to pack (default: all from exported/)')
    p.add_argument('--exported-dir', default='exported')
    p.add_argument('--packed-dir',   default='packed')
    p.add_argument('--output-dir',   default='packed_new')
    p.add_argument('--pal', default=None,
                   help='Path to pal.png (default: packed/pal.png)')
    p.add_argument('--no-reuse-headers', action='store_true')
    p.add_argument('--build-palette', action='store_true')
    p.add_argument('--max-colors', type=int, default=256)
    p.add_argument('--single-palette', action='store_true')
    p.add_argument('--target-colors', type=int, default=None)
    p.add_argument('--quality-threshold', type=int, default=DEFAULT_QUALITY_THRESHOLD)
    p.add_argument('--pre-reduce', type=int, default=None)
    p.add_argument('--color-tolerance', type=int, default=0)
    p.add_argument('--export', action='store_true')
    p.add_argument('--art-dir', default='.')
    p.add_argument('--assets', default=None)
    p.add_argument('--build-maps', action='store_true')
    p.add_argument('--map-filter', default=None)
    p.add_argument('--build-ids', action='store_true')
    p.add_argument('--ids-output', default=None)
    p.add_argument('--emit-raw', action='store_true',
                   help='After packing, convert each output-dir/*.png into '
                        'raw-dir/<stem>.raw (decoded RGBA bytes) for the Linux sim')
    p.add_argument('--raw-dir', default=None,
                   help='Destination for --emit-raw .raw files '
                        '(default: --packed-dir, where the sim reads packed/*.raw)')
    p.add_argument('--beta-app-dir', default=None,
                   help='Beta (octavios dev) app root. When set, after the '
                        'legacy pack a beta asset container is emitted there: '
                        'index.bin, art/packed/*.{raw,pal}, launcher icon '
                        'maps, and a kind-aware src/<app-name>_ids.h')
    p.add_argument('--app-name', default=None,
                   help='App name for the beta ids header filename '
                        '(<app-name>_ids.h; default: the --beta-app-dir folder name)')
    p.add_argument('--beta-ids-output', default=None,
                   help='Exact path of the beta ids header, overriding the '
                        '<app-name>_ids.h default. Use it when the app '
                        'includes a header whose name is not derived from the '
                        'app/target name (legacy !pack.bat sets app=app, so '
                        'src/app.h does #include "app_ids.h").')
    p.add_argument('--pack-bat', default=None,
                   help='Path to the app\'s art/!pack.bat, the artist\'s own '
                        'declaration of the pack (which PSDs are exported, '
                        'which are -map, which palette config utils.exe '
                        'consumes). Auto-detected as <art-dir>/!pack.bat.')
    p.add_argument('--no-pack-bat', action='store_true',
                   help='Ignore any !pack.bat and use the filename heuristics')
    p.add_argument('--pack-config', default=None,
                   help='Path to a legacy !pack.txt (palette buckets + '
                        '<FULLSIZE>/<ALPHA>/... tags). Auto-detected as '
                        '<art-dir>/!pack.txt when present, but an '
                        'auto-detected file is ignored when --manifest is '
                        'given (the manifest is the newer, richer source '
                        'and wins). An explicit --pack-config still applies '
                        'alongside --manifest.')
    p.add_argument('--no-pack-config', action='store_true',
                   help='Ignore any !pack.txt and use the auto median-cut '
                        'palette grouping instead')
    p.add_argument('--manifest', default=None,
                   help='Path to plans/<game>_assets.json. Sprites with '
                        'color=="full" are RAW565-encoded into the beta '
                        'container from their exported PNGs instead of the '
                        'palette codec. Optional; legacy invocations omit it.')
    p.add_argument('--icon', default=None,
                   help='Launcher icon PNG for the beta container (default: '
                        'auto-detect icon.png in --art-dir or --beta-app-dir)')
    p.add_argument('--icon-color', choices=('palette', 'full'), default=None,
                   help='Launcher icon art tier, overriding the manifest '
                        'icon object: "palette" quantizes the icon into its '
                        'own dedicated .pal, "full" is RAW565 '
                        '(default: manifest icon.color, else full)')
    p.add_argument('--icon-side', type=int, default=None,
                   help='Launcher icon side in pixels (square), overriding '
                        'the manifest icon object. Palette icons allow only '
                        'the proven 120 (drawn x2 -> 240) or 240 (fullsize, '
                        '1:1); full-color allows 1..240 '
                        '(default: manifest icon.side, else 160)')
    p.add_argument('--icon-dither', action=argparse.BooleanOptionalAction,
                   default=None,
                   help='Floyd-Steinberg dithering for a full-color icon, '
                        'overriding the manifest icon object '
                        '(default: manifest icon.dither, else off)')
    return p


def _resolve_asset_names(args: argparse.Namespace) -> set[str]:
    if args.assets is not None:
        return {n.strip() for n in args.assets.split(',') if n.strip()}
    asset_psds = sorted(Path(args.art_dir).glob('*assets*.psd'))
    if asset_psds:
        result = {p.stem for p in asset_psds}
        print(f"  Auto-detected assets: {', '.join(sorted(result))}")
        return result
    return {DEFAULT_ASSET_NAME}


def _resolve_pack_bat(args: argparse.Namespace):
    """Load the app's ``art/!pack.bat`` declaration, if it has one."""
    from packbat import find_pack_bat, parse_pack_bat

    if getattr(args, 'no_pack_bat', False):
        return None
    path = Path(args.pack_bat) if getattr(args, 'pack_bat', None) \
        else find_pack_bat(args.art_dir)
    if path is None:
        return None
    if not path.is_file():
        print(f"Error: --pack-bat {path} not found")
        sys.exit(1)
    try:
        pb = parse_pack_bat(path)
    except OSError as exc:
        print(f"  WARNING: {path} unreadable ({exc}) - falling back to "
              f"filename heuristics")
        return None
    if not pb.declares_anything:
        print(f"  NOTE: {path} declares no psd.exe/utils.exe runs - "
              f"falling back to filename heuristics")
        return None
    print(f"  Using {path}: {len(pb.assets)} asset PSD(s), {len(pb.maps)} "
          f"map PSD(s), {len(pb.fonts)} font(s)"
          + (f", config {pb.pack_config}" if pb.pack_config else ""))
    return pb


def _resolve_map_filter(args: argparse.Namespace, pack_bat=None) -> None:
    """Decide which PSDs are placement maps rather than sprite sheets.

    The app's own ``art/!pack.bat`` wins when it exists: it literally lists
    the ``psd.exe ... -map`` invocations, which is the only source that
    generalises. ``OCT_ladybug`` runs EIGHT PSDs through ``-map``
    (``splash, splash_wo_saves, countdown, hud, game_over, complete, win,
    ico``) and not one of them carries the ``map_`` prefix or a reserved
    launcher name, so the name-based fallback below finds exactly one of the
    eight — and the other seven then export sprite PNGs.

    Fallback, when there is no ``!pack.bat``: the ``map_`` filename prefix
    plus the launcher's two reserved map names. ``ico`` is looked up by name
    by the engine itself (``oct_shell.h``: ``OCT_external_map(..., "ico")``)
    and ``ahover`` is its hover twin, so ``art/ico.psd``/``art/ahover.psd``
    are maps by contract.

    Getting this wrong is not cosmetic: a map PSD exported in Assets mode
    writes PNGs, and its layers are *named after sprites that already exist*
    (``ahover.psd`` holds a 74x67 placement thumbnail called ``ahover_00``,
    the real 144x145 sprite lives in ``ahover_src.psd``), so the map
    silently overwrites the sprite it points at.
    """
    if args.map_filter is not None:
        return
    if pack_bat is not None and pack_bat.declares_export:
        if pack_bat.maps:
            args.map_filter = ','.join(pack_bat.maps)
            print(f"  Maps declared by {pack_bat.path.name}: {args.map_filter}")
        else:
            # An explicit declaration with no -map run means "no maps", which
            # is different from "we could not tell" - do not fall through.
            args.map_filter = ''
            print(f"  {pack_bat.path.name} declares no -map PSDs")
        return
    art = Path(args.art_dir)
    map_psds = [p.stem for p in sorted(art.glob(f'{MAP_FILENAME_PREFIX}*.psd'))]
    map_psds += [n for n in RESERVED_MAP_NAMES
                 if (art / f'{n}.psd').is_file() and n not in map_psds]
    if map_psds:
        args.map_filter = ','.join(map_psds)
        print(f"  Auto-detected maps: {args.map_filter}")


def _map_filter_value(args: argparse.Namespace):
    """``--map-filter`` normalised once: None (auto), 'all', or a name list.

    An empty string is a *declaration* of "no maps" (``!pack.bat`` with no
    ``-map`` run) and yields ``[]`` — distinct from None, which means "nobody
    told us, guess from filenames".
    """
    mf = args.map_filter
    if mf is None or mf == 'auto':
        return None
    if mf == 'all':
        return 'all'
    return [n.strip() for n in mf.split(',') if n.strip()]


def _phase_export(args: argparse.Namespace, asset_names_set: set[str],
                  pack_bat=None) -> None:
    if not args.export:
        return
    print("=== Exporting PSD/FNT layers (psd-tools) ===")
    export_psd(
        art_dir=args.art_dir,
        exported_dir=args.exported_dir,
        map_filter=_map_filter_value(args),
        asset_names=asset_names_set,
        psd_names=(pack_bat.psd_names if pack_bat is not None
                   and pack_bat.declares_export else None),
        font_sources=(pack_bat.fonts if pack_bat is not None
                      and pack_bat.fonts else None),
    )
    _apply_export_overrides(args.art_dir, args.exported_dir)
    print()


def _apply_export_overrides(art_dir: str, exported_dir: str) -> int:
    """Copy ``<art-dir>/overrides/*.png`` over the freshly exported sprites.

    An export run rebuilds ``art/exported/`` from the PSDs, which is exactly
    what CI wants — except that some sprites are deliberately NOT what their
    PSD layer holds. The reference corpus ships two variants of its QR code
    and the one the app draws is a plain committed PNG, copied over the
    exported layer as the last step of the artist's ``!pack.bat``. Without a
    convention for that, a python-only build silently ships the wrong artwork
    (measured on the corpus: mean abs error 146/255 against the shipped
    sprite) — a wrong pack that still passes every structural check.

    The rule is deliberately dumb and app-agnostic: a PNG in
    ``<art-dir>/overrides/`` replaces the exported sprite of the same name,
    and one that matches no exported sprite is simply added as a new sprite.
    Nothing here knows about QR codes. Returns the number of files copied.
    """
    src_dir = Path(art_dir) / 'overrides'
    if not src_dir.is_dir():
        return 0
    pngs = sorted(src_dir.glob('*.png'))
    if not pngs:
        return 0
    os.makedirs(exported_dir, exist_ok=True)
    for png in pngs:
        dst = Path(exported_dir) / png.name
        verb = 'overrides' if dst.exists() else 'adds'
        shutil.copy2(png, dst)
        print(f"  {src_dir.name}/{png.name} {verb} {dst}")
    print(f"  {len(pngs)} committed override PNG(s) applied over the export")
    return len(pngs)


def _declared_pack_config(args: argparse.Namespace, pack_bat) -> Path | None:
    """The palette config ``!pack.bat`` actually feeds to ``utils.exe``.

    Not a filename question. ``OCT_get_started`` passes ``!pack.txt``
    directly. ``OCT_ladybug`` first runs its own ``pack_palettes.py`` to
    expand ``!pack.txt`` (16 coarse buckets, used only as a ``--lock`` seed)
    into ``!pack_pal.txt`` (32 buckets) and passes *that* — so picking the
    config by name gives ladybug a much coarser palette set than the one its
    shipped container was built with. We never run the app's script: the
    generated config is committed, and if it is not, we fall back to the
    filename heuristic rather than guess.
    """
    if pack_bat is None or not pack_bat.pack_config:
        return None
    cand = Path(args.art_dir) / pack_bat.pack_config.replace('\\', '/')
    if cand.is_file():
        return cand
    print(f"  WARNING: {pack_bat.path.name} feeds {pack_bat.pack_config} to "
          f"utils.exe but {cand} does not exist (it is generated by the app's "
          f"own script and was not committed) - falling back to the "
          f"!pack.txt filename heuristic")
    return None


def _resolve_pack_config(args: argparse.Namespace, pack_bat=None):
    """Resolve the ``!pack.txt`` that drives palette buckets, if any.

    Precedence (documented in the CLI help too):

      1. ``--no-pack-config`` — explicit opt-out, back to auto-grouping,
         wins over everything else.
      2. ``--pack-config <path>`` — explicit config; honoured even when
         ``--manifest`` is also given.
      3. ``--manifest`` without an explicit ``--pack-config`` — the
         manifest is the modern asset spec and wins outright; an
         auto-detected ``!pack.txt`` sitting next to it is ignored.
      4. the config ``art/!pack.bat`` passes to ``utils.exe``
         (see :func:`_declared_pack_config`), or failing that
         ``<art-dir>/!pack.txt`` — auto-detected for legacy apps.
    """
    from packtxt import PackTxtError, find_pack_txt, parse_pack_txt

    if args.no_pack_config:
        return None
    if args.manifest and not args.pack_config:
        auto = _declared_pack_config(args, pack_bat) \
            or find_pack_txt(args.art_dir)
        if auto is not None:
            print(f"  NOTE: {auto} ignored - the manifest ({args.manifest}) "
                  f"takes precedence over !pack.txt")
        return None

    path = Path(args.pack_config) if args.pack_config \
        else (_declared_pack_config(args, pack_bat)
              or find_pack_txt(args.art_dir))
    if path is None:
        return None
    if not path.is_file():
        print(f"Error: --pack-config {path} not found")
        sys.exit(1)

    try:
        config = parse_pack_txt(path)
    except PackTxtError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    print(f"  Using palette config {path} "
          f"({len(config.buckets)} palette groups, "
          f"exported dir '{config.exported_dir}')")
    return config


def _phase_palette(args: argparse.Namespace, files: list[Path],
                   pack_config=None
                   ) -> tuple[dict[str, tuple[int, EncoderPalette, int]] | None,
                              dict[int, EncoderPalette],
                              bool]:
    """Resolve palette.  Returns (sprite_assignments, palettes, has_palette)."""
    palettes: dict[int, EncoderPalette] = {}
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None = None

    pal_path = args.pal or os.path.join(args.packed_dir, DEFAULT_PALETTE_FILENAME)
    has_palette = args.build_palette or os.path.exists(pal_path) \
        or pack_config is not None

    if not has_palette and (args.build_maps or args.build_ids):
        print("No palette found, skipping sprite packing (maps/ids only).")
        return None, palettes, False

    # !pack.txt replaces the auto median-cut grouping entirely: one palette per
    # block, sized exactly as the block declares. An already-built pal.png is
    # still reused unless --build-palette asks for a rebuild.
    if pack_config is not None and (args.build_palette
                                    or not os.path.exists(pal_path)):
        print("=== Building palettes from !pack.txt buckets ===")
        sprite_assignments, all_palette_data, _unmatched = build_config_palettes(
            [str(f) for f in files], pack_config,
            color_tolerance=args.color_tolerance,
        )
        os.makedirs(args.output_dir, exist_ok=True)
        pal_out = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
        save_palette_png([colors for colors, _ in all_palette_data],
                         pal_out, has_alpha=True)
        palettes = {i: EncoderPalette(colors, has_alpha=True)
                    for i, (colors, _sym) in enumerate(all_palette_data)}
        print()
        return sprite_assignments, palettes, True

    if args.build_palette:
        file_strs = [str(f) for f in files]

        if args.single_palette or args.target_colors:
            print("=== Auto-building single palette ===")
            auto_pal, _, auto_sym, auto_colors = build_auto_palette(
                file_strs,
                max_colors=args.max_colors,
                target_colors=args.target_colors,
                quality_threshold=args.quality_threshold,
            )
            pal_out = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
            save_palette_png(auto_colors, pal_out, has_alpha=True)
            palettes = {1: auto_pal}
            sprite_assignments = {
                f.stem: (1, auto_pal, auto_sym)
                for f in files
                if f.stem not in (PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME)
                and f.suffix.lower() == '.png'
            }
            print()
        else:
            print("=== Auto-building grouped palettes ===")
            sprite_assignments, all_palette_data = build_grouped_palettes(
                file_strs,
                max_colors=args.max_colors,
                quality_threshold=args.quality_threshold,
                pre_reduce=args.pre_reduce,
                color_tolerance=args.color_tolerance,
            )
            pal_out = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
            save_palette_png([colors for colors, _ in all_palette_data],
                             pal_out, has_alpha=True)
            palettes = {
                i + 1: EncoderPalette(colors, has_alpha=True)
                for i, (colors, _sym) in enumerate(all_palette_data)
            }
            print()
        return sprite_assignments, palettes, True

    # Load existing palette
    if not os.path.exists(pal_path):
        print(f"Error: palette not found: {pal_path}")
        print("  Use --build-palette to auto-generate one.")
        sys.exit(1)

    print(f"Loading palette from {pal_path}...")
    palettes, _raw = load_palette_for_encoding(pal_path)
    print(f"  Loaded {len(palettes)} palette(s)")
    for pidx, pal in palettes.items():
        print(f"    [{pidx}] {len(pal.colors)} colors, alpha={pal.has_alpha}")

    pal_dst = os.path.join(args.output_dir, DEFAULT_PALETTE_FILENAME)
    if os.path.abspath(pal_path) != os.path.abspath(pal_dst):
        shutil.copy2(pal_path, pal_dst)
        print(f"  Copied pal.png to {args.output_dir}/")

    return None, palettes, True


def _load_sprite_pivots_from_csvs(exported_dir: str
                                  ) -> dict[str, tuple[float, float]]:
    """Map png_name -> (pivot_x, pivot_y) extracted from every CSV.

    Reads the per-PSD CSV ``PivotX`` and ``PivotY`` columns (when present
    and non-empty). Empty values are skipped silently — sprites without
    a CSV pivot fall back to the default pivot computed from width and
    height inside :func:`build_header`.
    """
    sprite_pivots: dict[str, tuple[float, float]] = {}
    for csv_file in sorted(Path(exported_dir).glob('*.csv')):
        try:
            with open(csv_file, 'r') as f:
                reader = csv.reader(f)
                header_row = next(reader, None)
                if header_row is None:
                    continue
                col_names = [c.split()[-1] if ' ' in c else c for c in header_row]
                if 'PivotX' not in col_names or 'PivotY' not in col_names:
                    continue
                px_idx = col_names.index('PivotX')
                py_idx = col_names.index('PivotY')
                name_idx = col_names.index('Name')
                for row in reader:
                    if len(row) <= max(px_idx, py_idx, name_idx):
                        continue
                    raw_name = row[name_idx].strip('"')
                    try:
                        pvx = float(row[px_idx])
                        pvy = float(row[py_idx])
                    except (ValueError, IndexError):
                        continue
                    sprite_pivots[normalize_layer_name(raw_name)] = (pvx, pvy)
        except Exception:
            pass
    return sprite_pivots


def _load_sprite_pivot_rects_from_psls(
        exported_dir: str
) -> dict[str, tuple[int, int, tuple[int, int, int, int]]]:
    """Map png_name -> (layer_x, layer_y, pivot_rect) from the exported PSLs.

    ``psd.exe`` (and :func:`pack_psd.export_psd_file_python`) stores, per layer,
    the ``~pivot`` marker rect that overlaps it — falling back to the layer's
    own rect when no marker does. ``utils.exe`` turns that into the octBmp_t
    pivot; see :func:`pack_codec.compute_psd_marker_pivot`.

    Only Assets-mode PSLs are read: ``-map`` PSLs leave the pivot block zeroed,
    so a sprite listed in both (``ahover_00`` lives in ``ahover.psl`` and
    ``ahover_src.psl``) must keep the Assets record whatever order the files
    are visited in. Zero-area pivot blocks are dropped for the same reason.
    """
    rects: dict[str, tuple[int, int, tuple[int, int, int, int]]] = {}
    for psl_file in sorted(Path(exported_dir).glob('*.psl')):
        try:
            psl_type, records = parse_psl(str(psl_file))
        except Exception:
            continue
        if psl_type != PSL_TYPE_ASSET:
            continue
        for rec in records:
            name = rec['name']
            if not name:
                continue                      # marker layer: no exported PNG
            if rec['pivot_w'] <= 0 or rec['pivot_h'] <= 0:
                continue                      # no pivot information
            rects[name] = (
                rec['x'], rec['y'],
                (rec['pivot_x'], rec['pivot_y'],
                 rec['pivot_w'], rec['pivot_h']),
            )
    return rects


def _load_sprite_atlas_xy_from_csvs(exported_dir: str
                                    ) -> dict[str, tuple[int, int]]:
    """Map png_name → (atlas_x, atlas_y) extracted from every CSV.

    Atlas position is the sprite's top-left corner on the PSD canvas
    (columns ``X`` and ``Y`` of the per-PSD CSV). It is the input for
    pivot computation in the utils.exe-compatible scheme:
        pivot = -(atlas_xy * PIVOT_SCALE + PIVOT_HALFPIX)
    """
    atlas: dict[str, tuple[int, int]] = {}
    for csv_file in sorted(Path(exported_dir).glob('*.csv')):
        try:
            with open(csv_file, 'r') as f:
                reader = csv.reader(f)
                header_row = next(reader, None)
                if header_row is None:
                    continue
                col_names = [c.split()[-1] if ' ' in c else c for c in header_row]
                if 'X' not in col_names or 'Y' not in col_names \
                        or 'Name' not in col_names:
                    continue
                x_idx = col_names.index('X')
                y_idx = col_names.index('Y')
                name_idx = col_names.index('Name')
                for row in reader:
                    if len(row) <= max(x_idx, y_idx, name_idx):
                        continue
                    raw_name = row[name_idx].strip('"')
                    try:
                        ax = int(row[x_idx])
                        ay = int(row[y_idx])
                    except (ValueError, IndexError):
                        continue
                    atlas[normalize_layer_name(raw_name)] = (ax, ay)
        except Exception:
            pass
    return atlas


def _compute_map_skip_set(args: argparse.Namespace,
                          asset_names_set: set[str]) -> set[str]:
    """Sprite names that must be skipped because they are packed as maps."""
    if not (args.build_maps or args.build_ids):
        return set()

    mf = _map_filter_value(args)
    psl_cands = {p.stem for p in Path(args.exported_dir).glob('*.psl')}
    csv_cands = {p.stem for p in Path(args.exported_dir).glob('*.csv')}
    all_cands = psl_cands | csv_cands

    if isinstance(mf, list):
        skip = set(mf)
    elif mf == 'all':
        skip = all_cands
    else:
        skip = {n for n in all_cands
                if not n.startswith('font') and n not in asset_names_set}

    if skip:
        print(f"  Map names (will skip in sprite packing): "
              f"{', '.join(sorted(skip))}")
    return skip


def _phase_pack_sprites(
    args: argparse.Namespace,
    files: list[Path],
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None,
    palettes: dict[int, EncoderPalette],
    map_skip_names: set[str],
    sprite_pivots: dict[str, tuple[float, float]],
    has_palette: bool,
    sprite_pivot_rects: dict[str, tuple[int, int, tuple[int, int, int, int]]]
    | None = None,
    sprite_flags: dict[str, int] | None = None,
) -> int:
    """Pack every sprite PNG. Returns the number of per-sprite errors."""
    if sprite_pivot_rects is None:
        sprite_pivot_rects = {}
    if sprite_flags is None:
        sprite_flags = {}
    ok = skip = err = 0
    total_orig = total_packed = 0

    if not has_palette and not args.build_palette:
        return 0  # nothing to pack

    packable = [f for f in files
                if f.suffix.lower() == '.png'
                and f.stem != PALETTE_SPRITE_NAME
                and f.stem not in map_skip_names]
    if packable and not palettes:
        print(f"Error: no palette groups exist, but {len(packable)} PNG(s) "
              f"need packing from {args.exported_dir}/.")
        print("  --build-palette found no sprites to build a palette from "
              "(is the exported dir empty apart from the reserved 0.png?).")
        print("  NOTE: --export rebuilds the exported dir from --art-dir "
              "PSDs/FNTs and DELETES any pre-placed PNGs there. For sprites "
              "that are plain PNGs (no PSD), put them in --exported-dir and "
              "run WITHOUT --export.")
        sys.exit(1)

    for fpath in files:
        name = fpath.stem
        if name == PALETTE_SPRITE_NAME or name.endswith('.csv') or name.endswith('.psl'):
            skip += 1
            continue
        if name in map_skip_names:
            print(f"  [SKIP] {name}.png (map, will be packed by pack_maps)")
            skip += 1
            continue
        if fpath.suffix.lower() != '.png':
            skip += 1
            continue

        try:
            existing_packed = os.path.join(args.packed_dir, f"{name}.png")
            header_bytes = None
            if not args.no_reuse_headers and os.path.exists(existing_packed):
                header_bytes = read_existing_header(existing_packed)

            sym_override = None
            if sprite_assignments and name in sprite_assignments:
                pidx, palette, sym_override = sprite_assignments[name]
            elif header_bytes:
                pidx = header_bytes[HDR_OFF_PIDX]
                palette = palettes.get(pidx, next(iter(palettes.values())))
            else:
                # No !pack.txt bucket claimed this sprite (or there's no
                # !pack.txt at all) and no reusable header was found: it is
                # packed into palette group 0, or group 1 when its name
                # contains "font" -- not skipped. sym_override stays None,
                # so it gets the default 8-bit symbol bitness rather than
                # inheriting any bucket's reduced bitness.
                pidx = 1 if 'font' in name else 0
                palette = palettes.get(pidx, next(iter(palettes.values())))

            # Pivot precedence: CSV-provided per-sprite pivot wins, then the
            # placeholder sprite's hard-coded pivot, then the PSD ~pivot
            # marker rect carried by the exporter's PSL (utils.exe parity),
            # then build_header's default scheme. Re-use path
            # (header_bytes != None) ignores all of it and keeps the existing
            # pivot from the previous pack.
            pvx, pvy = sprite_pivots.get(name, (None, None))
            if name == PLACEHOLDER_SPRITE_NAME:
                pvx, pvy = PLACEHOLDER_SPRITE_PIVOT

            layer_x = layer_y = pivot_rect = None
            if pvx is None and name in sprite_pivot_rects:
                layer_x, layer_y, pivot_rect = sprite_pivot_rects[name]

            blob = pack_sprite(
                str(fpath), palette,
                header_bytes=header_bytes,
                pidx=pidx,
                flags=sprite_flags.get(name, int(SpriteFlag.ALPHA)),
                symbol_bitness_override=sym_override,
                pivot_x=pvx,
                pivot_y=pvy,
                layer_x=layer_x, layer_y=layer_y, pivot_rect=pivot_rect,
            )
            if blob is None:
                skip += 1
                continue

            packed_img = blob_to_packed_png(blob)
            out_path = os.path.join(args.output_dir, f"{name}.png")
            packed_img.save(out_path)

            compression = struct.unpack_from('<I', blob, HDR_OFF_COMPRESSION)[0]
            sym_bits = compression & 0xFF
            w, h_val = struct.unpack_from('<hh', blob, HDR_OFF_WIDTH)

            total_orig += len(Image.open(fpath).tobytes())
            total_packed += len(blob)

            mode = "reuse" if header_bytes else "new"
            print(f"  [OK] {name}.png ({w}x{h_val}, sym={sym_bits}bit, "
                  f"pal={pidx}, {len(blob)}B, header={mode})")
            ok += 1

        except Exception as e:
            import traceback
            print(f"  [ERR] {name}: {e}")
            traceback.print_exc()
            err += 1

    print(f"\nDone: {ok} packed, {skip} skipped, {err} errors")
    if total_orig > 0:
        ratio = total_packed / total_orig
        print(f"  Raw RGBA: {total_orig:,} bytes -> Packed: {total_packed:,} bytes "
              f"(ratio {ratio:.3f}x, saved {100*(1-ratio):.1f}%)")
    return err


class MapPhaseResult:
    """What the map/ids phase produced, for the beta emit that follows."""

    def __init__(self, map_names=(), legacy_bmp_names=None,
                 metadata_blocks=''):
        self.map_names = list(map_names)
        self.legacy_bmp_names = dict(legacy_bmp_names or {})
        self.metadata_blocks = metadata_blocks


def _phase_pack_maps(args: argparse.Namespace,
                     asset_names_set: set[str]) -> MapPhaseResult:
    """Pack PSD maps and optionally the legacy app_ids.h.

    Returns the packed map names (clean, without the map_ prefix) so later
    phases can tell map containers apart from sprite containers in
    --output-dir, the inverse legacy BMP index the beta emit needs to
    translate those maps' BmpIdx fields, and the $names/%types/&groups/#tags
    constants the beta ids header has to carry too.
    """
    if not (args.build_maps or args.build_ids):
        return MapPhaseResult()

    print("\n=== Building maps and/or app_ids.h ===")
    (map_names, bmp_index, sorted_names, name_map,
     type_map, group_map, tag_map) = pack_maps(
        args.exported_dir, args.packed_dir, args.output_dir,
        map_filter=_map_filter_value(args),
        asset_names=asset_names_set,
    )
    print(f"\n  Maps packed: {len(map_names)} ({', '.join(map_names)})")

    if args.build_ids:
        ids_path = args.ids_output or 'app_ids.h'
        ids_dir = os.path.dirname(ids_path)
        if ids_dir:
            os.makedirs(ids_dir, exist_ok=True)
        generate_app_ids_h(
            sorted_names, map_names,
            name_map, type_map, group_map, tag_map,
            ids_path, args.exported_dir,
        )

    return MapPhaseResult(
        map_names=map_names,
        legacy_bmp_names={idx: name for name, idx in bmp_index.items()},
        metadata_blocks=emit_index_blocks(name_map, type_map,
                                          group_map, tag_map),
    )


def _phase_emit_raw(args: argparse.Namespace) -> None:
    """Convert every freshly-packed output-dir/*.png into raw-dir/<stem>.raw.

    The Linux sim reads ``packed/*.raw`` byte-for-byte into the OctPack and
    DIEs if a file size is not a multiple of 4. A ``.raw`` file is simply the
    decoded RGBA bytes of the packed PNG container (``Image.tobytes()``), which
    — because the containers are single-pixel-high strips — is always W*4 bytes
    and therefore %4 == 0. This is NOT a renamed PNG: the PNG container's own
    on-disk size is not %4 and would crash the sim.
    """
    if not args.emit_raw:
        return

    raw_dir = args.raw_dir or args.packed_dir
    os.makedirs(raw_dir, exist_ok=True)
    print(f"\n=== Emitting .raw (decoded RGBA) to {raw_dir}/ ===")

    pngs = sorted(Path(args.output_dir).glob('*.png'))
    ok = bad = 0
    for png in pngs:
        raw_bytes = Image.open(png).convert('RGBA').tobytes()
        if len(raw_bytes) % 4 != 0:
            # Should be impossible for single-row strips, but never ship a
            # file that would DIE the sim.
            print(f"  [ERR] {png.name}: {len(raw_bytes)}B not %4 — skipped")
            bad += 1
            continue
        Path(raw_dir, png.stem + '.raw').write_bytes(raw_bytes)
        ok += 1

    print(f"  Wrote {ok} .raw file(s)" + (f", {bad} skipped (not %4)" if bad else ""))


def _encode_palette_icon(icon: Path, side: int
                         ) -> tuple[bytes, list[tuple[int, int]]]:
    """Quantize the launcher icon standalone through the pack_codec pipeline.

    Same geometry as the full-color path (to_rgb565): centre-crop to a
    square, LANCZOS-resize to side x side — but keeping RGBA so the PNG's
    transparency survives into palette index 0. The resized PNG is then run
    through the exact machinery every exported sprite uses
    (build_auto_palette -> pack_sprite), yielding a legacy palette-sprite
    blob plus the icon's own dedicated palette as (RGB565, alpha8) pairs —
    pack_sprite leaves OCT_FLAG_ALPHA set, so that pal is written in the
    spread format and the icon's antialiased rim survives.
    """
    import tempfile

    from pack_codec import rgba_to_rgb565
    with Image.open(icon) as img:
        img = img.convert('RGBA')
        w, h = img.size
        if w != h:
            edge = min(w, h)
            left, top = (w - edge) // 2, (h - edge) // 2
            img = img.crop((left, top, left + edge, top + edge))
        if img.size != (side, side):
            img = img.resize((side, side), Image.LANCZOS)
        with tempfile.TemporaryDirectory() as td:
            tmp_png = Path(td) / 'ico_idle.png'
            img.save(tmp_png)
            pal, _pal_size, sym, colors = build_auto_palette([str(tmp_png)])
            blob = pack_sprite(str(tmp_png), pal, symbol_bitness=sym)
    if blob is None:
        raise ValueError(f"palette icon {icon} produced no sprite blob")
    pal565 = [(0x0000, 0) if c[3] == 0
              else (rgba_to_rgb565(c[0], c[1], c[2]), c[3])
              for c in colors]
    return blob, pal565


def _phase_emit_beta(
    args: argparse.Namespace,
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None,
    palettes: dict[int, EncoderPalette],
    maps: MapPhaseResult,
) -> None:
    """Emit the beta (octavios dev) asset container into --beta-app-dir.

    Runs after the legacy outputs are all written; nothing here changes them.
    Palette-sprite payloads are taken from the freshly packed --output-dir
    containers, full-color manifest sprites are RAW565-encoded from their
    exported PNGs, palette groups become .pal assets, and index.bin pins the
    shared asset-id space (see pack_beta.emit_beta_layout).
    """
    if not args.beta_app_dir:
        return

    import pack_beta
    from pack_codec import rgba_to_rgb565

    app_dir = Path(args.beta_app_dir)
    app_name = args.app_name or app_dir.name
    print(f"\n=== Emitting beta container to {app_dir} ===")

    # Palette groups keyed by the Pidx values actually written into headers.
    # In the --build-palette grouped path those are the sprite_assignments'
    # 0-based group indices; in the load-pal.png path they are the dict keys
    # load_palette_for_encoding produced (same source the encoder used).
    # (rgb565, alpha8) per entry: the alpha channel is a full median-cut
    # dimension already (EncoderPalette holds RGBA), and pack_beta needs it to
    # write the spread .pal format for groups whose sprites carry
    # OCT_FLAG_ALPHA. Dropping it here is what used to flatten every
    # antialiased edge.
    def _to_565(pal: EncoderPalette) -> list[tuple[int, int]]:
        return [(0x0000, 0) if c[3] == 0
                else (rgba_to_rgb565(c[0], c[1], c[2]), c[3])
                for c in pal.colors]

    pal_groups: dict[int, list[tuple[int, int]]] = {}
    if sprite_assignments:
        for pidx, pal, _sym in sprite_assignments.values():
            pal_groups.setdefault(pidx, _to_565(pal))
    else:
        pal_groups = {pidx: _to_565(pal) for pidx, pal in palettes.items()}

    # Manifest full-color sprites bypass the palette codec entirely; manifest
    # palette sprites contribute their flag bits (fullsize/additive/bg) so
    # patch_palette_sprite can OR them into the beta header -- a PALETTE
    # sprite with flags.fullsize (tier 2) draws 1:1 exactly like a full-color
    # fullsize one, and keeps its index-0 transparency.
    def _manifest_flag_bits(s) -> int:
        return (pack_beta.OCT_FLAG_FULLSIZE if s.flags.fullsize else 0) \
             | (pack_beta.OCT_FLAG_ADDITIVE if s.flags.additive else 0) \
             | (pack_beta.OCT_FLAG_BG if s.flags.bg else 0)

    full_specs: list[tuple[str, Path, tuple[int, int], int, bool]] = []
    full_names: set[str] = set()
    palette_extra_flags: dict[str, int] = {}
    manifest = None
    if args.manifest:
        from manifest_schema import load_manifest
        manifest = load_manifest(args.manifest)
        for s in manifest.sprites:
            if s.color != 'full':
                palette_extra_flags[s.name] = _manifest_flag_bits(s)
                continue
            png = Path(args.exported_dir) / f'{s.name}.png'
            if not png.is_file():
                raise FileNotFoundError(
                    f"full-color sprite '{s.name}': {png} not found "
                    f"(generate/export assets first)")
            full_specs.append((s.name, png, s.size, _manifest_flag_bits(s),
                               s.dither))
            full_names.add(s.name)

    # Palette-sprite blobs = the packed containers just written to output-dir
    # (decoded strip bytes ARE the legacy octBmp_t + payload). pal.png, the
    # legacy 0 placeholder, map containers and full-color sprites are not
    # palette sprites. Without a manifest every extra_flags is 0, so the
    # legacy no-manifest output is byte-identical to before.
    map_names = maps.map_names
    skip = {PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME} \
        | set(map_names) | full_names
    palette_blobs: list[tuple[str, bytes, int]] = []
    psd_map_blobs: list[tuple[str, bytes]] = []
    for png in sorted(Path(args.output_dir).glob('*.png')):
        if png.stem in map_names:
            with Image.open(png) as img:
                psd_map_blobs.append((png.stem, img.convert('RGBA').tobytes()))
            continue
        if png.stem in skip or is_name_declaration(png.stem):
            continue
        with Image.open(png) as img:
            palette_blobs.append((png.stem, img.convert('RGBA').tobytes(),
                                  palette_extra_flags.get(png.stem, 0)))

    icon = Path(args.icon) if args.icon else None
    if icon is None:
        for cand in (Path(args.art_dir) / 'icon.png',
                     app_dir / 'icon.png',
                     app_dir / 'art' / 'icon.png'):
            if cand.is_file():
                icon = cand
                break

    # Resolve the icon art tier: CLI flags override the manifest icon object,
    # which overrides the defaults (full / 160 / no dither == the pre-tier
    # behaviour). The resolved combination is re-validated because CLI
    # overrides can produce combos no manifest ever held.
    from manifest_schema import Icon, validate_icon
    base_icon = manifest.icon if (manifest is not None
                                  and manifest.icon is not None) else Icon()
    icon_cfg = Icon(
        color=args.icon_color if args.icon_color is not None else base_icon.color,
        side=args.icon_side if args.icon_side is not None else base_icon.side,
        dither=args.icon_dither if args.icon_dither is not None else base_icon.dither,
    )
    icon_errors = validate_icon(icon_cfg)
    if icon_errors:
        for e in icon_errors:
            print(f"Error: {e}")
        sys.exit(1)

    # Cross-check manifest sounds against the mp3s actually present. Both
    # directions are non-fatal, but each gap gets a loud line: a missing mp3
    # means no KIND_SOUND record (SND_getAssetId returns -1 at runtime), a
    # stale mp3 gets packed even though the manifest no longer names it.
    if manifest is not None:
        snd_dir = app_dir / 'sound' / 'assets'
        mp3_names = {p.stem for p in snd_dir.glob('*.mp3')} \
            if snd_dir.is_dir() else set()
        manifest_sounds = {s.name for s in manifest.sounds}
        for name in sorted(manifest_sounds - mp3_names):
            print(f"  WARNING: manifest sound '{name}' has no "
                  f"{snd_dir / (name + '.mp3')} - the app gets no KIND_SOUND "
                  f"record for it and SND_getAssetId(\"{name}\") returns -1")
        for name in sorted(mp3_names - manifest_sounds):
            print(f"  WARNING: {snd_dir / (name + '.mp3')} has no matching "
                  f"manifest sound entry (stale file?) - it will still be "
                  f"packed as a KIND_SOUND record")

    icon_arg: Path | bytes | None = icon
    icon_palette = None
    if icon is not None and icon_cfg.color == 'palette':
        print(f"  Encoding palette icon ({icon_cfg.side}x{icon_cfg.side}, "
              f"own dedicated pal) from {icon}")
        icon_arg, icon_palette = _encode_palette_icon(icon, icon_cfg.side)

    records = pack_beta.emit_beta_layout(
        app_dir, app_name,
        palettes=pal_groups,
        palette_sprites=palette_blobs,
        full_sprites=full_specs,
        icon=icon_arg,
        icon_side=icon_cfg.side,
        icon_dither=icon_cfg.dither,
        icon_palette=icon_palette,
        psd_maps=psd_map_blobs,
        legacy_bmp_names=maps.legacy_bmp_names,
        metadata_blocks=maps.metadata_blocks,
        ids_path=args.beta_ids_output,
    )

    kinds = [k for k, _n in records]
    print(f"  {len(records)} asset records -> {app_dir / 'index.bin'}")
    print(f"    sprites={kinds.count(pack_beta.KIND_SPRITE)} "
          f"pals={kinds.count(pack_beta.KIND_PAL)} "
          f"maps={kinds.count(pack_beta.KIND_MAP)} "
          f"sounds={kinds.count(pack_beta.KIND_SOUND)}")
    if icon is None:
        print("  WARNING: no launcher icon found (--icon / icon.png) - the "
              "ico/ahover records were skipped, and the launcher needs them "
              "to install the app")
    ids_dest = Path(args.beta_ids_output) if args.beta_ids_output \
        else app_dir / 'src' / (app_name + '_ids.h')
    print(f"  ids header -> {ids_dest}")


def main() -> None:
    args = _build_arg_parser().parse_args()
    pack_bat = _resolve_pack_bat(args)
    asset_names_set = _resolve_asset_names(args)
    _resolve_map_filter(args, pack_bat)

    _phase_export(args, asset_names_set, pack_bat)

    files = [Path(f) for f in args.files] if args.files \
            else sorted(Path(args.exported_dir).glob('*.png'))
    # `$name` layers are NAME_ declarations, not artwork. The exporter no
    # longer writes them, but a committed art/exported/ from a real psd.exe
    # run can still hold them and CI packs committed exports as-is.
    decls = [f for f in files if is_name_declaration(f.stem)]
    if decls:
        print(f"  Ignoring {len(decls)} $name declaration PNG(s) in "
              f"{args.exported_dir}/ (NAME_ constants, not sprites)")
        files = [f for f in files if not is_name_declaration(f.stem)]
    os.makedirs(args.output_dir, exist_ok=True)

    pack_config = _resolve_pack_config(args, pack_bat)
    sprite_assignments, palettes, has_palette = _phase_palette(
        args, files, pack_config=pack_config)

    # Reserved placeholder: BMP_0 / BMP_none - must always exist in slot 0.
    # Guarantee 0.png in art_dir (auto-create if missing) and mirror it
    # into exported_dir if not already there.
    zero_art = _ensure_placeholder_sprite(args.art_dir)
    zero_exp = os.path.join(args.exported_dir, f'{PLACEHOLDER_SPRITE_NAME}.png')
    if not os.path.isfile(zero_exp):
        os.makedirs(args.exported_dir, exist_ok=True)
        shutil.copy2(zero_art, zero_exp)
        print(f"  Copied 0.png from {args.art_dir}/ to {args.exported_dir}/")

    map_skip_names = _compute_map_skip_set(args, asset_names_set)
    sprite_pivots = _load_sprite_pivots_from_csvs(args.exported_dir)
    if sprite_pivots:
        print(f"  Loaded pivot data for {len(sprite_pivots)} sprites from CSVs")

    sprite_pivot_rects = _load_sprite_pivot_rects_from_psls(args.exported_dir)
    if sprite_pivot_rects:
        print(f"  Loaded PSD pivot markers for {len(sprite_pivot_rects)} "
              f"sprites from PSLs")

    # !pack.txt decides the per-group flag byte (<FULLSIZE>/<BG>/<ADD>/... plus
    # the ALPHA bit, forced by <ALPHA>/<OPAQUE> or auto-detected from the
    # group's anti-aliasing). These must reach pack_sprite BEFORE the header is
    # built: FULLSIZE also halves the pivot scale.
    sprite_flags: dict[str, int] = {}
    if pack_config is not None:
        from packtxt import resolve_sprite_flags
        sprite_flags = resolve_sprite_flags(
            pack_config, args.exported_dir, [f.stem for f in files])
        n_full = sum(1 for v in sprite_flags.values()
                     if v & int(SpriteFlag.FULLSIZE))
        n_alpha = sum(1 for v in sprite_flags.values()
                      if v & int(SpriteFlag.ALPHA))
        print(f"  !pack.txt flags: {len(sprite_flags)} sprites "
              f"({n_alpha} ALPHA, {n_full} FULLSIZE)")

    sprite_errors = _phase_pack_sprites(
        args, files, sprite_assignments, palettes,
        map_skip_names, sprite_pivots, has_palette,
        sprite_pivot_rects=sprite_pivot_rects,
        sprite_flags=sprite_flags,
    )
    if sprite_errors:
        # A sprite that failed to pack means a missing .raw in the container;
        # never report success (exit 0) over an incomplete pack.
        print(f"Error: {sprite_errors} sprite(s) failed to pack (see [ERR] "
              f"lines above) - aborting before maps/ids/beta emit.")
        sys.exit(1)

    maps = _phase_pack_maps(args, asset_names_set)

    _phase_emit_raw(args)

    _phase_emit_beta(args, sprite_assignments, palettes, maps)

    if sprite_pivots:
        custom = [(n, px, py) for n, (px, py) in sprite_pivots.items()
                  if px is not None]
        if custom:
            print(f"\n=== Custom pivots ({len(custom)} sprites) ===")
            for name, px, py in sorted(custom):
                print(f"  {name:<30s} pivot=({px:.1f}, {py:.1f})")


if __name__ == "__main__":
    main()
