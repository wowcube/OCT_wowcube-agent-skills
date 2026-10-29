# WowCube Beta Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adapt the OCT_wowcube-agent-skills pipeline to the octavios BETA engine: beta-native asset container (`index.bin` + `.raw`/`.pal` assets), full-color RGB565 (2-byte/texel) sprite support, the full mandatory `app.h` define set, and the beta callback set (7 handlers).

**Architecture:** The pipeline keeps its existing stages (GDD → prompts → AI assets → code → package) and its pure-Python packing direction (PR #23). We add a *beta container layer* (`scripts/pack_beta.py`) that emits what the beta simulator actually loads: per-asset `art/packed/<name>.raw` files (48-byte `octBmp_t` header + payload), per-group `.pal` palette assets, a kind-tagged `index.bin` manifest in the app root, launcher icon MAP assets, and a single-id-space `_ids.h`. Full-color sprites use the RAW565 codec (plain or per-row RLE) ported from the reference implementation `../app_hulk/app_hulk/art/videopack.py`; palette sprites reuse the existing `pack_codec.py` quantizer/encoder, byte-verified against golden files produced by the real beta `utils.exe` (in `../app_hulk/app_hulk/art/packed/`).

**Tech Stack:** Python 3.12 (Pillow, numpy), PowerShell/bash scaffold scripts, ffmpeg (sound encoding), arm-none-eabi-gcc + CMake/Ninja (device), MSVC (Windows sim).

**Workspace layout** (everything sits in `C:\Users\igort\Desktop\wowcube_vibecode\beta transition\`):

```
beta transition/
├── OCT_wowcube-agent-skills/   # THIS repo, branch beta-transition (work here)
├── octavios/                   # beta engine, dev branch (reference, read-only)
└── app_hulk/app_hulk/          # beta example app + golden packed assets (read-only)
```

**Beta facts this plan is built on** (verified against `octavios` dev and `app_hulk`):

1. The beta simulator loads an app **only** through `<APP_DIR>/index.bin`: `int32 count`, then `count` records of `{int32 kind; char name[24]}` (28 bytes each). Record index **is** the runtime asset id. Missing file ⇒ sim dies with "Can't open index.bin". (`octavios/sim/src/sim.h:194-202`)
2. Asset kinds: `0=SPRITE`, `1=SOUND`, `2=PAL`, `3=MAP` — one shared id space (`octavios/engine/oct_pack.h:10`). Payload files: sprites/maps → `art/packed/<name>.raw`, palettes → `art/packed/<name>.pal`, sounds → `sound/assets/<name>.mp3` (22050 Hz mono CBR 32k).
3. A sprite `.raw` = 48-byte `octBmp_t` + payload. Confirmed by parsing golden `app_hulk/art/packed/ahover_00.raw`: `Pidx=8` (pal asset id), `Seq=11` (next-frame asset id), `Compression=0x706` (SymbolBitness=6, OffsetBitness=7 — the exact codec `scripts/pack_codec.py` already implements), `W=74,H=67`. A map `.raw` = `{int32 version; int32 count; octPlace_t[count]}` (28-byte places).
4. A `.pal` = 4 bytes per color: the RGB565 value stored **twice** as consecutive uint16 (golden `5.pal` = 64 colors = 256 bytes, starts `0000 0000 dfff dfff …`). Index 0 is the transparent index.
5. Full-color sprites: `octBmp_t.Flags` bit `OCT_FLAG_RAW565 (1<<7)`, payload = RGB565 texels; `Compression` field reused as sub-format `0=PLAIN`, `1=RLE` (per-row RLE with a uint16 row-length table). **No transparency** — 0x0000 is opaque black (`octavios/tests/test_render_raw565.cpp`). Reference encoder: `../app_hulk/app_hulk/art/videopack.py` (`to_rgb565`, `smooth_rows`, `rle_encode`, `rle_decode`, `build_bmp_header`).
6. Sprites render at **2× upscale** unless `OCT_FLAG_FULLSIZE (1<<1)` is set (`octavios/engine/oct_render.h:965`). So the existing ½-resolution authoring rule **stays** for normal sprites; full-color FULLSIZE art is authored at native size (up to 240×240).
7. Mandatory/expected `src/app.h` defines: `APP_VERSION`, `APP_TITLE`, `APP_DIR`, `APP_GUID1`, `APP_CATEGORIES`, `APP_COLORS` (see `app_hulk/src/app.h`; sim consumes them at `octavios/sim/src/sim.h:46-57,205-240`). The template currently defines only `APP_VERSION` + `APP_DIR`.
8. Beta callbacks an app **must define** (module link fails otherwise, `octavios/apps/src/app_module.cpp:27-45`): `on_init()`, `on_tick()`, `on_pretwisted(int32_t)`, `on_twisted(int32_t, uint32_t)`, **`on_tap(int32_t tapid, int32_t count)`** (two args — beta added `count`), **`on_shake(int32_t)`** (new; engine currently always runs the system default, but the symbol must exist), plus `on_proc_draw(...)` gated by `#define APP_HAS_PROC_DRAW`.
9. The launcher pulls two MAP assets from every installable pack: `ico` (resting icon) and `ahover` (hover animation), which must sit within the first 512 descriptors (`octavios/engine/oct_pack.h:17-19`, `videopack.py build_icon_assets`).
10. `SND_getAssetId(name)` strips a trailing `.mp3`/`.wav` and scans KIND_SOUND descriptors by name — sounds must be listed in `index.bin` or lookups return -1.

---

### Task 1: Full mandatory define set in the template `app.h`

**Files:**
- Modify: `templates/app_ai_template/src/app.h`

- [ ] **Step 1: Replace the file content**

```c
#pragma once
#include "app_ai_template.h"
#define APP_VERSION 100 //v1.00
#define APP_TITLE "app_ai_template"
#define APP_DIR "..\\..\\app_ai_template"
#define APP_GUID1 0x0000000000000000ULL
//APP_CATEGORY_GAME     - plain app/game (default)
//APP_CATEGORY_LAUNCHER - autoruns as the cube's HOME screen (see octavios/app_template/src/app.h)
#define APP_CATEGORIES (APP_CATEGORY_GAME)
#define APP_COLORS 0x00000000
```

Note: `app_ai_template` tokens are substituted by the scaffolder; `APP_GUID1` placeholder `0x0000000000000000ULL` is replaced with a random value in Task 2.

- [ ] **Step 2: Commit**

```bash
git add templates/app_ai_template/src/app.h
git commit -m "feat(template): full beta define set in app.h (TITLE, GUID1, CATEGORIES, COLORS)"
```

### Task 2: Scaffolder guarantees all six defines + a random GUID

**Files:**
- Modify: `scripts/new_app.ps1` (section "4. Guarantee APP_VERSION in app.h", around lines 134-146)
- Modify: `scripts/new_app.sh` (the equivalent section)

- [ ] **Step 1: Replace the APP_VERSION-only guarantee in `new_app.ps1`**

Replace the current block with a loop that guarantees every define and randomizes the GUID:

```powershell
# --- 4. Guarantee the full beta define set in app.h ------------------------
$appH = Join-Path $AppDir 'src\app.h'
if (-not (Test-Path $appH)) { Fail "missing src/app.h after scaffold" }
$appHraw = Get-Content $appH -Raw

# Random non-zero 64-bit GUID for this app
$bytes = [byte[]]::new(8)
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$guid = '0x{0:X16}ULL' -f [System.BitConverter]::ToUInt64($bytes, 0)

# Replace the template's zero GUID placeholder if present
if ($appHraw -match '0x0000000000000000ULL') {
    $appHraw = $appHraw -replace '0x0000000000000000ULL', $guid
    Step "Set APP_GUID1 = $guid"
}

$required = [ordered]@{
    'APP_VERSION'    = '#define APP_VERSION 100 //v1.00'
    'APP_TITLE'      = "#define APP_TITLE `"$app`""
    'APP_GUID1'      = "#define APP_GUID1 $guid"
    'APP_CATEGORIES' = '#define APP_CATEGORIES (APP_CATEGORY_GAME)'
    'APP_COLORS'     = '#define APP_COLORS 0x00000000'
}
$missing = $required.Keys | Where-Object { $appHraw -notmatch "define\s+$_" }
if ($missing) {
    Step "Adding missing defines to src/app.h: $($missing -join ', ')"
    $lines = $appHraw -split "`r?`n"
    $out = foreach ($l in $lines) {
        $l
        if ($l -match '^\s*#include\s+"app_') {
            foreach ($k in $missing) { $required[$k] }
        }
    }
    $appHraw = $out -join "`r`n"
}
Set-Content -Path $appH -Value $appHraw -Encoding UTF8
```

- [ ] **Step 2: Mirror the same logic in `new_app.sh`** (bash: `openssl rand -hex 8` or `head -c8 /dev/urandom | od -An -tx8` for the GUID; `grep -q "define APP_TITLE"` per key; insert after the `#include "app_` line with `awk`).

```bash
guid="0x$(od -An -tx8 -N8 /dev/urandom | tr -d ' ' | tr 'a-f' 'A-F')ULL"
sed -i "s/0x0000000000000000ULL/${guid}/" "$app_h"
ensure_define() { # $1=name $2=full line
    grep -q "define[[:space:]]\+$1" "$app_h" || \
        sed -i "/#include \"app_/a $2" "$app_h"
}
ensure_define APP_VERSION    '#define APP_VERSION 100 //v1.00'
ensure_define APP_TITLE      "#define APP_TITLE \"${app}\""
ensure_define APP_GUID1      "#define APP_GUID1 ${guid}"
ensure_define APP_CATEGORIES '#define APP_CATEGORIES (APP_CATEGORY_GAME)'
ensure_define APP_COLORS     '#define APP_COLORS 0x00000000'
```

- [ ] **Step 3: Smoke-test the PowerShell path** — run the scaffolder against a throwaway dir (or dot-source and call the block on a copy of the template `app.h`) and confirm the six defines are present and the GUID is non-zero. Delete the throwaway.

- [ ] **Step 4: Commit**

```bash
git add scripts/new_app.ps1 scripts/new_app.sh
git commit -m "feat(scaffold): guarantee all six beta app.h defines, randomize APP_GUID1"
```

### Task 3: Beta callback set in the template game header

**Files:**
- Modify: `templates/app_ai_template/src/app_ai_template.h` (handlers at lines ~722-857, instructional text at line ~40)

- [ ] **Step 1: Fix `on_tap` signature** at line ~783:

```c
OCT_CALLBACK void on_tap(int32_t tapid, int32_t count) {
    // on_tap is called when the user taps on a plane.
    // tapid  - the plane index (0..5) that was tapped
    // count  - tap-series counter: 1 for a single tap, 2 for the second tap
    //          in a quick series (within 500 ms), and so on
    (void)tapid; (void)count;
```

Keep the existing body/instructional comments below, adding `(void)count;` so `-Werror` builds stay clean when the body ignores it.

- [ ] **Step 2: Add the two new handlers after `on_tick`** (before the closing instructional sections):

```c
OCT_CALLBACK void on_shake(int32_t shakeid) {
    // on_shake fires when the cube is shaken. NOTE: in the current beta the
    // engine always runs the system default (animated go-home) and does NOT
    // route shakes here — but the symbol MUST exist or the ARM module fails
    // to link (octavios/apps/src/app_module.cpp references it).
    (void)shakeid;
}


//Enable the APP_HAS_PROC_DRAW define (top of this file) to use procedural sprites
OCT_CALLBACK void on_proc_draw(uint16_t* back, int idx, float x, float y, int angle, int vid, int reserved) {
    // Per-pixel procedural drawing callback. Only bound when APP_HAS_PROC_DRAW
    // is defined; keep the stub otherwise.
    (void)back; (void)idx; (void)x; (void)y; (void)angle; (void)vid; (void)reserved;
}
```

- [ ] **Step 3: Add the gate define comment near the top of the file** (next to the other config defines, ~line 10):

```c
//When defined, binds the per-pixel procedural callback (on_proc_draw) in both
//the simulator and the ARM module
///#define APP_HAS_PROC_DRAW
```

- [ ] **Step 4: Update the instructional text** at line ~40 from "…(on_init, on_tap, on_twisted, on_pretwisted) …" to name all seven: `on_init, on_tick, on_tap, on_twisted, on_pretwisted, on_shake, on_proc_draw` and state that the first six are mandatory and `on_proc_draw` must exist as a stub.

- [ ] **Step 5: Commit**

```bash
git add templates/app_ai_template/src/app_ai_template.h
git commit -m "feat(template): beta callbacks - on_tap(tapid,count), on_shake, on_proc_draw"
```

### Task 4: Fix the code skeleton `src/app_structure_example.h`

**Files:**
- Modify: `src/app_structure_example.h`

- [ ] **Step 1: Apply these fixes**
  - Line 5: `#include "app_test_ids.h"` → `#include "app_ai_template_ids.h"` with a comment `// renamed to app_<game>_ids.h by the scaffolder token pass`.
  - Lines 7-8: delete `APP_PNG`/`APP_SND` defines entirely — the beta engine reads assets via `index.bin`, these defines are dead.
  - Line 65: `on_tap(int32_t tapid)` → `on_tap(int32_t tapid, int32_t count)`.
  - After `on_tick` add the same `on_shake` + `on_proc_draw` stubs as Task 3 Step 2 (identical code).

- [ ] **Step 2: Commit**

```bash
git add src/app_structure_example.h
git commit -m "fix(skeleton): beta callbacks, real ids include, drop dead APP_PNG/APP_SND"
```

### Task 5: Golden-reference test harness for the beta container

**Files:**
- Create: `tests/golden/` — copy from `../app_hulk/app_hulk/`: `art/packed/ahover_00.raw`, `art/packed/ahover.raw`, `art/packed/5.pal`, `index.bin` (28 760 bytes)
- Create: `tests/test_beta_container.py`

- [ ] **Step 1: Copy the four golden files** (they are small; `index.bin` is 28 KB).

- [ ] **Step 2: Write the failing tests** — they import `scripts.pack_beta`, which does not exist yet:

```python
import struct
from pathlib import Path
import pytest
from scripts import pack_beta

GOLDEN = Path(__file__).parent / "golden"

def test_index_bin_roundtrip():
    records = pack_beta.read_index_bin(GOLDEN / "index.bin")
    assert len(records) == 1027
    assert records[0] == (pack_beta.KIND_SPRITE, "zero")
    assert records[1] == (pack_beta.KIND_PAL, "5")
    assert records[2] == (pack_beta.KIND_MAP, "ico")
    blob = pack_beta.build_index_bin(records)
    assert blob == (GOLDEN / "index.bin").read_bytes()

def test_bmp_header_parse_golden():
    hdr = pack_beta.parse_bmp_header((GOLDEN / "ahover_00.raw").read_bytes())
    assert (hdr.pidx, hdr.seq, hdr.w, hdr.h) == (8, 11, 74, 67)
    assert hdr.compression == 0x706  # SymbolBitness=6, OffsetBitness=7

def test_bmp_header_build_is_48_bytes():
    blob = pack_beta.build_bmp_header(w=74, h=67, flags=0, pidx=8, seq=11,
                                      compression=0x706, pivot=(73.5, 65.5), rate=1)
    assert len(blob) == 48
    hdr = pack_beta.parse_bmp_header(blob)
    assert (hdr.pidx, hdr.seq, hdr.w, hdr.h, hdr.compression) == (8, 11, 74, 67, 0x706)

def test_pal_roundtrip_golden():
    colors = pack_beta.read_pal(GOLDEN / "5.pal")
    assert len(colors) == 64
    assert colors[0] == 0x0000          # index 0 = transparent
    assert pack_beta.build_pal(colors) == (GOLDEN / "5.pal").read_bytes()

def test_map_raw_golden():
    blob = (GOLDEN / "ahover.raw").read_bytes()
    version, count = struct.unpack_from("<ii", blob, 0)
    assert (version, count, len(blob)) == (1, 1, 36)
```

- [ ] **Step 3: Run and verify failure**: `python -m pytest tests/test_beta_container.py -v` → FAIL with `ImportError` / `ModuleNotFoundError: pack_beta`.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/golden tests/test_beta_container.py
git commit -m "test: golden beta-container fixtures from app_hulk (index.bin, .raw, .pal)"
```

### Task 6: `scripts/pack_beta.py` — beta container primitives

**Files:**
- Create: `scripts/pack_beta.py`

- [ ] **Step 1: Implement the primitives the Task 5 tests demand**

```python
"""Beta (octavios dev) asset-container primitives.

The beta simulator loads an app from:
  <APP_DIR>/index.bin                  - kind-tagged asset manifest; record index == asset id
  <APP_DIR>/art/packed/<name>.raw      - sprites (48B octBmp_t + payload) and maps
  <APP_DIR>/art/packed/<name>.pal      - palettes (4 bytes per color: RGB565 twice)
  <APP_DIR>/sound/assets/<name>.mp3    - sounds (22050 Hz mono CBR 32k)

Struct layouts mirror octavios/engine/oct_types.h + oct_pack.h and are pinned
by tests/test_beta_container.py against golden files packed by the real beta
utils.exe (from the app_hulk example).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

KIND_SPRITE, KIND_SOUND, KIND_PAL, KIND_MAP = 0, 1, 2, 3
ASSET_NAME_MAXLEN = 24          # incl. NUL, oct_consts.h OCT_ASSET_NAME_MAXLEN
ASSETS_CAP = 2048               # oct_pack.h OCT_ASSETS_CAP
EXT_MAX_DESCS = 512             # launcher sees only the first 512 descriptors
INDEX_RECORD = struct.Struct("<i24s")
BMP_HEADER = struct.Struct("<HHffffffII hh hBBBbBB".replace(" ", ""))
BMP_SIZE = 48

OCT_FLAG_ALPHA = 1 << 0
OCT_FLAG_FULLSIZE = 1 << 1
OCT_FLAG_ADDITIVE = 1 << 2
OCT_FLAG_BG = 1 << 3
OCT_FLAG_RAW565 = 1 << 7
RAW565_PLAIN, RAW565_RLE = 0, 1


@dataclass
class BmpHeader:
    pidx: int; seq: int
    pivot_x: float; pivot_y: float
    bx: float; by: float; bw: float; bh: float
    tags: int; compression: int
    w: int; h: int
    number: int; group: int; type: int
    flags: int; rate: int


def build_bmp_header(*, w, h, flags, pidx=0, seq=0, compression=0,
                     pivot=None, bbox=(0.0, 0.0, 0.0, 0.0),
                     tags=0, number=0, group=0, type_=0, rate=1) -> bytes:
    if pivot is None:
        pivot = ((w - 1) / 2.0 if w else 0.0, (h - 1) / 2.0 if h else 0.0)
    blob = b"".join((
        struct.pack("<HH", pidx, seq),
        struct.pack("<ff", pivot[0], pivot[1]),
        struct.pack("<ffff", *bbox),
        struct.pack("<I", tags),
        struct.pack("<I", compression),
        struct.pack("<hh", w, h),
        struct.pack("<h", number),
        struct.pack("<BB", group, type_),
        struct.pack("<Bb", flags, rate),
        struct.pack("<BB", 0, 0),
    ))
    assert len(blob) == BMP_SIZE
    return blob


def parse_bmp_header(blob: bytes) -> BmpHeader:
    pidx, seq = struct.unpack_from("<HH", blob, 0)
    px, py = struct.unpack_from("<ff", blob, 4)
    bx, by, bw, bh = struct.unpack_from("<ffff", blob, 12)
    tags, compression = struct.unpack_from("<II", blob, 28)
    w, h = struct.unpack_from("<hh", blob, 36)
    number, = struct.unpack_from("<h", blob, 40)
    group, type_, flags = struct.unpack_from("<BBB", blob, 42)
    rate, = struct.unpack_from("<b", blob, 45)
    return BmpHeader(pidx, seq, px, py, bx, by, bw, bh, tags, compression,
                     w, h, number, group, type_, flags, rate)


def build_index_bin(records: list[tuple[int, str]]) -> bytes:
    if len(records) > ASSETS_CAP:
        raise SystemExit(f"{len(records)} assets exceeds OCT_ASSETS_CAP ({ASSETS_CAP})")
    out = [struct.pack("<i", len(records))]
    for kind, name in records:
        encoded = name.encode("ascii")
        if len(encoded) >= ASSET_NAME_MAXLEN:
            raise SystemExit(f"asset name '{name}' exceeds {ASSET_NAME_MAXLEN - 1} chars")
        out.append(INDEX_RECORD.pack(kind, encoded))
    return b"".join(out)


def read_index_bin(path: Path) -> list[tuple[int, str]]:
    blob = Path(path).read_bytes()
    count, = struct.unpack_from("<i", blob, 0)
    records = []
    for i in range(count):
        kind, raw = INDEX_RECORD.unpack_from(blob, 4 + i * INDEX_RECORD.size)
        records.append((kind, raw.split(b"\0", 1)[0].decode("ascii")))
    return records


def build_pal(colors_rgb565: list[int]) -> bytes:
    # each entry stores the RGB565 value twice (see golden 5.pal)
    return b"".join(struct.pack("<HH", c, c) for c in colors_rgb565)


def read_pal(path: Path) -> list[int]:
    blob = Path(path).read_bytes()
    out = []
    for off in range(0, len(blob), 4):
        a, b = struct.unpack_from("<HH", blob, off)
        assert a == b, f"pal entry mismatch at {off}: {a:04x} != {b:04x}"
        out.append(a)
    return out


PLACE = struct.Struct("<ffIhhhhHbbBBBB")

def build_map(bmp_id: int, w: int, h: int, *, x=120.0, y=120.0, looped=False) -> bytes:
    place = b"".join((
        struct.pack("<ff", x, y),
        struct.pack("<I", 0),                       # Tags
        struct.pack("<hh", w, h),
        struct.pack("<h", bmp_id),
        struct.pack("<h", 0),                       # Number
        struct.pack("<H", (1 << 1) if looped else 0),  # PLACE_LOOPED
        struct.pack("<bb", 1, 0),                   # Side, Rate
        struct.pack("<BBBB", 0, 0, 0, 0),           # Name, Group, Parent, Type
    ))
    assert len(place) == 28
    return struct.pack("<ii", 1, 1) + place
```

(If `BMP_HEADER`/`PLACE` Struct constants end up unused, drop them — the pack/unpack helpers above are the API.)

- [ ] **Step 2: Run the Task 5 tests**: `python -m pytest tests/test_beta_container.py -v` → all 5 PASS. If `test_index_bin_roundtrip` fails on padding, hexdump the first 64 bytes of the golden `index.bin` and adjust (the record layout is `<i24s`, total 4 + n*28).

- [ ] **Step 3: Commit**

```bash
git add scripts/pack_beta.py
git commit -m "feat(pack): beta container primitives - index.bin, octBmp_t, .pal, maps"
```

### Task 7: RAW565 full-color encoder (2-byte texels)

**Files:**
- Modify: `scripts/pack_beta.py` (append)
- Create: `tests/test_raw565.py`

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
from PIL import Image
from scripts import pack_beta

def _noise(w, h, seed=7):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8), "RGB")

def _flat(w, h, color=(30, 200, 90)):
    return Image.new("RGB", (w, h), color)

def test_to_rgb565_size():
    texels = pack_beta.to_rgb565(_flat(64, 64), 64)
    assert len(texels) == 64 * 64 * 2

def test_rle_roundtrip_noise():
    img = _noise(120, 120)
    texels = pack_beta.to_rgb565(img, 120)
    payload = pack_beta.rle_encode(texels, 120, 120)
    assert pack_beta.rle_decode(payload, 120, 120) == texels

def test_rle_roundtrip_flat_compresses():
    texels = pack_beta.to_rgb565(_flat(240, 240), 240)
    payload = pack_beta.rle_encode(texels, 240, 240)
    assert pack_beta.rle_decode(payload, 240, 240) == texels
    assert len(payload) < len(texels) // 10   # flat color must compress hard

def test_build_raw565_sprite_picks_smaller_encoding():
    noisy = pack_beta.to_rgb565(_noise(32, 32), 32)
    blob = pack_beta.build_raw565_sprite(noisy, 32, 32, flags=pack_beta.OCT_FLAG_RAW565)
    hdr = pack_beta.parse_bmp_header(blob)
    assert hdr.compression == pack_beta.RAW565_PLAIN   # noise doesn't shrink under RLE
    flat = pack_beta.to_rgb565(_flat(32, 32), 32)
    blob = pack_beta.build_raw565_sprite(flat, 32, 32, flags=pack_beta.OCT_FLAG_RAW565)
    assert pack_beta.parse_bmp_header(blob).compression == pack_beta.RAW565_RLE
```

- [ ] **Step 2: Run to verify failure**: `python -m pytest tests/test_raw565.py -v` → FAIL (`AttributeError: to_rgb565`).

- [ ] **Step 3: Port the encoder into `pack_beta.py`** from `../app_hulk/app_hulk/art/videopack.py` — copy these functions **verbatim** (they are already numpy-vectorized and battle-tested): `smooth_rows` (lines 74-104), `to_rgb565` (107-132), `rle_tokens` (135-160), `rle_blocks` (163-186), `rle_encode` (189-240), `rle_decode` (243-271). Adjust module-level constants they use: `RAW565_RUN = 0x80`, `MAX_LITERAL = RAW565_RUN`, `MAX_RUN = 0xFF - RAW565_RUN + 2`. Then add the sprite builder:

```python
def build_raw565_sprite(texels: bytes, w: int, h: int, *, flags, seq=0, rate=1) -> bytes:
    """48-byte octBmp_t + RGB565 payload; keeps RLE only when it shrinks."""
    flags |= OCT_FLAG_RAW565
    body = rle_encode(texels, w, h)
    if len(body) >= len(texels):
        return build_bmp_header(w=w, h=h, flags=flags, seq=seq, rate=rate,
                                compression=RAW565_PLAIN) + texels
    return build_bmp_header(w=w, h=h, flags=flags, seq=seq, rate=rate,
                            compression=RAW565_RLE) + body
```

Note `rle_encode` in videopack returns `table + body` where the table is the uint16 per-row length table padded to 4 bytes — keep that exact behavior; `rle_decode` mirrors it.

- [ ] **Step 4: Run tests**: `python -m pytest tests/test_raw565.py tests/test_beta_container.py -v` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pack_beta.py tests/test_raw565.py
git commit -m "feat(pack): RAW565 full-color encoder ported from videopack.py, with RLE"
```

### Task 8: Manifest v2 — full-color sprites

**Files:**
- Modify: `scripts/manifest_schema.py`
- Modify: `tests/test_manifest_schema.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_manifest_schema.py`; follow the file's existing fixture style):

```python
def test_fullcolor_sprite_accepted(base_manifest):
    base_manifest["sprites"][0].update(
        {"color": "full", "size": [240, 240], "flags": {"fullsize": True}})
    m = validate_manifest(base_manifest)
    assert m.sprites[0].color == "full"

def test_fullcolor_native_240_requires_fullsize(base_manifest):
    base_manifest["sprites"][0].update({"color": "full", "size": [240, 240]})
    with pytest.raises(ManifestError, match="fullsize"):
        validate_manifest(base_manifest)

def test_fullcolor_rejects_alpha(base_manifest):
    base_manifest["sprites"][0].update(
        {"color": "full", "flags": {"alpha": True}})
    with pytest.raises(ManifestError, match="alpha"):
        validate_manifest(base_manifest)

def test_palette_sprite_still_capped_at_120(base_manifest):
    base_manifest["sprites"][0]["size"] = [121, 121]
    with pytest.raises(ManifestError):
        validate_manifest(base_manifest)

def test_color_defaults_to_palette(base_manifest):
    m = validate_manifest(base_manifest)
    assert m.sprites[0].color == "palette"
```

(Adapt the fixture/validator names to what `test_manifest_schema.py` already uses — the file has an existing suite; reuse its helpers.)

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement in `manifest_schema.py`**
  - Add `color: str = "palette"` to the sprite dataclass; allowed values `{"palette", "full"}`.
  - Validation rules: `color == "full"` ⇒ `alpha` flag forbidden (RAW565 has no transparency — error message must say so and suggest `palette`); size cap becomes 240 when `fullsize` is set, else stays `SPRITE_MAX_SIDE` (120); `color == "palette"` keeps all existing rules.
  - Update the module docstring: normal sprites are authored at ½ resolution (engine draws at 2×); full-color `fullsize` sprites are authored at native resolution up to 240.

- [ ] **Step 4: Run the full suite**: `python -m pytest tests/ -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/manifest_schema.py tests/test_manifest_schema.py
git commit -m "feat(manifest): v2 color field - full-color RAW565 sprites, native fullsize sizing"
```

### Task 9: Beta emit layer in the packer — `index.bin`, `.pal` assets, ids, icon maps

This is the integration task: after the existing palette pack (`pack.py` / `pack_codec.py`), emit the beta layout.

**Files:**
- Modify: `scripts/pack_beta.py` (append the orchestration function)
- Modify: `scripts/pack.py` (add `--beta-app-dir` flag; call the emit layer)
- Modify: `scripts/build_pipeline.py` (pass the flag from the pack stage)
- Create: `tests/test_beta_emit.py`

- [ ] **Step 1: Write the failing test** — build a tiny app dir in `tmp_path` with two 16×16 palette sprite PNGs, one 32×32 full-color PNG (manifest `color: "full"`), one icon PNG, one mp3-less sound stub, then:

```python
def test_emit_beta_layout(tmp_path, tiny_app_fixture):
    result = pack_beta.emit_beta_layout(
        app_dir=tiny_app_fixture.app_dir,
        packed_sprites=tiny_app_fixture.packed,      # name -> .raw payload bytes (palette codec)
        palettes=tiny_app_fixture.palettes,          # group -> [rgb565, ...]
        fullcolor=tiny_app_fixture.fullcolor,        # name -> (texels, w, h, flags)
        icon_png=tiny_app_fixture.icon,
        sounds=["blip"],
        app_name="app_tiny",
    )
    app = tiny_app_fixture.app_dir
    records = pack_beta.read_index_bin(app / "index.bin")
    kinds = [k for k, _ in records]
    names = [n for _, n in records]
    assert records[0] == (pack_beta.KIND_SPRITE, "zero")      # id 0 reserved
    assert "ico" in names and "ahover" in names               # launcher maps
    assert names.index("ico") < pack_beta.EXT_MAX_DESCS
    assert kinds.count(pack_beta.KIND_SOUND) == 1
    for _, name in records:
        kind = dict(zip(names, kinds))[name]
        if kind in (pack_beta.KIND_SPRITE, pack_beta.KIND_MAP):
            assert (app / "art" / "packed" / f"{name}.raw").is_file()
        elif kind == pack_beta.KIND_PAL:
            assert (app / "art" / "packed" / f"{name}.pal").is_file()
    ids = (app / "src" / "app_tiny_ids.h").read_text()
    assert "BMP_none = 0" in ids
    # every sprite id in the header equals its index.bin record index
    for i, (k, n) in enumerate(records):
        if k == pack_beta.KIND_SPRITE and n not in ("zero",):
            assert f"BMP_{n} = {i}" in ids
    # palette sprites reference their pal by asset id
    hdr = pack_beta.parse_bmp_header(
        (app / "art" / "packed" / "sprite_a.raw").read_bytes())
    assert records[hdr.pidx][0] == pack_beta.KIND_PAL
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `emit_beta_layout`** in `pack_beta.py`. Record order (id = record index):
  1. `("zero", KIND_SPRITE)` — a 48-byte zero-size header, `build_bmp_header(w=0, h=0, flags=0)`; payload file `zero.raw`.
  2. Palette assets — one per palette group, named `"1"`, `"2"`, … ; write `<n>.pal`.
  3. Icon assets: `ico_idle` sprite (RAW565 from `icon.png` at 160×160 via `to_rgb565` + `build_raw565_sprite` with `OCT_FLAG_RAW565 | OCT_FLAG_FULLSIZE`), then `ico` and `ahover` MAP records both pointing at the `ico_idle` id (`build_map(idle_id, 160, 160)`) — mirrors `videopack.py build_icon_assets`.
  4. Every packed palette sprite: patch its 48-byte header — set `Pidx` to the pal asset id of its group and `Seq` to the asset id of the next animation frame (frames sort by the existing `_NN` suffix convention; last frame links back to the first, static sprites keep `Seq=0`). Write `<name>.raw`.
  5. Every full-color sprite from the manifest (`color: "full"`): `build_raw565_sprite` (+ `OCT_FLAG_FULLSIZE` when flagged), write `<name>.raw`.
  6. Sounds: one `KIND_SOUND` record per `sound/assets/*.mp3` basename (no payload file in `art/packed`).

  Then write `index.bin` to the app root and generate `src/<app>_ids.h`:

```python
def generate_ids_header(records, dest: Path, app_name: str) -> None:
    lines = [f"// generated by pack_beta.py for {app_name}, do not edit", "",
             "enum BMP {", "    BMP_none = 0,"]
    for i, (kind, name) in enumerate(records):
        if kind == KIND_SPRITE and i > 0:
            lines.append(f"    BMP_{name} = {i},")
    lines += ["    BMP_last", "};", "", "enum MAP {", "    MAP_none = 0,"]
    for i, (kind, name) in enumerate(records):
        if kind == KIND_MAP:
            lines.append(f"    MAP_{name} = {i},")
    lines += ["    MAP_last", "};", ""]
    dest.write_text("\n".join(lines))
```

  Add the animation aliases the current `pack_psd.generate_app_ids_h` emits (`BMP_<base>` = first frame, `BMP_<base>_end` = last frame for `_NN` sequences) — port that block from `scripts/pack_psd.py:1029-1060`.

- [ ] **Step 4: Wire into `pack.py`**: new args `--beta-app-dir <dir>` and `--app-name <name>`; when present, after `_phase_emit_raw`, collect the packed sprites + palettes and call `emit_beta_layout`. The legacy `pal.png` / packed-PNG outputs keep being written next to it (harmless, still useful for `unpack.py` debugging).

- [ ] **Step 5: Wire into `build_pipeline.py`** pack stage: pass `--beta-app-dir` + `--app-name` when the caller supplies `--src-dir` (it already knows the app dir).

- [ ] **Step 6: Run the full suite** `python -m pytest tests/ -v` → PASS.

- [ ] **Step 7: Byte-level sanity vs golden codec** — decode one of our freshly packed palette sprites with `scripts/unpack.py` logic and re-encode; then decode golden `ahover_00.raw` payload with the same decode path (using its `.pal`). If the golden payload does NOT decode cleanly, **stop and report** — the palette codec diverges from beta `utils.exe` output and palette sprites must fall back to the exe path (`octavios/utils/psd.exe` + `utils.exe`) until the codec is fixed. Record the outcome in the commit message.

- [ ] **Step 8: Commit**

```bash
git add scripts/pack_beta.py scripts/pack.py scripts/build_pipeline.py tests/test_beta_emit.py
git commit -m "feat(pack): emit beta container - index.bin, .pal assets, icon maps, kind-aware ids"
```

### Task 10: Sounds — encode to beta mp3 and register in index.bin

**Files:**
- Modify: `scripts/gen_sounds.py`
- Modify: `scripts/check_env.ps1`, `scripts/check_env.sh`
- Modify: `tests/test_gen_sounds.py`

- [ ] **Step 1: Write the failing test**

```python
def test_encode_mp3_beta_format(tmp_path, monkeypatch):
    wav = tmp_path / "blip.wav"
    _write_test_wav(wav)                      # reuse the module's existing helper/fixture
    out = gen_sounds.encode_beta_mp3(wav, tmp_path / "assets")
    assert out == tmp_path / "assets" / "blip.mp3"
    assert out.stat().st_size > 0
```

Mark it `@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")`.

- [ ] **Step 2: Implement `encode_beta_mp3`** in `gen_sounds.py`:

```python
def encode_beta_mp3(wav_path: Path, assets_dir: Path) -> Path:
    """Encode to the exact format the beta engine decodes:
    22050 Hz mono CBR 32k, no Xing header, no metadata
    (mirrors octavios/CMakeLists.txt pack target)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    out = assets_dir / (wav_path.stem + ".mp3")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
           "-ac", "1", "-ar", "22050", "-sample_fmt", "s16p",
           "-b:a", "32k", "-codec:a", "libmp3lame", "-cbr", "1",
           "-write_xing", "0", "-map_metadata", "-1", "-map", "0:a",
           "-id3v2_version", "0", str(out)]
    subprocess.run(cmd, check=True)
    return out
