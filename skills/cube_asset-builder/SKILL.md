---
name: cube_asset-builder
description: >-
  Stage 3 component of the WowCube pipeline, invoked by cube_orchestrator — not a
  standalone user entry point. Use only when the orchestrator routes to asset
  generation because the manifest exists but packed assets and _ids.h do not.
  Generates sprite PNGs from each sprite's gen_prompt — AI art via a
  multi-provider adapter (OpenRouter, OpenAI, xAI, Gemini, or local Stable
  Diffusion) when a provider is configured, or agent-authored placeholder art
  when none is — and synthesised WAV sounds (encoded to beta mp3), pauses for
  user review in stepwise mode, then packs them into the beta container: `app_<game>/index.bin`,
  `art/packed/*.raw` + `*.pal`, `sound/assets/*.mp3`, and `src/app_<game>_ids.h`.
---

# WowCube Asset Builder

> **This skill is Stage 3 of the `cube_orchestrator` pipeline.** The orchestrator invokes it (via the Skill tool) when the asset manifest exists but `assets/packed/` / `src/app_<game>_ids.h` do not. It is not a user-facing entry point — the user enters through `cube_orchestrator`, which routes here.

Drive the asset pipeline from a structured manifest. This skill never writes
game code and never creates prompts — it exists solely to turn a validated
`<game>_assets.json` into a runnable set of packed sprites and sound files that
`cube_orchestrator`'s coder agents can reference. The packed assets are the
Stage 3 artifact; `cube_orchestrator` checkpoints them with the user (stepwise
mode; auto-accepted in autonomous mode once the consistency review passes) and
then runs Stage 4 (implementation).

Sprites are generated from each sprite's `gen_prompt` (written by
`technical_prompter`, Step 4a). When an image provider is configured — any of
OpenRouter, OpenAI, xAI, Gemini, or a local Stable Diffusion endpoint, see
"Image provider chain" below — `scripts/genimg.py` sends the prompt to it and
resizes the result to the manifest's exact `size`. When **no** provider is
configured, this skill does not stop: the asset-builder agent draws each
sprite itself instead (see "Placeholder art (no image provider)" below),
writing PNGs into the exact same `assets/art/` layout AI art would use, so
every later stage is unaffected. Sounds are deterministic synthesised
placeholders written as mono PCM16 **WAV** (no external encoder), then — when
`ffmpeg` is on `PATH` — additionally encoded to the exact format the beta
engine decodes: **22050 Hz mono CBR 32k mp3**, no Xing header, no metadata.
The pack stage copies those mp3s into `app_<game>/sound/assets/` and records
one `KIND_SOUND` entry per mp3 in `index.bin`. AI sprite output is **not**
reproducible across runs, and neither is agent-drawn placeholder art; sounds
(both the WAV and the mp3 encode) are byte-identical across runs regardless
of the art path.

> **Sizes are authored (pre-upscale) pixels — ≤ 120×120.** The engine upscales
> every sprite ×2 at draw time, so the manifest `size` is HALF the on-screen
> size (full screen = `[120, 120]`, never `[240, 240]`). This skill generates and
> resizes to whatever `size` the manifest carries — it does not invent sizes — so
> a correct manifest from `technical_prompter` already encodes this. If you ever
> see a sprite `size` > 120 (or a size that reads like on-screen pixels), it is a
> manifest sizing error: delegate it back to `technical_prompter` rather than
> packing it. The one exception is sprites with `flags.fullsize` set — any
> color (see the tier table below) — those are authored at native resolution
> up to 240×240.

