# Legacy corpus parity report — full-python build vs `psd.exe` + `utils.exe`

**Task 4 of** `docs/superpowers/plans/2026-08-05-part3-python-parity.md`.
**Reference corpus:** `OCT_get_started` (read-only; all work on a scratch copy).
**Date of measurement:** 2026-08-07, branch `part3-python-parity`.

**Verification is byte-level against the reference toolchain's own output. No
simulator was involved** — the owner removed the simulator smoke from this task
(and from the rest of this plan): getting the simulator out of the build and
verification path is the point of the workstream. The corpus gives strictly
stronger evidence for free — `utils.exe`'s own `art/!pack.log`, the shipped
`art/packed/*.raw` + `*.pal` bytes, the shipped `index.bin`, the shipped
`sound/assets/*.mp3` — so every claim below is a byte or pixel comparison
against one of those. (Task 3's one simulator run was a one-off to prove the
`.pal` alpha-format hypothesis and is already done.)

---

## 1. What was built, and from what

Step 1 reconstructed the true fresh-clone state: every file `git ls-files`
reports in the corpus (54 files) copied to a scratch dir, then the generated
artefacts stripped — `art/exported/`, `art/packed/`, `sound/assets/`,
`index.bin`, `src/app_get_started_ids.h`, `art/app_get_started_ids.h`, `out/`,
`bin/`. What remains is 9 PSDs, `art/!pack.txt`, `art/!pack_pal.txt`, three
`.fnt` + atlases, `art/0.png`, `art/icon.png`, the QR PNGs, `src/*.h` (5
headers) and 11 WAVs.

Step 2 built it with one command, entirely in python:

```
python oct-builder/ci_build.py --app-dir app_get_started --octavios <sdk>
```

| stage | tool | result |
|---|---|---|
| sounds | ffmpeg via `ci_build.prepare_sounds` | 11 WAV → 11 beta mp3 |
| export | `pack_psd.export_all_python` (psd-tools) | 451 PNGs, 10 CSVs, 10 PSLs |
| pack | `pack.py` + `packtxt.py` + `pack_codec.py` | 46 palettes, 451 sprites, 3 maps |
| container | `pack_beta.emit_beta_layout` | `index.bin` 511 records, `art/packed/*.{raw,pal}`, `src/app_get_started_ids.h` |
| ARM | cmake + ninja + arm-none-eabi | `out/app_get_started.bin`, 10,964 B |
| `.oct` | `pack_beta.py --build-oct` | 1,666,052 B |
| verify | `ci_build.verify_oct` | pass |

