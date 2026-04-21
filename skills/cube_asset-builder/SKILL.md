---
name: cube_asset-builder
description: >-
  Use after `technical_prompter` has produced `plans/<game>_assets.json` and
  before `cube_orchestrator` runs. Generates deterministic PNG placeholders
  and short MP3 placeholders for every sprite and sound in the manifest,
  pauses for user review, then packs them through `build_psd.py` + `pack.py`
  to produce `assets/packed/`, `assets/mp3/`, and `src/app_<game>_ids.h`.
---

# WowCube Asset Builder

Drive the early-prototype asset pipeline from a structured manifest. This
skill never writes game code and never creates prompts — it exists solely to
turn a validated `<game>_assets.json` into a runnable set of packed sprites
and sound files that `cube_orchestrator`'s coder agents can reference.

**Core principle:** every asset name that appears in a prompt must exist as a
file after this skill runs. The manifest is the contract. No placeholder text
like "requires asset: X" is ever produced here; either the asset is in the
manifest and gets generated, or the user is asked to fix the manifest.

## When to Use

- A manifest `plans/<game>/<game>_assets.json` (or `plans/<game>_assets.json`)
  exists and the orchestrator has not yet started.
- The user says "generate assets", "build assets", "run the asset pipeline",
  or similar after `technical_prompter` finished.
- Resuming a partially-completed asset build after a user requested regeneration.

## When NOT to Use

- No manifest exists → delegate to `technical_prompter`.
- No GDD exists → delegate to `cube_game-designer`.
- The user wants to modify game code → this skill does not touch `src/app_<game>.h`.

## Prerequisites

| File | Source | Required |
|------|--------|----------|
| `plans/<game>/<game>_assets.json` OR `plans/<game>_assets.json` | `technical_prompter` | Yes |
| `build_psd.py` (at repo root or next to scripts/) | Project | Yes |
| `pack.py` (at repo root or next to scripts/) | Project | Yes |
| `Pillow`, `numpy`, `pytoshop`, `psd-tools` | `pip install` | Yes |
| `ffmpeg` on PATH | OS package / binary | Yes |

If any prerequisite is missing, print the gap and stop. Do not attempt to
generate partial output.

## Workflow

### Step 1: Locate the manifest

Look in this order:
1. `plans/<game>/<game>_assets.json`
2. `plans/<game>_assets.json`

If neither exists, delegate to `technical_prompter`.

### Step 2: Run the generate stage

Invoke the pipeline driver:

```
python OCT_wowcube-agent-skills/skills/cube_asset-builder/scripts/build_pipeline.py \
    generate --manifest <manifest-path> --workspace assets
```

Exit codes:
- `0` — success.
- `2` — manifest invalid (errors printed to stderr; relay verbatim to user).
- `3` — missing dependency (Pillow / numpy / pytoshop / psd-tools / ffmpeg).
- other — unexpected; surface stderr to user.

On success, the driver prints a summary: sprite count, sound count, group names.

### Step 3: User checkpoint — MANDATORY

**STOP. Do NOT proceed to the pack stage.** Print the summary and wait for
user input. Offer these options verbatim:

> Generated assets are in `assets/art/*.png` and `assets/mp3/*.mp3`.
> Review visually and by ear, then reply:
>
> - `ok` or `continue` — pack and hand off to orchestrator.
> - `regen <group>` — regenerate a single group (others untouched).
> - `swap <name>` — drop a PNG or MP3 into `assets/art/` or `assets/mp3/`
>   with that name, then reply `ok`.
> - `edit <name> size <WxH>` — edit the manifest, then I'll regenerate
>   that sprite.

Wait for an explicit reply. Never auto-continue.

For `regen <group>` — re-run the generate command with `--group <name>`.

For `edit <name> size <WxH>`:
1. Load the manifest JSON, find the entry, update `size`.
2. Save the manifest.
3. Run `build_pipeline.py generate --manifest <manifest> --workspace assets
   --group <group>` (where `<group>` is the sprite's group or derived group).
4. Return to Step 3.

### Step 4: Run the pack stage

After the user replies `ok`:

```
python OCT_wowcube-agent-skills/skills/cube_asset-builder/scripts/build_pipeline.py \
    pack --game <game> --workspace assets --src-dir src
```

On success the driver prints:
- Path to `assets/packed/pal.png` and the packed PNGs.
- Path to `src/app_<game>_ids.h` with the BMP_* constant count.

### Step 5: Hand-off

Print:

> Asset build complete.
> - `src/app_<game>_ids.h` ready with N BMP_* constants.
> - `assets/packed/*.png` + `pal.png` ready.
> - `assets/mp3/*.mp3` ready.
> Run `cube_orchestrator` next.

Do NOT invoke `cube_orchestrator` automatically. The user decides when to
proceed (same pattern used between `technical_prompter` and `cube_orchestrator`).

## Constraints

- **Assets are deterministic placeholders**, not final art. The user must
  approve before packing. Never silently replace a file the user provided
  by hand unless they explicitly said `regen`.
- **Never edit `_ids.h` by hand.** It is produced by `pack.py`.
- **Never edit `src/app_<game>.h`.** That is `cube_orchestrator`'s territory.
- **Never invent asset names.** Every sprite/sound name comes from the
  manifest. If a required asset is missing, stop and ask the user to add
  it to the manifest (and run `technical_prompter` again if appropriate).
- **2-second sound cap** and **96 kbps MP3** are enforced by the generator.
  Do not tell the user to set different values — the validator will reject
  out-of-range manifests.

## Error Handling

| Symptom | Action |
|---------|--------|
| Manifest invalid (`rc=2`) | Relay all stderr lines to the user; wait for them to fix the manifest (or delegate back to `technical_prompter`). |
| Missing dependency (`rc=3`) | Print the install hints printed by the driver; stop. |
| `build_psd.py` failure during pack | Show the failing filename from stderr. Ask the user to inspect `assets/art/<name>.png`. |
| `pack.py` palette overflow | Suggest `--target-colors 64`; the driver currently uses default grouped palette — add the flag if this becomes common. |
| Empty `_ids.h` after pack | Likely `build_psd.py` produced an empty PSD. Diagnose by listing `assets/exported/` contents. |
