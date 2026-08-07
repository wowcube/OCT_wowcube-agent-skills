# Part 3 Implementation Plan — full-python packing parity with `utils.exe`

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** make the python packer produce output equivalent to the legacy `psd.exe` + `utils.exe` chain for legacy/palette apps, so CI can build **entirely in python** from what an app repo commits today (PSD sources + `!pack.txt` + fonts + WAV sounds + src). Owner's decision: option B — no wine, no exes in CI.

**Branch:** `part3-python-parity` (off `part2-autonomous-orchestrator` tip `1a50c1a`, which carries the PSD-export fidelity fixes). PR #26 (part 2) stays untouched at `27fa9d3`. Part 3 gets its own PR, stacked.

**Reference corpus (the whole point — measure, don't guess):** `C:\Users\igort\Desktop\wowcube_vibecode\OCT_get_started` — READ-ONLY, never modify or commit there.
- Committed sources: 9 PSDs, `art/!pack.txt` (hand-tuned palette buckets + `<FULLSIZE>` tags), `art/!pack_pal.txt`, 3 `.fnt` + atlases, `art/0.png`, `art/icon.png`, QR PNGs, `art/qr_setalpha.py`, `src/*.h` (6 headers), `sound/*.wav` (11).
- **Golden outputs from the real toolchain, present in the working copy (gitignored but on disk):** `art/exported/` (478 psd.exe artifacts), `art/packed/*.raw` + `*.pal` (utils.exe, 1,291,936 B total), `index.bin` (511 records), `src/app_get_started_ids.h`. These are the ground truth every task below measures against.
- Additional golden `.pal` format evidence: `app_launcher`, `app_seabattle` packs (see the part-2 fidelity report).

**Known gap list (from the 2026-08-05 fidelity study — root causes already established):**
1. **Pivots**: `psd.exe` reads the `~pivot` layer, treats each 4-connected blob as a marker, assigns each sprite the overlapping marker (fallback: the layer's own rect); `utils.exe` packs `PivotX = 2*(marker_centre_x − layer_x) − 0.5`. Verified against real packed bytes (`ic_twist_00`: layer (20,20,37×36), marker (37,37,2×2) → pivot (35.5, 35.5)) and reproduces 320/320 pivots in `assets.psd`. Our packer uses `PIVOT_MODE = LEGACY` → **201/450 sprites mis-anchored, worst by 103 px** (`transit_w_new_01`).
   **Task 1 addendum (measured, not guessed):** the scale factor is the engine's draw zoom, so a `<FULLSIZE>` sprite (drawn 1:1) uses **scale 1, not 2**. The plain ×2 formula reproduces 400/450; keying the scale off `OCT_FLAG_FULLSIZE` reproduces **450/450**. The 50 affected sprites are exactly the `<FULLSIZE>` blocks of `!pack.txt` (`selectcube_*`, `selectcube_orange_*`, `ahover*`, `ico*`). **Consequence for Task 2:** the `<FULLSIZE>` tag is now load-bearing twice — flags *and* pivots — so losing it corrupts sprite anchoring as well as scale.
2. **`!pack.txt` ignored**: per-glob palette sizes (2/4/6/7/8-bit buckets, 46 palettes) and `<FULLSIZE>`/`<ALPHA>` tags. Our auto-palette makes 16×256-colour groups → 8-bit for 450/452 sprites, **+57 % packed size**, and **`<FULLSIZE>` lost on 50 `selectcube_*` sprites** (engine would draw them at 2× — a visible bug).
3. **Palette alpha format**: across 451 shipping sprites the rule is exact — `.pal` words are either `(alpha5<<27) | ((c|c<<16) & 0x07E0F81F)` **with** `OCT_FLAG_ALPHA`, or plain `c|c<<16` **without** it. `pack_beta.build_pal` always writes the second form while `pack_codec` always sets the flag — a combination that occurs in no shipping pack; the engine's `OCT_BLEND_alpha` (`alpha = pe >> 27`) would read the red channel as alpha. Measured effect: every antialiased pixel flattened to opaque (2328/2328 on `t_welcome`, 9596/9596 on `selector_00`).
4. Housekeeping blocking CI: sound basenames must be valid C identifiers (`Congratulations-007.wav` breaks `SND_*`); generated files tracked in app repos; unpinned deps; `oct-builder/scripts` snapshot diverged; the `APP_VER(x,y,z)` parser fix lives only in the oct-builder copy.

**Testing:** `$env:PYTHONPATH='scripts'; python -m pytest tests/ -q` from the repo root. Baseline on this branch: **271 passed**. Every task adds tests. No AI attribution in commits. Do not push until the owner asks.

**Simulator is available** (MSVC present) — use it for the visual checks the plan calls for; the engine source is at `..\octavios`.

---

### Task 1: Pivot parity — the packer honours PSD pivot markers

**Files:** `scripts/config.py` (pivot mode), `scripts/pack_codec.py` (`build_header` pivot maths), `scripts/pack.py` (pivot plumbing from csv/psl), `tests/test_pivot_parity.py` (new).

- [x] **Step 1: Write the failing parity test.** Build a fixture from the corpus: parse 10 representative sprites' pivots out of the golden `art/packed/*.raw` headers (offsets 4/8, floats) and their layer rects + markers from the golden `art/exported/*.csv`. Assert our packer reproduces each. Pick sprites spanning: marker-anchored (`ic_twist_00` — pinned in the study), own-rect fallback (a sprite from `eyes.psd`/`text.psd`, which have no `~pivot` layer), a `=num` sequence member, and a FULLSIZE one.

- [x] **Step 2: Run it — expect failures** on the marker-anchored ones (LEGACY formula gives `(w-0.5, h-0.5)`).

- [x] **Step 3: Implement.** Add `PivotMode.PSD`; the pivot source is the exporter's csv/psl records (`pack_psd.find_pivot_markers`/`pivot_for_layer` already exist from `1a50c1a` — reuse, don't duplicate). Wire `pack.py`'s existing `_load_sprite_pivots_from_csvs` path so a csv-carried pivot rect reaches `build_header` as `2*(centre − xy) − 0.5`. Default mode stays whatever keeps manifest-driven apps unchanged (full-color/manifest apps must not move a single byte — see Task 5's regression).