`.oct` structural verification (Step 3's third leg), read back off disk:

```
title      : 'Get started'          version : 259  (APP_VER(0,1,3))
guid1      : 0xCFE9FD70E105890A     categories : 0x00000018     format : 4
assets     : 511 descriptors @ 232
ARM code   : 10964 bytes @ 1655088   <- byte-identical to out/app_get_started.bin
total size : 1666052 bytes, CRC32 0x58C97A88 recomputed OK
```

---

## 2. Headline numbers

| metric | golden (`utils.exe`) | ours (python) | verdict |
|---|---|---|---|
| `index.bin` records | 511 | **511** | count exact |
| record kinds | 452 SPRITE / 46 PAL / 2 MAP / 11 SOUND | **identical** | exact |
| record *names* | — | 510/511 identical | 1 differs (§4.2) |
| sprites compared (present in both) | 450 | 450 | — |
| palette group vs golden `.raw` | — | **450/450** | exact |
| palette group vs `!pack.log` | — | **450/450** | exact |
| symbol bit depth vs golden `.raw` | — | **450/450** | exact |
| symbol bit depth vs `!pack.log` | — | **450/450** | exact |
| flags byte vs golden `.raw` | — | **450/450** | exact |
| flags byte vs `!pack.log` | — | 449/450 | 1 expected (§4.3) |
| packed pivots (float pair) vs golden | — | **450/450** | exact |
| sprite W×H vs golden | — | **450/450** | exact |
| `Rate` byte vs golden | — | **450/450** | exact |
| `Seq` chain presence vs golden | — | **450/450** | exact |
| exporter CSV/PSL bytes | 9 CSV + 9 PSL | **18/18 byte-identical** | exact |
| `sound/assets/*.mp3` bytes | 11 | **11/11 byte-identical** | exact |
| total `.pal` bytes | 18,036 | **18,036** | exact |
| total `.raw` bytes | 1,273,900 | 1,442,372 | **+13.2 %** |
| container (`raw`+`pal`+`index.bin`) | 1,306,248 | 1,474,720 | **+12.90 %** |
| decoded-pixel MAE vs source art (mean) | 5.33 / 255 | 6.16 / 255 | ours 16 % worse |

Every structural field the engine reads out of a sprite header now matches the
reference toolchain exactly. The two remaining gaps are **container size**
(§5) and **quantiser quality** (§6), both in the payload, neither structural.

---

## 3. Per-sprite sample (26 sprites)

Decoded through the same decoder for both packs; `=` means "identical to
golden". `premul MAE` is the mean absolute error of the **premultiplied** RGB
(0..255) — premultiplying is what makes the number meaningful, because raw RGB
under `alpha == 0` is undefined (palette index 0 decodes to black, the source
PNG keeps the layer colour). `src:` gives each packer's own quantisation error
against the exported source PNG — lower is closer to the artwork.

The corpus has **no font sprites** to sample: `art/font_{1,2,3}.fnt` + atlases
are committed but neither toolchain packs them (no `art/fonts/` dir, no font
bucket in `!pack.txt`, no font record in the golden `index.bin`) and the app
draws text with the engine's built-in fonts via `OCT_add_label`. The
pre-rendered text sheets (`t_*`, `cubetext_*`) are sampled in their place.

| sprite | category | W x H | pal grp | bits | flags | pivot | .raw bytes | premul MAE |
|---|---|---|---|---|---|---|---|---|
| `t_wow` | text glyph sheet (2-bit) | 110x43 = | 40 = | 2 = | 0x01 = | 113.5,41.5 = | 696 / 668 (-28) | 13.45 (src: ours 10.92 / golden 9.59) |
| `t_welcome` | text glyph sheet (7-bit) | 106x33 = | 36 = | 7 = | 0x01 = | 105.5,32.5 = | 2016 / 2400 (+384) | 1.45 (src: ours 1.38 / golden 2.10) |
| `t_selectcube_1` | text glyph sheet (7-bit) | 86x18 = | 26 = | 7 = | 0x01 = | 85.5,17.5 = | 1088 / 1136 (+48) | 1.59 (src: ours 1.73 / golden 2.81) |
| `cubetext_xl_00` | text glyph sheet (4-bit) | 84x80 = | 1 = | 4 = | 0x00 = | 83.5,79.5 = | 1288 / 1480 (+192) | 10.84 (src: ours 8.72 / golden 7.05) |
| `cubetext_hi_00` | text glyph sheet (4-bit) | 82x76 = | 2 = | 7 = | 0x00 = | 81.5,75.5 = | 3076 / 3200 (+124) | 5.14 (src: ours 5.80 / golden 4.72) |
| `selector_00` | ALPHA, antialiased | 120x120 = | 10 = | 4 = | 0x01 = | 119.5,119.5 = | 2648 / 3128 (+480) | 3.41 (src: ours 4.08 / golden 2.47) |
| `ic_twist_00` | ALPHA, antialiased | 37x36 = | 19 = | 8 = | 0x00 = | 35.5,35.5 = | 404 / 420 (+16) | 8.42 (src: ours 10.73 / golden 7.31) |
| `arrow_point_00` | ALPHA, antialiased | 27x22 = | 13 = | 4 = | 0x01 = | 27.5,21.5 = | 228 / 224 (-4) | 0.60 (src: ours 0.92 / golden 0.96) |
| `qr_code` | ALPHA, hard-edged (QR) | 120x120 = | 45 = | 4 = | 0x01 = | 119.5,119.5 = | 2216 / 2180 (-36) | **0.00** (src: ours 0.00 / golden 0.00) |
| `main_bg_00` | OPAQUE group | 120x120 = | 8 = | 4 = | 0x00 = | 120.5,120.5 = | 4712 / 4912 (+200) | 10.05 (src: ours 9.61 / golden 7.18) |
| `eyes_bg` | OPAQUE group | 121x121 = | 16 = | 2 = | 0x00 = | 120.5,120.5 = | 904 / 900 (-4) | **0.00** (src: ours 0.00 / golden 0.00) |
| `selectcube_00` | FULLSIZE | 113x105 = | 4 = | 8 = | 0x03 = | 55.5,52.5 = | 4140 / 6032 (+1892) | 3.72 (src: ours 2.42 / golden 3.59) |
| `selectcube_orange_00` | FULLSIZE | 113x105 = | 5 = | 8 = | 0x03 = | 56.5,52.5 = | 4372 / 6508 (+2136) | 3.30 (src: ours 2.00 / golden 3.07) |
| `selectcube_transit_00` | FULLSIZE | 6x6 = | 15 = | 4 = | 0x00 = | 5.5,5.5 = | 84 / 80 (-4) | 42.43 (src: ours 31.66 / golden 17.28) |
| `ico_get_started` | FULLSIZE (icon art) | 144x145 = | 44 = | 6 = | 0x02 = | 72.5,80.5 = | 4892 / 6912 (+2020) | 2.33 (src: ours 2.12 / golden 2.11) |
| `ahover_00` | FULLSIZE (icon art) | 144x145 = | 43 = | 6 = | 0x02 = | 72.5,80.5 = | 4892 / 6912 (+2020) | 2.33 (src: ours 2.12 / golden 2.11) |
| `transit_w_new_07` | animation frame | 120x120 = | 14 = | 4 = | 0x01 = | 119.5,119.5 = | 1956 / 2192 (+236) | 1.98 (src: ours 1.52 / golden 1.62) |
| `transit_w_new_18` | animation frame | 31x31 = | 14 = | 4 = | 0x01 = | 119.5,-58.5 = | 256 / 300 (+44) | 2.51 (src: ours 1.80 / golden 2.45) |
| `arrow_blue_01` | animation frame | 54x40 = | 11 = | 4 = | 0x01 = | 53.5,-18.5 = | 492 / 480 (-12) | 10.60 (src: ours 10.27 / golden 5.48) |
| `arrow_orange_17` | animation frame | 54x40 = | 12 = | 4 = | 0x01 = | 53.5,-18.5 = | 576 / 444 (-132) | 14.04 (src: ours 12.36 / golden 5.74) |
| `eyesblink_01` | animation frame | 120x120 = | 17 = | 2 = | 0x00 = | 119.5,119.5 = | 988 / 896 (-92) | 0.67 (src: ours 1.64 / golden 1.69) |
| `eyes_idle` | animation frame | 120x120 = | 17 = | 2 = | 0x00 = | 119.5,119.5 = | 1016 / 936 (-80) | 0.69 (src: ours 1.81 / golden 1.90) |
| `halftwist_ball_12` | animation frame | 120x120 = | 42 = | 6 = | 0x01 = | 119.5,119.5 = | 3108 / 3640 (+532) | 6.99 (src: ours 7.36 / golden 8.56) |
| `ic_qr_00` | animation frame | 37x45 = | 19 = | 8 = | 0x00 = | 35.5,35.5 = | 632 / 792 (+160) | 28.79 (src: ours 21.57 / golden 13.72) |
| `main_bg_29` | large background | 120x120 = | 8 = | 4 = | 0x00 = | 120.5,120.5 = | 4728 / 5076 (+348) | 8.63 (src: ours 7.09 / golden 6.40) |
| `bg_orange_s_21` | largest sprite | 120x120 = | 7 = | 4 = | 0x00 = | 119.5,119.5 = | 5848 / 5820 (-28) | 9.54 (src: ours 9.07 / golden 8.29) |

Every one of the 26 agrees exactly on size, palette group, bit depth, flags and
pivot. Whole-corpus pixel distribution (n = 450):

| premul MAE ours-vs-golden | sprites |
|---|---|
| exactly 0 | 5 |
| ≤ 2 | 89 |
| ≤ 5 | 186 |
| ≤ 10 | 376 |
| > 20 | 5 (`ic_pat_00`, `ic_pat_01`, `ic_qr_00`, `ic_qr_01`, `selectcube_transit_00`) |

mean 6.40, median 6.36, p95 13.43, max 42.43.
Against the source art, ours is the closer of the two packs on **154/450**
sprites.

---

## 4. The two `!pack.bat` post-steps, and how they are handled now

The artist's `art/!pack.bat` does two things after the exe runs that a naive
python build silently skips. Both are now expressed as **app-owned data**, not
as packer special cases.

### 4.1 `copy qr_code_transparent.png → exported/qr_code.png` → `art/overrides/`

Measured first, then designed: `assets.psd` *does* contain a `qr_code` layer,
and our exporter reproduces it faithfully — but it is not the artwork the app
ships. The `.bat` overwrites it with `qr_code_transparent.png` after the export
(`qr_code_darkcard.png` is the unpacked alternative). Golden
`art/exported/qr_code.png` is pixel-identical to `qr_code_transparent.png`;
our PSD-exported version differs by **mean abs error 146/255**. Nothing
structural notices — the pack succeeds, the size is right, the wrong picture
ships.

**Convention adopted:** `<art-dir>/overrides/*.png` are copied over
`art/exported/` immediately after the export, by filename
(`pack._apply_export_overrides`). A file that matches no exported sprite is
added as a new sprite. The packer knows nothing about QR codes; the rule is
"committed art wins over a PSD layer", which is the same principle
`ci_build.py` already applies to a committed `art/exported/`.

*Why here and not in `ci_build.py`:* the override has to land between export
and pack, and `pack.py --export` is the only thing that owns that seam —
putting it in the CI driver would leave `repack_app.py` and any direct
`pack.py` user silently wrong.

**App-repo migration:** `git mv art/qr_code_transparent.png
art/overrides/qr_code.png`. Seven tests in `tests/test_export_overrides.py`.

### 4.2 `python qr_setalpha.py` → `<ALPHA>` in `!pack.txt`

`qr_setalpha.py` does three things to the packed output: sets `OCT_FLAG_ALPHA`
on `qr_code.raw`, writes a centre pivot, and rewrites that palette into the
spread format. Its own docstring explains why: a QR is deliberately hard-edged,
so `utils.exe`'s anti-aliasing detector never fires.

But `utils.exe` already has a declarative override for exactly this — the
`<ALPHA>` tag (Task 2 pinned its semantics: force bit 0x01 on). Adding one line
to the app's `art/!pack.txt`

```
16
<ALPHA>
qr_code*
```

makes our packer set the flag (`packtxt.resolve_sprite_flags`) and, because
Task 3 tied the two together, emit the spread `.pal` automatically. The pivot
part of the script is a no-op for `qr_code` — it inherits a correct pivot from
its PSD layer, which we reproduce exactly (`119.5, 119.5`, matching golden).

**Result:** `qr_code` now matches the golden shipped bytes on flags, pivot,
palette format and **decoded pixels (MAE 0.00)** — with **zero packer changes**
and no post-pack hook at all. The legacy `.bat` would also stop needing the
python step, since `utils.exe` honours the same tag.

*Rejected alternatives:* a `post_pack.py` hook convention (a general-purpose
"run arbitrary code over the packed bytes" escape hatch is a worse contract
than a declarative tag, and would have to be replicated in every driver); a
manifest/pack-config extension (`!pack.txt` is `utils.exe`'s format — extending
it breaks the legacy tool, and the tag we need already exists).

---

## 5. Deviations from golden, with root causes

### 5.1 The reserved `0` placeholder — investigated, our behaviour is correct

Golden `index.bin` carries **two** empty-ish sprite records: `zero` at id 0
(48 all-zero bytes) and `0` at id 4 (the real 10×1 `art/0.png`, 68 bytes). Ours
carries only `zero`, and emits `BMP_0 = 0` in the ids header as an alias.

How the engine consumes it (`octavios/engine/oct_pack.h`) settles it:

```c
const octBmp_t* OCT_BMP_get(uint32_t bmp_idx)
    { if (bmp_idx == 0 || bmp_idx >= OctAssetsCount)  return &OctBmpZero; ... }

const void* OCT_PACK_getSprite(uint32_t id)
    { if (id == 0) return &OctBmpZero;   //Built-in placeholder ... }
```

Slot 0 is a **built-in** empty bitmap; the container's record at index 0 is
never dereferenced through the asset table. The separate `0` record exists only
because the legacy `app_ids.h` enumerated exported PNGs and `0.png` happened to
be one of them. In the beta id space it is a 68-byte asset nothing can reach,
and `BMP_0` aliased to 0 gives any app that uses it as a "clear" sentinel
exactly the built-in empty bitmap. Verified against this app's sources: the 94
`BMP_`/`MAP_`/`SND_` symbols they reference are all defined by our generated
header, and `BMP_0` is not among them.

**No fix needed.** The record count matches anyway (511 = 511) because our
container adds a synthesised `ico_idle` in its place (§5.2).

### 5.2 Launcher icon: `ico_idle` (ours) vs `ico_get_started` (golden)

Golden points its `ico`/`ahover` maps at `ico_get_started`, the 144×145 sprite
exported from `ico_sprite.psd`. `emit_beta_layout` instead synthesises an
`ico_idle` record from `art/icon.png` (160×160, committed) and points the two
reserved maps at that. Both sources are committed, both give the launcher a
valid icon within the first `EXT_MAX_DESCS` descriptors, and
`ico_get_started`/`ahover_00` are still present as ordinary sprites (packed
byte-for-byte structurally identical to golden). This is a pre-existing design
choice of the beta emitter, not a Task 4 regression — recorded here because it
is the one record-name difference in the whole container.

### 5.3 `index.bin` record *ordering* differs

Golden interleaves sounds alphabetically among the sprites (`congratulations_007`
is id 160, `wrongaction` id 510) and hoists the icon's palette to id 1; ours
groups the id space (palettes, icon assets, sprites, then sounds). The ids
header is generated from our own ordering, so every `BMP_`/`MAP_`/`SND_` symbol
the app compiles against is self-consistent. Asset ids are not an ABI across
packs — the header ships with the container. Not a defect; noted so nobody
diffs the two files expecting equality.

### 5.4 `qr_code` flags vs `!pack.log` (449/450)

`!pack.log` records what `utils.exe` decided (`flags:00`); the shipped
`art/packed/qr_code.raw` has `0x01` because `qr_setalpha.py` ran afterwards.
We match the **shipped bytes** (450/450) and therefore differ from the raw log
by exactly this one sprite. This is the expected and desired direction.

### 5.5 Two extra exporter artefacts

We export `map_18_18.psd` (→ `map_18_18.csv`/`.psl`, packed as map `18_18`);
the corpus's `!pack.bat` never runs `psd.exe` on it, so golden has 9 CSV/PSL
pairs and we have 10. Legacy PSD maps are not emitted into the beta container,
so `index.bin` is unaffected. The extra files are inert build products in a
gitignored directory. Left alone: refusing to export a committed `map_*.psd`
would be a stranger rule than exporting it.

---

## 6. Container size: **+12.90 %**, over the plan's ±10 % target

This is a real miss against the plan's success table, and it is a **deliberate
trade** made during this task. Both halves are measured.

**What happened.** The first full-python build came in at **−5.66 %** — inside
the target — but decoded-pixel comparison showed why: `pack_codec`'s two
group-palette builders called `median_cut([(c, 1) for c in colors], n)`, giving
**every unique colour weight 1 regardless of how many pixels use it**. That is
not a median cut. The corpus's `eyes*` bucket (41 sprites sharing a 4-colour
palette) is a solid black field with a white eye: 14,400 black pixels counted
exactly as much as one stray antialiased pixel, so both black and white fell
out and the entire eyes animation packed as three shades of the background
purple — premultiplied MAE **58/255** against the source art (golden: 1.9).
Flat art compresses well, which is precisely why the wrong pack was *smaller*.

