# Stage 3: assets (cube_orchestrator reference)

Style lock, art, sound, launcher icon, fonts, pack. The work is done by
`cube_asset-builder`, whose Codex path is `cube_art-director`; this file is the
orchestrator's order of steps and its gates. Read `cube_art-director/SKILL.md`,
`cube_art-director/references/QA_RULES.md` and `cube_art-director/references/CODEX.md`
before the first generation.

Per-game workspace `<ws>/assets_<game>/` (never one shared `assets/`):

| Path | Holds |
|---|---|
| `style/` | `STYLE.md` (style bible), `anchors/` (the lock), `candidates/`, `profile.json`, `palette.png`, `mock.png` |
| `raw/` | Codex output, prompts and keys used |
| `art/` | final exact-size PNGs; the pack reads them from here |
| `qa/` | QA sheets (`all.png`: every final at device scale; `sets.png` + GIFs when the manifest has sets) and `qa/sim/` simulator frames |
| `review.html`, `fixes.json` | the review page; every correction (a regeneration replays them) |
| `sound_src/` | approved downloads (one folder per source), `recipes.json` |
| `wav/assets/` | engine mp3s; the pack copies them into `app_<game>/sound/assets/` |
| `fonts/` | BMFonts copied in by the pack |

Art tool, run from `<ws>`: `python <skills>/skills/cube_art-director/scripts/art.py <command> plans/<game>_assets.json`
(it finds `assets_<game>/` itself). Commands below abbreviate it as `art.py <command> <manifest>`.

The infra gate has already scaffolded `app_<game>/` (the pack writes into it).

## 1. Gate the manifest (before any generation)

Return to Stage 2 (`technical_prompter`) when a check fails; never patch the manifest
yourself. Tiers, sizes and limits are in `<skills>/templates/app_ai_template/API.md`.

First the provider-free check (it never generates and never touches the network; exit 0
= valid, 2 = errors, each printed):

```
python <skills>/scripts/build_pipeline.py validate --manifest plans/<game>_assets.json
```

It covers the schema, names, sizes against the tier limits, the `background` field, the
`launcher_icon` entry and the Codex prompt rules it can check. Then look at what it
cannot judge (sizes that read like on-screen pixels, panoramas, the sound plan):

- **Names**: `[a-z][a-z0-9_]*` (a letter first), at most 23 characters, unique, not
  reserved (`pal`, `0`, `icon`, `zero`, `none`, `last`, `ico`, `ico_idle`, `ahover`,
  `bmp_none`, `bmp_last`, `bmp_0`, `map_none`, `map_last`), not shaped like a packer font
  glyph (`font_<x>_<5 digits>`) and not an animation's alias (`<base>`, `<base>_end`).
  The launcher icon is e.g. `launcher_icon`.
- **Sizes** are authored pixels: every sprite without `flags.fullsize` at most 120×120
  (drawn ×2); only `flags.fullsize` sprites go up to 240×240 (drawn 1:1). A sprite sized in on-screen
  pixels (a quarter-screen hero at `[60, 60]` instead of `[30, 30]`) is a sizing error.
- **Opaque backgrounds** are `color: "full"` (a palette `bg` sprite once rendered magenta).
- **`background`, the backdrop decision**: every sprite states `"key"` (a cut-out:
  characters, props, effects, UI, text) or `"opaque"` (a full-frame picture:
  backgrounds, tiles, panorama pieces, every `color: "full"` or `flags.bg` sprite).
  art.py wraps each prompt itself: the style block, a square canvas with one subject and
  a clear margin, and for `key` sprites a flat `#FF00FF` backdrop (`#00FF00` when the
  subject is pink or magenta) that it keys away afterwards. Opaque pictures get no
  backdrop and are never keyed.
- **`gen_prompt` describes the subject only** (`technical_prompter` Step 4a): what it
  is, its colours, which way it faces, the framing, frame phases, "no characters" for
  effects, holes that must stay solid described as dark. It never names a backdrop
  colour (except `#00FF00` to force the green key on a pink subject), never says
  "transparent background" and never gives a pixel size (the model cannot; fitting to
  `size` is processing). Later animation frames are drawn from the first frame.
- **Across faces**: scenery that spans faces is one panorama split per screen,
  continuous and upright around the four side faces; unique objects (sun, moon)
  appear exactly once on the cube.