- [x] **Step 4: Full-corpus proof.** Script it: export all 9 PSDs with our exporter, pack, then compare **every** sprite's packed pivot against the golden `.raw`. Target: **450/450 exact**. Report any residue with root cause.

- [x] **Step 5: Commit** `feat(pack): PSD pivot markers - packed pivots match utils.exe`

### Task 2: `!pack.txt` support — palette buckets and per-group flags

**Files:** `scripts/packtxt.py` (new parser), `scripts/pack.py` (use it when present), `scripts/pack_codec.py` (per-group palette sizing), `tests/test_packtxt.py` (new).

- [ ] **Step 1: Write the parser tests** against the real corpus file (`art/!pack.txt` and `art/!pack_pal.txt` — read both; the study quoted the format: an `exported` header line, then blocks of `<size>` + optional `<TAG>` lines + glob patterns, blank-line separated, later blocks overriding earlier for a matching sprite). Cases: catch-all `*` bucket, a 4-colour `font*` bucket, `<FULLSIZE>` tag, multiple globs per bucket, "later, more specific mask wins", and a sprite matching nothing (→ default bucket).

- [ ] **Step 2: Implement the parser** → a resolver: `assign(sprite_name) -> (palette_group_id, max_colors, flags)`.

- [ ] **Step 3: Wire into packing.** When `--pack-config <path>` is given (auto-detected as `art/!pack.txt` when present and no manifest), palette grouping follows the config instead of the auto median-cut grouping: one palette per bucket, `max_colors` per bucket, `<FULLSIZE>`/`<ALPHA>` tags OR'd into the sprite flags. Manifest-driven apps are unaffected (manifest wins; document precedence).

