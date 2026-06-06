---
name: cube_orchestrator
description: >-
  Use as the single entry point for ANY WowCube game work — when the user says
  "make a game", "design a game", "create a game", "build the game", "implement
  this", "start coding", "run the prompts", or wants to resume a WowCube project.
  The master controller for the whole pipeline: it routes through design, prompts,
  assets, and implementation, and manages every sub-skill and subagent.
---

# WowCube Cube Orchestrator

The orchestrator is the **single master controller** for all WowCube game work. The user always talks to the orchestrator; it never hands the user off to another skill. Instead, it detects which pipeline stage the project is in and drives the appropriate sub-skill or subagents itself.

**Core principle:** The orchestrator never writes game code, never designs the game, never authors prompts, and never generates assets *itself*. It reads, plans, routes, dispatches, and coordinates. Every stage of work is done by a sub-skill (`cube_game-designer`, `technical_prompter`, `cube_asset-builder`) or by a subagent (coder, verifier, fixer). Parallelism must never compromise correctness — when in doubt, wait.

## The Pipeline (what the orchestrator manages)

The orchestrator owns a four-stage pipeline. It is the only skill the user invokes; the other three skills are components the orchestrator drives.

| Stage | Produces | Driven by | How |
|-------|----------|-----------|-----|
| 1. Design | `plans/<game>_gdd.md` | `cube_game-designer` | Skill tool (interactive, main context) |
| 2. Prompts | `plans/<game>_prompts.md` + `plans/<game>_assets.json` | `technical_prompter` | Skill tool (main context) |
| 3. Assets | `assets/packed/*.png`, `assets/mp3/*.mp3`, `src/app_<game>_ids.h` | `cube_asset-builder` | Skill tool (runs Python pipeline + user review) |
| 4. Implement | `src/app_<game>.h` (per-prompt) | coder / verifier / fixer | Agent tool (subagents) |

**Invocation mechanism:**
- **Stages 1–3 run in the main context via the Skill tool**, because each requires user interaction (the designer's discovery interview, the asset-review checkpoint). The orchestrator invokes the sub-skill, lets it run to completion with its own internal interactions, then returns here.
- **Stage 4 dispatches subagents via the Agent tool**, exactly as described in the implementation workflow below.

## Stage Detection & Routing (do this FIRST on every entry)

On entry — including resumption — determine the active `<game>` (ask the user if ambiguous or multiple games exist; otherwise infer from `plans/` and `context/`). Then inspect the filesystem and route to the FIRST stage whose output is missing:

| Detected state | Route to | Action |
|----------------|----------|--------|
| No `plans/<game>_gdd.md` | **Stage 1** | Invoke `cube_game-designer` via the Skill tool |
| GDD exists, but no `plans/<game>_prompts.md` or no `plans/<game>_assets.json` | **Stage 2** | Invoke `technical_prompter` via the Skill tool |
| Prompts + manifest exist, but `assets/packed/` or `src/app_<game>_ids.h` is missing | **Stage 3** | Invoke `cube_asset-builder` via the Skill tool |
| All Stage 1–3 outputs present | **Stage 4** | Run the implementation workflow below |

After each stage completes, **re-run this detection** to find the next stage — do not assume the next stage; verify its inputs exist.

## Stage-Boundary Checkpoint (MANDATORY between every stage)

After a stage produces its artifact and BEFORE invoking the next stage, the orchestrator MUST:
1. Summarize what the completed stage produced (GDD path, prompt count, asset counts, etc.)
2. **STOP. Do NOT invoke the next stage's sub-skill or any agent.**
3. Present the next stage and wait for explicit user approval ("ok", "continue", "next", etc.)
4. Only after approval, route into the next stage

This is the same non-negotiable discipline as the per-prompt checkpoint in Stage 4. Never auto-advance across a stage boundary. The user reviews each artifact (design, prompts, assets) before the pipeline proceeds.

**MANDATORY RULE — CHECKPOINT AFTER EVERY PROMPT:**
After each prompt cycle (coder → verifier → context save), you MUST:
1. Present the summary and test instructions to the user
2. **STOP. Do NOT dispatch the next coder agent.**
3. Wait for the user's explicit approval ("ok", "continue", "next", etc.)
4. Only after receiving approval, proceed to the next prompt

This is NON-NEGOTIABLE. Never batch multiple prompts. Never skip the checkpoint. Never assume the user wants to continue. The user needs to test every build on the physical device before proceeding.

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
| `src/app_<game>_ids.h` | Stage 3 (`cube_asset-builder`) | Yes |
| `assets/packed/pal.png` | Stage 3 (`cube_asset-builder`) | Yes |
| `OCT_wowcube-agent-skills/templates/app_ai_template.h` | Project template | Yes |
| `app_<game>/` scaffolded, assets packed, **simulator builds and launches** | `wowcube-boilerplate` skill | Yes |

If any Stage 4 prerequisite is missing when implementation is expected, do NOT proceed — re-run **Stage Detection & Routing** above and drive the missing stage's sub-skill yourself (Stage 1 → `cube_game-designer`, Stage 2 → `technical_prompter`, Stage 3 → `cube_asset-builder`), checkpointing at each boundary.

**Infrastructure gate (do this before Step 1):** Verify the build environment is
ready — `app_<game>/` exists with its `.target` marker, `art/packed/*.raw` are
present, and `app_<game>/bin/app_<game>.exe` builds and launches. If any of these
is missing, **delegate to the `wowcube-boilerplate` skill** to scaffold and verify
the infra, then return here. Never dispatch the first coder agent against an
unverified or non-existent project — a broken toolchain discovered mid-implementation
is far more expensive to untangle than one caught before any code is written.

## Constraints

- **Assets (PNGs, MP3s) are prototyped by `cube_asset-builder`** BEFORE this skill runs. By the time this skill starts, the following are on disk and valid:
  - `assets/packed/*.png` and `assets/packed/pal.png` (packed sprites)
  - `assets/mp3/*.mp3` (sounds, ≤ 2 seconds, 96 kbps)
  - `src/app_<game>_ids.h` (BMP_* enum, generated by `pack.py`)
  Agents NEVER create sprite or sound files and NEVER edit `_ids.h`.
- Code agents work only with `src/app_<game>.h` — they reference existing `BMP_<name>` constants from the ids file and `"<name>.mp3"` string literals from `plans/<game>_assets.json`. They do NOT create new asset names.

## Architecture

All game code lives in a single file (`src/app_<game>.h`). This means:
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
    "OCT_wowcube-agent-skills/templates/app_ai_template.h",
    "src/app_<game>.h"
  ],
  "files_to_write": [
    "src/app_<game>.h"
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
    "src/app_<game>.h",
    "plans/<game>_gdd.md",
    "OCT_wowcube-agent-skills/templates/app_ai_template.h"
  ],
  "prior_context": [ ... ]
}
```

### Coder Response JSON (coder agent → orchestrator)

```json
{
  "status": "done|error",
  "prompt": N,
  "files_modified": ["src/app_<game>.h"],
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
    "api_correctness": 45,
    "platform_constraints": 35,
    "code_quality": 20
  },
  "total": 100,
  "status": "pass|fail",
  "issues": [
    {"severity": "critical|major|minor", "category": "api_correctness|platform_constraints|code_quality", "description": "...", "location": "...", "template_rule": "...", "deduction": N}
  ],
  "summary": "one sentence assessment"
}
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
6. Count total prompts, present execution plan to user

