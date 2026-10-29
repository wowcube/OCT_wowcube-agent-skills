---
name: cube_art-director
description: "Style-locked art production with Codex for artists and art leads: the artist draws or gives a style reference, Claude writes the style bible with them, generates the assets through the local Codex CLI (ChatGPT subscription, no API key), and acts as a strict art director that measures and rejects every deviation from the artist's style until the set is consistent. Use when an artist or designer wants sprites, icons, tiles, backgrounds or animation frames generated in THEIR style: \"generate assets in my style\", \"here is my reference, make the rest\", \"keep the style consistent\", \"draw the walk cycle from my sketch\", \"art director\", \"ассеты в моём стиле\", \"по референсу\". Standalone (works outside any game pipeline); cube_asset-builder also uses it as its Codex generation path."
---

# Art director: style-locked generation with Codex

The artist owns the style. Claude's job is to turn their references into an
explicit, checkable style lock, drive Codex to draw the assets, and refuse
everything that drifts from that lock, so the artist spends their time on
taste decisions instead of catching inconsistencies.

```
artist refs / drawings ──► style bible (STYLE.md) + anchors ──► profile.json (measured)
                                        │
asset list ──► Codex draws (anchors + subject refs attached) ──► key + fit ──► QA (numbers + eyes)
                                        ▲                                         │ fail
                                        └──────── fixes.json (every correction) ◄─┘
                                                                                  │ pass
                                     review.html ──► artist: OK / Fix + notes ──► anchors grow
```

## Ground rules

- **The artist's references are the law.** Never "improve" the style on your own; propose changes, the artist decides. Every accepted departure is written under "Approved exceptions" in STYLE.md.
- **Strict reviewer.** An asset that breaks a rule in `references/QA_RULES.md` is a FAIL even if it "basically works". Iterate (prompt, references, processing) until it passes; escalate only when a rule truly cannot be met, saying what was tried. Never show the artist a batch that fails QA.
- **Codex on the subscription, strongest model, maximum effort** (`references/CODEX.md`). No OpenRouter, no paid image APIs, never ask for API keys.
- **Everything reproducible**: prompts in the spec, corrections in `fixes.json`, anchors in `style/anchors/`. A regeneration must reproduce every fix without the chat history.
- The artist does not need to touch a terminal: Claude runs every command and shows the results (review page, sheets).

## Who approves (standalone vs inside the WowCube pipeline)

- **Standalone** (an artist or art lead drives it): every approval in the workflow below is theirs: the style bible (2), the style frame (3), each family leader (4), the review page (6).
- **Inside the WowCube pipeline** (`cube_asset-builder`, driven by `cube_orchestrator`), **autonomous run** (the default): the only user stop is the orchestrator's **style lock**: style frame, in-game mock, the style bible's short summary and the sound list in one message (`cube_orchestrator/references/STAGE3_ASSETS.md` §2). Family leaders and every batch are approved by the independent fresh-agent reviewer (5, step 5), never by stopping for the user; the review page is linked in the final report. An explicit waiver or the `YOLO` token lets that reviewer approve the style frame too.
- **Inside the pipeline, stepwise run**: the user takes the artist's role at every approval.

## Tool

`scripts/art.py` (Python 3.10+, `pip install pillow numpy`):