- [ ] **Step 4: Corpus proof.** Pack the corpus with `!pack.txt` honoured and compare against golden: per-sprite palette-group membership, symbol bit depth, `OCT_FLAG_FULLSIZE`/`ALPHA` bits, and total packed size. Targets: **flags 451/451 exact**, bit depths match on ≥95 % of sprites, total size within **±10 %** of the golden 1,291,936 B (we will not match the exe's quantiser exactly — measure and report). Explicitly verify the 50 `selectcube_*` sprites regain FULLSIZE.

- [ ] **Step 5: Commit** `feat(pack): read !pack.txt palette buckets and per-group flags`

### Task 3: Palette alpha — correct `.pal` format and flag

**Files:** `scripts/pack_beta.py` (`build_pal`), `scripts/pack_codec.py` (alpha carry + flag decision), `scripts/pack.py` (`_to_565` alpha path), `tests/test_pal_alpha.py` (new).

- [ ] **Step 1: Pin the golden format in a test.** Read golden `.pal` files from the corpus (and, if reachable, `app_launcher`/`app_seabattle`): assert the two-format rule — alpha-spread words iff the sprites referencing that palette carry `OCT_FLAG_ALPHA`. Encode the bit layout as a constant with the engine reference (`oct_render.h::OCT_BLEND_alpha`, `alpha = pe >> 27`, `fg = pe & 0x07FFFFFF`).

- [ ] **Step 2: Write the round-trip test** — a sprite with antialiased edges (build one with Pillow: a soft-edged circle) packed with alpha must decode back with its alpha gradient preserved (not flattened), and its palette must be in the spread format with the flag set.

- [ ] **Step 3: Run — expect failure** (today: alpha dropped in `_to_565`, plain palette, flag set anyway).

- [ ] **Step 4: Implement.** Carry per-colour alpha through quantisation into the palette; emit the spread format when the palette has any non-opaque entry and set `OCT_FLAG_ALPHA` then — and only then. Keep index 0 fully transparent in both formats.

- [ ] **Step 5: Visual verification in the simulator (mandatory — this changes rendering).** Build a small palette app with antialiased sprites (reuse `..\app_paltest`, or scaffold a fresh one; do NOT modify committed apps — copy first), pack it before and after the fix, run the Windows simulator on both, capture screenshots, and confirm: after = soft edges, before = hard/incorrect edges. Attach the evidence to the report. If the simulator shows the opposite, STOP and report — the format hypothesis would be wrong.

- [ ] **Step 6: Corpus cross-check.** Repack the corpus and compare `.pal` formats and `ALPHA` flags per sprite against golden: target **451/451 format+flag agreement**.

- [ ] **Step 7: Commit** `fix(pack): palette alpha - spread format with the ALPHA flag, antialiasing preserved`

### Task 4: End-to-end python build of the legacy corpus

**Files:** none in the packer (integration only); `oct-builder/ci_build.py` + `oct-builder/README.md` if the flow needs it; a report.

- [ ] **Step 1:** Copy `OCT_get_started` to a scratch dir, strip everything the app does NOT commit (`art/exported/`, `art/packed/`, `sound/assets/`, `index.bin`, `src/*_ids.h`, `art/*_ids.h`, `out/`, `bin/`) — this is the true fresh-clone state.
- [ ] **Step 2:** Build entirely in python: export PSDs → pack with `!pack.txt` → sounds WAV→mp3 → ARM → `.oct` → tail verification. Fix whatever breaks in `ci_build.py` (e.g. it must export when `art/exported` is absent, which is now the normal legacy case).
- [ ] **Step 3:** Compare the result against the golden pack: record count, per-sprite flags/pivots/palette groups, total size, and a per-sprite visual diff (mean abs error) on ≥20 sprites spanning fonts, alpha sprites, FULLSIZE, and animation frames. Produce a written parity report at `docs/part3-parity-report.md`.
- [ ] **Step 4:** Build the simulator for the freshly built app and smoke it (8 s alive); if the app renders, screenshot a couple of faces as evidence.
- [ ] **Step 5: Commit** the report + any `ci_build` fixes: `docs: legacy corpus parity report (full-python build)`

### Task 5: Regression + housekeeping

**Files:** `scripts/gen_sounds.py` (name normalisation), `oct-builder/*` (re-sync, pinned deps), `scripts/pack_beta.py` (upstream the `APP_VER` parser fix), docs.

- [ ] **Step 1: Full-color regression (must be byte-identical).** Rebuild `app_gbhotel` and `app_photoframe` (copies, not the originals) with the part-3 packer and confirm the `.oct` bytes match the current ones (modulo `APP_VERSION`). Any drift = a bug in Tasks 1-3; fix before proceeding.
- [ ] **Step 2: Sound name normalisation.** Sound asset ids must be valid C identifiers: normalise WAV basenames (lowercase, non-alphanumerics → `_`, leading digit → prefixed) consistently in `gen_sounds.py` and the packer, so `Congratulations-007.wav` → `congratulations_007`. Tests: the corpus's 11 names, plus a leading-digit case. Verify the corpus's `SND_getAssetId("...")` call sites still resolve.
- [ ] **Step 3: Upstream the `APP_VER(x,y,z)` macro parsing** from `oct-builder/scripts/pack_beta.py` into the skills repo copy, with a test (`APP_VERSION APP_VER(0,1,3)` and plain-int forms).
- [ ] **Step 4: Pin dependency versions** in both `scripts/requirements.txt` and `oct-builder/requirements.txt` (`==` pins for Pillow, numpy, psd-tools) so CI output stays reproducible.
- [ ] **Step 5: Re-sync `oct-builder/scripts`** as a verbatim snapshot of the skills-repo scripts (they diverged), and update `oct-builder/README.md`: the CI contract for legacy apps is now "commit sources (PSD, `!pack.txt`, fonts, WAV, src); CI generates everything else", plus the app-repo cleanup (`git rm --cached index.bin src/*_ids.h art/*_ids.h`).
- [ ] **Step 6: Full suite green**, then commit: `chore: sound-name normalisation, pinned deps, oct-builder re-sync`

### Task 6: Final review + PR

- [ ] Whole-branch review against this plan and the parity report; suite green; no attribution.
- [ ] Push `part3-python-parity`, open a PR **stacked on / after** #26 (state the dependency in the body: it contains `1a50c1a` from the part-2 branch). Summarise the parity numbers. **Do not merge.**

---

## Success criteria (the honest bar)

| Metric | Target |
|---|---|
| Packed pivots vs golden | 450/450 exact |
| Sprite flags (`ALPHA`/`FULLSIZE`) vs golden | 451/451 exact |
| `.pal` format vs golden (spread-vs-plain) | 451/451 agreement |
| Antialiased alpha preserved | verified in the simulator, screenshots |
| Total packed size vs golden 1,291,936 B | within ±10 % |
| Full-color apps (gbhotel/photoframe) | byte-identical `.oct` |
| Legacy corpus builds fully in python from committed sources | yes, `.oct` verified, sim smoke passes |
