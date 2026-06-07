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
)

from pack_codec import (
    EncoderPalette,
    blob_to_packed_png,
    build_auto_palette,
    build_grouped_palettes,
    load_palette_for_encoding,
    pack_sprite,
    read_existing_header,
    save_palette_png,
)
from pack_psd import (
    _ensure_placeholder_sprite,
    export_psd,
    generate_app_ids_h,
    normalize_layer_name,
    pack_maps,
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


def _resolve_map_filter(args: argparse.Namespace) -> None:
    if args.map_filter is not None:
        return
    map_psds = sorted(Path(args.art_dir).glob(f'{MAP_FILENAME_PREFIX}*.psd'))
    if map_psds:
        args.map_filter = ','.join(p.stem for p in map_psds)
        print(f"  Auto-detected maps: {args.map_filter}")


def _phase_export(args: argparse.Namespace, asset_names_set: set[str]) -> None:
    if not args.export:
        return
    print("=== Exporting PSD/FNT layers (psd-tools) ===")
    mf = args.map_filter
    if mf is None or mf == 'auto':
        export_map_filter = None
    elif mf == 'all':
        export_map_filter = 'all'
    else:
        export_map_filter = [n.strip() for n in mf.split(',') if n.strip()]

    export_psd(
        art_dir=args.art_dir,
        exported_dir=args.exported_dir,
        map_filter=export_map_filter,
        asset_names=asset_names_set,
    )
    print()


def _phase_palette(args: argparse.Namespace, files: list[Path]
                   ) -> tuple[dict[str, tuple[int, EncoderPalette, int]] | None,
                              dict[int, EncoderPalette],
                              bool]:
    """Resolve palette.  Returns (sprite_assignments, palettes, has_palette)."""
    palettes: dict[int, EncoderPalette] = {}
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None = None

    pal_path = args.pal or os.path.join(args.packed_dir, DEFAULT_PALETTE_FILENAME)
    has_palette = args.build_palette or os.path.exists(pal_path)

    if not has_palette and (args.build_maps or args.build_ids):
        print("No palette found, skipping sprite packing (maps/ids only).")
        return None, palettes, False

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

    mf = args.map_filter or ''
    psl_cands = {p.stem for p in Path(args.exported_dir).glob('*.psl')}
    csv_cands = {p.stem for p in Path(args.exported_dir).glob('*.csv')}
    all_cands = psl_cands | csv_cands

    if ',' in mf:
        skip = {n.strip() for n in mf.split(',') if n.strip()}
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
) -> None:
    ok = skip = err = 0
    total_orig = total_packed = 0

    if not has_palette and not args.build_palette:
        return  # nothing to pack

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
                pidx = 1 if 'font' in name else 0
                palette = palettes.get(pidx, next(iter(palettes.values())))

            # Pivot precedence: CSV-provided per-sprite pivot wins,
            # placeholder sprite uses its hard-coded pivot, otherwise
            # build_header falls back to the default scheme. Re-use
            # path (header_bytes != None) ignores pvx/pvy and keeps the
            # existing pivot from the previous .ass.
            pvx, pvy = sprite_pivots.get(name, (None, None))
            if name == PLACEHOLDER_SPRITE_NAME:
                pvx, pvy = PLACEHOLDER_SPRITE_PIVOT

            blob = pack_sprite(
                str(fpath), palette,
                header_bytes=header_bytes,
                pidx=pidx,
                symbol_bitness_override=sym_override,
                pivot_x=pvx,
                pivot_y=pvy,
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


def _phase_pack_maps(args: argparse.Namespace,
                     asset_names_set: set[str]) -> None:
    if not (args.build_maps or args.build_ids):
        return

    print("\n=== Building maps and/or app_ids.h ===")
    mf = args.map_filter
    if mf is None or mf == 'auto':
        map_filter_val = None
    elif mf == 'all':
        map_filter_val = 'all'
    else:
        map_filter_val = [n.strip() for n in mf.split(',') if n.strip()]

    (map_names, _bmp_index, sorted_names, name_map,
     type_map, group_map, tag_map) = pack_maps(
        args.exported_dir, args.packed_dir, args.output_dir,
        map_filter=map_filter_val,
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


def main() -> None:
    args = _build_arg_parser().parse_args()
    asset_names_set = _resolve_asset_names(args)
    _resolve_map_filter(args)

    _phase_export(args, asset_names_set)

    files = [Path(f) for f in args.files] if args.files \
            else sorted(Path(args.exported_dir).glob('*.png'))
    os.makedirs(args.output_dir, exist_ok=True)

    sprite_assignments, palettes, has_palette = _phase_palette(args, files)

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

    _phase_pack_sprites(
        args, files, sprite_assignments, palettes,
        map_skip_names, sprite_pivots, has_palette,
    )

    _phase_pack_maps(args, asset_names_set)

    if sprite_pivots:
        custom = [(n, px, py) for n, (px, py) in sprite_pivots.items()
                  if px is not None]
        if custom:
            print(f"\n=== Custom pivots ({len(custom)} sprites) ===")
            for name, px, py in sorted(custom):
                print(f"  {name:<30s} pivot=({px:.1f}, {py:.1f})")


if __name__ == "__main__":
    main()