**Fix.** `extract_per_sprite_color_counts()` now returns pixel counts,
`pool_color_weights()` sums them per group, and both `build_config_palettes`
and `build_grouped_palettes` pass real weights to `median_cut` (which has
always accepted them). Nine tests in `tests/test_palette_weights.py`.

**Cost/benefit, measured:**

| | unweighted (before) | weighted (now) | golden |
|---|---|---|---|
| container vs golden | −5.66 % | **+12.90 %** | — |
| mean premul MAE vs source art | 15.0 | **6.16** | 5.33 |
| `eyes*` bucket MAE | ~58 | ~1.7 | ~1.9 |

A better-fitting palette maps a smooth gradient onto more distinct indices, so
runs get shorter and the RLE payload grows. `utils.exe` gets both — better
fidelity *and* smaller output — so a real quantiser gap remains; it is not a
tuning preference. The growth is concentrated: palette groups 4 and 5
(`selectcube_*`/`selectcube_orange_*`, 24 sprites each, 256 colours, smooth 3D
renders) are +38 % and +28 % and account for 70 KB of the 168 KB.

**Recommendation:** accept +12.9 % for now — correct artwork beats a size
target that was set as a sanity bound before pixel fidelity was measured at all
— and open a follow-up on the quantiser (spatially-coherent palette selection,
and the alpha channel's weight relative to RGB inside the median cut, which is
also where the remaining `ic_pat_*`/`ic_qr_*` error lives: their MAE is
*entirely* alpha error).