> **`color` picks the sprite's encoding — `"palette"` (default) or `"full"` —
> and together with `flags.fullsize` selects one of three art tiers:**
>
> | Tier | Manifest | `size` (authored) | Colors / transparency | Drawn at | Use for |
> |------|----------|-------------------|-----------------------|----------|---------|
> | Palette (default) | `color: "palette"` | ≤ `[120, 120]` (= on-screen ÷ 2) | shared quantized palette, index 0 transparent | ×2 upscale | characters, icons, HUD — anything needing transparency |
> | Palette fullsize | `color: "palette"` + `flags.fullsize` | native, up to `[240, 240]` | shared palette, transparency KEPT | 1:1 | native-resolution art that still needs alpha |
> | Full-color fullsize | `color: "full"` + `flags.fullsize` | native, up to `[240, 240]` | RGB565, 2 bytes/texel, **no transparency** | 1:1 | opaque backgrounds, tiles, photographic full-screen art |
>
> `flags.alpha` is forbidden on `"full"` sprites (0x0000 is opaque black, not
> transparent); palette sprites keep index-0 transparency in both tiers. A
> `"full"` sprite without `flags.fullsize` still draws at ×2 and is capped at
> 120, same as a default palette sprite. Full-color sprites also accept
> `dither: true` — Floyd–Steinberg dithering to the RGB565 lattice, applied
> during conversion, before the lossless RLE encode. Recommended for
> photographic art and smooth gradients (kills banding); pointless for
> flat-color art, and it costs a somewhat larger RLE payload (dither noise
> breaks up runs). Prefer the cheapest tier that does
> the job (the table is ordered cheapest-first): there is no hard packer-side
> cap on pack size — only the cube's flash software region (contiguous free
> 512 KB cells) bounds it — but lean packs are good practice.
>
> **The canonical MAXIMUM-QUALITY recipe (no compromises) is exactly:**
> `color: "full"` + `flags.fullsize` + `dither: true`. The pipeline applies
> nearest-level RGB565 rounding + Floyd–Steinberg dithering, then the plain
> lossless RLE — and **nothing else**. No smoothing, no pre-filtering, no
> lossy "optimizations" of any kind: the only loss between the source PNG and
> the cube's screen is the display's own 16-bit format. When the user asks
> for "maximum quality", this recipe IS the answer — never add smoothing
> (`smooth_rows`-style texel snapping exists in `pack_beta.py` strictly as an
> opt-in size tool for noisy video sources and is NEVER applied by default or
> in the name of quality), never trade fidelity for pack size unless the user
> explicitly asks to shrink the pack.
>
> Why this is absolute: a smoothed/degraded full-color sprite looks about the
> same as a 256-color palette fullsize sprite — at twice the bytes. Degrading
> tier 3 collapses it into tier 2 and makes it pointless. So the three tiers
> are really three commitments: **fast** (palette + ×2 upscale — cheapest to
> render and store), **mid** (palette fullsize — native sharpness, 1 byte-class
> payload, keeps alpha), **fat** (full-color fullsize — uncompromised color,
> 2 bytes/texel). Pick by the art's needs; once picked, deliver the tier's
> full promise.
>
> **The launcher icon supports the same three tiers**, configured by the
> optional top-level `icon` object in the manifest —
> `{"color": "palette"|"full", "side": N, "dither": true|false}` — or
> overridden per-invocation by `pack.py --icon-color/--icon-side/--icon-dither`:
>
> | Icon tier | Manifest `icon` | `side` | Encoding | Drawn at |
> |-----------|-----------------|--------|----------|----------|
> | Palette 120 (cheap) | `"color": "palette", "side": 120` | 120 only | quantized into its **own dedicated `.pal`**, index 0 transparent | ×2 upscale → 240 |
> | Palette 240 | `"color": "palette", "side": 240` | 240 only | own dedicated `.pal`, transparency kept, FULLSIZE | 1:1 |
> | Full-color (default) | `"color": "full"` (or no `icon` object) | 1..240 (default 160) | RAW565, FULLSIZE, optional `dither` | 1:1 |
>
> Palette icons ship only in the two device-proven shapes (120 or 240 — the
> validator rejects anything else), keep the PNG's transparency for the hex
> icon shape via palette index 0, and do NOT join the sprites' shared palette
> groups: the icon gets its own `KIND_PAL` record. `dither` is full-color
> only (palette + dither is a validation error). Omitting the `icon` object
> entirely keeps today's default exactly: full-color, 160×160, no dither.

