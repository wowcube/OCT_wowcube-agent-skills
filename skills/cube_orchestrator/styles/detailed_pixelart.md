# Style preset: detailed_pixelart

> Saturated, multi-tonal pixel-art on a dark backdrop. Each sprite reads as a tactile object with directional light and material identity, not a flat shape.

## Visual identity

- **Pixel-art rendering, no anti-aliasing on outer silhouette.** Edges are 1-pixel hard. Inside the sprite, dithering and shaped highlights are used to imply curvature and material.
- **Multi-tone shading: 3–4 distinct tone steps per sprite minimum.**
  - Tone 0 — base color (≈ 50–60% of surface area)
  - Tone 1 — mid-shadow (≈ 20–25%, on the side opposite the light)
  - Tone 2 — deep-shadow / outline color (≈ 10–15%, on the rim and underside)
  - Tone 3 — highlight (≈ 5–10%, capsule-shaped or shard-shaped, never spread thin)
- **Light direction: top-left at ~35°.** Highlights cluster on the upper-left of every primary form, shadows fall to the lower-right. This is consistent across the entire asset set; never flip light per sprite.
- **Material specifics matter.** Glossy fruits get a sharp white capsule highlight with a small secondary spec; matte surfaces get a soft gradient highlight; granular surfaces (strawberry seeds, pineapple lattice) get individual tiny highlight pixels.
- **Outline color is sprite-internal, not a uniform black.** Use a darker shade of the base color for the outline (e.g., dark wine-red around a strawberry, dark indigo around a blueberry). This keeps the silhouette readable on a dark background without going cartoon-flat.
- **Detail density scales with sprite size.** A 48×48 fruit carries 4–8 distinct features (stem, calyx, body, highlight, seed cluster, undershadow). A 12×12 particle carries 2 (base, highlight pixel).

## Palette policy

- Each sprite group (fruit, bonus, hazard, particle, background) gets **its own palette ramp of 4–5 colors**, contributed to a total game palette of ≤ 64 colors.
- Ramps are warm-to-cool *within their hue family*, not across hue boundaries. A red fruit ramp goes from `#FFD8C0` (highlight) → `#E23A2B` (base) → `#9C1B12` (mid) → `#4A0A05` (deep). Do NOT add an unrelated cool tone into a warm ramp.
- Background palette is **darker and cooler** than the foreground so any fruit pops without an extra rim-light.
- The full game palette is published in the art bible under `## Palette` with hex + role + ramp ownership.

## Composition rules

- Every primary sprite has a **clear silhouette readable as black-on-white** — squint at the pixel grid; if the shape isn't obvious, redraw.
- **No element touches the canvas edge** — leave at least 1 transparent pixel on every side for safe scaling and rotation.
- **Centered composition** — the sprite's visual center of mass aligns with the pivot specified in the manifest. For asymmetrical objects (banana crescent, cherry pair), pivot is the geometric center of the bounding box, not the centroid.
- **Animation frames must preserve silhouette** — frame N+1 of a 2-frame animation differs from frame N only in highlight/sparkle/spark, never in body shape or pivot.

## Typography (when present)

- Brand typeface only (`canvas-fonts/Rubik-Bold.ttf`) — non-negotiable.
- For pixel-art labels rendered AS sprites, use the typeface at **integer scaling only** — no fractional scaling, no anti-aliasing fallback.
- Label color = 1 base color + 1 highlight pixel per glyph stem; no gradients.

## Output policy

- Save raster as `assets/art/<name>.png`, RGBA, exact size from manifest (no padding).
- Background of the PNG is fully transparent. No magenta key, no checker pattern.
- DO NOT pre-quantize or pre-pack. The raw PNG goes into `cube_asset-builder`'s pipeline, which handles palette quantization.

## What this style ISN'T

- Not flat vector cartoon (no single-color fills with thick uniform black outlines).
- Not painterly (no gradients, no soft brushwork, no airbrush highlights).
- Not photorealistic (no smooth shading, no PBR-style surfaces).
- Not procedural primitives (no plain ellipse/triangle fills with one base color and one highlight blob — that's the "minimalist_flat" preset, a different choice).

## Reference language for prompts

When per-asset prompts describe a sprite under this style, they MUST include phrasing like:
- "4-tone pixel-art shading: highlight, base, mid-shadow, deep-shadow"
- "1-pixel hard outline using the base ramp's deepest tone"
- "Top-left ~35° light, highlight cluster on upper-left, shadow on lower-right"
- "Per-feature pixel highlights (one bright pixel per seed / per grape / per spike)"
- "Silhouette-first composition; details secondary"

Reference aesthetic vocabulary (text-only, no copyrighted images):
- "Stardew Valley produce sprite density"
- "Celeste asset clarity at small sizes"
- "Old-school point-and-click adventure inventory icons"
