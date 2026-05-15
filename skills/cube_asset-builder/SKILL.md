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

## Execution environment

**The pipeline runs entirely inside the agent's own shell sandbox, not on
the user's machine.** In Cowork mode this is the `mcp__workspace__bash`
Linux environment; Claude Code users likewise have a local shell. The user
never needs to install Python, pip packages, or `ffmpeg` on their own
machine — every dependency listed below is checked and installed in the
agent's sandbox, and only the final artefacts (`assets/**`, `src/app_<game>_ids.h`)
land in the user's workspace folder.

If the agent has no shell access at all, stop and tell the user the skill
cannot run in this environment.

## Prerequisites

File inputs (must already be in the user's workspace):

| File | Source | Required |
|------|--------|----------|
| `plans/<game>/<game>_assets.json` OR `plans/<game>_assets.json` | `technical_prompter` | Yes |
| `scripts/build_psd.py` | Vendored in this skill | Yes |
| `scripts/pack.py` | Vendored in this skill | Yes |

Runtime dependencies (checked and, if missing, installed by the agent
inside its own shell sandbox — NOT on the user's machine):

| Dependency | How the agent gets it | Required |
|------------|-----------------------|----------|
| `Pillow`, `numpy`, `pytoshop`, `psd-tools` | `pip install --break-system-packages` inside the agent sandbox | Yes |
| `ffmpeg` on PATH | Usually preinstalled in the sandbox; otherwise `apt install ffmpeg` | Yes |

If any prerequisite is missing, print the gap and stop. Do not attempt to
generate partial output. Do not ask the user to install anything locally
unless the sandbox truly cannot be provisioned.

## Workflow

### Step 1: Locate the manifest

Look in this order:
1. `plans/<game>/<game>_assets.json`
2. `plans/<game>_assets.json`

If neither exists, delegate to `technical_prompter`.

### Step 2: Run the generate stage

Invoke the pipeline driver **in the agent's own shell sandbox** (in Cowork
this means `mcp__workspace__bash`; in Claude Code this is the local shell).
Use the mounted path to the workspace, not the Windows path — e.g. on Linux
the user's `D:\wowcube\git\OCT_wowcube-agent-skills\` is mounted at
`/sessions/<id>/mnt/OCT_wowcube-agent-skills/`.

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

After the user replies `ok`, run the driver in the same agent shell sandbox
that ran generate (never on the user's machine):

```
python OCT_wowcube-agent-skills/skills/cube_asset-builder/scripts/build_pipeline.py \
    pack --game <game> --workspace assets --src-dir src
```

On success the driver prints:
- Path to `assets/packed/pal.png` and the packed PNGs.
- Path to `src/app_<game>_ids.h` with the BMP_* constant count.
- Path to `assets/assets.psd` (multi-layer atlas, opens in Photoshop).
- Path to `assets/exported/` (per-sprite PNGs exported from the PSD + `assets.csv` pivots + `assets.psl` packer log).

### Step 5: Hand-off

Print:

> Asset build complete.
> - `src/app_<game>_ids.h` ready with N BMP_* constants.
> - `assets/packed/*.png` + `pal.png` ready.
> - `assets/mp3/*.mp3` ready.
> - `assets/assets.psd` ready (multi-layer atlas for Photoshop review / edits).
> - `assets/exported/` ready (per-sprite PNGs + assets.csv pivots + assets.psl packer log).
> Run `cube_orchestrator` next.

Do NOT invoke `cube_orchestrator` automatically. The user decides when to
proceed (same pattern used between `technical_prompter` and `cube_orchestrator`).

## Workspace layout (after `pack`)

```
assets/
  art/                    <- source PNGs
    <name>.png            <- one file per manifest sprite
  mp3/                    <- source sound placeholders
    <name>.mp3            <- one file per manifest sound
  assets.psd              <- multi-layer atlas (Photoshop-editable)
  exported/               <- psd-tools re-exports from assets.psd
    <name>.png            <- per-layer PNG (final pixels that were packed)
    assets.csv            <- pivot/size table for each sprite
    assets.psl            <- packer log
  packed/                 <- final packed atlas + palette
    <name>.png            <- packed sprite (8-bit indexed)
    pal.png               <- grouped palette
  app_<game>_ids.h        <- authoritative BMP_* enum (also copied to src/)
  .pipeline_state.json    <- internal stage + approval record
```

`pack.py` is invoked with `--art-dir assets --assets assets`, which
resolves to `assets/assets.psd`.

## Constraints

- **Reserved placeholder `0.png` is auto-created and must always exist.**
  Slot 0 of the BMP enum is hard-aliased to `BMP_none` by the engine
  (`enum BMP { BMP_none = 0, BMP_0 = 0, ... }`). The packer guarantees
  this slot by ensuring `assets/art/0.png` is present before every pack
  run: if it is missing, a 1x1 fully transparent PNG is generated from
  `PLACEHOLDER_SPRITE_SIZE` / `PLACEHOLDER_SPRITE_COLOR` (see
  `scripts/config.py`). A hand-crafted `0.png` is preserved if already
  present. `0.png` is NOT a gameplay sprite - it must NOT appear in the
  asset manifest, the GDD asset list, or any per-asset prompt; the
  manifest schema explicitly rejects the reserved name `0`. Game code
  MUST use `BMP_none` (preferred) or `BMP_0` for any 'no sprite / empty
  slot / placeholder' intent and MUST NOT redefine or shadow them.
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
| Missing dependency (`rc=3`) | Install the missing package inside the agent's OWN sandbox (e.g. `pip install pytoshop psd-tools --break-system-packages`), then retry. Do NOT ask the user to install anything on their machine. |
| `build_psd.py` failure during pack | Show the failing filename from stderr. Ask the user to inspect `assets/art/<name>.png`. |
| `pack.py` palette overflow | Suggest `--target-colors 64`; the driver currently uses default grouped palette — add the flag if this becomes common. |
| Empty `_ids.h` after pack | Likely `build_psd.py` produced an empty PSD. Diagnose by listing `assets/exported/` contents. |
| `SyntaxError` from `build_pipeline.py` or `build_psd.py` | The workspace mount may have delivered a truncated copy of the vendored script. Verify file size vs. the repo's canonical version; if truncated, rewrite it from the repo or a writable scratch copy before retrying. |
