---
name: cube_svg-design
description: >-
  Render WowCube sprites as scalable SVG, then convert to PNG via cairosvg.
  Use this skill when the active style profile is `minimalist_flat`,
  `cartoon_thick_outline`, or `realistic_render`. For `detailed_pixelart`,
  `retro_8bit`, or `painterly_storybook` use `canvas-design` instead — those
  presets are raster-native and SVG would only get in the way.
---

# WowCube SVG Designer

Author one sprite at a time as a hand-crafted SVG, save it next to the
final PNG, then rasterize the SVG via cairosvg into the canonical
`assets/art/<name>.png` location consumed by `cube_asset-builder`.

**Core principle:** the SVG is the source of truth, the PNG is its
deterministic projection. The same SVG, rendered tomorrow, produces a
byte-for-byte identical PNG. Hand-tuning lives in the vector form;
rasterization is mechanical.

## When to Use

- Active style profile (`plans/<game>/style_profile.md`) is one of:
  - `minimalist_flat`
  - `cartoon_thick_outline`
  - `realistic_render`
- A per-asset prompt file exists at
  `plans/<game>/prompts/<name>.md` (produced by `cube_asset-prompter`).
- The user says "render assets", "draw sprites", "build PNGs", or
  similar after the prompts are ready.

## When NOT to Use

- Style profile is `detailed_pixelart`, `retro_8bit`, or
  `painterly_storybook` → delegate to `canvas-design`. Those presets are
  raster-native (per-pixel control, paper grain), and SVG cannot reach
  their quality bar without absurd workarounds.
- No `style_profile.md` → delegate to `cube_asset-prompter` to set one up.
- No prompt file → delegate to `cube_asset-prompter`.
- The user wants the packed atlas, `pal.png`, or `_ids.h` → that is
  `cube_asset-builder`'s territory.

## Execution environment

The pipeline runs entirely inside the agent's own shell sandbox, never
on the user's machine. In Cowork that is `mcp__workspace__bash`; in
Claude Code it is the local shell. The user does NOT need cairosvg or
any other dependency installed locally — only the final
`assets/art/<name>.png` (and `assets/svg/<name>.svg`) lands in the
workspace folder.

If the agent has no shell access at all, stop and tell the user the
skill cannot run in this environment.

## Prerequisites

