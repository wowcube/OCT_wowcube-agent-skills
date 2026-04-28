# canvas-design / scripts

Reusable pixel-art primitives for `canvas-design` integration mode when no real image-generation tool is available in the environment.

## Files

- `pixel_lib.py` — utility library for pixel-art presets: palette ramps, capsule highlights, dithering, light-direction shading, 1-pixel hard outlines, safety-margin / unique-color assertions.
- `painterly_lib.py` — utility library for `painterly_storybook`: watercolor blob compositing, highlight/shadow gradient washes, paper-texture grain overlay, ambient-occlusion halo, optional jittered pencil-sketch outline, soft-AA / gradient-color assertions.

## When to use this

Read in order:

1. `canvas-design/SKILL.md` — see the section on **"Forbidden render shortcuts when integrated"**.
2. `cube_orchestrator/styles/<chosen>.md` — the binding style profile.
3. `plans/<game>/art_bible.md` — game-specific palette and rules.

Then:

| Environment has… | Style preset | What to do |
|------------------|--------------|-----------|
| Real image-gen tool (DALL-E / SD / Imagen) | any | Use it. Libs not needed. |
| No image-gen | `minimalist_flat` | OK to use plain PIL primitives. Libs optional. |
| No image-gen | `detailed_pixelart` or `retro_8bit` | Use **`pixel_lib.py`**. |
| No image-gen | `painterly_storybook` | Use **`painterly_lib.py`**. |
| No image-gen | `cartoon_thick_outline` | Mix: thick-outline silhouette via `pixel_lib.trace_outline` (with width override), cel-shaded fills via `painterly_lib.paint_blob` (no blur). |
| No image-gen, no PIL | any | **Fail loud** — write `<name>.md` failure notes per the SKILL.md "fail loudly" rule. |

The libs give you the floor — everything you write on top of them is the per-game silhouette and feature placement.

## Per-game renderer pattern (pixel_lib — for pixel-art presets)

For each sprite name in `plans/<game>_assets.json`, write a function that:

1. Pulls its 4-tone ramp from `art_bible.md §1` via `make_ramp(...)`.
2. Builds an empty canvas via `blank_rgba(w, h)`.
3. Fills the silhouette with `ramp.base` (per-sprite shape).
4. Calls `apply_4tone_distribution(img, ramp)` OR shades manually with `shade_lower_right`.
5. Calls `place_capsule_highlight(img, cx_ul, cy_ul, ramp, length=4)` for the upper-left shine.
6. Stamps per-feature pixels (seeds, grapes, spikes) via `place_feature_pixel`.
7. Optionally calls `base_to_mid_band(img, ramp.base, ramp.mid)` for soft transitions.
8. Calls `trace_outline(img, ramp.deep)` LAST — outlines must come after all interior shading.
9. Optionally calls `add_occlusion_band(img, ramp.deep, side="br")` for ambient occlusion.
10. Asserts quality with `assert_unique_colors(img, minimum=6)` and `assert_safety_margin(img)`.

## Per-game renderer pattern (painterly_lib — for painterly_storybook)

For each sprite, write a function that:

1. Pulls its 3-tone ramp from `art_bible.md §1` via `make_painterly_ramp(...)`.
2. Builds an empty canvas via `blank_rgba(w, h)`.
3. Stacks 3–5 overlapping `paint_blob(img, cx, cy, ramp.base, r, alpha, blur_radius)` calls with slight position/radius/alpha jitter to build a watercolor body.
4. Adds `paint_wash_upper_left(img, ramp.wash, alpha=120)` for the highlight wash (NOT a hard spec).
5. Adds `paint_shadow_lower_right(img, ramp.shade, alpha=110)` for the soft mid-shadow.
6. Adds per-sprite features (stems, calyces, leaves) via `paint_brushstroke` or extra small `paint_blob`s in feature colors.
7. `paper_texture_overlay(img, intensity=0.10)` — mandatory grain overlay.
8. `ao_halo(img, color=warm_shadow, radius=2.5, alpha=30)` — warm shadow underneath.
9. Optional: `pencil_outline(img, color=pencil_line, alpha=60, jitter=1)` — sparingly, only on sprites where value contrast alone doesn't read.
10. Asserts quality with `assert_painterly_aa(img, min_intermediate_alphas=5)`, `assert_unique_colors(img, minimum=200)`, and `assert_no_pure_black(img)`.

## Minimal example (pixel_lib)