| Command | What it does |
|---|---|
| `doctor [<spec>]` | setup check: Python deps, Codex CLI found, ChatGPT login, chosen model/effort, spec valid |
| `init <dir>` | new project: `art.json`, `style/STYLE.md` (from `references/STYLE_TEMPLATE.md`), `style/anchors/`, `style/candidates/`, `refs/`, `drawn/` |
| `candidates <spec> --subject "..." [--n 3]` | first style frames BEFORE the lock: the artist's `refs/` + `drawn/` are attached as style references -> `style/candidates/` |
| `style <spec>` | measures the anchors -> `style/profile.json` + `palette.png` (palette, light range, saturation ceiling, outline). One anchor = default thresholds; 2+ anchors widen them to what the anchors need, capped at 2x the default, with a warning when the anchors look like different styles (split them into families) |
| `anchor <spec> --only a,b` | promotes approved assets to anchors and rebuilds the profile |
| `gen <spec> [--only a,b] [--set s] [--force] [--jobs 3]` | Codex draws every asset without a raw image (anchors + subject/sketch refs attached; assets whose `subject_ref` is drawn in the same batch go second) |
| `process <spec> [--only a,b]` | key out the backdrop, fit to size; `motion` sets share one scale and are centroid-aligned; `colour_lock` frames are colour-matched. A set is always fitted together; while some members still have no raw image (a family leader drawn first), the members that have one are fitted together and it prints `partial set: refit when the family is complete` |
| `qa <spec> [--only a,b] [--set s]` | size, real cut-out, key, alpha, fill, set rules (scale, jitter, colour lock) and the style score per asset; exit 1 on hard failures; sheets + per-animation GIFs in `<ws>/qa/`. Scope it to a family leader while the rest is still pending |
| `review <spec>` | `<ws>/review.html`: anchors, palette, sets with onion skin, every asset (raw, final x4, verdicts, prompt) with OK / Fix + note |
| `feedback <spec> --file fb.json` | folds the page's "Copy feedback" JSON into `fixes.json` and prints the regen command |
| `all <spec>` | gen -> process -> qa -> review |

`<spec>` is `art.json` (format at the top of `scripts/art_spec.py`) or a
WowCube manifest `plans/<game>_assets.json` (then the workspace is
`assets_<game>/`, the style lives in `assets_<game>/style/`, and final images
land in `assets_<game>/art/` where the WowCube pack stage reads them; give
every sprite an explicit `"background": "key" | "opaque"`).

Project layout (art.json):
```
<project>/art.json            asset list + style paths
<project>/refs/  drawn/       artist references and drawings (inputs)
<project>/style/STYLE.md      style bible;  anchors/  approved anchors;  candidates/  first style frames
<project>/style/profile.json  measured style lock (+ palette.png)
<project>/art_work/raw/       model output (+ keys.json backdrop per asset, prompts.json, logs/)
<project>/art_work/final/     exact-size images (the deliverable)
<project>/art_work/qa/        report.txt/json, all.png (every final), sets.png + GIFs (sets only), provenance.json
<project>/art_work/fixes.json every correction, replayed on regeneration
<project>/art_work/review.html the artist's review page
```
Run commands from anywhere as `python <skill>/scripts/art.py <cmd> <path to art.json>`; the
commands the tool prints are copy-pasteable (interpreter, script, spec, workspace).
`candidates` and `gen` need the Codex CLI; `style`, `anchor`, `process`, `qa`, `review` and
`feedback` work on whatever images are in the raw folder (in the WowCube pipeline also a
paid provider's, but only when the user explicitly asked for one and agreed to pay:
`cube_asset-builder/references/ART.md` "No Codex"). Codex must be logged in with ChatGPT:
`gen` refuses an API-key login, which would bill that key.

## Workflow

### 1. Intake
Ask for: the references (their own drawings, finished sprites, or mood images
they like), the list of assets with sizes (or a manifest), where the art will
be used (WowCube cube screens: 240x240, sprites usually authored at half size;
other targets: say so), and hard constraints (transparent background, palette
limits, text). Run `art.py init`, put references in `refs/`, drawings in
`drawn/`.

### 2. Style bible
Study the references closely (zoom in: outline pixels, tone steps, light
direction, palette). Fill `style/STYLE.md`: one-line summary, viewpoint,
palette with roles, rendering (outline, shading, light, detail at final size),
proportions, Do/Don't, and the operational `## Prompt block` that is injected
into every prompt. Show the artist a short summary and get explicit approval;
their corrections go straight into the file. (Pipeline, autonomous: the summary rides
with the style-lock message; no separate stop.)