**Core principle:** every asset name that appears in a prompt must exist as a
file after this skill runs. The manifest is the contract. No placeholder text
like "requires asset: X" is ever produced here; either the asset is in the
manifest and gets generated, or the user is asked to fix the manifest. Every
sprite MUST carry a non-empty `gen_prompt` — generation fails loudly otherwise.

## When to Use

- `cube_orchestrator` routed here because the manifest exists but `assets/packed/`
  or `src/app_<game>_ids.h` is missing.
- Resuming a partially-completed asset build after a user requested regeneration.

Do not trigger this skill directly for "generate assets" / "build assets"
requests — those are owned by `cube_orchestrator`, which routes here as Stage 3.

## When NOT to Use

- No manifest exists → the orchestrator will route to Stage 2 (`technical_prompter`).
- No GDD exists → the orchestrator will route to Stage 1 (`cube_game-designer`).
- The user wants to modify game code → this skill does not touch `src/app_<game>.h`.

## Prerequisites

| File | Source | Required |
|------|--------|----------|
| `plans/<game>/<game>_assets.json` OR `plans/<game>_assets.json` | `technical_prompter` | Yes |
| A non-empty `gen_prompt` on every sprite in the manifest | `technical_prompter` (Step 4a) | Yes |
| `build_psd.py` (at repo root, its `scripts/`, or next to scripts/) — internal: the pack stage uses it to atlas the sprite PNGs into a throwaway `assets.psd`; no hand-authored PSD is ever needed | Project | Yes |
| `pack.py` (at repo root, its `scripts/`, or next to scripts/) | Project | Yes |
| `Pillow`, `numpy`, `requests`, `pytoshop`, `psd-tools` | `pip install` | Yes |
| An image provider resolved via the chain below | User / config file | No — see "Image provider chain"; absence routes to "Placeholder art" |
| `ffmpeg` on `PATH` | Windows: `winget install Gyan.FFmpeg`. Linux: distro package. | Yes (beta mp3 encode) |

If any prerequisite other than the image provider is missing, print the gap
and stop — do not attempt to generate partial output. The image provider is
the one deliberate exception: nothing resolving is not a failure, it is the
signal to follow "Placeholder art (no image provider)" below instead of AI
generation. `ffmpeg` is only needed to encode the synthesised WAVs down to
the beta mp3 format — without it the `generate` stage still writes the WAVs,
it just skips the mp3 step (pass `--mp3` to make a missing `ffmpeg` a hard
error instead); a missing `ffmpeg` can also be worked around by dropping
pre-encoded mp3 files straight into `sound/assets/`.

### Image provider chain

AI sprite generation is multi-provider (`scripts/image_providers.py`) — it is
no longer OpenRouter-only. `scripts/genimg.py`'s `generate_image()` resolves
one provider per run via `image_providers.resolve_provider()`, in this order
(first hit wins):

1. `OPENROUTER_API_KEY` environment variable — backward compat, treated as an
   OpenRouter key.
2. `IMAGE_API` environment variable — a bare key/URL, or a JSON object
   `{"provider": "...", "key": "...", "base_url": "...", "model": "..."}`
   (every field optional; a missing `provider` is auto-detected from
   `key`/`base_url`).
3. `~/.wowcube/image_api.json` (`image_providers.CONFIG_PATH`) — same JSON
   shape as `IMAGE_API`. Written once by `image_providers.save_provider()`
   when the user pastes a key/URL during the orchestrator's intake, so the
   key question never repeats on later runs.
4. Nothing resolves → no image provider — not an error, see "Placeholder
   art (no image provider)" below.

A pasted key/URL is auto-detected by pattern
(`image_providers.detect_provider`):

