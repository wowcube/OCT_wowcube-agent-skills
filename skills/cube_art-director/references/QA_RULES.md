# QA rules: the reviewer's contract

The goal is a set that is *good*, not merely *present*. Claude reviews every
asset against these rules and makes Codex redraw until each one passes. "It
basically works" while a rule is broken is a FAIL. There is no "good enough
after N tries": change the prompt, the references or the processing until it
passes, and only escalate to the artist when a rule genuinely cannot be met,
saying what was tried.

`art.py qa` measures what can be measured (exit 1 on a hard failure); the
visual rules need eyes on three views of every asset: the raw model output,
the final image at x4 nearest-neighbour, and the asset composed in its real
context (on the game background, next to its neighbours, at device scale).
Most defects show in only one of the three.

## S. Style lock (the artist's references are the law)

| # | Rule | How checked |
|---|------|-------------|
| S1 | **Matches the anchors**: palette family, outline colour and weight, shading steps, light direction, detail density. | `qa` style score (palette distance, off-palette share, over-saturation, light/dark range, outline) + visual side-by-side with the anchors |
| S2 | **Matches the style bible's Do/Don't list** line by line. | visual, against STYLE.md |
| S3 | **No content leak** from a reference: only the style is copied, never a character, prop, composition or background of the anchor (a person inside a muzzle-flash sprite = FAIL). | visual |
| S4 | **Deliberate departures are declared**, never silent: an asset that must break the palette (sky, logo, UI, glowing effect) is marked `style_check: false` (or `@style_exempt`) and listed under "Approved exceptions" in STYLE.md once the artist accepts it. | spec + STYLE.md |
| S5 | **The lock grows with approvals**: once the artist approves a new family's first asset (first character, first prop; in an autonomous WowCube run the fresh reviewer approves it), promote it with `art.py anchor` so the rest of that family is held to it. | workflow |

## A. Every asset

| # | Rule | How checked |
|---|------|-------------|
| A1 | **Right subject, nothing else**: exactly what the prompt names; no extra props, no text unless the asset is text. | visual |
| A2 | **Viewpoint** as the style bible says (a front-view window in a top-down room = FAIL). | visual |
| A3 | **Exact size**, transparent or opaque as specified. | qa |
| A4 | **Clean key**: no key-colour pixels, no fringe; no semi-transparent pixels when alpha is binary. Holes that should be solid (glass, gaps) must not be keyed out: draw them dark in the prompt. A subject that uses pink/magenta gets the green key. | qa + visual |
| A5 | **Footprint**: objects that occupy a cell/slot fill it (`fill`), nothing looks smaller or bigger than its gameplay size. | qa (`fill`) + in-context view |
| A6 | **Readable at final size** on its real background: silhouette and key features survive the downscale (if a tiara or a weapon vanishes, enlarge or simplify it in the prompt). | final x4 + in-context |
| A7 | **Text is spelled exactly.** | visual |
| A8 | **Names** are `[a-z][a-z0-9_]*` (a letter first) and short (WowCube packer: 23 characters max, no reserved name; `build_pipeline.py validate` checks a manifest). | spec validation |

## B. Sets and sequences (the strictest part)

A set = assets with the same `set` and size: animation frames, a character's
idle/walk/attack, state pairs (intact/broken, full/empty).

| # | Rule | Threshold |
|---|------|-----------|
| B1 | **Same design in every frame**: same character, costume, proportions; only the described pose changes. Later frames are generated with the first as `subject_ref`. | visual (onion skin, flipbook) |
| B2 | **No scale pumping** inside one animation (`motion` sets share one scale; frames are never fitted to their own bbox). | area 0.85-1.15, height 0.93-1.07 vs the anim's first frame (hard for colour-locked characters; `pose_free` frames such as an attack lunge only warn) |
| B3 | **No position jitter**: frames aligned on the centre of mass. | centroid drift <= 1.0 px |
| B4 | **Colours logical within a set**: one character keeps its colours (`colour_lock`); a change only where it means something (wounded, broken, empty) and marked `colour_exempt`. | mean dRGB <= 10 |
| B5 | **The loop reads as the intended motion**, no flicker of random details. | flipbook GIF |
| B6 | **States are distinguishable** at final size while keeping the footprint. | final x4 + in-context |
| B7 | **Paired scenes line up** (day/night versions of one background): generated with the first as `subject_ref`. | visual overlay |

## Reporting

- Per asset: PASS, or what failed and what was changed.
- Never present a set to the artist while `qa` fails or a visual rule is knowingly broken.
- Every fix goes to `fixes.json` (or the spec), never only into the chat, so a regeneration reproduces it.
- Before the artist sees a batch: an independent consistency review by a fresh agent (no anchoring on your opinion), then the review page.