```

Call it from the generate flow so every synthesized WAV lands in `sound/assets/<name>.mp3` (keep the WAV in `sound/` as the editable source). If ffmpeg is missing, fail with the exact message: `ffmpeg is required to encode beta sounds (22050 Hz mono mp3). Install it and re-run, or drop pre-encoded mp3 files into sound/assets/.`

- [ ] **Step 3: Add ffmpeg to the env checks** — `check_env.ps1`: winget id `Gyan.FFmpeg` in the tools table; `check_env.sh`: `command -v ffmpeg`.

- [ ] **Step 4: Run tests, commit**

```bash
git add scripts/gen_sounds.py scripts/check_env.ps1 scripts/check_env.sh tests/test_gen_sounds.py
git commit -m "feat(sound): encode beta mp3 (22050 mono CBR32k) into sound/assets, require ffmpeg"
```

### Task 11: Boilerplate scripts — beta gates

**Files:**
- Modify: `scripts/new_app.ps1`, `scripts/new_app.sh` (pack step + success gate)
- Modify: `scripts/build_device.ps1`, `scripts/build_device.sh`

- [ ] **Step 1: Update the pack step in both scaffolders** to pass the new flags: `--beta-app-dir "$AppDir" --app-name $app` (ps1) / `--beta-app-dir "$app_dir" --app-name "$app"` (sh).

- [ ] **Step 2: Update the success gates**: after packing, require **both** `art/packed/*.raw` (>0 files) **and** `<AppDir>/index.bin` present; fail message: `beta pack incomplete: index.bin missing — the simulator cannot load this app`.

- [ ] **Step 3: `build_device` scripts**: no logic change to the ARM build; add after the `.oct` verification a note-check that warns if a stray `<app>_*.oct` (timestamped) sits in the app root (the Linux sim deletes root `.oct` files at startup — keep deliverables in `pack/` or copy them out).

- [ ] **Step 4: Commit**

```bash
git add scripts/new_app.ps1 scripts/new_app.sh scripts/build_device.ps1 scripts/build_device.sh
git commit -m "feat(boilerplate): beta pack flags and index.bin gates in scaffold/build scripts"
```

### Task 12: SKILL.md sweep — orchestrator, prompter, designer, verifier, asset-builder, boilerplate

One commit per skill file; each is a focused text edit. The changes each file needs:

**Files:**
- Modify: `skills/cube_orchestrator/SKILL.md`
- Modify: `skills/technical_prompter/SKILL.md`
- Modify: `skills/cube_game-designer/SKILL.md`
- Modify: `skills/cube_verifier/SKILL.md`
- Modify: `skills/cube_asset-builder/SKILL.md`
- Modify: `skills/wowcube-boilerplate/SKILL.md`

- [ ] **Step 1: `cube_orchestrator/SKILL.md`**
  - Every "all 5 handler functions" → "all 7 handler functions (`on_init`, `on_tick`, `on_tap(tapid, count)`, `on_twisted`, `on_pretwisted`, `on_shake`, `on_proc_draw` stub)" (lines ~560, ~583).
  - Readiness/refresh artifact lists (lines ~206, ~800): add `index.bin` next to `art/packed/*.raw`.
  - Sizing rule section (~372-391): keep the ½-resolution rule for palette sprites, add the exception: *"full-color sprites (`color: "full"` + `fullsize`) are authored at native resolution up to 240×240; they have NO transparency — use them for backgrounds, tiles and full-screen art only."*
  - Sound mentions `.wav` (~217, 220, 424, 431-432, 785): source stays `.wav` in `sound/`, but packing now produces `sound/assets/*.mp3`; code references `SND_getAssetId("<name>.mp3")`.
  - Stage 4 Step 1 (~511): the skeleton copy now includes 7 handlers (no text change needed beyond the handler count).

- [ ] **Step 2: `technical_prompter/SKILL.md`**
  - "All 5 handlers" → 7 (lines ~208, ~312); `on_tap` signature gains `count`.
  - Manifest field docs: add `color: "palette" | "full"` with the full-color constraints (no alpha, fullsize→240 native).
  - Scaffold defines: prompts must never touch `app.h` defines (they are guaranteed by the scaffolder) — extend the existing `_ids.h` "never edit" rule to `app.h` defines.
  - Sound naming stays `SND_getAssetId("<name>.mp3")` — now true by construction.

- [ ] **Step 3: `cube_game-designer/SKILL.md`**
  - Sizing text (~197-206, 281): add the full-color option sentence (native-res, opaque, for backdrops/fullscreen scenes).
  - "sound MP3s are created by humans" (~290-296): sounds are synthesized (WAV) then encoded to beta mp3 automatically; humans *may* supply their own mp3.

- [ ] **Step 4: `cube_verifier/SKILL.md`**
  - Template Agent checklist (~152): "All 5 handlers" → 7, `on_tap(tapid, count)`; add checks: `src/app.h` defines all six `APP_*` macros; `on_shake`/`on_proc_draw` stubs present; no code edits `_ids.h`/`index.bin`.
  - `platform_constraints` (~163): note the full-color exception to upscale-aware coordinates (FULLSIZE draws 1:1).

- [ ] **Step 5: `cube_asset-builder/SKILL.md`**
  - Outputs section: `art/packed/*.raw` + `*.pal` + `<app>/index.bin` + `src/app_<game>_ids.h` + `sound/assets/*.mp3`.
  - Prereqs: add ffmpeg; keep Pillow/numpy/pytoshop/psd-tools.
  - Document the `color: "full"` manifest option and when to use it.
  - Error table: add `index.bin missing after pack` → re-run pack with `--beta-app-dir`; `ffmpeg not found` → install (winget `Gyan.FFmpeg`).

- [ ] **Step 6: `wowcube-boilerplate/SKILL.md`**
  - Scaffold guarantees (~142, ~216-223): "Guarantee `APP_VERSION`" → "Guarantee the full define set (`APP_VERSION`, `APP_TITLE`, `APP_DIR`, `APP_GUID1` (random, non-zero), `APP_CATEGORIES`, `APP_COLORS`)".
  - Artifact lists: replace `pal.raw` (never existed) with `index.bin` + `*.pal`; gates = `*.raw` **and** `index.bin`.
  - Add the beta `.oct` root-deletion caveat (sim deletes/rewrites root `.oct`; deliver from a `pack/` copy or take the file after the final device build — existing "critical ordering" text already covers most of this).

- [ ] **Step 7: Commit after each file** (6 commits, message pattern `docs(<skill>): beta - 7 callbacks, index.bin artifacts, full-color assets`).

### Task 13: README, pipeline-flow, plugin manifest, dead code

**Files:**
- Modify: `README.md`, `docs/pipeline-flow.md`, `.claude-plugin/plugin.json`
- Delete: `scripts/pack_patched.py` (orphan, ~2450 lines, imported by nothing)
- Modify: `scripts/config.py` (truncated last line)

- [ ] **Step 1: `README.md`**: structure block lists all 6 skills + real template paths (`templates/app_ai_template/src/app_ai_template.h`); Stage 3 wording "AI PNGs + synthesized WAVs → beta mp3"; asset outputs incl. `index.bin`; fix the stale `templates/app_test_ids.h` / `context/` references.
- [ ] **Step 2: `docs/pipeline-flow.md`**: `assets/mp3/*.mp3` → `sound/assets/*.mp3`; pack stage node mentions `index.bin`; drop the hardcoded image-model name (say "the configured OpenRouter image model").
- [ ] **Step 3: `plugin.json`**: description mentions all skills; bump version to `2.0.0` (beta transition).
- [ ] **Step 4: Delete `scripts/pack_patched.py`**; verify with `grep -r pack_patched` → only its own filename. Fix `scripts/config.py` last line (truncated comment `# (config rev 2026-04-29: a`) → complete or delete the comment.
- [ ] **Step 5: Run full test suite** `python -m pytest tests/ -v` → PASS. Commit.

```bash
git add -A
git commit -m "docs: beta transition sweep - README, pipeline-flow, plugin 2.0.0; drop orphan pack_patched"
```

### Task 14: End-to-end verification against the real beta workspace

**Files:** none new in the repo (throwaway app dir + report)

- [ ] **Step 1:** In `beta transition/`, scaffold `app_bdemo` with `scripts/new_app.ps1` (workspace = `beta transition/`, octavios already sits next to it). Expect: template copied, six defines present with a random GUID.
- [ ] **Step 2:** Drop a minimal manifest (2 palette sprites, 1 full-color 240×240 fullsize background, 1 sound) and run the asset pipeline in placeholder mode (no API key needed) + pack. Expect: `art/packed/*.raw` + `*.pal`, `index.bin`, `src/app_bdemo_ids.h`, `sound/assets/*.mp3`.
- [ ] **Step 3:** Validate `index.bin` against `pack_beta.read_index_bin` (record 0 = zero sprite, ico/ahover maps present, sound record present) and every referenced payload file exists.
- [ ] **Step 4:** If MSVC is available: `octavios/apps/build_sim.cmd` from the app dir → `bin/app_bdemo.exe`; launch for 5 s; expect it not to die (the DIE paths are all asset-container errors, so surviving startup proves the container). If MSVC is absent, record that and skip.
- [ ] **Step 5:** If arm-none-eabi-gcc is available: `cmake -G Ninja -S ../octavios/apps -B out && cmake --build out` → `out/app_bdemo.bin`; rerun the sim to get `app_bdemo.oct`; verify the tail bytes equal the `.bin` (build_device.ps1 does this). Else record and skip.
- [ ] **Step 6:** Write the outcome (what ran, what was skipped and why) into the final report; delete `app_bdemo` or keep it as a demo per user preference. Commit any fixes discovered.

### Task 15: Finish

- [ ] Run the whole test suite one final time.
- [ ] Summarize alpha→beta changes for the team in the PR body (defines, callbacks, index.bin container, full-color assets, mp3 sounds).
- [ ] **Ask the user** before pushing `beta-transition` and opening a PR to `wowcube/OCT_wowcube-agent-skills` (also flag that `origin/feat/sprite-upscale-sizing` + YOLO were merged in, and that the genimg fixes from the local working copy are included).

---

## Known risks & fallbacks

1. **Palette codec byte-compat** (Task 9 Step 7). The container layout is golden-verified, but the bit-packed sprite payload produced by `pack_codec.py` has never been decoded by a real beta engine. Fallback if the golden decode fails: keep full-color RAW565 + maps + index.bin from the Python path, and route palette sprites through the beta `psd.exe`/`utils.exe` (they live in `octavios/utils/`), merging their output records into our `index.bin`. The plan's module boundaries (`emit_beta_layout` takes pre-packed sprite bytes) make this swap local.
2. **`.pal` duplicate-word semantics.** Golden pals store each color twice; we replicate byte-for-byte. If the second word turns out to be a variant (e.g. dimmed), replication of the same value is still what `utils.exe` produced for hulk, so it is safe.
3. **`on_shake` routing** is currently disabled engine-side (system default always runs). The template documents this so game designs don't rely on shake input.
4. **Windows sim `sound` conversion**: the sim reads only `sound/assets/*.mp3`; our ffmpeg step covers it. Users without ffmpeg get a hard, actionable error.
