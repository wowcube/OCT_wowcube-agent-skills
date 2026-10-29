# Packing the beta container

The AI manifest/PNG path packs with the plugin's python packer
(`scripts/build_pipeline.py pack` → `scripts/pack.py`): it understands the
manifest tiers (palette ×2, palette fullsize, full-colour fullsize + dither)
and reproduced a shipped game's pack byte for byte. The SDK's own `octpacker`
(`art/octpack.json` + `!pack.txt`) is the path for PSD-authored art by human
artists and builds the device `.oct` at Stage 5 (`wowcube-boilerplate`).

## Canonical command

From the project root:

```
python <skills>/scripts/build_pipeline.py pack --game <game> --workspace assets_<game> \
    --src-dir app_<game>/src --app-dir app_<game> --manifest plans/<game>_assets.json \
    --icon app_<game>/art/icon.png
```

| Step | What happens |
|---|---|
| completeness | **before anything is written**: every manifest sprite needs `assets_<game>/art/<name>.png`, every manifest sound an mp3 in `assets_<game>/wav/assets/` or `app_<game>/sound/assets/`; an incomplete set is refused with the missing names (a missing sound would not break the compile, it would just stay silent) |
| clean | the intermediates `assets_<game>/packed/` and `assets_<game>/exported/` are cleared first, so frames retired from the manifest cannot linger in the pack |
| fonts | `app_<game>/art/font_*.fnt` + their `_0.png` atlases are synced to `assets_<game>/fonts/` on every run (a changed `.fnt` or atlas is copied again, stale pages replaced; BMFont glyphs are packed only from there); afterwards the pack fails if the ids lack `font_` glyphs, since every `OCT_label_set` would draw nothing |
| icon | warns when `app_<game>/art/icon.png` is still the template icon and no `--icon` was given |
| sounds | `assets_<game>/wav/assets/*.mp3` → `app_<game>/sound/assets/` before pack.py scans the app |
| atlas | `build_psd.py` puts `assets_<game>/art/*.png` into a throw-away `assets_<game>/assets.psd` (no hand-authored PSD): every PNG there is packed, so PNGs of sprites no longer in the manifest are moved out first (e.g. to `assets_<game>/retired/`) |
| pack.py | `--export --build-palette --build-ids --emit-raw` + `--beta-app-dir app_<game> --app-name app_<game> --manifest ... --icon ...`: palettes with alpha, RAW565 for `color: "full"`, manifest flags (`fullsize`, `additive`, `bg`) into each header, the launcher `ico` map from the icon |
| outputs | `app_<game>/index.bin` (record index = asset id), `app_<game>/art/packed/*.raw` + `*.pal`, `app_<game>/src/app_<game>_ids.h` (`enum BMP/MAP/SND` + `BMP_<anim>` / `BMP_<anim>_end` aliases) |
| pivots | utils.exe-style centred pivots written into every manifest sprite's packed header |
| record | `app_<game>/.pack_inputs.json`: sha1 of the manifest, every input PNG and mp3, the fonts and the icon |

`--src-dir app_<game>/src` keeps one ids header (the app's); another folder
gets a copy.

## Is the pack current? (`pack-status`)

```
python <skills>/scripts/build_pipeline.py pack-status --game <game> --workspace assets_<game> \
    --app-dir app_<game> --manifest plans/<game>_assets.json
```

Exit 0 = `app_<game>/.pack_inputs.json` matches the current inputs and the pack outputs
are still the ones it wrote; 1 = stale or missing, with what changed (a redrawn PNG, a
rebuilt mp3, a font, the icon, the manifest, a touched output). It only reads files.
The completeness check and this record need the canonical command's `--manifest` and
`--app-dir`. The orchestrator's stage detection and Stage 5 use it:
any changed input means pack again (then the visual gate and a new device build).

## Tiers and quality

The tier table is in `templates/app_ai_template/API.md`; the manifest fields
in `technical_prompter` Step 4. The packer applies exactly what the manifest
says: `color: "full"` + `flags.fullsize` + `dither: true` is the
maximum-quality recipe (nearest-level RGB565 + Floyd–Steinberg + lossless
RLE, nothing else). Smoothing (`smooth_rows` in `pack_beta.py`) exists only
as an opt-in size tool for noisy video sources; never apply it by default or
in the name of quality.

The launcher icon's tier comes from the manifest `icon` object (default
full colour, 160×160); `pack.py --icon-color palette|full`, `--icon-side N`
and `--icon-dither` override it for one run. The default full-colour icon is
RAW565: no transparency, so the badge's transparent corners render black on the
dark launcher. Palette icons (120, drawn ×2, or 240, fullsize; nothing else) keep
the PNG's alpha as palette index 0: the PNG is resized to that side.

## Direct pack.py calls (rarely needed)

PNG-only, all sprites full colour (no palette work):

```
python <skills>/scripts/pack.py --build-ids --exported-dir <png-dir> \
    --beta-app-dir app_<game> --app-name app_<game> --manifest plans/<game>_assets.json --icon app_<game>/art/icon.png
```

PNG-only with palette sprites (PNGs already in an exported dir):

```
python <skills>/scripts/pack.py --build-palette --build-ids \
    --exported-dir <png-dir> --packed-dir <out> --output-dir <out> \
    --assets assets --ids-output <out>/ids.h \
    --beta-app-dir app_<game> --app-name app_<game> \
    --manifest plans/<game>_assets.json --icon app_<game>/art/icon.png
```

**Never add `--export` to a PNG-only call**: it rebuilds the exported dir from
PSD/FNT sources and deletes every pre-placed PNG first. `build_pipeline.py
pack` handles this itself.

## Troubleshooting

| Symptom | Action |
|---|---|
| `build_psd.py` failure | The failing file name is in stderr: inspect `assets_<game>/art/<name>.png`. |
| `pack.py` exit 1: `no palette groups exist, but N PNG(s) need packing` | `--export` ran on a PNG-only workflow and deleted the PNGs. Restore them (`ART process M`) and use `build_pipeline.py pack`. |
| Palette overflow | Pass `--target-colors 64` to `pack.py`. |
| Container noticeably bigger than an earlier build of the same art | Not a regression by itself: the palette builder keeps rare accent colours an older build averaged away. Check decoded-pixel fidelity before treating size as a bug. |
| Empty ids header | `assets_<game>/art/` held no PNGs when packing; list it. |
| Refused: incomplete set | The message names every missing PNG or mp3: draw or build them (or fix the manifest at Stage 2), then pack again. Never pack a partial set by hand. |
| An old frame or sprite still in `_ids.h` | Its PNG is still in `assets_<game>/art/`: move it out and pack again (the intermediates are rebuilt on every run). |
| `index.bin` missing | `--app-dir` was omitted: only legacy intermediates were written. Rerun with `--app-dir app_<game>`. |
| A sprite name longer than 23 characters | The manifest validator rejects it; rename in the manifest (Stage 2) and regenerate that sprite. |
| An opaque palette `bg` sprite renders magenta | Make it `color: "full"` + `"flags": {"alpha": false, "bg": true}`. |
| Sprites off centre by a pixel or two | The pack's pivot step needs `--manifest`; rerun with it. |