## 7. Remaining quantiser gap (fidelity)

Mean premultiplied MAE against the source art: **ours 6.16 vs golden 5.33**;
ours is closer on 154/450 sprites. Five sprites exceed MAE 20 vs golden:

| sprite | MAE | root cause |
|---|---|---|
| `selectcube_transit_00` | 42.4 | 6×6 sprite, 36 pixels, in a 16-colour group shared with its 6 larger siblings — a handful of pixel decisions dominate the average |
| `ic_qr_00`, `ic_qr_01` | 28.8, 21.3 | 256-colour group; the error is **100 % alpha** (rgbMAE == alphaMAE), i.e. the alpha channel's weight inside the 4-D median cut |
| `ic_pat_00`, `ic_pat_01` | 20.8, 23.3 | same group, same cause |

No structural field is affected — palette group, bit depth, flags and pivots
are exact for all five.

---

## 8. Changes this task made

**Packer (`scripts/`)** — the plan said "integration only"; these three were
each forced by a *measured wrong output*, not by convenience:

| file | change | why |
|---|---|---|
| `pack.py` | `_apply_export_overrides()` + call in `_phase_export` | §4.1 — otherwise the wrong QR artwork ships |
| `pack.py`, `config.py` | `_resolve_map_filter` also treats `ico.psd`/`ahover.psd` as maps (`RESERVED_MAP_NAMES`) | see below |
| `pack_codec.py` | population-weighted median cut | §6 |
| `pack_beta.py` | `APP_VER(x,y,z)` macro expansion in `read_app_defines` | see below |