| Pattern | Provider |
|---|---|
| `sk-or-...` | OpenRouter |
| `sk-...` (not `sk-or-`) | OpenAI |
| `xai-...` | xAI / Grok |
| `AIza...` | Google Gemini ("nano banana") |
| `http://...` / `https://...` | Local/self-hosted Stable Diffusion — Automatic1111-compatible `/sdapi/v1/txt2img` |
| anything else | `UnknownProviderError` naming the supported forms above |

Before a run commits to AI art, the resolved provider is checked with one
cheap authenticated call (`image_providers.validate()`); a failed validation
degrades exactly like "nothing resolved" — placeholder art, one report line,
never a mid-run stall. This skill only *consumes* whatever
`resolve_provider()` finds; asking the user for a key and calling
`save_provider()` on the answer is the orchestrator's intake job (its
`SKILL.md` documents that flow), not this skill's.

## Placeholder art (no image provider)

`gen_placeholders.py` (a procedural placeholder generator) has been removed
— its canned output looked worse than no art at all. When no image provider
resolves (previous section), this skill does **not** stop: **the
asset-builder agent authors each sprite itself**, by whatever means it
judges best (ad-hoc Pillow code is the natural default; nothing is
prescribed or canned) — one PNG per manifest sprite, drawn from that
sprite's `gen_prompt` and `description`: a flat, readable silhouette that
actually conveys what the sprite is (character, enemy, tile, icon…), not a
gray box or a plain rectangle.

Practical flow, since `build_pipeline.py generate` refuses to run sprite
generation without a resolved provider:

1. Synthesize sounds directly — they need no image provider at all:
   `python scripts/gen_sounds.py <manifest-path> --out <workspace>/wav`
   (add `--no-mp3` only if `ffmpeg` is unavailable and a WAV-only pass is
   acceptable for now; otherwise it beta-encodes automatically when
   `ffmpeg` is on `PATH`, same as the `generate` stage).
2. For every sprite in the manifest, write `<workspace>/art/<name>.png`
   yourself — the exact same directory the AI `generate` stage would have
   populated.
3. Continue at Step 3 (user checkpoint) and Step 4 (pack) below unchanged:
   placeholder PNGs flow through the identical `build_pipeline.py pack` /
   `pack.py` invocation as AI PNGs — nothing downstream branches on how the
   art was produced.

Pinned requirements (non-negotiable, whichever technique you use to draw):

- **Every sprite in the manifest gets a file.** No skipping, no "TODO"
  placeholders — the manifest is still the contract (see "Core principle"
  above): every asset name that appears in a prompt must exist as a file
  after this skill runs.
- **Exact `size`.** Same sizing rules as AI art, not a placeholder-specific
  exception: palette sprites get the manifest's authored (pre-upscale)
  `size`, ≤ 120×120 unless `flags.fullsize`; full-color/fullsize sprites are
  native size up to 240×240.
- **Correct alpha (palette tiers) / opacity (full-color).** Palette sprites
  (`color: "palette"`, either tier): RGBA with the silhouette opaque and
  everywhere else alpha-0, unless the manifest sets `flags.alpha: false` —
  same transparency contract a cutout AI sprite would have. Full-color
  fullsize sprites (`color: "full"` + `flags.fullsize`): fully opaque RGBA
  (alpha 255 everywhere) — `flags.alpha` is forbidden on these regardless of
  art source.
- **Visually distinct, readable silhouettes.** Different sprites must look
  different enough (shape and/or color, not just filename) that a human can
  actually playtest the game with placeholder art and tell entities apart at
  a glance. Flat solid-color shapes are fine; detail and shading are not the
  point — distinguishability is.
- **Same downstream path as AI art.** Placeholder PNGs are not a special
  case anywhere past this point — Step 4 packs them with the same
  `build_pipeline.py pack` / `pack.py` invocation, through the same
  palette/full-color tier encoding, into the same
  `app_<game>/art/packed/*.raw` + `*.pal` outputs.