- **Animation**: 20 fps is the hardware cap; there is no pack-size or clip-length
  budget (many frames, even video sequences, are fine). "One animated full-screen
  (fullsize) picture per physical module" is the owner's guideline, informational until
  the owner confirms it: mention it, never block or send the manifest back for it.
- **Sounds**: one entry per event moment plus a music loop (unless the GDD explicitly
  says "no music"), same naming rules.
- **Launcher icon**: one sprite `launcher_icon` (`icon` is reserved), `[160, 160]`,
  `color: "palette"` + `flags.fullsize`, `background: "key"`: a flat-top hexagon badge in
  the game's style with transparent corners in its PNG. The **packed** tier comes from
  the manifest's top-level `icon` object: the default (full colour, 160) is RAW565, so
  the corners render black on the dark launcher; transparent corners need
  `"icon": {"color": "palette", "side": 120}` (drawn ×2) or `240` (fullsize). Details:
  `cube_asset-builder/references/ART.md` "Launcher icon".

## 2. Style lock: the one creative checkpoint

Runs in every mode. Only an explicit user waiver ("стиль не согласовывай") or the
`YOLO` token skips the user's approval. *(stepwise)* First ask the source: Codex art,
the user's own art (§8), or PSDs from an artist (§9).

1. **Style bible.** Copy `<skills>/skills/cube_art-director/references/STYLE_TEMPLATE.md`
   to `assets_<game>/style/STYLE.md` and fill it from the GDD's art direction and any
   references the user gave (references in `<ws>/refs/`, their drawings in
   `<ws>/drawn/`). Its `## Prompt block` is injected into every prompt.
2. **Style frames.** With references: `art.py candidates <manifest> --subject "<a representative scene of this game>" --n 3`.
   Without: draw the family leaders (the hero, the main backdrop, one prop or UI
   piece) with `art.py gen <manifest> --only <leaders>`, then
   `art.py process <manifest> --only <leaders>` and `art.py qa <manifest> --only <leaders>`.
   A leader whose set-mates have no raw image yet is fitted on its own and `process`
   prints `partial set: refit when the family is complete`: expected here; the whole
   set is refitted at one shared scale once the family is drawn (§3). `candidates` and
   `gen` need Codex; without it see the fallbacks at the end of §3.
3. **In-game mock at cube resolution.** Compose one face (four 240×240 screens with
   the 18 px gaps) from the leaders exactly as the game will draw them: palette
   sprites scaled ×2 nearest-neighbour, fullsize ones 1:1, a HUD line. Save it as
   `assets_<game>/style/mock.png` (a few lines of Pillow).
4. **Sound list** (§4.1) prepared at the same time, so the user answers once.
5. **Show the user, one short message**: the style frame(s), the mock, the one-line
   style summary from STYLE.md, the sound list with licences and sizes. Ask which
   frame, what to change, whether to download the sounds. Iterate until the style is
   approved; corrections go into STYLE.md.
6. **Lock it.** Put the approved images into `assets_<game>/style/anchors/` (generated
   assets: `art.py anchor <manifest> --only <names>`), run `art.py style <manifest>`
   (profile + palette swatch), record in the context:
   `"style_lock": {"status": "approved", "anchors": [...], "date": "..."}` (shape:
   `AGENT_BRIEFS.md`, "Context file").
   One profile covers the whole set, so anchor one leader of **every** family together.
   Anchoring a single family (the stone pad) made every other family fail the measured
   palette score when STYLE.md gives each family its own colour role (gold basket, cyan
   orb). With all leaders anchored, `style` may warn that the anchors "may not be one
   style": expected for deliberate colour roles; the thresholds widen to cover them
   (capped at 2x). An object whose colours stay outside even then goes to `@style_exempt`
   + "Approved exceptions".

Before the lock nothing can be measured (`art.py qa` reports style as UNCHECKED until `art.py style` has a
profile): the style frames are judged by eye against STYLE.md, the GDD's Art Style and the mock.
Waiver: dispatch a fresh reviewer (§10, style-frame variant) on the candidates against STYLE.md, lock the
best one, record `"status": "waived"`; the final report says the user did not approve
the style. User-supplied art: `"status": "user_art"` (their art is the lock).

## 3. Generate and review (strict)

Through `cube_asset-builder`:

