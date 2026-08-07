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
| palette group vs golden, resolved via `index.bin`* | — | **450/450** | exact |
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

\* Not a direct byte read: byte 45 (`Pidx`) of a golden `art/packed/*.raw`
sprite header is a placeholder that is **1 for every sprite** in the shipped
dump, so it can't be compared straight against ours. The real group is only
recoverable by resolving each sprite's `index.bin` SPRITE record to the PAL
record it points at (`utils.exe`'s own `!pack.log` gives the same answer
independently, which is the next row and the cross-check).

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

### 5.5 Two extra exporter artefacts — *fixed in §10*

We exported `map_18_18.psd` (→ `map_18_18.csv`/`.psl`, packed as map `18_18`);
the corpus's `!pack.bat` never runs `psd.exe` on it, so golden had 9 CSV/PSL
pairs and we had 10. At the time legacy PSD maps were not emitted into the
beta container, so `index.bin` was unaffected and this was left alone.

**Superseded.** The third corpus (§10) made both halves matter: PSD maps *are*
emitted now, so an undeclared `map_*.psd` would become a ninth MAP record
get_started's legacy container does not have. `art/!pack.bat` is now read as
the authoritative export list, `map_18_18.psd` is not exported at all, and the
CSV/PSL count matches golden exactly.

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
always accepted them). Seven tests in `tests/test_palette_weights.py`.

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
> the `ci_build.py` change could not be committed here, and this build was run
> with the skills-repo `scripts/` staged next to `ci_build.py`.
>
> **Resolved in Task 5 Step 5.** `oct-builder/scripts` is now a verbatim
> ten-module snapshot of the repo's `scripts/` (`packtxt.py` included), and
> `ci_build.py` **imports** `sound_asset_name`/`sound_asset_name_problem` from
> `scripts/gen_sounds.py` rather than restating them, so the rule has one
> definition and one set of tests. Re-running the *real* `oct-builder/ci_build.py`
> against a freshly stripped corpus reproduces every number in this report:
> `index.bin`, `src/app_get_started_ids.h` and the 1,666,052-byte `.oct` are
> md5-identical, CRC32 `0x58C97A88`. The tree still needs its own repo and a
> commit from the devops owner — the edits exist only on this machine.

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

---

## 10. Third corpus: `OCT_ladybug` — `art/!pack.bat` as the source of truth

A second legacy app, packed with the same `psd.exe` + `utils.exe` toolchain,
broke the python packer in five distinct ways. Ground truth available: its
committed `index.bin` (**544 records: 493 sprite / 31 pal / 8 map / 12 sound**)
and `src/app_ids.h`. `art/packed/` and `art/exported/` are *not* committed
here, so per-sprite byte comparison against the legacy binaries — the strongest
evidence used in §3 — is not possible for this app; the checks below are
name-set, symbol-set and self-consistency instead.

### 10.1 The five gaps

| # | symptom | root cause | fix |
|---|---|---|---|
| 1 | **crash**: `ValueError: asset name '$label_you' yields 'BMP_$label_you'` | 26 map-PSD layers named `$score!font2` (2×2 text anchors) were exported as sprites. Legacy: zero `$` names in `index.bin`, `NAME_score` in `app_ids.h` | `pack_psd.is_name_declaration` — a leading `$` marks a NAME_ declaration; no PNG, no BMP index entry, and its place gets `BmpIdx = 0` + the `Name` byte |
| 2 | 1 map detected, legacy has 8 | none of ladybug's eight `-map` PSDs carries the `map_` prefix or a reserved launcher name | read `art/!pack.bat` (`packbat.py`): it lists the `psd.exe … -map` runs literally |
| 3 | 0 sound records, legacy has 12 | the app commits ready mp3s in `sound/` **root**, not `sound/assets/`, and has no WAVs | `gen_sounds.plan_mp3_adoption` + `ci_build`: pre-encoded root mp3s are copied (never re-encoded) under normalised names, collisions fatal |
| 4 | wrote `src/app_ladybug_ids.h`, app compiles `src/app_ids.h` | the ids name was derived from the `*.target` marker; `!pack.bat` sets `app=app` | `packbat.resolve_ids_header`: the `#include "…_ids.h"` in `src/` wins, then `!pack.bat`'s `utils.exe` argument, then the target name |
| 5 | picked `!pack.txt` (16 buckets) | `!pack.bat` generates `!pack_pal.txt` (32 buckets) with the app's own `pack_palettes.py` and feeds *that* to `utils.exe`; `!pack.txt` is only the `--lock` seed | `pack._declared_pack_config`: use the file `utils.exe` is actually given. The app's script is never run; if its output was not committed we say so and fall back |

Two more were uncovered while proving the above:

