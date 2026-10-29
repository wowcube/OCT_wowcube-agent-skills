---
name: cube_asset-builder
description: >-
  Stage 3 component of the WowCube pipeline, invoked by cube_orchestrator — not a
  standalone user entry point. Use only when the orchestrator's stage detection
  routes to Stage 3: the GDD, prompts, manifest and infra gate are done, but the
  context's style_lock is not approved/waived/user_art, or `build_pipeline.py
  pack-status` does not exit 0 (never packed by Stage 3, or an input changed; the
  infra gate's template pack does not count). Locks the art style with
  the user (style frame), draws every sprite with Codex through cube_art-director
  (ChatGPT subscription, no key; without Codex placeholders, a paid API only on the user's explicit opt-in), runs the strict
  QA loop and the review page, sources user-approved CC0 sounds and builds them
  with sound_kit, makes the launcher icon, then packs the beta container into
  app_<game>/.
---

# WowCube Asset Builder

> **This skill is Stage 3 of the `cube_orchestrator` pipeline.** The orchestrator invokes it (via the Skill tool) when its stage detection (`cube_orchestrator/SKILL.md`, "Stage detection and routing") stops at a Stage 3 row: the style lock is not `approved` / `waived` / `user_art`, or `build_pipeline.py pack-status` does not exit 0. The infra gate's template pack already writes `index.bin` and `_ids.h`, so their existence never means Stage 3 is done. It is not a user-facing entry point — the user enters through `cube_orchestrator`, which routes here.

Turn `plans/<game>_assets.json` into the packed art and sound the coder agents reference: `app_<game>/index.bin`, `art/packed/*.raw` + `*.pal`, `sound/assets/*.mp3`, `src/app_<game>_ids.h`, the launcher icon `app_<game>/art/icon.png` and the licence log `app_<game>/sound/CREDITS.md`. This skill never writes game code and never invents asset names: every name in a prompt exists as a file after it runs, or the manifest goes back to `technical_prompter`.

## Ground rules

- **Codex on the user's ChatGPT subscription draws the art** (no key, nothing billed per image), through `skills/cube_art-director` (`scripts/art.py`). Never ask for an API key while Codex works. Without Codex the art is agent-drawn placeholders, never accepted as final art. A paid image API is used only when the user, in this run, explicitly asked for it and agreed to pay (`--allow-paid`), in every mode including autonomous and `YOLO`; a configured key is not consent (`cube_orchestrator/references/RUN_MODES.md`, `references/ART.md`).
- **Style lock first**: no mass generation before the user approved a style frame shown at cube resolution.
- **Strict reviewer**: an asset that breaks a rule in `cube_art-director/references/QA_RULES.md` is a FAIL. Iterate until every rule passes — there is no "N cycles, then accept"; escalate only when a rule truly cannot be met, saying what was tried. The one exception is a spent art budget set by the user (`cube_orchestrator/references/STAGE3_ASSETS.md`, Step 3): then the remaining style/set failures are waived in `fixes.json` and reported, never silently accepted.
- **Reproducible**: every correction lives in `assets_<game>/fixes.json` (never only in the chat); regeneration replays it.
- **Real sounds**: CC0 recordings the user approved (file, source URL, licence, size), built with `scripts/sound_kit.py`; synthesised sounds only as placeholders. **Never play audio** — judge sounds by `sound_kit.py inspect`.
- **One workspace per game**: `assets_<game>/` next to `plans/` and `app_<game>/`; never a shared `assets/` folder.
- Agent safety: `skills/cube_orchestrator/references/AGENT_SAFETY.md` (downloads only after approval, no credentials, PID-only process kills).

## Files

```
<root>/plans/<game>_assets.json   manifest (Stage 2): sprites (incl. launcher_icon), sounds, _style, icon tier, _panoramas
<root>/refs/ , <root>/drawn/      the user's reference images / drawings (optional)
<root>/assets_<game>/
  style/        STYLE.md (Prompt block = _style), anchors/, candidates/, profile.json, mock.png
  raw/          Codex output (+ keys.json, prompts.json, logs/)
  art/          final PNGs at manifest size (+ 0.png)  <- what the pack reads
  qa/           report.txt/json, sets.png, per-animation GIFs
  fixes.json    every correction (refs, colour lock, prompt lines)
  review.html   the user's review page
  pano/         art.json + work/final/<panorama>.png   (only with _panoramas)
  sound_src/    proposal.md, dl/ (approved downloads), recipes.json
  wav/          placeholder WAVs + placeholders.json; wav/assets/*.mp3 = every sound the pack ships
  fonts/ exported/ packed/ assets.psd   pack intermediates
<root>/app_<game>/                scaffolded app (wowcube-boilerplate); the pack writes into it
```

Commands below run from `<root>` (the folder holding `plans/`; the orchestrator's `<ws>`); `<skills>` is this skills repository (the folder holding `skills/`, `scripts/`, `templates/`, `tools/`). `ART` stands for `python <skills>/skills/cube_art-director/scripts/art.py`, `M` for `plans/<game>_assets.json`; on a manifest art.py works in `assets_<game>/` by default (`--workspace` overrides).

## Prerequisites

| What | How to check / get it |
|---|---|
| Valid manifest with a `gen_prompt` on every sprite | `python <skills>/scripts/build_pipeline.py validate --manifest M`: provider-free (schema, names, tiers, `background`, `launcher_icon`, the Codex prompt rules; never generates, never touches the network). Exit 0 = valid, 2 = back to `technical_prompter` with every printed error. Never use `generate` as a check: it draws (and without Codex may reach a paid provider) |
| Python 3.11+ with Pillow, numpy, requests, pytoshop, psd-tools | `pip install -r <skills>/scripts/requirements.txt` |
| Codex CLI logged in with ChatGPT | `ART doctor M` (CLI found, ChatGPT login, model and effort, spec valid). Not logged in: the user runs `codex login` themselves |
| `ffmpeg` on PATH (mp3 encoding, sound_kit) | part of the one-time environment approval (`cube_orchestrator/references/AGENT_SAFETY.md`): Windows `check_env.ps1 -Install` (quiet winget, `Gyan.FFmpeg`); Linux: the distro package |
| Scaffolded `app_<game>/` (pack step only) | `app_<game>/app_<game>.target` exists. Missing: hand back to the orchestrator to scaffold first (`wowcube-boilerplate`). Never let the pack create a bare `app_<game>/`: the scaffolder refuses an existing folder, and fonts and metadata come from the scaffold |

## Run modes

- **Autonomous (default)**: one stop — the **style lock** (Step 2). The user approves the style frame there and, in the same message, the **CC0 sound list** (Step 6) — downloads need explicit approval. Everything else runs on: the strict QA loop, the fresh-agent review, the review page (linked in the final report; feedback can come later through `art.py feedback`). Only an explicit user waiver or the `YOLO` token skips the stop: a fresh reviewer subagent picks the style frame against STYLE.md, sounds stay synthesised placeholders (nothing was approved for download), and the report says both. Run-mode details: `cube_orchestrator/references/RUN_MODES.md`; the orchestrator's gates for this stage: `cube_orchestrator/references/STAGE3_ASSETS.md`.
- **Stepwise** ("stepwise" / "stop", in any language): stops at the style lock, the sound list, the review page (OK / Fix per asset) and before packing.

## Workflow

### Step 1: Manifest and setup check
1. Manifest at `plans/<game>_assets.json`; missing → return to `cube_orchestrator` (Stage 2).
2. `ART doctor M`. Codex unavailable → placeholders, and tell the user once that `codex login` brings real art (a paid provider only on their explicit opt-in, `references/ART.md` "Provider chain"). With an opted-in paid provider, `ART candidates` and `ART gen` (they call Codex) are out; the provider draws through `build_pipeline.py generate` and art.py's other tools work on its images: `references/ART.md` "No Codex".

### Step 2: Style lock (the one creative checkpoint)
1. Copy `cube_art-director/references/STYLE_TEMPLATE.md` to `assets_<game>/style/STYLE.md` and fill it from GDD §1 Art Style; its `## Prompt block` starts as the manifest's `_style` (art.py seeds it and warns when they differ; keep them equal, 60-120 words). Rules a reviewer adds go into STYLE.md's rule sections and `fixes.json`; they reach the Prompt block (and `_style`) only when they change how every prompt should read, and the block stays within 120 words (`validate` warns above).
2. Style frames, matching GDD §1 "Style frame":
   - the user gave references (images in `<root>/refs/` or `<root>/drawn/`): `ART candidates M --subject "<the style frame from GDD §1>" --n 3` → `style/candidates/`;
   - no references: draw the frame's family leaders (hero, main background, one enemy) with the Prompt block alone: `ART gen M --only <leaders>` then `ART process M --only <leaders>`. A leader whose set-mates have no raw image yet is fitted with the members that have one, and `process` prints `partial set: refit when the family is complete`: expected now; the batch's `process` refits the whole set at one shared scale (Step 3).
3. Build the **in-game mock at cube resolution**: one screen (240×240, or a 2×2 face) composed at real on-screen size → `style/mock.png` (`references/ART.md` "Mock").
4. Show the user the frames, the mock and a five-line STYLE.md summary; iterate (STYLE.md, prompts) until they approve one.
5. Lock it: put the approved image(s) into `style/anchors/` (for drawn leaders: `ART anchor M --only <leaders>`), then `ART style M` (profile + palette swatch).

### Step 3: Generate
```
python <skills>/scripts/build_pipeline.py generate --manifest M --workspace assets_<game>
```
- With Codex it first gives every later animation frame a subject reference to its first frame in `fixes.json` (a merge: existing entries keep their text, an entry that already names a `ref` — `null` = deliberately none — is untouched), then delegates to `ART gen` (draws only sprites without a raw image) and `ART process` (key, fit, shared scale per set, colour lock) → `assets_<game>/art/<name>.png`. `generate` takes `--group G` (one manifest group), `--force` (redraw) and `--jobs N` (parallel Codex runs); called directly, `ART gen` selects with `--only a,b` or `--set <group>` (a manifest `group` is an art.py set) and takes `--force` and `--jobs N` too.
- With `_panoramas`: cut the pieces first (Step 5), so each piece has its raw image before the batch; `gen` never redraws a sprite that has one (unless `--force`).
- Before the first run write what the seed cannot infer into `assets_<game>/fixes.json` (`references/ART.md` "fixes.json"): `@colour_lock` for characters, `@colour_exempt` for intended changes (wounded, broken), refs for state variants (hurt, attack, shoot → the idle), "no characters, only the effect" lines for effects.
- It also writes placeholder sounds for every manifest sound that has no sourced mp3 yet (`assets_<game>/wav/`, never overwriting a sourced one), so `sound_kit.py build` may run before or after it.
- Later art-only iterations can call art.py directly: `ART all M --jobs 3` (gen → process → qa → review).
- Exit codes: `0` ok · `2` manifest invalid (relay, back to Stage 2) · `3` missing Python module, or no image provider at all (`references/ART.md` placeholders) · `6` sprite generation failed (art.py's lines name the sprites and print the retry command) · `7` mp3 encode failed (ffmpeg).

### Step 4: Strict QA loop
For every batch:
1. `ART qa M` — exit 1 = hard failure.
2. Look at three views of each asset: raw (`raw/`), final ×4 (`qa/`), in context (on its background, next to its neighbours, at device scale — extend the mock). Read `qa/sets.png` and every animation GIF.
3. Fix every FAIL at its cause in `fixes.json` (sharper prompt line, subject ref, green key for pink subjects, `@fill`, `@pose_exempt` / `@colour_exempt` only for intended changes); redraw only what failed plus set partners that must match: `ART gen M --only a,b --force`, then `ART process M --only a,b`.
4. Repeat until every QA_RULES.md rule passes.
5. Before the user sees the batch: an independent consistency review by a **fresh subagent** — give it `style/anchors/`, STYLE.md, QA_RULES.md and `qa/sets.png`, not your conclusions — and fix what it finds.

### Step 5: Panoramas (only when the manifest has `_panoramas`)
One source picture per panorama, split into its per-screen sprites: `references/ART.md` "Panoramas". Run it right after the style lock, before Step 3's batch (the pieces' own `gen_prompt`s are only a fallback).

### Step 6: Sounds
`references/SOUND.md`: CC0 proposal (sound, event, source URL, file, licence, author, size) → the user approves → download into fresh folders → `sound_kit.py build` (layered recipes) and `sound_kit.py loop` (music) into `assets_<game>/wav/assets/` → judge with `sound_kit.py inspect` → write the measured music length into the manifest → `app_<game>/sound/CREDITS.md`. Sounds not approved or not found keep their placeholder; the hand-off lists them.

### Step 7: Launcher icon
The manifest's `launcher_icon` sprite (160×160, palette fullsize, `background: "key"`; `icon` is a reserved name) is drawn with the set and held to the same QA: a **flat-top hexagon badge** in the game's style with transparent corners in its PNG (`references/ART.md` "Launcher icon"). Copy `assets_<game>/art/launcher_icon.png` to `app_<game>/art/icon.png`, replacing the template icon; the pack takes it with `--icon`. The manifest's `icon` object decides the packed tier: the default (full colour, 160) is RAW565, so the corners render black on the dark launcher; transparent corners need palette 120 or 240. A manifest without the entry goes back to Stage 2.

### Step 8: User review page
`ART review M` → `assets_<game>/review.html` (anchors, palette, sets with onion skin, every asset: raw, final ×4, verdicts, prompt, OK / Fix + note).
- Stepwise: the user marks OK / Fix and presses "Copy feedback"; save it to a file, `ART feedback M --file <fb.json>` folds it into `fixes.json` and prints the regeneration command; redraw → Step 4 → review again until every asset is OK. Promote newly approved family leaders with `ART anchor`.
- Autonomous: link the page in the report and go on; later feedback re-enters here.
- Sounds are reviewed as a list (name, event, source, licence, length, inspect numbers); the user may listen to `assets_<game>/wav/assets/*.mp3` themselves.

### Step 9: Pack
Requires the scaffolded `app_<game>/` and the game's icon in `app_<game>/art/icon.png`. Move PNGs of sprites no longer in the manifest out of `assets_<game>/art/` (e.g. into `assets_<game>/retired/`): everything there gets atlased.
```
python <skills>/scripts/build_pipeline.py pack --game <game> --workspace assets_<game> \
    --src-dir app_<game>/src --app-dir app_<game> --manifest M --icon app_<game>/art/icon.png
```
Before writing anything it checks the set is complete (every manifest sprite has `assets_<game>/art/<name>.png`, every manifest sound an mp3 in `assets_<game>/wav/assets/` or `app_<game>/sound/assets/`) and refuses an incomplete one, naming what is missing. Then it clears its intermediates (`assets_<game>/packed/`, `assets_<game>/exported/`: frames retired from the manifest cannot survive in the pack), syncs the app's fonts (`app_<game>/art/font_*`, changed `.fnt` files and atlases re-copied) into `assets_<game>/fonts/`, atlases `assets_<game>/art/*.png`, runs `pack.py` (palette alpha, full-colour RAW565 for `color: "full"`, the launcher `ico` map from `--icon`), copies `assets_<game>/wav/assets/*.mp3` into `app_<game>/sound/assets/`, writes `app_<game>/src/app_<game>_ids.h`, centres the pivots and records its inputs in `app_<game>/.pack_inputs.json` (sha1 of the manifest, every input PNG and mp3, the fonts, the icon). It fails when the ids lack the font glyphs (labels would draw nothing) and warns when the template icon would ship.

Check after packing: `app_<game>/index.bin` exists; the ids header has a `BMP_` per sprite (plus `BMP_<anim>` / `BMP_<anim>_end`), a `SND_` per sound and `font_` glyphs; `app_<game>/art/packed/` has a `.raw` per sprite; and `python <skills>/scripts/build_pipeline.py pack-status --game <game> --workspace assets_<game> --app-dir app_<game> --manifest M` exits 0 (1 = stale or missing record; it prints what changed). The orchestrator's stage detection and delivery use the same check. Direct `pack.py` invocations, tiers and pack troubleshooting: `references/PACK.md`. Re-pack after any art, sound, font or icon change with the same command (version bump and device build: `scripts/repack_app.py`, owned by `wowcube-boilerplate`).

### Step 10: Hand-off
Print:

> Asset build complete.
> - `app_<game>/index.bin`, `art/packed/*.raw` + `*.pal`, `sound/assets/*.mp3` ready; `src/app_<game>_ids.h` with N BMP_/MAP_/SND_ constants.
> - Art: N sprites drawn with Codex, style locked on <date>, QA clean; review page `assets_<game>/review.html`.
> - Sounds: K sourced (CC0, `app_<game>/sound/CREDITS.md`), P placeholders (<names>).
> - Launcher icon: `app_<game>/art/icon.png`.

When the art came from the placeholder path, add exactly one line: graphics are temporary (no Codex login and no image key) — `codex login`, then ask to regenerate the art. Then **return control to `cube_orchestrator`**; do not start implementation.

## Constraints

- **Never edit `_ids.h`, `index.bin` or `src/app_<game>.h`.** The packer writes the first two; the third belongs to the coder agents.
- **Never invent asset names.** Every sprite/sound name comes from the manifest; a missing asset goes back to `technical_prompter`.
- **Sizes come from the manifest** (authored, pre-upscale pixels; ≤ 120 unless `flags.fullsize`); a size that reads like on-screen pixels is a manifest error — send it back, do not pack it.
- **Never replace a file the user provided by hand** unless they ask for it.
- **Never play audio**, never download before the list is approved, never type credentials, never kill processes by name (AGENT_SAFETY.md).

## Error Handling

| Symptom | Action |
|---------|--------|
| Manifest invalid (`validate` or `generate` exit 2) | Relay every printed error line; delegate back to `technical_prompter`. |
| Pack refuses an incomplete set (names the missing PNGs / mp3s) | Draw the missing sprites (Step 3) or build the missing sounds (Step 6, placeholders through `generate` if nothing was approved); a name that should not exist goes back to Stage 2. Never pack around it. |
| Missing Python module (`rc=3`, names a module) | Print the `pip install` hint; stop. |
| No image provider (`rc=3`, names the chain) | Codex not installed or not logged in and no key: ask the user once to run `codex login`; meanwhile `references/ART.md` placeholders. |
| `art.py doctor` FAIL on the login | The user runs `codex login` (ChatGPT account); never log in for them. |
| Sprite generation failed (`rc=6`) | Read art.py's per-sprite lines: "model at capacity" is retried by art.py; rerun the printed command (only missing sprites are drawn). A sprite with no `gen_prompt` goes back to Stage 2. |
| Two sprites came back as the same picture, a person inside an effect, a pink subject keyed out | Known Codex gotchas with fixes: `cube_art-director/references/CODEX.md`. |
| mp3 encode failed (`rc=7`) or `ffmpeg not found` | Install or repair ffmpeg (`winget install Gyan.FFmpeg` / distro package) and rerun. |
| Pack: `no PNGs found in assets_<game>/art` | Run Step 3 first, or the workspace path is wrong. |
| `pack-status` exits 1 after a pack | An input changed since (a redrawn PNG, a rebuilt mp3, a font, the icon, the manifest): pack again. |
| Pack: `BMFont(s) in app art/ but no font_ glyphs` | The fonts did not reach the pack: `assets_<game>/fonts/` must hold each `font_*.fnt` with its `font_*_0.png`; fix and rerun. No `app_<game>/art/font_*.fnt` at all means the app was not scaffolded from the template (labels would draw nothing) — scaffold first. |
| Pack: template icon warning | Step 7 was skipped — make the icon, pass `--icon`. |
| An opaque background renders in wrong colours (magenta) | Make it `color: "full"` + `"flags": {"alpha": false, "bg": true}` in the manifest (Stage 2) and re-pack. |
| Other pack failures | `references/PACK.md`. |