### 3. Anchors (the style lock)
- If the artist supplied finished art in the target style, those images are the anchors.
- Otherwise draw 1-3 **style frames** with `art.py candidates --subject "<a representative character, prop or scene>"` (refs/ and drawn/ are attached), show them, iterate until the artist approves one. Never mass-generate before an approved frame.

Put the approved images in `style/anchors/`, list them in `art.json`
(`style.anchors`), run `art.py style`. Check the palette swatch with the artist.

### 4. Family leaders first
For each family (a character, a prop group, the UI kit, effects), generate ONE
leader asset (`gen --only <leader>`), run `process --only <leader>` + `qa --only <leader>`, look
at it, fix, get the artist's OK (pipeline, autonomous: the fresh reviewer's OK), then
`art.py anchor --only <leader>` (it stores the approved look: keyed and colour-matched like
the final). While the rest of its set has no raw image, `process` fits the leader alone and
prints `partial set: refit when the family is complete`: expected. The rest of the family is
generated with the leader as `subject_ref` (same design, only the pose/state changes) and
held to the grown profile; the next `process` refits the complete set at one shared scale
(look at the leader again in `qa/sets.png`; its anchor keeps the approved look).

### 5. Batch + strict review loop
For every batch:
1. `art.py gen` (only what is missing or failed), `process`, `qa`.
2. Look at three views of each asset: raw output, final x4, and in context (on its background/next to neighbours at the real display scale). Read `qa/sets.png` and the GIFs for every set.
3. Every FAIL: fix the cause (sharper prompt line in `fixes.json`, better subject ref, green key for pink subjects, `fill`, `pose_free`/`colour_exempt` only for intended changes) and regenerate only what failed plus set partners that must match.
4. Style score FAIL: decide drift vs intended exception. Drift -> fix and redraw. Intended -> propose it to the artist; once accepted, `style_check: false` + a line under "Approved exceptions".
5. Before the artist sees the batch: an independent consistency review by a fresh subagent (give it the anchors, STYLE.md, QA_RULES.md, `qa/all.png` and `qa/sets.png` when there are sets, not your conclusions). Codex in read-only mode is a good second opinion too (`references/CODEX.md`).

### 6. Artist review
`art.py review`, send/open `review.html`. The artist marks OK / Fix with
notes and presses "Copy feedback"; paste it into a file and run
`art.py feedback --file`. Notes become `fixes.json` entries; recurring notes
("outlines too thin", "too shiny") become STYLE.md rules and Prompt block
lines. Redraw, re-review, repeat until every asset is OK. Promote newly
approved family leaders to anchors.

### 7. Delivery
`final/` (or `assets_<game>/art/`) holds the exact-size PNGs; `raw/` the
model outputs; `style/` the bible, anchors and profile; `review.html` the
last review. For WowCube, hand off to the pack stage (cube_asset-builder).

## Asset spec cheatsheet (art.json)

```json
{"name": "hero_walk_01", "size": [40, 40], "set": "hero", "motion": true, "colour_lock": true,
 "subject_ref": "hero_idle_00", "prompt": "the heroine mid-stride, left foot forward, facing down"}
```
`background: "opaque"` for full-frame pictures, `sketch: "drawn/pose.png"`
to follow the artist's drawing, `source: "drawn/logo.png"` for art the artist
made themselves (no redraw: it is copied in as the raw image, then keyed/fitted and checked like any other asset), `fill: 0.8` for tiles that must cover their cell,
`style_check: false` for approved departures, `pose_free: true` for frames
whose pose change is the point.

## Prompt craft that worked

- Describe the subject, pose and colours; let the Prompt block and the anchors carry the style. Do not re-describe the style per asset in different words (it drifts).
- Name the view every time for non-standard assets ("flat front view" for UI in a top-down game).
- For animation frames, name the phase and what must stay identical ("same character, same tiara, same dress length, only the legs move").
- For effects (flash, blast, slash): "no characters, no objects, only the effect", or the anchor's content leaks in.
- Square canvas, single subject, clear margin, flat key backdrop; the processor crops and scales.