### Step 2: Validate Prompts

Each prompt must represent a testable build. Before executing, validate:
- Has a clear **Verification** section
- Does not depend on a subsequent prompt to be testable
- Instructions are self-contained for a compilable result

Failed validation → return to `technical_prompter` for rework.

### Step 3: Execute Prompt Cycle

For each prompt, repeat this cycle:

#### 3a. Build Coding Task JSON

1. Read current `src/app_<game>.h`
2. Read `context/<game>_context.json` for prior context
3. Construct the Coding Task JSON
4. Select relevant platform reminders:

| If prompt mentions... | Include reminder |
|-------------------|----------|
| new global, TL, static | `"All globals must use TL macro: TL static type name;"` |
| iterate, loop, gObjects, for | `"gObjects[0] is reserved — start from index 1, validate with obj->Idx == i"` |
| label, text, OCT_label, glyph | `"Label visibility: must also toggle all child glyphs where obj->Parent == label->Idx"` |
| OCT_add, sprite, layer | `"SPRITES_CAP = 400 max. Verify total count. NO NEED to account for GAP in x/y coordinates — the engine handles GAP offsets automatically."` |
| walk, move, cross, plane, wrap | `"Cross-display distance = 240.0f + 2.0f * GAP. Use OCT_TM_walk with wrap=true. OCT_TM_move is in-plane only — no cross-plane handling."` |
| sound, SND, audio, mp3 | `"Pattern: int32_t id = SND_getAssetId(name); SND_play(id, volume);"` |
| animation, sequence, frame | `"OCT_sequence restart: OCT_SEQ_RESTART, OCT_SEQ_REVERSE, OCT_SEQ_REFRESH"` |
| twist, twid, on_twisted | `"Full twists: twid 0-11. Half twists: twid 12-23 (offset by OCT_TWIST_HALF). CW/CCW defined looking from outside the cube at the given face (right-hand rule)."` |
| angle, rotation, direction | `"Angle 'a' / Tm.A: degrees, positive = CCW, 0 = right (+X)."` |
| background, color, OCT_background | `"OCT_background color is in RGB565 format."` |
| random, OCT_random | `"OCT_random(dmin, dmax): upper bound dmax is exclusive."` |
| transparency, transp, fade | `"Transparency: 0 = fully opaque, OCT_TRANSP_MAX = fully transparent."` |
| teleport, set, OCT_TM_set | `"OCT_TM_set overwrites position, angle, and plane directly (teleport) — no animation."` |
| XSIGN, YSIGN, quad coords | `"XSIGN/YSIGN are already declared in oct_shared.h — do NOT redeclare."` |