1. **Family leaders first**: one asset per family (character, prop group, UI kit,
   effects): `gen --only <leader>`, `process --only <leader>` (the partial-set warning
   above is expected), `qa --only <leader>`, look, fix, then
   `art.py anchor <manifest> --only <leader>`. The rest of the family uses the leader as
   `subject_ref` and is held to the grown profile.
2. **The batch**: `art.py all <manifest> --jobs 3` (gen, process, qa, review). Its
   `process` refits every now-complete set at one shared scale, leaders included: look
   at the leaders again in `qa/sets.png` (the anchors keep the approved look).
3. **The loop**, for every batch: look at three views of each asset (raw output, final
   ×4, in context at device scale) plus `assets_<game>/qa/sets.png` and the set GIFs.
   Every FAIL gets a cause-level fix (a prompt line in `fixes.json`, a better subject
   reference, the green key, `fill`; exemptions only for intended changes) and a redraw
   of what failed plus the set partners that must match:
   `art.py gen <manifest> --only <names> --force`, then `process` and `qa`.
   **Repeat until every rule in QA_RULES.md passes.** There is no "accept after N
   rounds". Escalate only when a rule genuinely cannot be met, saying what was tried:
   *(stepwise)* ask the user; autonomous: simplify the asset within its manifest entry
   (same name and size: fewer distinct poses, a simpler subject) and list it in the
   final report.
   **A budget, when one is set, ends the redraws, not the rules.** If the user (or the
   run's brief) caps the art (`art_budget: {"images": N, "minutes": M}` in the context;
   none by default), count every Codex image against it. Once it is spent: no more
   redraws; fix what processing can fix (`process` options, `@post`), then waive each
   style or set rule still failing where `art.py qa` reads waivers: `fixes.json`
   `@style_exempt` / `@colour_exempt` / `@pose_exempt` / `@fill` (plus the line under
   "Approved exceptions" in STYLE.md, with the finding) and list them in the final report
   as `accepted_under_budget`. A hard failure no key waives (wrong size, key colour left,
   an empty frame) is a processing problem: fix it with `process`; if one remains, Stage 3
   is not done (*(stepwise)* ask; autonomous: report it and stop before packing). On a real run three
   fresh reviews of 9 sprites took ~42 min and ~580k tokens, longer than all the drawing:
   say so when the user sets a tight cap.
4. **Fresh-agent consistency review** (§10) before anyone sees the batch; its findings
   go through the same loop. A read-only Codex pass (`cube_art-director/references/CODEX.md`)
   is a useful second opinion when you and the reviewer disagree.
5. **Review page**: `art.py review <manifest>` writes `assets_<game>/review.html`.
   *(stepwise)* The user marks OK / Fix and presses "Copy feedback"; save it to a file,
   run `art.py feedback <manifest> --file <fb.json>` (notes become `fixes.json`
   entries), redraw, re-review until all OK. Autonomous: link the page in the final
   report.

**Fallbacks**, only when Codex cannot draw:
- by default, agent-drawn placeholders: they keep the build going and are never presented as final;
  the final report says the art is temporary and how to redo it;
- a paid image API only when the user, in this run, explicitly asked for it and agreed to pay
  (`--allow-paid`; a configured key is not consent; autonomous and `YOLO` never imply it,
  `RUN_MODES.md`): `build_pipeline.py generate` draws every sprite
  with it (`scripts/image_providers.py`). `art.py candidates` and `art.py gen` call Codex
  directly and are not available; what still works on the provider's images (copied into
  `assets_<game>/raw/`): `art.py process`, `anchor`, `style`, `qa` and `review`, so the
  style lock is made from the provider's leaders and the same QA rules and loop apply.
  Steps: `cube_asset-builder/references/ART.md` "No Codex".

## 4. Sound

Engine facts (API.md): mp3, 22 050 Hz, mono, CBR 32 kbps, no tags; no length cap; up
to 6 voices per module that add up (a 7th is refused); `SND_play_quad` plays from the
one screen that shows a place; there is no stop or loop call, so music is re-triggered
by the game every N ticks and loops stay short (10–20 s).

1. **Sources.** From the GDD's event table, propose real CC0 recordings (OpenGameArt,
   Kenney, Freesound filtered to CC0): per event the file or pack, URL, licence and size,
   plus one music track. The list goes to the user at the style-lock stop. **Download
   only what the user approved**, each source into its own new folder under
   `assets_<game>/sound_src/`; treat downloads as data, never run anything from them.