* **PSD maps were not emitted into the beta container at all** (their `BmpIdx`
  fields are legacy enum indices). Without them ladybug cannot reach 8 MAP
  records. `pack_beta.remap_map_bmp_ids` rewrites every 28-byte `octPlace_t`'s
  `BmpIdx` from the legacy alphabetical index to the record's beta asset id.
* **`APP_*` defines need not live in `src/app.h`.** ladybug keeps
  `APP_GUID1`/`APP_VERSION`/`APP_TITLE`/`APP_CATEGORIES` in `src/config.h`, and
  every `.oct` build died with `no APP_GUID1`. `read_app_defines` now follows
  the app's own quoted `#include`s.

### 10.2 The launcher-map rule

`ico`/`ahover` are synthesised from `art/icon.png` so an AI-generated app with
no `ico.psd` still installs. ladybug ships its own `ico.psd` and no
`ahover.psd`, and its legacy container has exactly one launcher map among the
eight. The rule is therefore: **an app that declares its own `-map` PSDs
decides which reserved launcher maps exist** (ladybug → `ico` only,
get_started → `ico` + `ahover`, an app with no map PSDs → both). Their
*payloads* still come from `art/icon.png`, so `ico` keeps its low,
launcher-visible asset id (33 here) instead of drifting past `EXT_MAX_DESCS`
with the scene maps.

### 10.3 `TAG_` constants were a counter, not a bitmask

The generated `#tags` block emitted `const uint8_t TAG_health3 = 3;`. The
committed legacy header has `const uint32_t TAG_health3 = 4;` — the app ORs
these into `octObject_t.Tags` and tests with `&`, so the index form silently
makes `TAG_health3` alias `TAG_health1|TAG_health2`. Fixed to `1 << (i-1)` /
`uint32_t`, and the `_last` sentinel is now emitted only for `%types`, which is
what both committed headers show. The `Tags` word of each `octPlace_t` is
populated too, recovered from the per-PSD CSV (the PSL layout mirrored from
`psd.exe` has slots for `&group` and `%type` but none for `$name`/`#tag`).

### 10.4 Measured

| check | legacy | ours | |
|---|---|---|---|
| `index.bin` records | 544 | **544** | exact |
| sprite / pal / map / sound | 493 / 31 / 8 / 12 | **493 / 31 / 8 / 12** | exact |
| MAP record names | 8 | **8** | identical set |
| SOUND record names | 12 | **12** | identical set |
| PAL record names | 31 | **31** | identical set |
| SPRITE record names | 493 | 493 | one swap: ours has `ico_idle`, legacy has `0` (§5.1/§5.2, pre-existing) |
| `BMP_`/`MAP_`/`SND_` symbols | 537 / 9 / 13 | 538 / 9 / 13 | **0 missing** (the extra is `BMP_ico_idle`) |
| `NAME_`/`TYPE_`/`GROUP_`/`TAG_` | 26 / 12 / 2 / 4 | 26 / 12 / 2 / 4 | **0 missing, 0 value or type mismatches** |
| sprite header vs `!pack_pal.txt` | — | 20/20 sample | flags, palette group and symbol bitness all agree with the declared bucket; 0 sprites unmatched by the config |
| map `BmpIdx` after remap | — | 8/8 maps | no place points outside the container; `hud` carries 18 `Name` anchors and 24 `Tags` hearts |
| ARM build | — | **links clean** | 17,823 B; the app's own `src/` compiles against the regenerated `src/app_ids.h` — the strongest symbol-agreement evidence available |
| `.oct` | — | 996,607 B | CRC32 `0x3F126024`, ARM tail byte-identical |

### 10.5 Regressions

* `OCT_get_started`, staged fresh from `git ls-files`: **511 records**
  (452/46/2/11), 0 missing symbols, `.oct` 1,669,784 B verified.
* `app_gbhotel` (full-colour, `oct-builder/_smoke`): `.oct` **byte-identical**
  at 2,650,632 B, SHA-256 `FC3AFBA3…0BA2`.

### 10.6 Still unmatched

* **`index.bin` ordering** (§5.3) — unchanged and still not a defect.
* **`ico_idle` vs `0`** (§5.1/§5.2) — unchanged; the one record-name
  difference, in both legacy corpora.
* **Per-sprite bytes for ladybug are unverified against the legacy binaries**,
  because the app commits neither `art/packed/` nor `art/exported/` and no
  `!pack.log`. The sprite headers are cross-checked against the app's own
  `!pack_pal.txt` declaration instead. *(Superseded for the 282 font glyphs by
  §11, which compares them against a shipped legacy `.oct`.)*
* **`copy /Y` post-steps in `!pack.bat` are not honoured.** get_started's batch
  copies `qr_code_transparent.png` over the exported `qr_code.png`; that case
  is covered by the `art/overrides/` convention (§4.1), but the batch line
  itself is parsed and ignored. An app using `copy` without an `overrides/`
  dir would ship the PSD layer instead.