**Always include these reminders in EVERY coding task (mandatory for all prompts):**
- `"Use explicit type casts — never rely on implicit conversions between numeric types, pointers, or enums."`
- `"Use only fixed-width types from <stdint.h> (int8_t, int16_t, int32_t, uint8_t, uint16_t, uint32_t, size_t). Never use plain int, short, long."`
- `"All 5 handler functions must be present (on_init, on_tick, on_tap, on_twisted, on_pretwisted). If a handler has no game logic, reference every parameter to suppress warnings (e.g., twid; disconnected_ms;)."`

#### 3b. Dispatch Coder Agent

Deploy one Agent with the coding task JSON.

##### Coder Agent Prompt Template

```
You are a WowCube game coder. Implement exactly what the task describes.

## Task
<insert Coding Task JSON>

## Rules
1. Read ALL files listed in `files_to_read` BEFORE writing any code
2. `OCT_wowcube-agent-skills/templates/app_ai_template.h` is the SOURCE OF TRUTH for API usage — do NOT copy demo code
3. Follow `instructions` exactly — do not add features, do not refactor unrelated code
4. Respect all `platform_reminders`
5. Use `prior_context` to understand what already exists — do not break it
6. ALWAYS use explicit type casts — never rely on implicit conversions between numeric types, pointers, or enums. Every narrowing, widening, or cross-type assignment must have a visible cast
7. Use only fixed-width types from `<stdint.h>` (int8_t, int16_t, int32_t, uint8_t, uint16_t, uint32_t, size_t). Never use plain `int`, `short`, `long`
8. All 5 handler functions (on_init, on_tick, on_tap, on_twisted, on_pretwisted) must be present. If a handler has no game logic, reference every parameter as a statement to suppress unused-variable warnings
9. Write modular, readable code: extract game state into structs, split logic into small focused functions, use named constants instead of magic numbers
10. After implementing, respond with the Coder Response JSON

## Response
Return ONLY the Coder Response JSON. No markdown, no explanation outside the JSON.
```

#### 3c. Dispatch Verifier Agents

After coder completes, deploy two verifier agents **sequentially** using the `cube_verifier` skill. Pass the same Verification Task JSON to each.

**Step 1 — Requirements Agent.** Deploy an agent with the Requirements Agent prompt template from the `cube_verifier` skill. Returns a JSON with scores for: completeness (25), gdd_alignment (15), no_regressions (10), verification_criteria (5). Max 55 points.

**Step 2 — Template Agent.** Deploy an agent with the Template Agent prompt template from the `cube_verifier` skill. Returns a JSON with scores for: api_correctness (20), platform_constraints (15), code_quality (10). Max 45 points.

**Evaluate:** Each agent scores out of 100 independently. Both must score >= 90 to pass. If either fails, pass its issues to the fix agent.

**Pipeline rule:** If the orchestrator is confident that prompt N+1 does NOT depend on N's verification outcome (see Pipeline Model table), it MAY begin preparing N+1's task JSON while the verifiers run. But it MUST NOT dispatch N+1's coder until verification passes.

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
  "files_to_read": ["src/app_<game>.h", "OCT_wowcube-agent-skills/templates/app_ai_template.h"],
  "files_to_write": ["src/app_<game>.h"]
}

## Rules
1. Read the source file FIRST
2. Fix ONLY the listed issues — do not refactor or add features
3. Return Coder Response JSON when done
```

After fix agent completes → re-deploy verifier. Repeat until pass or 5 attempts exhausted.

After 5 failures:
1. Save current state to context
2. Present issues to user
3. Ask: "Verification failed after 5 attempts (best score: X). Continue / retry / stop?"

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

### Step 5: Checkpoint with User (MANDATORY — NEVER SKIP)

**After EVERY prompt completes (verified), you MUST checkpoint and STOP.**

Do NOT proceed to the next prompt. Do NOT dispatch any more agents. WAIT for the user.

1. **Summarize:**
   - Prompt number, title, verification score
   - Features added, files modified
   - Fix cycles needed (if any)

2. **Test instructions** — what to look for on the cube

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
2. **Point the user to the cube-loadable binary.** The file to flash onto the
   physical WowCube is the `.oct` package at:

   ```
   app_<game>/app_<game>.oct
   ```

   This is **not** produced by the simulator build alone — it must contain the
   ARM device code. Tell the user to produce it via the `wowcube-boilerplate`
   skill's device build (`scripts/build_device.ps1 -AppDir <workspace>/app_<game>`),
   which runs the ARM build (`out/app_<game>.bin`) and then has the simulator
   pack assets + sounds + ARM code into `app_<game>/app_<game>.oct`. Report the
   absolute path to that `.oct` once generated.
3. Suggest next steps (testing on device, polish, features)

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Verification threshold | 90 | Minimum score to pass (per agent, each scores out of 100) |
| Max retry attempts | 5 | Max fix+re-verify cycles per prompt |
| Start from | 1 | First prompt to execute (for resumption) |