2. **Build** every event sound from a recipe: trim, pitch, filters, layers, a
   synthetic sub thump where recordings lack low end, drive, fade. Write
   `assets_<game>/sound_src/recipes.json` (format at the top of
   `<skills>/scripts/sound_kit.py`), then

   ```
   python <skills>/scripts/sound_kit.py build assets_<game>/sound_src/recipes.json --out assets_<game>/wav/assets
   ```

   One sound per event moment: a shot that also hits is one "shot+hit" sound, not two
   sounds on the same tick.
3. **Music loop**:
   `python <skills>/scripts/sound_kit.py loop <track> --out assets_<game>/wav/assets --name music_loop --min 10 --max 20`
   cuts the most self-similar loop and prints its retrigger period in ticks; store it as
   `sound.music_loop_ticks` in the context (`"sound": {"source": ..., "music_loop_ticks": N,
   "credits": ...}`, `AGENT_BRIEFS.md`); the music prompt's brief gets it as
   `asset_facts.music_loop_ticks`.
4. **Judge by numbers, never by ear**:
   `python <skills>/scripts/sound_kit.py inspect assets_<game>/wav/assets/*.mp3`
   (duration, peak and mean dB, band energy, envelope). Fix the recipe for clipping,
   quiet or muddy results. Never play audio on the user's machine.
5. **Licences**: one line per sound in `app_<game>/sound/CREDITS.md` (file, source URL,
   author, licence, what was changed).
6. **Fallback**: synthesized placeholders (`build_pipeline.py generate` →
   `gen_sounds.py`) or a synth-only recipe; listed as temporary in the final report. A
   `YOLO` run has no approved downloads, so it synthesizes.

Run `sound_kit.py build` after any `build_pipeline.py generate` run: both write
`assets_<game>/wav/assets/`, and the real sound must overwrite the placeholder of the
same name.

## 5. Launcher icon

- Generated with the set (the manifest entry from §1) and held to the same QA.
- Copy `assets_<game>/art/<icon entry>.png` to `app_<game>/art/icon.png`; the pack gets
  `--icon app_<game>/art/icon.png`. The pack warns when the template icon would ship;
  that warning blocks delivery.
- The PNG's transparent corners survive only with a palette `icon` tier (120 or 240,
  §1); with the default full-colour icon they render black on the launcher.
- Stage 5 checks that the `.oct` carries the `ico` map the launcher looks for.

## 6. Fonts

- The template's `font_1..3` (BMFont binary v3 + `font_<n>_0.png`, in `app_<game>/art/`)
  cover ASCII. Every pack syncs them into `assets_<game>/fonts/` (a changed `.fnt` or
  atlas is copied again, stale pages are replaced) and fails when `_ids.h` lacks the
  `font_` glyphs (every label would draw nothing).
- Another font only when the GDD asks: BMFont binary v3, one page, ASCII 0x20–0x7F,
  `font_<n>.fnt` + `font_<n>_0.png` (n = 1..3) in `app_<game>/art/`.

## 7. Pack

The repo's python packer packs the AI-manifest path (it reproduced a shipped game's
pack byte for byte, and it understands the manifest tiers). From `<ws>`:

```
python <skills>/scripts/build_pipeline.py pack --game <game> --workspace assets_<game> --src-dir app_<game>/src --app-dir app_<game> --manifest plans/<game>_assets.json --icon app_<game>/art/icon.png
```

Before writing anything it refuses an incomplete set: every manifest sprite needs
`assets_<game>/art/<name>.png` and every manifest sound an mp3 in
`assets_<game>/wav/assets/` or `app_<game>/sound/assets/` (it names what is missing).
It then clears its intermediates (`assets_<game>/packed/`, `assets_<game>/exported/`),
so frames retired from the manifest cannot linger in the pack, syncs the fonts (§6), and
writes `app_<game>/index.bin`, `art/packed/*.raw` + `*.pal`, `sound/assets/*.mp3`,
`src/app_<game>_ids.h` (record index = asset id; `BMP_`/`MAP_`/`SND_` enums) and
`app_<game>/.pack_inputs.json` (sha1 of the manifest, every input PNG and mp3, the fonts
and the icon). PNGs of sprites no longer in the manifest are still atlased from
`assets_<game>/art/`: move them out (e.g. to `assets_<game>/retired/`) before packing.

