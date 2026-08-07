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
    SpriteFlag,
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


def _phase_pack_maps(args: argparse.Namespace,
                     asset_names_set: set[str]) -> list[str]:
    """Pack PSD maps and optionally the legacy app_ids.h.

    Returns the packed map names (clean, without the map_ prefix) so later
    phases can tell map containers apart from sprite containers in
    --output-dir. Empty when the phase is skipped.
    """
    if not (args.build_maps or args.build_ids):
        return []

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

    return map_names


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


def _encode_palette_icon(icon: Path, side: int) -> tuple[bytes, list[int]]:
    """Quantize the launcher icon standalone through the pack_codec pipeline.

    Same geometry as the full-color path (to_rgb565): centre-crop to a
    square, LANCZOS-resize to side x side — but keeping RGBA so the PNG's
    transparency survives into palette index 0. The resized PNG is then run
    through the exact machinery every exported sprite uses
    (build_auto_palette -> pack_sprite), yielding a legacy palette-sprite
    blob plus the icon's own dedicated palette as RGB565 values.
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
    pal565 = [0x0000 if c[3] == 0 else rgba_to_rgb565(c[0], c[1], c[2])
              for c in colors]
    return blob, pal565


def _phase_emit_beta(
    args: argparse.Namespace,
    sprite_assignments: dict[str, tuple[int, EncoderPalette, int]] | None,
    palettes: dict[int, EncoderPalette],
    map_names: list[str],
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
    def _to_565(pal: EncoderPalette) -> list[int]:
        return [0x0000 if c[3] == 0 else rgba_to_rgb565(c[0], c[1], c[2])
                for c in pal.colors]

    pal_groups: dict[int, list[int]] = {}
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
    skip = {PALETTE_SPRITE_NAME, PLACEHOLDER_SPRITE_NAME} \
        | set(map_names) | full_names
    palette_blobs: list[tuple[str, bytes, int]] = []
    for png in sorted(Path(args.output_dir).glob('*.png')):
        if png.stem in skip:
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
    print(f"  ids header -> {app_dir / 'src' / (app_name + '_ids.h')}")


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

    sprite_pivot_rects = _load_sprite_pivot_rects_from_psls(args.exported_dir)
    if sprite_pivot_rects:
        print(f"  Loaded PSD pivot markers for {len(sprite_pivot_rects)} "
              f"sprites from PSLs")

    sprite_errors = _phase_pack_sprites(
        args, files, sprite_assignments, palettes,
        map_skip_names, sprite_pivots, has_palette,
        sprite_pivot_rects=sprite_pivot_rects,
    )
    if sprite_errors:
        # A sprite that failed to pack means a missing .raw in the container;
        # never report success (exit 0) over an incomplete pack.
        print(f"Error: {sprite_errors} sprite(s) failed to pack (see [ERR] "
              f"lines above) - aborting before maps/ids/beta emit.")
        sys.exit(1)

    map_names = _phase_pack_maps(args, asset_names_set)

    _phase_emit_raw(args)

    _phase_emit_beta(args, sprite_assignments, palettes, map_names)

    if sprite_pivots:
        custom = [(n, px, py) for n, (px, py) in sprite_pivots.items()
                  if px is not None]
        if custom:
            print(f"\n=== Custom pivots ({len(custom)} sprites) ===")
            for name, px, py in sorted(custom):
                print(f"  {name:<30s} pivot=({px:.1f}, {py:.1f})")


if __name__ == "__main__":
    main()
