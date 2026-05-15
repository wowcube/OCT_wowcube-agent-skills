# Style presets

Visual style profiles. Ownership of the `plans/<game>/style_profile.md` artifact is **split**:

- **Initial selection** — `cube_asset-prompter` Step 0. The prompter picks a preset (interactively, with the user) at the start of a new game's asset pipeline and copies the chosen preset into `plans/<game>/style_profile.md`. The prompter is the first consumer of the profile — it lifts the preset into the game's `art_bible.md` and bakes preset-specific phrasing into every per-asset prompt — so it makes sense for it to also own creation.
- **Lifecycle / rotation** — `cube_orchestrator` Step 0. If the user later asks to "change the look" mid-implementation, the orchestrator rotates the file, then re-invokes the prompter, `canvas-design`, and `cube_asset-builder` to cascade the change.

The presets themselves physically live under this folder (`skills/cube_orchestrator/styles/`) for historical reasons — they are read-only templates regardless of who copies them.

Downstream skills MUST read `plans/<game>/style_profile.md` and obey it:

- `cube_asset-prompter` lifts the preset into the game's `art_bible.md` and bakes preset-specific phrasing into every per-asset prompt.
- `canvas-design` honors the preset verbatim when rendering and refuses procedural shortcuts that would violate it.
- `cube_asset-builder` does not interpret style — but its palette policy (max colors, group ramps) is informed by the preset's palette section.

## Available presets

| File | One-liner | Best for |
|------|-----------|----------|
| `detailed_pixelart.md` | 4-tone pixel-art, multi-tonal, materiality, dithering | Saturated, "tactile" arcade games |
| `minimalist_flat.md` | 2-tone flat shapes, thick outline, procedural-friendly | Fast iteration, abstract puzzles, prototyping |
| `cartoon_thick_outline.md` | Cel-shaded vector look, smooth AA silhouettes | Casual mobile-style games |
| `retro_8bit.md` | Strict 16-color palette, hard pixels, NES/PICO-8 era | Hardcore retro, smallest footprint |
| `painterly_storybook.md` | Soft watercolor, hand-drawn, warm muted | Narrative, contemplative, cozy games |
| `realistic_render.md` | Photo-leaning rendering, smooth gradients, ≤256 colors, no outline | Premium-feel arcade/casual; product-shot polish |

## Adding a new preset

A preset is a markdown file with these sections:

1. **Visual identity** — concrete rules (tone count, light direction, edge treatment, dithering policy)
2. **Palette policy** — total color count, ramp structure, sharing rules
3. **What this style IS / ISN'T for** — fast comparison vs. siblings
4. **Reference language for prompts** — exact phrases per-asset prompts MUST include

Keep presets short (≤ 80 lines). Detail belongs in the per-game `art_bible.md` derived from the preset, not in the preset itself.

## Why ownership is split (initial pick vs. rotation)

The style decision is a **product-level choice** that affects every other artifact in the pipeline (GDD references, art bible, per-asset prompts, render output, palette quantization, even code-side BG color constants). Two facts shape the split:

1. **Initial pick belongs at the point of first use.** `cube_asset-prompter` is the first skill in the asset pipeline that needs a concrete style — it has to bake the preset's "Reference language for prompts" into every per-asset prompt. Asking the prompter to delegate back upstream just to obtain the file is an awkward cross-skill loop. It is cleaner for the prompter to own the initial selection itself.
2. **Lifecycle and cascade belong to the orchestrator.** Once code generation is underway, a style change is a multi-skill cascade (rewrite art bible → re-render sprites → re-pack atlas) that only `cube_orchestrator` is positioned to coordinate. The orchestrator therefore owns rotation.

The presets continue to live physically under `cube_orchestrator/styles/` because the orchestrator was historically the one referencing them; both skills read from this folder.