```python
from pixel_lib import (
    make_ramp, blank_rgba, fill_circle, place_capsule_highlight,
    place_feature_pixel, trace_outline, add_occlusion_band,
    assert_unique_colors, assert_safety_margin, save_rgba,
)

CHERRY = make_ramp(
    hi="#FFC0C0", base="#C8202E", mid="#700814", deep="#380408",
)

def render_cherry():
    img = blank_rgba(48, 48)

    # 1. Two cherry bodies, base color
    fill_circle(img, cx=18, cy=32, r=8, color=CHERRY["base"])
    fill_circle(img, cx=32, cy=34, r=8, color=CHERRY["base"])

    # 2. Stem (dark green is from another ramp; here just a darker tone)
    for y in range(10, 26):
        img.putpixel((20 + (y % 2), y), (60, 80, 30, 255))
        img.putpixel((30 - (y % 2), y), (60, 80, 30, 255))

    # 3. Highlights upper-left of each cherry
    place_capsule_highlight(img, cx=15, cy=29, length=4, ramp=CHERRY)
    place_capsule_highlight(img, cx=29, cy=31, length=4, ramp=CHERRY)

    # 4. Per-feature dot — small secondary spec
    place_feature_pixel(img, 20, 32, CHERRY["hi"])
    place_feature_pixel(img, 34, 34, CHERRY["hi"])

    # 5. Outline last (uses ramp.deep, NOT black)
    trace_outline(img, deep_color=CHERRY["deep"])

    # 6. Occlusion under the cherries
    add_occlusion_band(img, deep_color=CHERRY["deep"], side="br")

    # 7. Quality gate
    assert_unique_colors(img, minimum=6, label="cherry")
    assert_safety_margin(img, label="cherry")
    return img

save_rgba(render_cherry(), "assets/art/cherry.png")
```

## Minimal example (painterly_lib)

```python
from painterly_lib import (
    make_painterly_ramp, blank_rgba, paint_blob, paint_brushstroke,
    paint_wash_upper_left, paint_shadow_lower_right,
    paper_texture_overlay, ao_halo,
    assert_painterly_aa, assert_unique_colors, assert_no_pure_black,
    save_rgba,
)

APPLE = make_painterly_ramp(wash="#F1A99B", base="#D9665A", shade="#A24338")
WARM_BROWN = (155, 122, 74, 255)

def render_apple():
    img = blank_rgba(48, 48)

    # 1. Body — overlapping watercolor blobs
    paint_blob(img, 24, 28, APPLE["base"], r=15, alpha=220, blur_radius=1.4)
    paint_blob(img, 22, 27, APPLE["base"], r=13, alpha=180, blur_radius=1.2)
    paint_blob(img, 26, 29, APPLE["base"], r=12, alpha=160, blur_radius=1.0)

    # 2. Highlight wash UL, shadow LR
    paint_wash_upper_left(img, APPLE["wash"], alpha=120, coverage=0.45)
    paint_shadow_lower_right(img, APPLE["shade"], alpha=110, coverage=0.40)

    # 3. Stem (per-sprite feature)
    paint_brushstroke(img, 24, 12, 24, 18, WARM_BROWN, width=2, alpha=180)

    # 4. Paper grain + AO halo
    paper_texture_overlay(img, intensity=0.10)
    ao_halo(img, alpha=30, radius=2.5)

    # 5. Quality gates
    assert_painterly_aa(img, label="apple", min_intermediate_alphas=5)
    assert_unique_colors(img, minimum=200, label="apple")
    assert_no_pure_black(img, label="apple")
    return img

save_rgba(render_apple(), "assets/art/apple.png")
```

## What these libs do NOT cover (you must do per-game)

- Silhouette: the actual shape of each fruit, half, bomb, bonus token. The lib gives you `fill_circle` / `fill_ellipse` / `fill_polygon` building blocks; the per-sprite assembly is your job.
- Composition: where the calyx sits, how seeds are arranged, what the bomb fuse looks like. These are creative decisions per-asset, not library functions.
- Animation timing: the lib doesn't know about animation frames. You write `render_bomb_00()` and `render_bomb_01()` separately, ensuring the silhouette and pivot stay constant per the style profile rule.
- Backgrounds and HUD: typically simpler 2–3 tone tiles; you can either use the lib (capsule highlights, gradient bands) or simple `Image.new` fills.

## Quality bar

The library's quality gates (`assert_unique_colors`, `assert_safety_margin`) are intentionally strict for `detailed_pixelart`:

- 48×48 fruit / half / bomb / bonus → minimum 6 unique colors (the 4 ramp tones + outline pixel + at least one feature highlight).
- 12×12 particle → minimum 3 unique colors (base + highlight + outline).
- All canvases → 1-pixel transparent border on every side.

If a per-game renderer fails an assertion, fix the renderer — do NOT loosen the assertion. The output of this lib is supposed to satisfy the style profile by construction.

## Why this isn't in `cube_asset-builder`

`cube_asset-builder` packs PNGs into the WowCube atlas — it doesn't decide how they look. Style and quality are upstream concerns owned by `canvas-design` (rendering) and `cube_orchestrator` (style profile selection). This lib lives next to its consumer, not next to the packer.
