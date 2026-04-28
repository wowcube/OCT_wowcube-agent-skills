# Style preset: retro_8bit

> Strict 16-color palette, hard pixel edges, no anti-aliasing, no transparency gradients. NES/PICO-8 era aesthetic.

## Visual identity

- **Strict 16-color global palette.** Every sprite, every effect, every UI element samples from these 16 colors only.
- **No anti-aliasing anywhere** — 1-bit alpha (fully opaque or fully transparent).
- **3-tone shading max per sprite** (base, shadow, highlight) — pulled from the global 16-color palette.
- **Pixel grid is sacred** — sprites at 16×16 or 32×32 native, scaled by integer factors only.
- **Outlines optional** — if used, 1px in the palette's darkest tone.

## Palette policy

- 16-color palette published in art bible §1, hex + role.
- Reuse aggressively — a brown rind shadow doubles as a wood-grain accent.

## What this style IS for

- Hardcore retro vibe. Reads instantly as "8-bit". Smallest possible memory footprint.

## Reference language for prompts

- "16-color global palette, sample only from the published list"
- "1-bit alpha, no AA, integer-scaled pixel grid"
- "PICO-8 / NES era aesthetic"