Accept it when: exit code 0, no template-icon warning, `BMP_<name>` for every manifest
sprite, `font_` entries present, and

```
python <skills>/scripts/build_pipeline.py pack-status --game <game> --workspace assets_<game> --app-dir app_<game> --manifest plans/<game>_assets.json
```

exits 0 (1 = an input changed after the pack, or no record: pack again). Stage
detection and delivery use the same check. Never hand-edit `_ids.h`. Then the Stage 3→4
boundary (stepwise: asset counts, then wait).

## 8. The user's own art (Path B)

Hand the user the exact spec from the manifest: `<name>.png`, exact size, RGBA with
transparency unless the sprite is opaque (`color: "full"`), complete frame sets, the
GDD style; files go to `assets_<game>/art/`. Sounds (`.wav` / `.mp3`) go to
`assets_<game>/sound_src/` and through `sound_kit.py build`. `0.png` is made by the
pipeline, never by the user.

**Completeness check, every mode**: list every missing file by name and size (the
pack refuses an incomplete set anyway, §7). *(stepwise)* Wait for them. Autonomous:
fill the gaps through the Codex path with the user's art as the anchors, and report it.
Run `art.py qa <manifest>` on the delivered files (size, key, alpha) and report
problems before packing (§7).

## 9. PSD-authored art (artists in Photoshop)

Artists who deliver PSDs use the SDK's official packer instead of the manifest path:
`app_<game>/art/octpack.json` lists the inputs (`assets` PSDs, `maps`, `fonts`, `raw`
PNG folders), `art/!pack.txt` assigns palette groups and flags (`<FULLSIZE>`,
`<ALPHA>`, `<ARGB>`, `<SOFTKEY>`, `<HALF>`); pack with
`powershell -File <ws>\octavios\tools\pack.ps1 <ws>\app_<game>` (`pack.sh` on Linux), or
`<skills>/scripts/repack_app.py`, which sees `art/octpack.json` first and runs the
official `uv run --project <ws>/octavios/octpacker octpack-pack <app>`.
`octpack-build` then re-packs from those sources at Stage 5. There is no adapter from
our manifest to octpack yet (open item); do not mix both paths in one app.

## 10. Consistency reviewer (fresh subagent)

**Style-frame variant (before the lock; used for a waived lock).** Inputs: STYLE.md, the GDD's Art Style section,
the candidates (raw + final), the in-game mock. Task: pick the candidate that best fits STYLE.md and the GDD, list
what must change before it can anchor the style, or reject all. Output JSON:
`{"task": "style_frame_approval", "verdict": "approve|revise|reject", "anchors": ["<file>"], "findings": [...]}`.
The batch variant below needs anchors and `qa/sets.png`, which exist only after the lock.

Dispatched with the Agent tool. Give it the files, not your conclusions.

```
You are an independent art reviewer for a WowCube game. You never generate or edit
images; you inspect and report.

<Safety block from references/AGENT_BRIEFS.md>

## Task
{"task": "asset_consistency", "game": "<game>",
 "style_bible": "<ws>/assets_<game>/style/STYLE.md",
 "anchors_dir": "<ws>/assets_<game>/style/anchors",
 "rules": "<skills>/skills/cube_art-director/references/QA_RULES.md",
 "sets_sheet": "<ws>/assets_<game>/qa/sets.png (only when the manifest has sets)",
 "all_sheet": "<ws>/assets_<game>/qa/all.png",
 "art_dir": "<ws>/assets_<game>/art",
 "manifest": "<ws>/plans/<game>_assets.json",
 "gdd": "<ws>/plans/<game>_gdd.md"}

## Rules
1. Read STYLE.md and QA_RULES.md, look at every anchor, then judge every asset and
   every set against them. Form your own view; no earlier verdicts are given to you.
2. Check rules S1-S5, A1-A8, B1-B7, plus the cube rules: panoramas continuous across
   the side faces, unique objects once, everything readable at device scale.
3. Be specific: asset, rule id, what is wrong, what would fix it.
4. Return only this JSON:
{"agent": "asset_consistency", "status": "pass|fail",
 "findings": [{"asset": "hero_walk_02", "rule": "B2", "severity": "major|minor",
               "description": "...", "fix": "..."}],
 "summary": "one sentence"}
```

`fail` sends the findings through the §3 loop; then dispatch a new reviewer (fresh,
not the same one) on the redrawn set.