*Map auto-detection.* `_resolve_map_filter` only recognised the `map_` filename
prefix, but the corpus's `!pack.bat` runs `psd.exe -map` on `ico.psd` and
`ahover.psd`. Exported in Assets mode instead, they wrote PNGs whose layer
names collide with real sprites — `ahover.psd` holds a 74×67 placement
thumbnail called `ahover_00`, and it silently overwrote the 144×145 sprite from
`ahover_src.psd` (same for `ico_get_started`). The engine looks the `ico` map
up **by name** (`oct_shell.h`: `OCT_external_map(guid1, guid2, "ico")`), so
those two names are maps by contract, not by convention. With the fix, all 18
CSV/PSL artefacts are byte-identical to golden and both sprites pack at the
right size. Seven tests in `tests/test_map_detection.py`.

*`APP_VER`.* `pack_beta.read_app_defines` could not evaluate
`#define APP_VERSION APP_VER(0, 1, 3)` and the `.oct` step died with
`unknown token 'APP_VER 0, 1, 3'`. The fix existed only in the
`oct-builder/scripts` snapshot; it is now upstreamed (function-like macro
expansion + an AST whitelist of C integer operators) with ten tests in
`tests/test_app_defines.py`. **This completes Task 5 Step 3 early.**

**CI driver (`oct-builder/ci_build.py`)** — sound asset names. The build died
at the first stage on `Congratulations-007.wav` (`SND_Congratulations-007` is
not a C identifier). `sound_asset_name()` now normalises a WAV *source* name on
encode — lowercase, non-`[a-z0-9_]` → `_`, leading digit prefixed `s_` — which
reproduces the names the legacy toolchain shipped exactly, and collisions are a
hard error. A *committed* `.mp3` with an illegal name stays a hard error
(renaming it would shift every asset id the app already ships). All **11
encoded mp3s are byte-identical to golden**, `wrongaction` included. **This is
Task 5 Step 2's normalisation rule, in the one place Task 4 needed it;** Task 5
still owns making `gen_sounds.py` agree and adding its tests.