- **The graphics-are-temporary note travels with the hand-off.** Step 5's
  hand-off (and, ultimately, `cube_orchestrator`'s final report to the user)
  carries exactly one line noting the graphics are temporary, naming the
  config file path so the user knows where to drop a key later —
  `~/.wowcube/image_api.json`. This skill surfaces that fact at hand-off; the
  orchestrator is what phrases it for the user.

Regenerating later is cheap: once a provider is configured — the user pastes
a key (persisted by `image_providers.save_provider()`) or a local SD URL —
re-run Step 2 (`build_pipeline.py generate`, per-group or in full) to replace
placeholders with AI art, then re-pack. Nothing about the manifest or the
pack invocation changes.

## Workflow

### Step 1: Locate the manifest

Look in this order:
1. `plans/<game>/<game>_assets.json`
2. `plans/<game>_assets.json`

If neither exists, stop and **return control to `cube_orchestrator`** — the manifest is a Stage 2 output, so the orchestrator will route to Stage 2 (`technical_prompter`) to produce it.

### Step 2: Run the generate stage

If no image provider resolves (see "Image provider chain" above), skip this
command entirely and follow "Placeholder art (no image provider)" instead —
that section's step 1 covers sounds, step 2 covers sprites, and both land in
the same `assets/wav/` / `assets/art/` layout this command would have
produced.

Otherwise invoke the pipeline driver:

```
python OCT_wowcube-agent-skills/scripts/build_pipeline.py \
    generate --manifest <manifest-path> --workspace assets
```

The generate stage sends every sprite's `gen_prompt` to the resolved image
provider, resizes the result to the manifest `size`, and writes it into
`assets/art/`; it also synthesises a WAV for every sound into `assets/wav/`.

Exit codes:
- `0` — success.
- `2` — manifest invalid (errors printed to stderr; relay verbatim to user).
- `3` — missing Python dependency (Pillow / numpy / requests / pytoshop /
  psd-tools), message names which — a real stop, relay it. This code is also
  raised when no image provider resolves from the full chain at all; treat
  that case as the "Placeholder art" branch, not a failure to relay —
  configuring `IMAGE_API` or `~/.wowcube/image_api.json` (see "Image provider
  chain") switches back to AI art on the next run.
- `6` — sprite generation failed (provider/network error, or a sprite has no
  `gen_prompt`); relay stderr to the user.
- other — unexpected; surface stderr to user.

On success, the driver prints a summary: PNG count, WAV count, group names.

### Step 3: User checkpoint — MANDATORY in stepwise mode

**In autonomous mode** (see `cube_orchestrator` Run Modes) there is no one to
wait for: once the asset-consistency review subagent passes the generated
set, the review is auto-accepted and the run continues straight to Step 4
(pack) without printing this checkpoint or pausing. The STOP below applies in
**stepwise mode**.

**STOP. Do NOT proceed to the pack stage.** Print the summary and wait for
user input. Offer these options verbatim:

> Generated assets are in `assets/art/*.png` and `assets/wav/*.wav`.
> Review visually and by ear, then reply:
>
> - `ok` or `continue` — pack and hand off to orchestrator.
> - `regen <group>` — regenerate a single group (others untouched). For
>   sprites this re-runs AI generation, so the art will differ from the
>   previous attempt even with the same prompt.
> - `swap <name>` — drop a PNG or WAV into `assets/art/` or `assets/wav/`
>   with that name, then reply `ok`.
> - `edit <name> prompt <text>` — edit the sprite's `gen_prompt` in the
>   manifest, then I'll regenerate that sprite.
> - `edit <name> size <WxH>` — edit the manifest, then I'll regenerate
>   that sprite. (Sizes are authored, pre-upscale pixels — keep `W` and `H`
>   ≤ 120; full screen is `120x120`, since the engine upscales ×2 on draw.)

Wait for an explicit reply. Never auto-continue in stepwise mode.

For `regen <group>` — re-run the generate command with `--group <name>`.

For `edit <name> size <WxH>` or `edit <name> prompt <text>`:
1. Load the manifest JSON, find the entry, update `size` (or `gen_prompt`).
2. Save the manifest.
3. Run `build_pipeline.py generate --manifest <manifest> --workspace assets
   --group <group>` (where `<group>` is the sprite's group or derived group).
4. Return to Step 3.

### Step 4: Run the pack stage

After the user replies `ok`:

```
python OCT_wowcube-agent-skills/scripts/build_pipeline.py \
    pack --game <game> --workspace assets --src-dir src \
    --app-dir <workspace>/app_<game> --manifest <manifest-path>
```

`--app-dir` and `--manifest` are what make this the **beta** pack: without
`--app-dir` you only get the legacy `assets/packed/*.png` + `pal.png`
intermediates, not the container the simulator/`.oct` actually load.
`--manifest` is what lets `color: "full"` sprites be RAW565-encoded into the
container instead of run through the palette codec, and what carries each
palette sprite's manifest flags (`fullsize`/`additive`/`bg`) into its packed
header. Under the hood this
drives `scripts/pack.py --export --build-palette --build-ids --emit-raw
--beta-app-dir <app-dir> --app-name app_<game> --manifest <manifest-path>`.

**Full-color-only apps can skip the palette pipeline entirely.** When every
sprite in the manifest is `color: "full"` (e.g. a photo/video app packing
pre-made PNGs, nothing PSD-authored to export or palette-encode), drop
`--export` and `--build-palette` from the `pack.py` invocation — the legacy
export/palette phases self-skip when there's nothing for them to do, and only
the beta container gets emitted:

```
python scripts/pack.py --build-ids \
    --beta-app-dir <app-dir> --app-name <app-name> \
    --manifest <manifest-path> --icon <icon.png>
```

`--build-ids` is still required (it's what lets the no-palette legacy phase
exit cleanly instead of erroring on a missing `pal.png`); the pre-made sprite
PNGs must already sit in `--exported-dir` (default `exported/`) since there's
no `--export` step to populate it.

**Palette sprites from PNGs need NO hand-authored PSD — and no PSD knowledge
at all.** The pack stage reads one `<name>.png` per manifest sprite from
`<workspace>/art/` (default `assets/art/` — the same folder the `generate`
stage writes into; PNGs made or edited outside the generate stage go there
too: RGBA, transparent background, sized to the manifest `size`). The driver
then atlases those PNGs into a throwaway `assets.psd` internally
(`build_psd.py` — this is the only reason `pytoshop` is a dependency) and
packs from its export; nothing is ever authored in Photoshop. So the
`build_pipeline.py pack` command at the top of this step **is** the complete,
canonical palette invocation — run it from the workspace root (every path it
takes is cwd-relative), copy-pasteable form:

```
python OCT_wowcube-agent-skills/scripts/build_pipeline.py \
    pack --game <game> --workspace assets --src-dir src \
    --app-dir app_<game> --manifest plans/<game>_assets.json
```

The equivalent direct `pack.py` call — mirroring the full-color-only recipe
above, for when the PNGs already sit in an exported dir — keeps
`--build-palette` and drops `--export`:

```
python scripts/pack.py --build-palette --build-ids \
    --exported-dir <png-dir> --packed-dir <out> --output-dir <out> \
    --assets assets --ids-output <out>/ids.h \
    --beta-app-dir <app-dir> --app-name app_<game> \
    --manifest plans/<game>_assets.json --icon <icon.png>
```

The launcher icon's art tier comes from the manifest `icon` object (see the
icon tier table above); `--icon-color palette|full`, `--icon-side N`, and
`--icon-dither` override it per invocation. Without either, the icon packs
as today's default: full-color RAW565 at 160×160, no dither.

**Never add `--export` to a PNG-only invocation.** `--export` means "rebuild
the exported dir from `--art-dir` PSD/FNT *sources*" — it deletes every
pre-placed PNG in `--exported-dir` first (it warns loudly and the pack then
fails with exit 1, but the PNGs are already gone). Use `--export` only for
PSD-authored art such as the template's `assets.psd`.

On success the driver prints:
- Path to `assets/packed/pal.png` and the packed PNGs (legacy intermediates).
- Count of `assets/packed/*.raw` — the decoded-RGBA asset bitmaps (emitted by
  `pack.py --emit-raw`; pure Python, no `utils.exe`/`psd.exe`).
- Path to `src/app_<game>_ids.h` with the BMP_* constant count.
- The beta container written to `--app-dir`: `index.bin` (kind-tagged asset
  index — record index == asset id), `art/packed/*.raw` (sprites/maps) +
  `art/packed/*.pal` (palettes), `sound/assets/*.mp3` (copied in from the
  `generate` stage), and the kind-aware `src/app_<game>_ids.h` (BMP/MAP/SND
  enums plus animation aliases) written straight into the app.

### Step 5: Hand-off

Print:

> Asset build complete.
> - `app_<game>/index.bin` ready (sprites, palettes, maps, sounds).
> - `app_<game>/art/packed/*.raw` + `*.pal` ready.
> - `app_<game>/sound/assets/*.mp3` ready (beta mp3, 22050 Hz mono CBR 32k).
> - `src/app_<game>_ids.h` ready with N BMP_*/MAP_*/SND_* constants.

If the art in this build was agent-drawn placeholders (no image provider
resolved — "Placeholder art (no image provider)" above), append exactly one
more line so the fact reaches the orchestrator's final report to the user:

> Graphics are temporary (no image provider was configured) — drop a key or
> local Stable Diffusion URL into `~/.wowcube/image_api.json` and ask to
> regenerate the art.

Then **return control to `cube_orchestrator`**. Do NOT start implementation
yourself. The orchestrator will run the Stage 3→4 boundary checkpoint with the
user (stepwise mode; auto-accepted in autonomous mode) and begin the
implementation workflow (coder/verifier/fixer subagents) when approved.

## Constraints

- **Sprites come from a provider or from the agent; sounds are always
  deterministic.** Sprite PNGs come from whichever image provider resolved
  (OpenRouter, OpenAI, xAI, Gemini, or local Stable Diffusion — via
  `scripts/genimg.py`/`image_providers.py`) and differ run-to-run, or are
  agent-drawn placeholder art (also not reproducible run-to-run) when no
  provider resolved — see "Placeholder art (no image provider)". Sound WAVs
  are pure synthesis and byte-identical across runs regardless of the art
  path, and so is their mp3 encode. Sounds never ship as WAV — the WAV is an
  intermediate the `generate` stage (or `gen_sounds.py` directly, in the
  placeholder path) encodes (via `ffmpeg`) to the beta mp3 the engine
  actually decodes (22050 Hz mono CBR 32k); only the mp3 is copied into
  `sound/assets/` and indexed in `index.bin`. Either way the user must
  approve before packing in stepwise mode (auto-accepted in autonomous mode
  once the consistency review passes). Never silently replace a file the user
  provided by hand unless they explicitly said `regen`.
- **Per-sprite `gen_prompt` (plus `description`) is the source of the art,
  whichever path produces it.** `technical_prompter` (Step 4a) writes a
  ready-to-run image-generation prompt into every sprite entry; the AI
  `generate` stage sends it to the resolved provider and resizes the result
  to the manifest `size`, and the placeholder path draws from the same
  `gen_prompt`/`description` pair. A sprite with no `gen_prompt` aborts AI
  generation (`rc=6`) — do not invent one here; send the user back to
  `technical_prompter`. Sounds have no `gen_prompt`.
- **The image provider chain is read from environment/config, never
  hardcoded.** `OPENROUTER_API_KEY` env var → `IMAGE_API` env var →
  `~/.wowcube/image_api.json` → nothing (see "Image provider chain"). Nothing
  resolving is not an error — follow "Placeholder art (no image provider)"
  instead of stopping. A key/URL the user pastes is persisted via
  `image_providers.save_provider()` so the orchestrator's key question never
  repeats.
- **Never edit `_ids.h` by hand.** It is produced by `pack.py`.
- **Never edit `src/app_<game>.h`.** That is `cube_orchestrator`'s territory.
- **Never invent asset names.** Every sprite/sound name comes from the
  manifest. If a required asset is missing, stop and ask the user to add
  it to the manifest (and run `technical_prompter` again if appropriate).
- **2-second sound cap** and **mono PCM16 WAV** are enforced by the generator.
  Do not tell the user to set different values — the validator will reject
  out-of-range manifests.

## Error Handling

| Symptom | Action |
|---------|--------|
| Manifest invalid (`rc=2`) | Relay all stderr lines to the user; wait for them to fix the manifest (or delegate back to `technical_prompter`). |
| Missing Python dependency (`rc=3`, names a module) | Print the install hint (`pip install <pkg>`) printed by the driver; stop. |
| No image provider resolves (`rc=3`, message names the provider chain) | Not a failure — this is the "Placeholder art (no image provider)" branch. Skip `build_pipeline.py generate`'s sprite step, run `python scripts/gen_sounds.py <manifest> --out <workspace>/wav` for sounds, author the sprite PNGs yourself into `<workspace>/art/`, then continue at Step 3. Configuring `IMAGE_API` or `~/.wowcube/image_api.json` (see "Image provider chain") switches back to AI art on a later run. |
| Sprite generation failed (`rc=6`) | Relay stderr. If it is a provider/network error, retry (optionally `--group` for just the failed group). If it names a sprite with no `gen_prompt`, send the user back to `technical_prompter` to add it. |
| mp3 encode failed (`rc=7`) | The mp3 encode is attempted whenever `ffmpeg` is on PATH — even without `--mp3` — and `--mp3` additionally forces the encode when `ffmpeg` is missing (a hard error instead of a skip). Either way, `rc=7` means `ffmpeg` was found but the encode itself errored — relay stderr. Install/repair `ffmpeg` via `winget install Gyan.FFmpeg` (Windows) or the distro package (Linux), or drop pre-encoded mp3s straight into `sound/assets/` and retry. |
| `ffmpeg not found` (no `rc=7`, mp3s just silently absent) | Without `--mp3`, a missing `ffmpeg` degrades the `generate` stage to WAV-only instead of failing. If beta mp3s are needed, install `ffmpeg` (`winget install Gyan.FFmpeg` on Windows) or supply pre-encoded mp3 files in `sound/assets/` before packing. |
| `build_psd.py` failure during pack | Show the failing filename from stderr. Ask the user to inspect `assets/art/<name>.png`. |
| `pack.py` exit 1: `no palette groups exist, but N PNG(s) need packing` | The exported dir held no sprites when the palette build ran. Almost always: `--export` was passed on a plain-PNG workflow and deleted the pre-placed PNGs (the export phase prints a `WARNING: --export cleaned ...` line when this happens). Restore the PNGs and re-run without `--export` — or use `build_pipeline.py pack` with the PNGs in `<workspace>/art/`, which never needs `--export` by hand. |
| `pack.py` palette overflow | Suggest `--target-colors 64`; the driver currently uses default grouped palette — add the flag if this becomes common. |
| Repacked `.raw`/container got noticeably bigger than a previous build of the same app, no other change | Not a regression by itself. The palette builder weighs colours by pixel population, so it now keeps a rare but real accent colour that an older build would have averaged away — a better-fitting palette can be less compressible. Check decoded-pixel fidelity against the source art before treating a size increase as a bug. |
| Empty `_ids.h` after pack | Likely `build_psd.py` produced an empty PSD. Diagnose by listing `assets/exported/` contents. |
| `index.bin` missing after pack | The pack command omitted `--app-dir` (which maps to `pack.py --beta-app-dir`) — only the legacy `assets/packed/` intermediates were produced. Re-run `build_pipeline.py pack` with `--app-dir <workspace>/app_<game>` (or invoke `pack.py` directly with `--beta-app-dir <app-dir> --app-name app_<game>`). |