File inputs (must already exist in the user's workspace):

| File                                              | Source              | Required |
|---------------------------------------------------|---------------------|----------|
| `plans/<game>/style_profile.md`                   | `cube_asset-prompter` | Yes |
| `plans/<game>/art_bible.md`                       | `cube_asset-prompter` | Yes |
| `plans/<game>/prompts/<name>.md`                  | `cube_asset-prompter` | Yes |
| `skills/canvas-design/canvas-fonts/Rubik-Bold.ttf` | Vendored brand font  | When sprite contains text |

Runtime dependencies (checked and installed by the agent in its own
sandbox — NOT on the user's machine):

| Dependency  | How the agent gets it                                  | Required |
|-------------|--------------------------------------------------------|----------|
| `cairosvg`  | `pip install --break-system-packages cairosvg`         | Yes |
| `Pillow`    | `pip install --break-system-packages Pillow`           | Yes (size check) |

If any prerequisite is missing, print the gap and stop. Do not produce
partial output. Do not ask the user to install anything locally.

## Workflow

### Step 1: Locate inputs

Resolve the prompt file passed by the orchestrator:

1. `plans/<game>/prompts/<name>.md`

Read alongside it (in this order, all three are mandatory):

1. `plans/<game>/style_profile.md` — the binding visual contract.
2. `plans/<game>/art_bible.md` — game-specific palette, typography, mood.
3. `plans/<game>/prompts/<name>.md` — the per-sprite brief.

Confirm the style profile names one of the three SVG-supported presets.
If it names `detailed_pixelart`, `retro_8bit`, or `painterly_storybook`
— STOP and tell the user to invoke `canvas-design` for that asset.

### Step 2: Author the SVG

For each sprite, write a small Python renderer in the agent's sandbox
that uses `scripts/svg_lib.py` to compose the SVG. The renderer MUST:

1. Pull the palette from `art_bible.md §1`.
2. Build a canvas via `SvgCanvas(width, height)` using the manifest size
   (no padding, no enlargement).
3. Apply the style-specific construction order documented in
   `scripts/README.md`:
   - `minimalist_flat` — flat fills + single highlight blob + 2-px ink stroke.
   - `cartoon_thick_outline` — cel-shaded fills + thick uniform stroke + small accents.
   - `realistic_render` — radial/linear gradients + soft shadow filter + rim spec, no stroke.
4. Honour the binding light direction from the style profile (top-left).
5. Use the brand typeface (`Rubik-Bold.ttf`) for any glyph and embed it
   into the SVG via `<defs><style>` with a `@font-face` data-URI block —
   never reference system fonts.
6. Save the SVG to `assets/svg/<name>.svg` (create the folder if needed).

The SVG must be self-contained: no external font URLs, no remote images,
no `<script>` blocks, no `<foreignObject>`. Cairosvg renders only
SVG 1.1 static content; anything outside that subset is invalid here.

### Step 3: Rasterize SVG → PNG

Invoke the converter in the same sandbox shell:

```
python OCT_wowcube-agent-skills/skills/cube_svg-design/scripts/svg_to_png.py \
    --svg assets/svg/<name>.svg \
    --png assets/art/<name>.png \
    --width <W> --height <H>
```

`<W>` and `<H>` come from the manifest sprite entry. The converter:

- Calls `cairosvg.svg2png(...)` with explicit `output_width` and
  `output_height` so the PNG matches the manifest size to the pixel.
- Writes RGBA PNG with a transparent background.
- Verifies the resulting PNG dimensions via Pillow before returning 0.

Exit codes (defined in `scripts/config.py::ExitCode`):

- `0` — success.
- `2` — bad arguments.
- `3` — missing dependency (`cairosvg` or `Pillow`).
- `4` — SVG cannot be parsed by cairosvg (malformed XML, unsupported feature).
- `5` — failed to write PNG (filesystem / permissions).
- `6` — output PNG dimensions do not match `--width`/`--height`.

### Step 4: Quality gates

After the PNG is written, run the per-style assertions defined in
`scripts/svg_lib.py`:

| Style                    | Assertion                                                   |
|--------------------------|-------------------------------------------------------------|
| `minimalist_flat`        | `assert_unique_colors >= MIN_UNIQUE_COLORS_BY_STYLE[..]`    |
| `cartoon_thick_outline`  | `assert_unique_colors >= MIN_UNIQUE_COLORS_BY_STYLE[..]` + thick-stroke check |
| `realistic_render`       | `assert_unique_colors >= 12` + `assert_no_outline_stroke`   |
| all                      | `assert_safety_margin(image, SAFETY_MARGIN_PX[_REALISTIC])` |

If a renderer fails an assertion, FIX THE RENDERER — do NOT loosen the
assertion. The minimum quality bars per style are baked into config
values in `scripts/config.py`.

If even a careful hand-authored SVG cannot meet the contract, write a
`<name>.md` failure note to `assets/art/` (per the `canvas-design`
fail-loudly convention) instead of producing a thin placeholder.

### Step 5: Hand-off

Print:

> SVG render complete: `<name>`
> - SVG source: `assets/svg/<name>.svg`
> - PNG output: `assets/art/<name>.png` (<W>×<H> RGBA)
> - Style profile: `<style_name>`

Do NOT invoke `cube_asset-builder` automatically — the orchestrator (or
the user) decides when to pack.

## Workspace layout (after this skill runs)

```
assets/
  svg/
    <name>.svg            <- SVG source (hand-authored, editable)
  art/
    <name>.png            <- rasterized PNG (consumed by cube_asset-builder)
plans/
  <game>/
    style_profile.md      <- read-only here
    art_bible.md          <- read-only here
    prompts/
      <name>.md           <- read-only here
```

## Constraints

- **One render = one asset.** When invoked from `cube_asset-prompter` or
  `cube_orchestrator`, you receive ONE per-asset prompt file at a time
  and produce ONE SVG + ONE PNG. Do not batch-render.
- **SVG is canonical.** Never edit the PNG by hand — rerun
  `svg_to_png.py` after changing the SVG. Hand-edited PNGs will be
  silently overwritten by the next pack run.
- **PNG path is fixed.** `assets/art/<name>.png` is the contract with
  `cube_asset-builder`. Do not write the PNG anywhere else.
- **SVG path is fixed.** `assets/svg/<name>.svg` lives next to the PNG
  set so it can be reviewed in Inkscape/Figma without hunting.
- **No external resources in SVG.** No remote images, no remote fonts,
  no `<script>`, no `<foreignObject>`. Cairosvg ignores or rejects all
  of these.
- **Brand typeface only.** `Rubik-Bold.ttf` is the only permitted
  typeface in any text node. Embed it as a data-URI inside the SVG; do
  NOT rely on the host's installed fonts.
- **Style profile is the law.** If the SVG renderer's instinct fights
  the style profile, the profile wins. Update the renderer, not the
  profile.
- **Never overwrite a hand-edited SVG silently.** If
  `assets/svg/<name>.svg` already exists and the user did not request
  regeneration, print a diff and ask before overwriting.

## Error Handling

| Symptom                                       | Action |
|-----------------------------------------------|--------|
| `cairosvg` not installed (`rc=3`)             | `pip install --break-system-packages cairosvg` in the agent sandbox, retry. |
| `Pillow` not installed (`rc=3`)               | `pip install --break-system-packages Pillow` in the agent sandbox, retry. |
| SVG fails to parse (`rc=4`)                   | Show the cairosvg traceback. Inspect the SVG for bad XML or unsupported features (e.g., `<foreignObject>`, animated SMIL). Rewrite the renderer. |
| PNG size mismatch (`rc=6`)                    | The viewBox or `output_width/height` is wrong — verify manifest size matches the SvgCanvas constructor and the converter `--width/--height`. |
| Quality gate fails (`assert_unique_colors`)   | Renderer is too sparse for the chosen style; add per-feature highlights, gradient stops, or accent shapes. |
| Style profile is unsupported by this skill    | Stop and route to `canvas-design`. |
| Both this skill AND `canvas-design` are needed across the asset set | Run them in parallel batches: one per style. The orchestrator routes each prompt to the correct skill based on the active style profile. |
