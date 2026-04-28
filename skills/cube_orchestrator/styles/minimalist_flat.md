# Style preset: minimalist_flat

> Bold flat shapes, single base color + single lighter highlight per sprite, thick outline. Reads cleanly at a glance, deliberately simple, designed for fast procedural rendering.

## Visual identity

- **Flat 2-tone shading** — one base color plus one lighter highlight blob (≤ 30% of surface), no mid-tones.
- **Uniform 2-pixel outline** in a dark "ink" color (one common ink across all sprites).
- **Light direction: top-left at 45°.** Highlight is one consistent shape (round blob).
- **Silhouette is everything.** Internal detail is minimal — a fruit is recognizable by silhouette + 1 hue.
- **No dithering, no gradients, no per-pixel highlights.**

## Palette policy

- ≤ 12 colors total across the whole game.
- One outline-ink color shared by every sprite.
- Each fruit gets exactly 2 colors (base + highlight).

## What this style IS for

- Fast iteration, procedural generation (PIL primitives), clear readability at small sizes, very small palette.

## What this style ISN'T

- Detailed pixel-art (use `detailed_pixelart` preset).
- Cartoon vector (use `cartoon_thick_outline`).
- Hand-drawn / painterly (use `painterly_storybook`).

## Reference language for prompts

- "Flat fill, single highlight blob upper-left, 2px ink outline"
- "No mid-tones, no gradients, no individual feature highlights"
