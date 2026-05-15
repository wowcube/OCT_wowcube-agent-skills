# cube_svg-design / scripts

SVG-first sprite renderer for WowCube. Used by the `cube_svg-design`
skill when the active style profile is one of the vector-friendly
presets:

- `minimalist_flat`
- `cartoon_thick_outline`
- `realistic_render`

For raster-native presets (`detailed_pixelart`, `retro_8bit`,
`painterly_storybook`) use the `canvas-design` skill and its `pixel_lib`
/ `painterly_lib` instead.

## Files

- `config.py` — every tunable constant, enum, and exit code. If a value
  matters to behaviour, it lives here, not inline.
- `svg_lib.py` — primitives: `SvgCanvas`, color helpers, palette,
  gradients, shadow / blur / glow filters, embedded brand-font text,
  per-style assertions.
- `svg_to_png.py` — CLI converter that runs `cairosvg.svg2png` with
  explicit `output_width` / `output_height` and verifies the result via
  Pillow. Honours the exit codes in `config.ExitCode`.
- `requirements.txt` — `cairosvg`, `Pillow`. Installed inside the
  agent's sandbox, not on the user's machine.

## Authoring contract (per-style)

For each sprite a per-game renderer pulls the palette from
`art_bible.md §1` and walks the construction order below. The numbers
are baked into `config.py` and enforced by assertions.

### `minimalist_flat`

1. `SvgCanvas(w, h)` from manifest size.
2. Body: `add_circle` / `add_ellipse` / `add_path` with `fill = palette["base"]`,
   `stroke = palette["outline"]`,
   `stroke_width = OUTLINE_WEIGHT_BY_STYLE[MINIMALIST_FLAT].value` (= 2).
3. One highlight blob (upper-left), `fill = palette["highlight"]`, no stroke.
4. Optional 1–2 accents (e.g. stem) using the same outline color.
5. `assert_unique_colors >= MIN_UNIQUE_COLORS_BY_STYLE[MINIMALIST_FLAT]` (= 3).
6. `assert_safety_margin` with the default 1-pixel margin.

### `cartoon_thick_outline`

1. `SvgCanvas(w, h)`.
2. Silhouette layer with the thick outline (`stroke_width = 3`).
3. One mid-tone cel-shaded fill on the lower-right via `add_path` or
   clipped polygon.
4. Two or three feature accents (eyes, sparkle, shine) using the
   `highlight` and `accent` palette entries.
5. Optional `ensure_soft_shadow()` for a small ground shadow when the
   sprite has a clear "below" axis.
6. `assert_unique_colors >= MIN_UNIQUE_COLORS_BY_STYLE[CARTOON_THICK_OUTLINE]`
   (= 4) and `assert_safety_margin`.

### `realistic_render`

1. `SvgCanvas(w, h)` (use the wider safety margin: 2 pixels per side).
2. Body filled with a `add_radial_gradient` going through 3+ stops:
   highlight → base → mid-shadow → deep-shadow. No stroke.
3. Optional `add_linear_gradient` overlay to add subsurface-tone hints
   on the rim opposite the light source.
4. `ensure_soft_shadow(dx, dy, std_deviation)` for the ground-contact
   shadow under the sprite. The shadow is always softer and offset
   slightly toward the lower-right.
5. Specular spot highlight: a small `add_ellipse` with
   `fill = palette["highlight"]`, `opacity ≈ 0.85`, optionally referencing
   `ensure_inner_glow` for a soft falloff.
6. Rim spec: a thin `add_path` along the silhouette edge using
   `palette["highlight"]` at low opacity.
7. `assert_unique_colors >= 12` and `assert_no_outline_stroke` and
   `assert_safety_margin` (2-pixel margin).

## Minimal example (minimalist_flat)