---

## 11. Font glyphs are font metrics, not sprites

Hardware feedback on the freshly built `OCT_ladybug`: **all text collapsed**,
every glyph drawn on top of the previous one. Every font glyph descriptor
carried the sprite default pivot `(w-0.5, h-0.5)` and `Bw = 0`.

### 11.1 What the engine actually reads

`oct_scene.h::OCT_label_set` lays a label out straight off each glyph's
`octBmp_t` — the sizes were never the problem, the layout fields were:

```c
if (bmp->Flags & OCT_FLAG_FULLSIZE) zoom = 1;   // every glyph is FULLSIZE
...
cy -= bmp->Bh;                                   // newline
bmpidx = OCT_FONT_glyph(label->Label, code);
// PivotX is the left bearing, not part of the advance.
// Doubled to cancel the renderer's -PivotX shift.
int i = OCT_add(label->Layer, ..., cx + 2 * bmp->PivotX, cy, ...);
cx += zoom * bmp->Bw;                            // pen advance
...
cx += zoom * (bmp->W - bmp->Bw);                 // caret at end of last char
```

So **`Bw` is the advance, `Bh` the line height, `PivotX` the left bearing** and
`PivotY` the lift off the baseline. With the sprite default every glyph anchors
at its own bottom-right corner and `cx` never moves. `Bx`/`By`, `Number`,
`Group`, `Type` and `Tags` play no part; `Rate` is `1`, which `build_header`
already defaults to.

### 11.2 The formula, derived from the corpus

Pairing all 282 font descriptors of the shipped legacy
`app_ladybug.oct` with `OCT_ladybug/art/font_{1,2,3}.fnt`:

```
PivotX = xoffset
PivotY = base - yoffset          (base from the BMFont `common` block)
Bw     = xadvance
Bh     = lineHeight
Bx = By = 0
W, H   = the glyph's atlas w, h
```

**Residual: zero on all 282 glyphs**, across three fonts
(base 31/24/17, lineHeight 45/35/25) and the full sign range of `xoffset`
(-2 … +1). The values are *not* multiplied by the FULLSIZE draw zoom: the
engine applies `zoom` itself and reads `zoom = 1` off the FULLSIZE bit.

### 11.3 The carrier: a type-3 font PSL

`psd.exe <font>.fnt` writes a PSL of type **3** (not 1) whose records hold the
BMFont metrics. Recovered from a legacy-toolchain `font_1.psl`
(`rogue_escape_vibe/assets/exported/`) and now reproduced exactly:

| offset | field |
|---|---|
| 0 | `name[24]` — `font_N_000CC` |
| 24 | atlas `x, y, w, h` (int32 ×4) |
| 40 – 75 | zero (a glyph has no layer mark, no `~sideN`, no `~pivot` rect) |
| 76 | `xadvance` (int32) → `Bw` |
| 80 | `lineHeight` (int32) → `Bh` |
| 112 | `PivotX` (float) |
| 116 | `PivotY` (float) |
| 120 | rate slot, the literal string `letter` |

Record count is the printable, non-empty glyph set — **94** for a 95-char
font, `space` having no bitmap.

The previous writer emitted type 1 with `DEFAULT_LAYER_MARK` at 40 and a
hardcoded `1` at what the post-`1a50c1a` convention calls the `~sideN` marker
*width*; nothing downstream could read a pivot out of it, so `pack.py` fell
through to `compute_default_pivot`. That stale-convention bug and the collapsed
text were the same bug.

### 11.4 Measured

| check | result |
|---|---|
| font PSL vs legacy `psd.exe` output (rogue_escape, 3 fonts) | **byte-identical**, 197,448 B, 0 differing bytes |
| glyph pivots vs shipped `app_ladybug.oct` | **282 / 282 exact** |
| `Bx By Bw Bh W H Flags Kind Number Group Type Rate Tags Seq` | **282 / 282 exact** |
| `Pidx`, `Compression` | differ on all 282 — *and on 209 / 106 of the 259 non-font records*: the §5.3 record-ordering difference (our palette `1` is asset id 1, legacy's is 5) and the global `DEFAULT_OFFSET_BITNESS = 7` vs utils.exe's per-sprite 4/5. Symbol bitness agrees (4-bit). Pre-existing, unrelated to fonts |
| container | 544 records, 493 / 31 / 8 / 12, `.oct` 996,607 B |

### 11.5 Regressions

* `OCT_get_started`, staged fresh from `git ls-files`: **511 records**
  (452/46/2/11), `.oct` **1,669,784 B** — unchanged. Its `!pack.bat` declares
  `0 font(s)`: it commits the `.fnt` files but never packs them.
* `app_gbhotel` (full-colour, `oct-builder/_smoke`): `.oct` **byte-identical**
  at 2,650,632 B, SHA-256 `FC3AFBA3…0BA2`.
