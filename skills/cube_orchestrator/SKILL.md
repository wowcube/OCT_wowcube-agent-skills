---
name: cube_orchestrator
description: >-
  Use as the single entry point for ANY WowCube game work — when the user says
  "make a game", "design a game", "create a game", "build the game", "implement
  this", "start coding", "run the prompts", or wants to resume a WowCube project.
  ALSO the entry point for modding an existing, already-working game — when the
  user wants to change, tweak, reskin, or extend one ("замодить", "swap this
  sprite", "change the speed", "add a level"); it detects build-from-scratch vs
  modding and routes accordingly. The master controller for the whole pipeline:
  it routes through design, prompts, assets, and implementation, and manages
  every sub-skill and subagent. Supports an opt-in YOLO mode that runs the whole
  pipeline autonomously with no checkpoints until the final device .oct.
---

# WowCube Cube Orchestrator

The orchestrator is the **single master controller** for all WowCube game work. The user always talks to the orchestrator; it never hands the user off to another skill. Instead, it detects which pipeline stage the project is in and drives the appropriate sub-skill or subagents itself.

**Core principle:** The orchestrator never writes game code, never designs the game, never authors prompts, and never generates assets *itself*. It reads, plans, routes, dispatches, and coordinates. Every stage of work is done by a sub-skill (`cube_game-designer`, `technical_prompter`, `cube_asset-builder`, `wowcube-boilerplate`) or by a subagent (coder, verifier, fixer). Parallelism must never compromise correctness — when in doubt, wait.

## Mode Detection (do this FIRST on every entry — before Stage Detection)

Before routing into the pipeline, decide which of two modes the request is in. Run this on every entry, including resumption:

- **Build mode** — create a game (from scratch or resume a partially-built one). This is the five-stage pipeline below; route via **Stage Detection & Routing**.
- **Mod mode** — change an existing, already-working game. Route to **Mod Mode Workflow** (near the end of this skill).

**Choose Mod mode when a signal OR the heuristic points to it:**
- **Signal in the prompt:** the user asks to *change / tweak / add to / fix / reskin* an existing game ("замодить", "поменяй спрайт", "доработай готовую игру", "add a level to `<game>`"), or names a specific already-built game/folder.
- **Heuristic:** the workspace already holds a *working* `app_<game>/` — a `.target` marker, a built simulator (`bin/app_<game>.exe` on Windows or `build-sim/octavios_sim` on Linux) and/or `app_<game>.oct`, and a non-trivial `app_<game>/src/app_<game>.h` — and the request is about altering it, not starting something new.

**When it's ambiguous** — e.g. a working project exists but the wording reads like a brand-new game — **ask the user which they mean.** Never guess between building fresh and modifying working code: picking wrong is expensive in both directions (clobbering a working game, or grafting a mod onto the wrong base).

Default: if nothing indicates an existing project (greenfield workspace, "make a game"), it's **Build mode**.

**Run mode (orthogonal to Build/Mod):** YOLO mode turns on **only if the literal token `YOLO` (case-insensitive) is present in the body of the current user prompt** — see the HARD ACTIVATION RULE in `## YOLO Mode`. No paraphrase, translation, or inferred intent activates it. When OFF (the default) every checkpoint in this skill is in full force. When ON, the autonomous rules in `## YOLO Mode` override the checkpoints in both Build and Mod mode.

## The Pipeline (what the orchestrator manages)

The orchestrator owns a five-stage pipeline. It is the only skill the user invokes; the other four skills are components the orchestrator drives.

| Stage | Produces | Driven by | How |
|-------|----------|-----------|-----|
| 1. Design | `plans/<game>_gdd.md` | `cube_game-designer` | Skill tool (interactive, main context) |
| 2. Prompts | `plans/<game>_prompts.md` + `plans/<game>_assets.json` | `technical_prompter` | Skill tool (main context) |
| 3. Assets | `assets/packed/*.png`, `assets/wav/*.wav`, `sound/assets/*.mp3`, `src/app_<game>_ids.h`, `app_<game>/index.bin` | `cube_asset-builder` + asset-consistency review subagent | Skill tool: AI sprite generation (OpenRouter image model from each sprite's `gen_prompt`), then an agent consistency review, then the mandatory user review — see [Stage 3: Asset Generation](#stage-3-asset-generation-ai) |
| 4. Implement | `app_<game>/src/app_<game>.h` (per-prompt) | coder / verifier / fixer | Agent tool (subagents) |
| 5. Package | `app_<game>/app_<game>.oct` (ARM code embedded, verified) | `wowcube-boilerplate` | Skill tool (runs `build_device.ps1` / `build_device.sh`) |

**Invocation mechanism:**
- **Stages 1–3 and Stage 5 run in the main context via the Skill tool.** Stages 1–3 each require user interaction (the designer's discovery interview, the asset-review checkpoint); Stage 5 invokes `wowcube-boilerplate` to run the device build. In each case the orchestrator invokes the sub-skill, lets it run to completion, then returns here.
- **Stage 3 additionally dispatches one read-only subagent via the Agent tool** — the asset-consistency reviewer — after AI generation and before the user review. See [Stage 3: Asset Generation](#stage-3-asset-generation-ai).
- **Stage 4 dispatches subagents via the Agent tool**, exactly as described in the implementation workflow below.

## Stage Detection & Routing (Build mode — runs after Mode Detection)

On entry — including resumption — determine the active `<game>` (ask the user if ambiguous or multiple games exist; otherwise infer from `plans/` and `context/`). Then inspect the filesystem and route to the FIRST stage whose output is missing:

| Detected state | Route to | Action |
|----------------|----------|--------|
| No `plans/<game>_gdd.md` | **Stage 1** | Invoke `cube_game-designer` via the Skill tool |
| GDD exists, but no `plans/<game>_prompts.md` or no `plans/<game>_assets.json` | **Stage 2** | Invoke `technical_prompter` via the Skill tool |
| Prompts + manifest exist, but `assets/packed/pal.png` is missing | **Stage 3** | Run the [Stage 3: Asset Generation](#stage-3-asset-generation-ai) workflow (gate the manifest + key, drive `cube_asset-builder`, run the consistency review, then user review) |
| All Stage 1–3 outputs present, but prompts remain unimplemented | **Stage 4** | Run the implementation workflow below |
| All prompts implemented, but no verified device `.oct` exists (or it was last touched by a sim run) | **Stage 5** | Invoke `wowcube-boilerplate` via the Skill tool to run the device build (`build_device.ps1` on Windows / `build_device.sh` on Linux) |

After each stage completes, **re-run this detection** to find the next stage — do not assume the next stage; verify its inputs exist.

## Stage-Boundary Checkpoint (MANDATORY between every stage)

After a stage produces its artifact and BEFORE invoking the next stage, the orchestrator MUST:
1. Summarize what the completed stage produced (GDD path, prompt count, asset counts, etc.)
2. **STOP. Do NOT invoke the next stage's sub-skill or any agent.**
3. Present the next stage and wait for explicit user approval ("ok", "continue", "next", etc.)
4. Only after approval, route into the next stage

This is the same non-negotiable discipline as the per-prompt checkpoint in Stage 4. Never auto-advance across a stage boundary. The user reviews each artifact (design, prompts, assets, device package) before the pipeline proceeds.

**Exception — YOLO Mode:** this stage-boundary checkpoint is SUSPENDED when the user explicitly activated YOLO (see `## YOLO Mode`). In YOLO, after a stage's artifact is produced the orchestrator re-runs Stage Detection and auto-advances to the next stage without stopping.

**MANDATORY RULE — CHECKPOINT AFTER EVERY PROMPT:**
After each prompt cycle (coder → verifier → context save), you MUST:
1. Present the summary and test instructions to the user
2. **STOP. Do NOT dispatch the next coder agent.**
3. Wait for the user's explicit approval ("ok", "continue", "next", etc.)
4. Only after receiving approval, proceed to the next prompt

This is NON-NEGOTIABLE. Never batch multiple prompts. Never skip the checkpoint. Never assume the user wants to continue. The user needs to test every build **in the simulator** before proceeding. (Per-prompt iteration uses the simulator; the authoritative physical-cube test happens once at **Stage 5**, when the device `.oct` is built and verified — see below for why it cannot be built per-prompt without being clobbered.)

**Exception — YOLO Mode:** this per-prompt checkpoint, and every "wait for user approval" instruction in this skill, is SUSPENDED in YOLO (see `## YOLO Mode`). YOLO runs all prompts back-to-back and only reports once, at the final device build.

## YOLO Mode (Autonomous Run — opt-in)

**Default OFF.** YOLO is an explicit, opt-in override of every checkpoint and approval in this skill.

**HARD ACTIVATION RULE — the only way YOLO turns on:** activate YOLO **if and only if the literal token `YOLO` (case-insensitive) appears in the body of the user's prompt.** Nothing else activates it:
- No paraphrase, synonym, or translation activates YOLO — "автономный режим", "no checkpoints, just build it", "фигачь до финального билда / .oct", "go autonomous", etc. do **NOT** count. Only the literal string `YOLO`.
- Never infer it from intent, tone, or context.
- Never carry it across turns or unrelated requests — the token must be present in the current prompt body. A prior prompt's `YOLO` does not keep the mode on.
- If the user clearly wants autonomy but did not write `YOLO`, do **not** enter YOLO; proceed with normal checkpoints (you may note that they can write `YOLO` to enable it).

When activated this way, it applies to both Build and Mod mode.

### Mandatory pre-activation double-check (risk disclosure + explicit confirmation)

Even when the literal `YOLO` token is present, **the orchestrator does NOT go autonomous immediately.** It MUST first stop, explain the risks in plain language, and get one explicit confirmation. This is the single allowed prompt between seeing `YOLO` and going silent — never skip it, never assume the answer.

Present the risks clearly (adapt wording, but cover all of these):
- **Result is not guaranteed.** The pipeline runs unattended; the final game may not match what you pictured, and YOLO won't stop to course-correct.
- **No per-stage verification by you.** Design, prompts, assets, and gameplay are auto-accepted at each boundary — without your eyes on each stage, the cumulative result can drift far from your expectations, and a wrong early decision propagates through everything downstream.
- **It can take a long time.** A full design → prompts → assets → implement → device-build run is long-running with no interaction in between.
- **It can burn a lot of tokens / cost.** Autonomous generation, multi-agent verification, and up-to-5 fix cycles per prompt consume significantly more tokens than a checkpointed run.
- **Rework risk.** If the outcome is off, you may have to redo or heavily mod the game afterward — possibly costing more total than running with checkpoints.

Then ask for an explicit go/no-go, e.g. *"YOLO means I run the whole pipeline unattended to the final `.oct` — no result guarantee, no per-stage review from you, it can take a while and burn a lot of tokens. Confirm you want YOLO, or I'll proceed with normal checkpoints."*

- Proceed into YOLO **only on a clear affirmative** ("yes", "да", "go", "confirm").
- On anything ambiguous, silence, or "no" → **do NOT enter YOLO**; fall back to the normal checkpointed flow.

Only after this confirmation do the One-time intake and the autonomous run begin.

When YOLO turns on, the orchestrator runs the **entire pipeline in one session** and does not prompt the user again until it delivers the final device package `app_<game>/app_<game>.oct`. The only thing it removes is the human checkpoints — it does NOT remove the correctness gates that decide whether that `.oct` actually runs on the cube.

### One-time intake (gather BEFORE going autonomous)

A truly autonomous run still needs the few inputs that cannot be invented. Collect these once, up front, then go silent:

1. **Game concept** (Build mode, if not already given) — ask for the brief now (genre, core mechanic, vibe, length). YOLO does not run the designer's interview turn-by-turn; it takes the brief once and lets `cube_game-designer` produce the GDD from it.
2. **Asset source + key** (Stage 3) — default to **Path A (AI generation)**, the autonomous path, and obtain `OPENROUTER_API_KEY` now. Path B (self-supplied art) is inherently non-autonomous (it waits on human-made files); use it in YOLO only if complete assets are already on disk.

Then announce YOLO once ("YOLO ON — running design → prompts → assets → implement → device build autonomously; next stop is the final .oct") and proceed without further prompts.

### What YOLO suspends

| Checkpoint (default) | YOLO behavior |
|---|---|
| Stage-Boundary Checkpoint (between every stage) | **Suspended** — re-run Stage Detection, auto-advance. |
| Per-prompt checkpoint (Stage 4, Step 5) | **Suspended** — save context, go straight to the next prompt. |
| Stage 3 user asset review (Step 3.4) | **Suspended** — auto-accept any set the consistency reviewer passes (the review→regen loop, max 3, still runs). |
| Mod-mode mini-plan & per-change checkpoints (M3, M5) | **Suspended** — auto-advance through plan and per-change review. |
| 5-attempt verification failure → ask user | **Auto-decide** per the Failure policy below. |

### What YOLO NEVER drops (hard invariants — these decide whether the .oct runs)

Dropping any of these yields a package that won't load or won't run on the cube, defeating the whole point of an autonomous run.

- **Both verifier agents** (Requirements + Template) run every prompt, threshold **90/90**, max **5** fix attempts.
- The orchestrator still **never writes code, design, prompts, or assets itself**.
- **`_ids.h` is never hand-edited; assets stay valid; the asset-set completeness check still blocks a partial set** (a missing sprite/sound = uncompilable build).
- **Stage 5 device build + ARM-embed verification still runs and must exit 0** — a sim-only `.oct` is never delivered.
- All mandatory platform reminders, explicit casts, fixed-width types, and all seven handlers (`on_init`, `on_tick`, `on_tap(tapid, count)`, `on_twisted`, `on_pretwisted`, `on_shake`, `on_proc_draw` stub) — still enforced.

### Safe parallelism (Stage 4)

All game code is one file (`app_<game>/src/app_<game>.h`), so **coding stays sequential** — only one coder writes the file at a time. YOLO extracts parallelism from everything else:

1. Build a prompt dependency graph up front (foundational vs. cosmetic/isolated, per the Pipeline Model table).
2. **Verifiers (Requirements + Template) and fixers fan out** in parallel; verification of prompt N overlaps task-JSON prep for N+1.
3. **Independent cosmetic/isolated prompts** (audio, visual polish, UI text — touching disjoint code regions, no mutual dependency) batch their verify+fix in parallel.
4. Coders for independent prompts are still serialized on the file but dispatched back-to-back with no waiting between them.
5. **Foundational prompts** (scaffold, data structures, core init) stay strictly sequential and fully verified before anything downstream is dispatched.
6. Never dispatch two coders that could both edit the file concurrently. When in doubt, serialize the coding and parallelize only the checking.

### Failure policy in YOLO (no user to ask)

When a prompt fails verification after the 5-attempt limit:
- **Foundational prompt** → **abort the run**, save context, surface immediately. This is the one time YOLO breaks silence before the `.oct` — downstream prompts can't be trusted.
- **Non-foundational prompt** → keep the best-scoring version, record it as a known issue for the final report, and **continue**.

A **Stage 5 ARM build failure** (missing toolchain, asset-only pack) is always a hard stop — surface it; never ship a sim-only `.oct`.

### YOLO completion

After the device build verifies, present a single end-of-run report: stages run, per-prompt verification scores, total fix cycles, any prompts that finished below threshold (with best scores), the consistency-review outcome, and the absolute path to the verified `app_<game>/app_<game>.oct`.

## When to Use

- ANY WowCube game request, at any stage — this is the entry point
- User says "make a game," "design a game," or "create a game" (→ routes to Stage 1)
- User says "implement this," "start coding," "run the prompts," or "build the game from prompts" (→ routes to the first incomplete stage)
- Resuming a partially-completed project at any stage (read `context/<game>_context.json` and re-run stage detection)

## When NOT to Use

- The request is not about a WowCube game
- (There is no "use another skill first" case — the orchestrator owns the whole pipeline and routes into the sub-skills itself.)

## Stage 4 Prerequisites

These files must exist before the **implementation workflow (Stage 4)** runs. They are produced by Stages 1–3, so under normal flow they will already be present when stage detection routes here.

| File | Produced by | Required |
|------|-------------|----------|
| `plans/<game>_prompts.md` | Stage 2 (`technical_prompter`) | Yes |
| `plans/<game>_gdd.md` | Stage 1 (`cube_game-designer`) | Yes |
| `plans/<game>_assets.json` | Stage 2 (`technical_prompter`) | Yes |
| `app_<game>/src/app_<game>_ids.h` | Stage 3 (`cube_asset-builder`) | Yes |
| `assets/packed/pal.png` | Stage 3 (`cube_asset-builder`) | Yes |
| `OCT_wowcube-agent-skills/templates/app_ai_template/src/app_ai_template.h` | Project template | Yes |
| `app_<game>/` scaffolded, assets packed, **simulator builds and launches** | `wowcube-boilerplate` skill | Yes |

If any Stage 4 prerequisite is missing when implementation is expected, do NOT proceed — re-run **Stage Detection & Routing** above and drive the missing stage's sub-skill yourself (Stage 1 → `cube_game-designer`, Stage 2 → `technical_prompter`, Stage 3 → `cube_asset-builder`), checkpointing at each boundary.

**Infrastructure gate (do this before Step 1):** Verify the build environment is
ready — `app_<game>/` exists with its `.target` marker, `art/packed/*.raw` and
the asset index `app_<game>/index.bin` are present (the index is as load-bearing
as the `.raw` files — the simulator dies without it), and the simulator builds
and launches (`app_<game>/bin/app_<game>.exe` on
Windows, `app_<game>/build-sim/octavios_sim` on Linux). If any of these
is missing, **invoke the `wowcube-boilerplate` skill (Skill tool)** to scaffold and
verify the infra, then return here. Never dispatch the first coder agent against an
unverified or non-existent project — a broken toolchain discovered mid-implementation
is far more expensive to untangle than one caught before any code is written.

## Constraints

- **Assets (PNGs, WAVs) are prototyped by `cube_asset-builder`** BEFORE this skill runs. By the time this skill starts, the following are on disk and valid:
  - `assets/packed/*.png` and `assets/packed/pal.png` (packed sprites)
  - `assets/wav/*.wav` (source sounds, ≤ 2 seconds) — packing encodes each to `app_<game>/sound/assets/<name>.mp3` (22050 Hz mono CBR 32k, via ffmpeg); the app ships the mp3, never the raw `.wav`
  - `src/app_<game>_ids.h` (BMP_* enum, generated by `pack.py`)
  Agents NEVER create sprite or sound files and NEVER edit `_ids.h`.
- Code agents work only with `app_<game>/src/app_<game>.h` — they reference existing `BMP_<name>` constants from the ids file and sounds via `SND_getAssetId("<name>.mp3")`, with names taken from `plans/<game>_assets.json`. They do NOT create new asset names.

## Architecture

All game code lives in a single file (`app_<game>/src/app_<game>.h`). This means:
- **Coding is always sequential** — only one coder agent modifies the file at a time
- **Verification can overlap with preparation** — while verifier checks prompt N, orchestrator can prepare the task JSON for prompt N+1
- **Quality over speed** — if the next prompt depends on verification results (e.g., the verifier might find issues that change the code), WAIT for verification before dispatching the next coder

### Pipeline Model

```
Time →

Prompt 1:  [===CODER===][==VERIFIER==]
Prompt 2:               [prep JSON..][===CODER===][==VERIFIER==]
Prompt 3:                                         [prep JSON..][===CODER===][==VERIFIER==]
```

The orchestrator decides at each step whether to pipeline or wait:

| Situation | Decision |
|-----------|----------|
| Prompt N verification is running, prompt N+1 does NOT depend on N's verified output | **Pipeline**: prepare N+1 JSON now, dispatch coder as soon as N's coder is done |
| Prompt N verification is running, prompt N+1 builds directly on N's code | **Wait**: verification might trigger fixes that change the code N+1 depends on |
| Prompt N verification failed, fix agent deployed | **Wait**: do not prepare N+1 until fix is verified |
| Prompt N is a foundational prompt (scaffold, data structures, core init) | **Always wait**: later prompts depend heavily on getting this right |
| Prompt N is cosmetic/isolated (audio, visual polish, UI text) | **Safe to pipeline**: failures here won't cascade |

> **In YOLO mode** this same table drives parallelism: "Pipeline" / "Safe to pipeline" rows become parallel verifier+fixer batches, while "Wait" / "Always wait" rows stay strictly sequential. The decision criteria do not change — only the per-prompt user checkpoint between them is removed.

## JSON Communication Protocol

All data between orchestrator and agents is JSON.

### Coding Task JSON (orchestrator → coder agent)

```json
{
  "task": "code",
  "game": "<game_name>",
  "prompt_number": N,
  "prompt_title": "...",
  "total_prompts": M,
  "instructions": "<full prompt instructions text>",
  "platform_reminders": ["..."],
  "verification_criteria": "<what the user should see/hear>",
  "files_to_read": [
    "OCT_wowcube-agent-skills/templates/app_ai_template/src/app_ai_template.h",
    "app_<game>/src/app_<game>.h"
  ],
  "files_to_write": [
    "app_<game>/src/app_<game>.h"
  ],
  "prior_context": [
    {
      "prompt": 1,
      "title": "...",
      "structs_added": [],
      "fields_added": {},
      "functions_added": [],
      "globals_changed": [],
      "sprites_used": 0,
      "notes": "..."
    }
  ]
}
```

### Verification Task JSON (orchestrator → verifier agent)

```json
{
  "task": "verify",
  "game": "<game_name>",
  "prompt_number": N,
  "prompt_title": "...",
  "instructions": "<original prompt instructions>",
  "verification_criteria": "<what the user should see/hear>",
  "files_to_read": [
    "app_<game>/src/app_<game>.h",
    "plans/<game>_gdd.md",
    "OCT_wowcube-agent-skills/templates/app_ai_template/src/app_ai_template.h"
  ],
  "prior_context": [ ... ]
}
```

### Coder Response JSON (coder agent → orchestrator)

```json
{
  "status": "done|error",
  "prompt": N,
  "files_modified": ["app_<game>/src/app_<game>.h"],
  "summary": {
    "structs_added": [],
    "fields_added": {},
    "functions_added": [],
    "globals_changed": [],
    "sprites_used": 0,
    "notes": "..."
  },
  "error": null
}
```

### Requirements Verifier Response JSON (requirements agent → orchestrator)

```json
{
  "agent": "requirements",
  "prompt": N,
  "scores": {
    "completeness": 45,
    "gdd_alignment": 25,
    "no_regressions": 20,
    "verification_criteria": 10
  },
  "total": 100,
  "status": "pass|fail",
  "issues": [
    {"severity": "critical|major|minor", "category": "completeness|gdd_alignment|no_regressions|verification_criteria", "description": "...", "location": "...", "deduction": N}
  ],
  "summary": "one sentence assessment"
}
```

### Template Verifier Response JSON (template agent → orchestrator)

```json
{
  "agent": "template",
  "prompt": N,
  "scores": {
    "api_correctness": 40,
    "platform_constraints": 30,
    "code_quality": 30
  },
  "total": 100,
  "status": "pass|fail",
  "issues": [
    {"severity": "critical|major|minor", "category": "api_correctness|platform_constraints|code_quality", "description": "...", "location": "...", "template_rule": "...", "deduction": N}
  ],
  "summary": "one sentence assessment"
}
```

## Stage 3: Asset Generation

Reached when the GDD, prompts, and manifest exist but `assets/packed/` or `src/app_<game>_ids.h` is missing. Stage 3 produces the source art (`assets/art/*.png`, `assets/wav/*.wav`) and then packs it. The **source art can be produced two ways**, and the orchestrator MUST let the user choose before generating or packing anything. Both paths converge on the same pack step (Step 3.5).

### Display & sprite sizing (CRITICAL — applies to every sprite, both paths)

The two facts below are the authoritative sizing rule for all WowCube assets. Honor them whenever gating the manifest (Step 3.A1), generating (Path A), validating self-supplied art (Path B), or reviewing sizes — and surface them to the user whenever sprite dimensions come up.

1. **The physical screen (quadrant) is 240×240 px.** That is the hardware resolution of one of the cube's 24 displays.
2. **But every palette sprite is authored/generated at HALF resolution, because the engine applies a software ×2 upscale at draw time.** (Full-color sprites are the one exception — see below.) The governing formula for palette assets (not just backgrounds) is:

   > **authored size = intended on-screen size ÷ 2**

   The engine multiplies the authored sprite by 2 when drawing it. So a full-screen sprite is authored at **120×120** (→ 240×240 on screen), making **120×120 the hard maximum** — no sprite is ever larger than that.

This applies to **every** asset, sized proportionally to how much of the screen it should cover:
- **Full screen** → on-screen 240×240 → authored **120×120** (the ceiling).
- **Character/object covering a quarter of the screen** → on-screen 60×60 → authored **30×30** — **not 60×60**. (Thinking "a quarter of 240 = 60, so 60×60" is the classic mistake: that 60 is the *on-screen* size, which must still be halved to 30 for authoring.)
- **Any other sprite** → take its target footprint on the 240×240 screen and halve both dimensions.

Practical consequences:
- **Never generate or request a sprite larger than 120×120**, and for every smaller asset compute its authored size as (intended on-screen px ÷ 2) — apply this to characters, items, UI elements, effects, everything, not only fullsize/`bg` sprites.
- Manifest `size` values (`plans/<game>_assets.json`) are in **authored (pre-upscale) pixels**: full-screen = `[120, 120]`, quarter-screen character = `[30, 30]`, etc.
- If a manifest sprite's `size` looks like it was set in on-screen pixels (e.g. a quarter-screen sprite at `[60, 60]`, or anything > 120), treat it as a sizing error: return to Stage 2 (`technical_prompter`) to halve it rather than generating it — unless the sprite is a full-color fullsize sprite, per the exception below.

**Full-color exception (beta).** A manifest sprite may set `color: "full"` — full-color RGB565 (2 bytes/texel) with **NO transparency** (0x0000 draws as opaque black, so the alpha flag is forbidden). Combined with `flags.fullsize`, a full-color sprite draws **1:1 with no ×2 upscale** and is therefore authored at its **native on-screen size, up to the full 240×240**. Use full-color for backgrounds, tile sheets, and full-screen art only; anything that needs transparency stays a palette sprite under the ½-resolution rule above. A small full-color sprite (each side ≤ 120, no `fullsize`) is also legal, but it still draws at ×2 like every other sprite — so its `size` still follows the ÷2 formula.

### Step 3.0: Choose the asset source (ASK FIRST — before any generation or packing)

Before touching `cube_asset-builder`, present the choice with the **Agent tool's `AskUserQuestion`** (or a short bullet list + wait). Do NOT pick for the user.

- **Option 1 — AI generation.** The user provides an image-model API key (GPT Image 2 / OpenRouter); the orchestrator generates every sprite from its `gen_prompt`. → **Path A**.
- **Option 2 — Self-supplied assets.** The user creates the assets themselves, following the manifest's exact specs (name, size, animation frames) and the GDD's art style. The orchestrator does NOT generate — it validates completeness, then packs. → **Path B**.

Route to the chosen path below.

> **YOLO mode:** do not ask here. Default to **Path A** and use the `OPENROUTER_API_KEY` gathered during the YOLO one-time intake. Only use Path B in YOLO if a complete asset set is already on disk (the completeness check in 3.B2 still applies). If Path A is required but the key is missing, that is the one input YOLO must request before continuing.

### Path A — AI generation (Option 1)

**3.A1 Pre-generation gates** (both must pass; if either fails, do NOT generate):
1. **`gen_prompt` coverage.** Load `plans/<game>_assets.json` and confirm **every sprite** has a non-empty `gen_prompt`. (Sounds do NOT need one.) A blank `gen_prompt` makes `gen_sprites.py` fail with `ValueError`. If any sprite is missing it, **return to Stage 2 (`technical_prompter`)** — do not patch the manifest yourself.
2. **Image-model key present.** Generation calls OpenRouter; without the key `genimg.py` raises `ImageGenError`. If `OPENROUTER_API_KEY` is not set in the sandbox where `build_pipeline.py` runs, **this is the "add a key" step** — ask the user to export it (`export OPENROUTER_API_KEY=sk-or-...`) now, before proceeding. Never hardcode it; never commit it.

**3.A2 Generate.** Invoke `cube_asset-builder` (Skill tool). It runs `build_pipeline.py generate` → `gen_sprites.generate()` → `genimg.generate_image(gen_prompt, size)` per sprite (OpenRouter image model) → PNGs in `assets/art/`; sounds synthesised as placeholders into `assets/wav/`. Output is non-deterministic across runs.

**3.A3 Consistency review** (automated, BEFORE the user review). Dispatch one **read-only** asset-consistency reviewer via the Agent tool. It inspects `assets/art/*.png` against the GDD's global art style and each `gen_prompt`, reporting which **groups** (derived per `manifest_schema`) drift — wrong palette/mood, inconsistent line weight or scale, broken animation continuity, leaked text/watermark/background, off-spec dimensions. Pass it the Asset Consistency Task JSON; it returns the Asset Consistency Response JSON (both below).
- **`status: "pass"`** → go to Step 3.4 (user review).
- **`status: "fail"`** → for each flagged group, re-run `cube_asset-builder`'s `regen <group>` (→ `build_pipeline.py generate --group <name>`), then re-run this review. **Max 3 review→regen cycles**, then hand the remaining issues to the user at Step 3.4.

This is a quality gate, not a replacement for the human checkpoint. Path A then continues at **Step 3.4**.

### Path B — Self-supplied assets (Option 2)

The user makes the art by hand (or with their own tools) from the GDD. The orchestrator's job is to make the spec unambiguous, then refuse to pack an incomplete set.

**3.B1 Hand the user the exact asset spec** (derive entirely from `plans/<game>_assets.json` + GDD §1 art style):
- **Sprites** → drop into `assets/art/`. For each: filename **`<name>.png`** (verbatim, lowercase), exact size **`[w, h]`** in pixels, RGBA, transparent background (unless `flags.bg`/`flags.fullsize`), plus the `description` (and `gen_prompt` if present) as the visual brief. Animation frames must be the full contiguous `_00.._NN` set.
- **Sounds** → drop into `assets/wav/`. For each: **`<name>.wav`**, ≤ `duration_ms`. (Packing encodes it to `sound/assets/<name>.mp3` automatically — the user supplies only the source `.wav`.)
- The reserved **`0.png` is auto-created by the packer** — the user must NOT make it.
- Stress that the **GDD's global art style applies to every file** so the set stays cohesive.

**3.B2 Completeness check (MANDATORY — a partial set is an unplayable build).**
Validate the files actually present against the manifest:
- For every sprite in the manifest, confirm `assets/art/<name>.png` exists (optionally verify pixel dimensions match `size`).
- For every sound, confirm `assets/wav/<name>.wav` exists.
- **List EVERY missing file explicitly** (by `<name>` and expected size/duration). If anything is missing, **STOP**: tell the user exactly which sprites/sounds are absent and that the build will not be playable — every `BMP_<name>`/`SND_getAssetId("<name>.mp3")` referenced in the prompts must exist or the code fails to compile. Wait for the user to add the missing files, then re-run this check. **Never pack a partial set.** (This check holds even in YOLO — a partial set cannot compile.)

**3.B3 When complete → pack.** Skip generation and the AI consistency review (the user authored and approved their own art). Go straight to **Step 3.5**.

### Step 3.4: User review checkpoint (Path A only; MANDATORY — never skip)

This is `cube_asset-builder`'s own mandatory review of the AI-generated set. Present the generated set and the consistency reviewer's verdict, then STOP and wait for the user. Offer the verbatim options the asset-builder supports: `ok`/`continue`, `regen <group>`, `swap <name>`, `edit <name> size <WxH>`. Never auto-continue to pack.

> **YOLO mode:** skip this user review. Auto-accept any set the consistency reviewer (3.A3) passed; the review→regen loop already enforced cohesion. Proceed directly to Step 3.5.

### Step 3.5: Pack & boundary checkpoint (both paths)

After approval (Path A: user replies `ok`; Path B: the completeness check passed), invoke `cube_asset-builder`'s pack stage → `build_pipeline.py pack`. It **assembles `assets/assets.psd`, fills `assets/exported/` and `assets/packed/` (+ `pal.png`), and writes `src/app_<game>_ids.h`** with the `BMP_*` enum. Then run the normal **Stage 3→4 boundary checkpoint** (summarize asset counts + `BMP_*` constant count, wait for approval) before any Stage 4 work. (In YOLO, the boundary checkpoint is auto-advanced — see `## YOLO Mode`.)

### Asset Consistency Task JSON (orchestrator → reviewer agent)

```json
{
  "task": "asset_consistency",
  "game": "<game_name>",
  "art_style": "<GDD §1 global art style, palette, mood — the cohesion contract>",
  "art_dir": "assets/art",
  "files_to_read": [
    "plans/<game>_assets.json",
    "plans/<game>_gdd.md"
  ],
  "sprites": [
    {"name": "hero_idle_00", "size": [64, 64], "group": "hero",
     "anim": "hero_idle", "frame": 0, "gen_prompt": "..."}
  ]
}
```

### Asset Consistency Response JSON (reviewer agent → orchestrator)

```json
{
  "agent": "asset_consistency",
  "status": "pass|fail",
  "groups": [
    {
      "group": "hero",
      "verdict": "pass|fail",
      "issues": [
        {"sprite": "hero_idle_01", "category": "palette|style|scale|anim_continuity|leaked_content|dimensions", "severity": "major|minor", "description": "..."}
      ],
      "regen_recommended": true
    }
  ],
  "summary": "one-sentence assessment of set-wide visual cohesion"
}
```

### Asset Consistency Reviewer Agent Prompt Template

```
You are a WowCube asset-consistency reviewer. You do NOT generate or edit images — you only inspect and report.

## Task
<insert Asset Consistency Task JSON>

## Rules
1. Read the GDD art style and every sprite's gen_prompt. The `art_style` field is the cohesion contract — the whole set must look like one game.
2. View each PNG in `art_dir`. Judge per derived group (sprites sharing a group, e.g. all frames of one animation).
3. Flag: palette/mood drift from the GDD, inconsistent line weight or scale across the set, broken animation continuity (pose jumps, pivot drift), leaked text/watermark/border/background scenery, and dimensions that do not match the manifest `size`.
4. Recommend `regen` for any group that fails. Be specific and per-sprite.
5. Return ONLY the Asset Consistency Response JSON. No markdown, no prose outside the JSON.
```

## Stage 4: Implementation Workflow

This is the implementation stage — reached only after Stages 1–3 are complete and their boundary checkpoints approved. Here the orchestrator dispatches coder/verifier/fixer **subagents via the Agent tool** to implement the prompts one at a time.

### Step 1: Initialize

1. Verify all Stage 4 prerequisites exist
2. Read `plans/<game>_prompts.md` — parse all prompts (delimited by `## Prompt N:`)
3. Read `plans/<game>_gdd.md` for game understanding
4. Check if `context/<game>_context.json` exists — if yes, offer to resume
5. If new game, reset the game source to a clean skeleton: copy
   `OCT_wowcube-agent-skills/src/app_structure_example.h` → `app_<game>/src/app_<game>.h`.
   (`wowcube-boilerplate` left a working demo there to prove the build; overwriting
   it with the skeleton is expected — the verified folder, marker, packed assets,
   and toolchain are what carry forward.)
6. Count total prompts, present execution plan to user. **In YOLO**, also build the prompt dependency graph now (foundational vs. cosmetic/isolated) so parallel batches can be planned, and do not wait for approval of the plan.

### Step 2: Validate Prompts

Each prompt must represent a testable build. Before executing, validate:
- Has a clear **Verification** section
- Does not depend on a subsequent prompt to be testable
- Instructions are self-contained for a compilable result

Failed validation → return to `technical_prompter` for rework.

### Step 3: Execute Prompt Cycle

For each prompt, repeat this cycle:

#### 3a. Build Coding Task JSON

1. Read current `app_<game>/src/app_<game>.h`
2. Read `context/<game>_context.json` for prior context
3. Construct the Coding Task JSON
4. Select relevant platform reminders:

| If prompt mentions... | Include reminder |
|-------------------|----------|
| new global, TL, static | `"All globals must use TL macro: TL static type name;"` |
| iterate, loop, gObjects, for | `"gObjects[0] is reserved — start from index 1, validate with obj->Idx == i"` |
| label, text, OCT_label, glyph | `"Label visibility: must also toggle all child glyphs where obj->Parent == label->Idx"` |
| OCT_add, sprite, layer | `"SPRITES_CAP = 400 max. Verify total count. NO NEED to account for GAP in x/y coordinates — the engine handles GAP offsets automatically."` |
| position, coordinate, x/y, center, place, fit, bounds, edge | `"Coordinates live in the 240x240 on-screen space (screen center = 120,120). Sprites are authored at HALF size and the engine upscales them x2 at draw time, so a sprite's ON-SCREEN extent = 2x its authored size. Do ALL position/centering/edge-fit math in on-screen pixels using the upscaled extent (2x authored), NEVER the authored sprite size."` |
| collision, overlap, hit, distance, spacing, grid, snap | `"Compute collision boxes, overlap tests, spacing and grid steps from the UPSCALED on-screen sprite extent (2x authored size) in the 240x240 space — using the authored (half) size makes hitboxes and gaps half as big as what's drawn and breaks gameplay."` |
| walk, move, cross, plane, wrap | `"Cross-display distance = 240.0f + 2.0f * GAP. Use OCT_TM_walk with wrap=true. OCT_TM_move is in-plane only — no cross-plane handling."` |
| sound, SND, audio, mp3 | `"Pattern: int32_t id = SND_getAssetId(\"<name>.mp3\"); SND_play(id, volume); — sounds are packed as mp3, so the name passed to SND_getAssetId always ends in .mp3, never .wav."` |
| animation, sequence, frame | `"OCT_sequence restart: OCT_SEQ_RESTART, OCT_SEQ_REVERSE, OCT_SEQ_REFRESH"` |
| twist, twid, on_twisted | `"Full twists: twid 0-11. Half twists: twid 12-23 (offset by OCT_TWIST_HALF). CW/CCW defined looking from outside the cube at the given face (right-hand rule)."` |
| angle, rotation, direction | `"Angle 'a' / Tm.A: degrees, positive = CCW, 0 = right (+X)."` |
| background, color, OCT_background | `"OCT_background color is in RGB565 format."` |
| random, OCT_random | `"OCT_random(dmin, dmax): upper bound dmax is exclusive."` |
| transparency, transp, fade | `"Transparency: 0 = fully opaque, OCT_TRANSP_MAX = fully transparent."` |
| teleport, set, OCT_TM_set | `"OCT_TM_set overwrites position, angle, and plane directly (teleport) — no animation."` |
| XSIGN, YSIGN, quad coords | `"XSIGN/YSIGN are already declared in oct_shared.h — do NOT redeclare."` |

**Always include these reminders in EVERY coding task (mandatory for all prompts, including YOLO):**
- `"Use explicit type casts — never rely on implicit conversions between numeric types, pointers, or enums."`
- `"Use only fixed-width types from <stdint.h> (int8_t, int16_t, int32_t, uint8_t, uint16_t, uint32_t, size_t). Never use plain int, short, long."`
- `"All 7 handler functions must be present: on_init(), on_tick(), on_tap(int32_t tapid, int32_t count), on_twisted(int32_t twid, uint32_t disconnected_ms), on_pretwisted(int32_t twid), on_shake(int32_t shakeid), on_proc_draw (stub). on_shake and on_proc_draw are mandatory stubs: on_shake is link-required — the ARM module fails to link without it; on_proc_draw is bound unconditionally by the simulator, so the SIM build fails without the stub, while the ARM module only references it under #define APP_HAS_PROC_DRAW. Never build gameplay on shake input (the engine currently always runs the system default go-home). If a handler has no game logic, reference every parameter to suppress warnings (e.g., twid; disconnected_ms;)."`
- `"Sprites are authored at HALF resolution and the engine upscales them x2 at draw time. ALL coordinate math (positioning, centering, edge/screen-fit, movement bounds, collision boxes, spacing, grids) runs in the 240x240 on-screen space and MUST use each sprite's UPSCALED on-screen extent = 2x its authored size. Never use the authored (half) sprite dimensions for layout or collision — that makes everything half as big as drawn and breaks the game."`

#### 3b. Dispatch Coder Agent

Deploy one Agent with the coding task JSON.

##### Coder Agent Prompt Template

```
You are a WowCube game coder. Implement exactly what the task describes.

## Task
<insert Coding Task JSON>

## Rules
1. Read ALL files listed in `files_to_read` BEFORE writing any code
2. `OCT_wowcube-agent-skills/templates/app_ai_template/src/app_ai_template.h` is the SOURCE OF TRUTH for API usage — do NOT copy demo code
3. Follow `instructions` exactly — do not add features, do not refactor unrelated code
4. Respect all `platform_reminders`
5. Use `prior_context` to understand what already exists — do not break it
6. ALWAYS use explicit type casts — never rely on implicit conversions between numeric types, pointers, or enums. Every narrowing, widening, or cross-type assignment must have a visible cast
7. Use only fixed-width types from `<stdint.h>` (int8_t, int16_t, int32_t, uint8_t, uint16_t, uint32_t, size_t). Never use plain `int`, `short`, `long`
8. All 7 handler functions (on_init, on_tick, on_tap(tapid, count), on_twisted, on_pretwisted, on_shake, on_proc_draw) must be present — on_shake and on_proc_draw stay stubs (they are link-required; do not build gameplay on shake, and on_proc_draw is only active under APP_HAS_PROC_DRAW). If a handler has no game logic, reference every parameter as a statement to suppress unused-variable warnings
9. Write modular, readable code: extract game state into structs, split logic into small focused functions, use named constants instead of magic numbers
10. Sprites are authored at HALF resolution; the engine upscales them x2 when drawing. The 240x240 quad is the on-screen coordinate space (center = 120,120). Do EVERY layout and collision computation — positioning, centering, screen/edge fitting, movement bounds, hitboxes, spacing, grid steps — in on-screen pixels using each sprite's UPSCALED extent (2x its authored size). NEVER use the authored (half) sprite size for coordinates or collision, or everything ends up half the size it's drawn and the game breaks
11. After implementing, respond with the Coder Response JSON

## Response
Return ONLY the Coder Response JSON. No markdown, no explanation outside the JSON.
```

#### 3c. Dispatch Verifier Agents

After coder completes, deploy two verifier agents **sequentially** using the `cube_verifier` skill. Pass the same Verification Task JSON to each.

**Step 1 — Requirements Agent.** Deploy an agent with the Requirements Agent prompt template from the `cube_verifier` skill. Returns a JSON with scores for: completeness (45), gdd_alignment (25), no_regressions (20), verification_criteria (10). Max 100 points.

**Step 2 — Template Agent.** Deploy an agent with the Template Agent prompt template from the `cube_verifier` skill. Returns a JSON with scores for: api_correctness (40), platform_constraints (30), code_quality (30). Max 100 points.

**Evaluate:** Each agent scores out of 100 independently. Both must score >= 90 to pass. If either fails, pass its issues to the fix agent.

**Pipeline rule:** If the orchestrator is confident that prompt N+1 does NOT depend on N's verification outcome (see Pipeline Model table), it MAY begin preparing N+1's task JSON while the verifiers run. But it MUST NOT dispatch N+1's coder until verification passes. **In YOLO**, this fan-out is the norm: verifiers and fixers for independent prompts run in parallel batches and the next coder is dispatched as soon as the file is free — coding still serialized, no user checkpoint between prompts.

#### 3d. Handle Verification Result

- **Score >= 90:** Save context (Step 4), proceed to checkpoint (Step 5)
- **Score < 90:** Deploy fix agent. Max **5 attempts** per prompt.

##### Fix Agent Prompt Template

```
You are a WowCube code fixer. Fix the issues found by the verifier.

## Task
{
  "task": "fix",
  "game": "<game_name>",
  "prompt_number": N,
  "original_instructions": "<original prompt instructions>",
  "issues": <issues array from verifier>,
  "files_to_read": ["app_<game>/src/app_<game>.h", "OCT_wowcube-agent-skills/templates/app_ai_template/src/app_ai_template.h"],
  "files_to_write": ["app_<game>/src/app_<game>.h"]
}

## Rules
1. Read the source file FIRST
2. Fix ONLY the listed issues — do not refactor or add features
3. Return Coder Response JSON when done
```

After fix agent completes → re-deploy verifier. Repeat until pass or 5 attempts exhausted.

**After 5 failures (checkpointed mode):**
1. Save current state to context
2. Present issues to user
3. Ask: "Verification failed after 5 attempts (best score: X). Continue / retry / stop?"

**After 5 failures (YOLO mode) — auto-decide, do not ask:**
- **Foundational prompt** (scaffold, data structures, core init): save context and **abort the run**, surfacing the failure immediately.
- **Non-foundational prompt**: keep the best-scoring version, record it as a known issue for the end-of-run report, and **continue** to the next prompt.

### Step 4: Save Context

After verification passes (score >= 90), update `context/<game>_context.json`:

```json
{
  "game": "<game_name>",
  "last_completed_prompt": N,
  "total_prompts": M,
  "prompts": [
    {
      "prompt": 1,
      "title": "Project scaffold and background",
      "structs_added": ["appObject_t fields: type, state"],
      "fields_added": {"appvars_t": ["gameState", "score"]},
      "functions_added": ["initGame"],
      "globals_changed": [],
      "sprites_used": 0,
      "verification_score": 97,
      "notes": "Black background on all faces, engine initialized"
    }
  ]
}
```

### Step 5: Checkpoint with User (MANDATORY in checkpointed mode — SKIPPED in YOLO)

> **YOLO mode:** skip this entire step. Do not summarize, do not stop, do not ask. Save context (Step 4) and immediately proceed to the next prompt cycle. The only report is the single end-of-run report at completion (see `## YOLO Mode` → YOLO completion).

**In checkpointed mode, after EVERY prompt completes (verified), you MUST checkpoint and STOP.**

Do NOT proceed to the next prompt. Do NOT dispatch any more agents. WAIT for the user.

1. **Summarize:**
   - Prompt number, title, verification score
   - Features added, files modified
   - Fix cycles needed (if any)

2. **Test instructions** — what to look for in the simulator

3. **STOP and ask the user** (present these options):
   - "Everything works — continue"
   - "Found bugs — here is what I see: ..."
   - "Want to change the design — ..."
   - "Stop here — will resume later"

4. **Wait for explicit user response.** Do not interpret silence as approval.

5. **Handle feedback:**
   - **Continue**: proceed to next prompt cycle
   - **Bugs**: deploy fix agent → re-verify → re-checkpoint (and STOP again)
   - **Design change**: note change, adjust remaining prompts
   - **Stop**: context already saved, safe to resume

### Step 6: Handle Errors

#### Agent Failure
1. Read the error from agent response
2. Deploy fix agent with error details
3. Re-verify after fix

#### Context Drift
If actual source diverges from context JSON:
1. Re-read all source files
2. Update context JSON to match reality
3. Adapt remaining prompts if needed

#### Resume After Interruption
1. Read `context/<game>_context.json`
2. Identify `last_completed_prompt`
3. Read current source to verify consistency
4. Continue from next prompt

### Step 7: Complete

After all prompts executed and final checkpoint passes:
1. Summary: total prompts, fix cycles, average verification score
2. **Run Stage 5 — Package & Verify (mandatory, not optional).** A passing
   simulator build is **not** a shippable result. The simulator runs its own
   PC-compiled code, so a game can look perfect in the sim while the `.oct`
   contains **no ARM code at all** and is completely dead on the physical cube.
   This is the single most common way to "finish" a game that doesn't actually
   run on hardware — so the orchestrator closes this gap itself (Stage 5) rather
   than handing it to the user.

   Following the same mechanism as the other stages, **invoke the
   `wowcube-boilerplate` skill via the Skill tool** as the final action; it runs
   the device build:

   ```
   # Windows
   scripts/build_device.ps1 -AppDir <workspace>/app_<game>
   # Linux
   scripts/build_device.sh --app-dir <workspace>/app_<game>
   ```

   That compiles the ARM target (`out/app_<game>.bin`), has the simulator pack
   assets + sounds + ARM code into `app_<game>/app_<game>.oct`, and **verifies the
   ARM code is actually embedded** (it fails loudly on an asset-only pack). The
   task is not complete until this exits 0. If the ARM toolchain is missing, that
   is a `wowcube-boilerplate` toolchain problem (`check_env.ps1` / `check_env.sh`)
   to resolve — not a reason to ship the sim-only `.oct`. (This Stage 5
   verification is a hard invariant even in YOLO — a sim-only `.oct` is never
   delivered.)

   **Critical ordering:** the simulator rewrites `app_<game>.oct` as an
   asset-only pack on *every* launch, so all per-prompt sim testing (Stage 4)
   necessarily happens *before* Stage 5. This is exactly why the device `.oct` is
   built once, here at the end, and never per-prompt — a per-prompt device build
   would just be clobbered by the next sim run. Never hand the user a `.oct` that
   was last touched by a plain sim run.

   Then **checkpoint with the user (Stage 5 boundary):** report the absolute path
   to the verified package and confirm it is ready to flash onto the cube:

   ```
   app_<game>/app_<game>.oct
   ```

   (In YOLO this final report is delivered automatically without waiting — it is
   the single end-of-run report.)
3. Suggest next steps (testing on the physical cube, polish, features)

## Mod Mode Workflow

Reached when **Mode Detection** selects Mod mode: the user wants to change a game that already works. The whole mode is governed by one rule.

### Prime directive — the working project is the source of truth

**Make the smallest change that satisfies the request.** Do not rewrite, refactor, re-architect, or restructure code, assets, or data beyond what the change strictly needs. Structural or design-level changes are allowed **only when the user explicitly asks for them**; in every other case, solve it минимально — "малой кровью". A working game the user is happy with is far more valuable than a "cleaner" one that now behaves differently, so when a change *can* be done as a small local edit, it MUST be.

This mode adds no new agents or sub-skills — it reuses `cube_asset-builder`, the coder/verifier/fixer subagents, and `wowcube-boilerplate`, routing them at the smallest scope that does the job.

### M1 — Analyze the target project

1. Locate the game to mod. It must already exist in the project folder as `app_<game>/`. If several games are present, **ask which one**. If the named project isn't there, stop and tell the user.
2. Read the baseline — this is the source of truth: `app_<game>/src/app_<game>.h`, plus `plans/<game>_assets.json` and `app_<game>/src/app_<game>_ids.h` if present, and `plans/<game>_gdd.md` if present. A hand-dropped project may have none of the `plans/` files — that's fine; the code and ids header are enough to mod.
3. Confirm the baseline currently builds/runs, so regressions are detectable later.

### M2 — Analyze the request and classify it

Map the change to the smallest applicable type. Pick the **cheapest type that fully covers the request** — never escalate higher than needed.

| Type | What it is | Minimal path |
|------|-----------|--------------|
| **T1 — Logic / parameters** | speed, balance, timing, small behavior tweaks | one scoped coder task on `app_<game>/src/app_<game>.h` → verify → fix |
| **T2 — Sprite** | replace/add an image (e.g. a friend's photo) | **user supplied the image** → asset-builder Path B (fit it to the manifest spec, resize, repack); **needs generating** → asset-builder Path A (OpenRouter key, `regen`/add for *that sprite only*) → repack → if a new `BMP_*` appears, one scoped coder edit to reference it |
| **T3 — Sound** | replace/add a sound (source `.wav`; packing re-encodes it to `sound/assets/<name>.mp3`) | asset-builder for that one sound → repack |
| **T4 — Structural** | new mechanic, refactor, architecture/design change | **only if the user explicitly asked.** Otherwise propose the smallest alternative that meets the intent and ask before doing it. |

Asset work (T2/T3) needs a manifest entry for the affected asset. If `plans/<game>_assets.json` exists, edit just that one entry; if there is none, add a single minimal entry for the changed asset rather than regenerating the whole manifest.

### M3 — Mini-plan + checkpoint (MANDATORY before any change)

Present a short plan: the chosen type, exactly which files/assets change, and why this is the minimal path. If the optimal path needs a resource (e.g. an OpenRouter image key for T2 generation), request it here. **STOP and wait for explicit user approval before touching anything.** Never start editing or generating before the plan is approved.

> **YOLO mode:** the mini-plan is still composed but auto-approved — do not stop. Gather any required resource (e.g. the OpenRouter key) during the YOLO intake; if it is genuinely missing, that single input may be requested, otherwise proceed.

### M4 — Execute at minimal scope

Run the chosen path through the existing components, scoped to the change:
- **Code (T1, or the wiring step of T2):** dispatch one coder subagent (Stage 4 mechanism) whose task is *only* the requested edit. `files_to_write` stays `app_<game>/src/app_<game>.h`; `prior_context` describes the existing structures so the agent extends, never rewrites.
- **Assets (T2, T3):** drive `cube_asset-builder` for the specific sprite/sound (Path A `regen`/add, or Path B user-supplied), then its pack stage to refresh `assets/packed/*`, `app_<game>/art/packed/*.raw`, `app_<game>/index.bin`, and `src/app_<game>_ids.h`.

### M5 — Verify, then sim checkpoint

Run the same verifier (threshold 90/90), but frame the criteria for a mod: **(a)** the requested change is implemented, and **(b)** nothing else regressed versus the M1 baseline. `no_regressions` carries the most weight here; `gdd_alignment` is checked only if a GDD exists. On failure, deploy the fixer (max 5 attempts), exactly as in Stage 4.

Then run the per-change checkpoint just like the Stage 4 per-prompt checkpoint: summarize what changed, give sim test instructions, **STOP**, and wait for the user. Several independent mods are handled one at a time, each with its own checkpoint — never batch.

> **YOLO mode:** the verifier (90/90) and fixer still run — that gate is never dropped. The per-change user checkpoint is skipped; independent mods are processed back-to-back and reported once at the end alongside the repackaged `.oct`.

### M6 — Repackage for the device

A mod isn't done until the cube package is rebuilt. Run **Stage 5** (`wowcube-boilerplate` → `build_device.ps1` / `build_device.sh`) so `app_<game>/app_<game>.oct` re-embeds the ARM code — mandatory for the same reason as in Build mode: the simulator rewrites the `.oct` as asset-only on every launch, so the device build must be the last action. Then checkpoint with the absolute `.oct` path. (In YOLO, the device build + ARM-embed verification still run; the final path is reported automatically.)

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Verification threshold | 90 | Minimum score to pass (per agent, each scores out of 100) |
| Max retry attempts | 5 | Max fix+re-verify cycles per prompt |
| Start from | 1 | First prompt to execute (for resumption) |
| Run mode | checkpointed | `checkpointed` (default — stop at every stage boundary and after every prompt) or `yolo` (autonomous — no checkpoints until the final device `.oct`). YOLO is opt-in only; see `## YOLO Mode`. |
| YOLO foundational-failure | abort | On 5-attempt failure of a foundational prompt in YOLO, abort the run; non-foundational failures keep best effort and continue. |
| YOLO asset path | A (AI gen) | YOLO defaults to AI generation (Path A) and gathers the OpenRouter key up front; Path B only if a complete set is already on disk. |