```python
from pathlib import Path
from svg_lib import (
    SvgCanvas, make_palette, save_svg,
    assert_unique_colors, assert_safety_margin,
)
from svg_to_png import convert
from config import OUTLINE_WEIGHT_BY_STYLE, SupportedStyle, ExitCode

STYLE = SupportedStyle.MINIMALIST_FLAT
APPLE = make_palette(base="#E23A2B", highlight="#FFD8C0", outline="#3A0808")

def render_apple() -> SvgCanvas:
    c = SvgCanvas(48, 48)
    c.add_circle(cx=24, cy=27, r=15,
                 fill=APPLE["base"],
                 stroke=APPLE["outline"],
                 stroke_width=OUTLINE_WEIGHT_BY_STYLE[STYLE].value)
    c.add_ellipse(cx=18, cy=21, rx=4, ry=6, fill=APPLE["highlight"])
    c.add_path("M24,11 Q26,7 30,9",
               stroke=APPLE["outline"], stroke_width=2, fill="none")
    return c

svg = save_svg(render_apple(), "assets/svg/apple.svg")
rc = convert(Path(svg), Path("assets/art/apple.png"), width=48, height=48)
assert rc is ExitCode.OK
assert_unique_colors("assets/art/apple.png", STYLE, label="apple")
assert_safety_margin("assets/art/apple.png", STYLE, label="apple")
```

## Minimal example (realistic_render)

```python
from svg_lib import (
    SvgCanvas, make_palette, save_svg,
    assert_unique_colors, assert_no_outline_stroke, assert_safety_margin,
)
from config import SupportedStyle

STYLE = SupportedStyle.REALISTIC_RENDER
APPLE = make_palette(
    base="#D9665A", highlight="#FFE6DC", outline="none",
    mid="#A24338", deep="#5B1F1A",
    accent="#FFC2A8", shadow="#3D2624",
    subsurface="#FF9A7A",
)

def render_apple() -> SvgCanvas:
    c = SvgCanvas(48, 48)
    grad = c.add_radial_gradient(
        cx=0.35, cy=0.30, r=0.75,
        stops=[(0.0, APPLE["highlight"], 1.0),
               (0.30, APPLE["base"], 1.0),
               (0.65, APPLE["mid"], 1.0),
               (1.0, APPLE["deep"], 1.0)],
    )
    shadow = c.ensure_soft_shadow(dx=1.5, dy=2.5, std_deviation=2.0,
                                  flood_color=APPLE["shadow"], flood_opacity=0.4)
    c.add_circle(cx=24, cy=26, r=15, fill=grad, filter_id=shadow)
    # Rim spec along the upper-right
    c.add_path("M30,12 Q36,16 36,24",
               stroke=APPLE["highlight"], stroke_width=1, fill="none",
               opacity=0.55)
    # Specular spot
    c.add_ellipse(cx=19, cy=20, rx=3, ry=5,
                  fill=APPLE["highlight"], opacity=0.85)
    # Subsurface hint on lower-right rim
    c.add_ellipse(cx=32, cy=32, rx=6, ry=4,
                  fill=APPLE["subsurface"], opacity=0.40)
    return c
```

## Why we route per-style

`canvas-design`'s pixel and painterly libs were tuned for raster output
where every pixel matters. Forcing those styles through SVG would mean
either generating thousands of `<rect width="1" height="1">` elements
(wasteful) or losing pixel control (defeats the style profile). Three
SVG-friendly presets stay with this skill; the rest stay with
`canvas-design`. The orchestrator picks per-prompt based on the active
`style_profile.md`.

## Quality bar

The assertions in `svg_lib.py` are intentionally strict:

- `assert_unique_colors` runs against the rasterized PNG (not the SVG
  string), so gradient richness is observed AFTER cairosvg renders it.
- `assert_safety_margin` enforces a clean transparent border so packing
  in `cube_asset-builder` does not crop the silhouette.
- `assert_no_outline_stroke` is realistic-render-only; if it fails, the
  renderer accidentally added a dark ring around the silhouette.

If a renderer fails an assertion, fix the renderer — never loosen the
gate. The minimums per style are baked into `config.py`.
