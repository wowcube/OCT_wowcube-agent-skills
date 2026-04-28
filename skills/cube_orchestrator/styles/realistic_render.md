# Style preset: realistic_render

> Photo-leaning rendering with rich materiality. Smooth gradients, subsurface tones, multiple specular highlights, soft contact shadows. Generous palette — no quantization budget. Each sprite reads as a small studio render, not a stylized illustration.

## Visual identity

- **Smooth gradient fills** — base color blends through multiple intermediate tones into mid-shadow and deep-shadow without banding. Aim for 6+ tonal steps inside the silhouette, not just 4.
- **Multiple highlights per sprite** — a primary specular highlight (sharp, smaller) plus a secondary diffuse wash (broader, softer). Glossy fruits also get a tiny "rim spec" near the silhouette edge.
- **Subsurface tone hint** — for translucent fruits (cherry, watermelon flesh, grape, strawberry), warm light scatter shows through the form: a slightly redder/brighter band on the side opposite the light. This is what separates "realistic" from "cel-shaded".
- **Soft contact shadow** — every sprite has a subtle warm-grey shadow under it, slightly offset toward the light's opposite direction, with feathered edges (Gaussian blur radius ~3px).
- **Anti-aliased silhouette** — no hard 1-pixel edges. Outer contours feather out over 1–2 pixels.
- **No outlines.** Silhouettes are defined by value/color contrast against the background, not by a stroke.

## Palette policy

- **Generous: up to 256 colors total game palette.** Do NOT enforce ≤ 64 like other presets. The atlas packer can quantize down later if needed, but the source PNGs should ship rich color depth.
- Each sprite group has a 6–10-color extended ramp covering specular/highlight/base/sub-surface/mid/deep/contact-shadow/rim-spec.
- Hue shifts within ramps are allowed — a red apple ramp can warm-shift toward orange in the highlights and cool-shift toward purple in the deepest shadows. This mimics real-world physics of light.
- Background palette is darker and slightly desaturated, providing strong value contrast for foreground objects.

## Composition rules

- Every primary sprite has a clear silhouette — squint at half-resolution; if the shape isn't obvious, redraw.
- **No element touches the canvas edge** — leave at least 2 transparent pixels on every side (more breathing room than other presets, because contact shadows extend beyond the silhouette proper).
- **Pivot at visual center of mass.** For asymmetric shapes (banana crescent, cherry pair), the pivot is the bounding-box center, but the lighting clusters on the *visual* center.
- **Animation frames** preserve silhouette and material identity — frame N+1 differs only in highlight position, fuse spark, halo intensity, etc., never in body shape.

## Typography (when present)

- Brand typeface only: `canvas-fonts/Rubik-Bold.ttf`. Non-negotiable.
- For realistic rendering, typography may have:
  - A subtle drop shadow (warm dark hue, ~30% alpha, 1px offset, 1px blur)
  - An inner highlight gradient (lighter at top, darker at bottom)
  - Optional: a 1px highlight rim along the top of each glyph
- Color: any from the palette; favor warm cream / off-white over pure white for legibility on light grounds.
- Anti-aliasing on glyphs is required (since the silhouette is AA'd).

## Output policy

- Save raster as `assets/art/<name>.png`, RGBA, exact size from manifest (no padding).
- Background fully transparent.
- Do NOT pre-quantize — let `cube_asset-builder`'s `pack.py` handle palette generation. The grouped-palette quantizer can produce excellent results from rich source PNGs.

## What this style ISN'T

- Not pixel-art (no hard pixel edges, no 4-tone ramps).
- Not painterly (no paper texture, no watercolor blob compositing).
- Not flat vector cartoon (no thick outlines, no single base + highlight).
- Not pure photograph — still stylized: light direction is consistent, exposure is flattering, no harsh shadows, no real-world chromatic aberration. Think "carefully lit product photo" or "high-end mobile-game asset", not "snapshot from a fruit market".

## Reference language for prompts

When per-asset prompts describe a sprite under this style, they MUST include phrasing like:
- "Smooth gradient fill with 6+ tonal steps from highlight to deep shadow, no banding"
- "Primary specular highlight cluster + secondary diffuse wash + rim spec at silhouette edge"
- "Subsurface tone hint on the rim opposite the light source (translucent fruits)"
- "Soft anti-aliased silhouette with feathered 1–2 pixel falloff"
- "Soft contact shadow underneath, warm-grey, Gaussian-blurred ~3px"
- "No outline; silhouette defined by value contrast"

Reference aesthetic vocabulary (text-only, no copyrighted images):
- "Apple App Store icon polish circa 2018–2022"
- "Premium mobile-game inventory icons (Hearthstone-style polish, not exactly that art)"
- "Studio product photography of stylized fruit"

## Procedural-fallback policy

- This preset CANNOT be reasonably faked with `pixel_lib.py` (it requires multi-tone gradients and AA edges, which pixel_lib explicitly doesn't do).
- It CAN be approximated by a careful combination of `painterly_lib.paint_blob` (with smaller blur radii, no paper texture overlay) plus additional specular spot highlights and contact shadow primitives — but the result still reads as "soft illustrated", not truly photographic.
- The honest path is: when no real image-gen tool is available and this preset is selected, write a per-game renderer that uses `painterly_lib` primitives with these adjustments:
  - `paper_texture_overlay()` — DO NOT call (no paper grain in realistic).
  - `paint_blob()` — call with `blur_radius=0.4..0.8` (sharper than painterly's 1.0..1.4).
  - Add explicit specular spot highlights (small, sharp, near-white pixels with 1-pixel feather).
  - Add explicit contact shadow as a separate `ao_halo()` call with larger radius (3–4) and offset (2, 3) outside the silhouette.
  - Add subsurface tint by calling `paint_wash_upper_left()` with a complementary warmer hue at low alpha on the LR side opposite the light.
- If even this hybrid cannot meet quality, FAIL LOUDLY per the SKILL.md rule.