> `oct-builder/` lives outside this repo and is not under version control, so
> the `ci_build.py` change could not be committed here. Task 5 Step 5 re-syncs
> that tree; until then, the current `oct-builder/scripts` snapshot is stale
> (it predates Tasks 1–3 and has no `packtxt.py`), and this build was run with
> the skills-repo `scripts/` staged next to `ci_build.py`.

**App-repo migration** (applied to the scratch copy; the corpus was never
touched):

```
git mv art/qr_code_transparent.png art/overrides/qr_code.png
# art/!pack.txt: add <ALPHA> to the qr_code* block
git rm art/qr_setalpha.py          # both of its jobs are now declarative
```

---

## 9. Verdict against the plan's success criteria

| criterion | target | measured |
|---|---|---|
| Packed pivots vs golden | 450/450 exact | **450/450** |
| Sprite flags vs golden | 451/451 exact | **450/450** vs the shipped bytes — the 450 sprite records both packs carry. Golden's other two are `zero` (all-zero header, we write it byte-identically) and `0` (not emitted, §5.1) |
| `.pal` format vs golden | 451/451 agreement | 46/46 groups, total `.pal` bytes exact |
| Antialiased alpha preserved | verified | Task 3; here `qr_code` and `eyes_bg` decode at MAE 0.00 |
| Total packed size vs golden | within ±10 % | **+12.90 % — MISS**, deliberate (§6) |
| Legacy corpus builds fully in python | yes, `.oct` verified | **yes** — one command, CRC + ARM tail verified |
| Simulator smoke | *removed by owner* | n/a — byte-level verification instead |

Test suite: **400 passed**, up from the 369 baseline — +7
`test_export_overrides.py`, +7 `test_map_detection.py`, +10
`test_app_defines.py`, +7 `test_palette_weights.py`. Nothing removed, nothing
skipped, no test weakened.
