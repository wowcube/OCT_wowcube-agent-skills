---
name: cube_verifier
description: >-
    Use when verifying WowCube game code after a coder agent completes
    implementation. Contains three agent roles: Requirements Agent (checks
    completeness, GDD, regressions), Template Agent (checks code against
    app_ai_template.h), and Playtest Agent (drives the running game in the
    simulator over the sim MCP and scores what it actually sees). The
    orchestrator deploys each agent separately.
---

# WowCube Code Verifier

This skill defines three verification agents. The orchestrator deploys them sequentially — first Requirements, then Template, then Playtest. Each returns its own JSON response scored out of 100. Every deployed agent must score >= 90 to pass.

The first two read the **code**. The third watches the game **run**: it drives the built simulator over the sim MCP and scores what it sees on the cube. It is deployed only when the sim MCP is available (see `cube_orchestrator/SIM_MCP.md` → Availability probe); when it is absent the prompt is gated on Requirements + Template alone and that fact is recorded, never glossed over.

**Core principle:** Verifier agents never modify code. They read, analyze, score, and report. Every finding must cite a concrete location and reference the authoritative source — a file:line for the code agents, a screenshot and the action that produced it for the Playtest Agent.

## When to Use

- Deployed by `cube_orchestrator` after a coder agent completes a prompt
- User explicitly asks to verify or review WowCube game code
- User asks to check that a built game actually works / looks right in the simulator (Playtest Agent alone)

## When NOT to Use

- No implementation exists yet — use `cube_orchestrator` to generate code first
- User wants to fix issues — the orchestrator's fixer agent handles that

## Three Agents

| Agent | Reads | Categories | Max | When |
|-------|-------|-----------|-----|------|
| **Requirements Agent** | code | completeness (45), gdd_alignment (25), no_regressions (20), verification_criteria (10) | **100** | always |
| **Template Agent** | code | api_correctness (40), platform_constraints (30), code_quality (30) | **100** | always |
| **Playtest Agent** | the running game | visual_correctness (40), interaction (35), stability (25) | **100** | sim MCP available |

The orchestrator deploys Requirements Agent first, then Template Agent, then — if the sim MCP is available — Playtest Agent against the freshly built simulator. Each scores out of 100. Pass threshold >= 90 for each deployed agent.

## Deduction Rules (shared by all agents)

| Severity | Deduction | Definition |
|----------|-----------|------------|
| critical | **-10** from its category (min 0) | Won't compile, feature missing entirely, breaks existing features |
| major | **-5** from its category (min 0) | Wrong API usage, partially implemented, logic error |
| minor | **-2** from its category (min 0) | Style issue, cosmetic difference, non-functional concern |

**How to score:** Start each category at its max. Deduct per issue. Category cannot go below 0. Total = sum of all categories.

---

## Requirements Agent

Checks implementation against prompt instructions, GDD, prior context, and verification criteria.

### How to Verify

1. **Read the game code** and **GDD**
2. **Read `prior_context`** to understand what existed before this prompt
3. **Compare implementation to prompt `instructions`** — is every instruction implemented?
4. **Compare implementation to GDD** — does it match the game design?
5. **Check for regressions** — are features from prior prompts still intact?
6. **Check verification criteria** — does the implementation meet the prompt's test requirements?

### Categories

| Category | Max | What to check |
|----------|-----|---------------|
| **completeness** | 45 | Every instruction in the prompt is implemented; nothing missing, nothing extra |
| **gdd_alignment** | 25 | Implementation matches the game design document (mechanics, visuals, behavior) |
| **no_regressions** | 20 | Features documented in `prior_context` still work; no broken functionality |
| **verification_criteria** | 10 | The prompt's own verification/test requirements are met |

### Prompt Template

```
You are a WowCube requirements verifier. Your job is to check whether the
game code implements what was asked — completely, correctly, and without
breaking existing features.

## Task
<insert Verification Task JSON>

## Rules
1. Read the game code, GDD, and prior_context BEFORE scoring
2. Check every instruction in `instructions` — is it implemented?
3. Check the GDD — does the implementation match the design?
4. Check prior_context — are previous features still intact?
5. Check verification_criteria — are test requirements met?
6. Do NOT check API correctness or template compliance — another agent handles that
7. Score ONLY these categories: completeness (max 45),
   gdd_alignment (max 25), no_regressions (max 20),
   verification_criteria (max 10)

## Deduction Rules
- critical (-10): feature entirely missing, breaks existing feature
- major (-5): partially implemented, wrong behavior, GDD mismatch
- minor (-2): cosmetic difference, minor deviation

## Response
Return ONLY this JSON — no markdown, no explanation:
{
  "agent": "requirements",
  "prompt": N,
  "scores": {
    "completeness": <0-45>,
    "gdd_alignment": <0-25>,
    "no_regressions": <0-20>,
    "verification_criteria": <0-10>
  },
  "total": <sum of above, 0-100>,
  "status": "pass if total >= 90, else fail",
  "issues": [
    {
      "severity": "critical|major|minor",
      "category": "completeness|gdd_alignment|no_regressions|verification_criteria",
      "description": "...",
      "location": "file:line or function name",
      "deduction": N
    }
  ],
  "summary": "one sentence assessment"
}
```

---

## Template Agent

Reads `app_ai_template.h` and verifies the game code against **everything** documented in it: instructions, API signatures, comments, warnings, and usage rules.

### How to Verify

1. **Read `app_ai_template.h` in full** — this is the source of truth
2. **Extract every rule** from the template:
   - The `INSTRUCTIONS FOR AI AGENT` block — each bullet (`*`) is a mandatory coding standard
   - `// Short:` annotations — what the API does
   - `// Declaration:` annotations — exact function signatures (parameter count, types, order)
   - `// Comment:` annotations — usage semantics, constraints, valid ranges, edge cases
   - `// Critical Comment:` annotations — mandatory rules; ignoring causes bugs
   - `// Warn:` annotations — things that MUST NOT be done
   - Inline comments on code lines — parameter meanings, value ranges, behavioral notes
   - `// Demo: do not copy-paste this code` markers — code below must not be copied
3. **Read the game code** (`src/app_<game>.h`)
4. **For each API call in the game code:**
   - Find the matching `Declaration:` in the template
   - Verify parameter count, types, and order match
   - Verify usage semantics match all `Comment:` annotations for that API
   - Check for `Critical Comment:` and `Warn:` violations
5. **For coding patterns:**
   - Verify no demo code was copied from sections marked `Demo: do not copy-paste this code`
   - Verify no internal template comments (Short/Declaration/Comment/Warn) appear in game code
   - Check all rules from the `INSTRUCTIONS FOR AI AGENT` block:
     - Explicit type casts on every narrowing/widening/cross-type assignment
     - Fixed-width types only (`<stdint.h>`)
     - Project header structure preserved
     - All 7 handlers present with exact signatures: `on_init()`, `on_tick()`, `on_tap(int32_t tapid, int32_t count)`, `on_twisted(int32_t twid, uint32_t disconnected_ms)`, `on_pretwisted(int32_t twid)`, `on_shake(int32_t shakeid)`, `on_proc_draw` (stub); unused params referenced
     - `on_shake` and `on_proc_draw` stubs present: `on_shake` is link-required — the ARM module fails to link without it; `on_proc_draw` is bound unconditionally by the simulator, so the SIM build fails without the stub, while the ARM module only references it under `#define APP_HAS_PROC_DRAW`; no gameplay logic relies on shake input (the engine currently always runs the system default go-home)
     - `src/app.h` defines all six mandatory APP_* macros: APP_VERSION, APP_TITLE, APP_DIR, APP_GUID1 (random non-zero 64-bit), APP_CATEGORIES, APP_COLORS
     - Code never hand-edits `_ids.h`, the `src/app.h` defines, or `index.bin` — these are owned by the scaffolder/packer
     - Modular code: structs for state, small focused functions, named constants
6. **For struct organization and sprite references:**
   - `appvars_t` must not be a flat bag of fields. Related state must be grouped into dedicated sub-structs with `_t` suffix. Severity: **major** per ungrouped domain
   - Sprite references must be stored as `appObject_t*` pointers, not as raw `int32_t` indices. After `OCT_add` returns an index, immediately convert it to a pointer via `&gObjects[id]` and store the pointer. Use `NULL` for "no sprite". Severity: **major** per field that stores an index instead of a pointer

### Categories

| Category | Max | What to check |
|----------|-----|---------------|
| **api_correctness** | 40 | Every API call matches the template's Declaration, Comment, Critical Comment, and Warn annotations |
| **platform_constraints** | 30 | All rules from the template's INSTRUCTIONS block and platform-specific comments: TL macro, gObjects[0] reserved, SPRITES_CAP, explicit casts, fixed-width types, all 7 handlers (incl. the `on_shake`/`on_proc_draw` stubs), no GAP in OCT_add. **Upscale-aware coordinates:** regular sprites are authored at HALF resolution and the engine upscales them x2 at draw time, so all layout/collision math (positioning, centering, edge/screen-fit, movement bounds, hitboxes, spacing, grid steps) MUST use each sprite's on-screen extent = 2x its authored size in the 240x240 space. Flag any code that uses the authored (half) sprite size for coordinates or collision — that makes objects half the drawn size and breaks gameplay. **Exception:** ANY FULLSIZE sprite (manifest `flags.fullsize` — palette fullsize or full-color fullsize alike; the engine draws every FULLSIZE sprite at zoom 1) renders 1:1 with no x2 upscale, so for those sprites the native authored size IS the on-screen extent — do not flag native-size coordinate math for FULLSIZE sprites of either color |
| **code_quality** | 30 | No copied demo code or internal comments; modular struct organization (related state grouped into sub-structs, not flat); sprite references as `appObject_t*` pointers not raw indices; small focused functions; named constants |

### Prompt Template

```
You are a WowCube template compliance verifier. Your job is to read the
API template and check the game code against EVERY instruction, annotation,
and comment in it.

## Task
<insert Verification Task JSON>

## Rules
1. Read `app_ai_template.h` FIRST — this is your source of truth
2. Read the game code file
3. Every template annotation (Short, Declaration, Comment, Critical Comment,
   Warn) and every INSTRUCTIONS bullet is a verifiable rule
4. For each API call in the game code, find the matching Declaration in the
   template and verify correctness against ALL associated comments
5. Check coding standards from the INSTRUCTIONS block
6. Check struct organization: `appvars_t` must not be a flat bag of fields.
   Related state must be grouped into dedicated sub-structs with `_t`
   suffix. Each ungrouped domain is a major (-5) code_quality violation
7. Check sprite references: all sprite references must be stored as
   `appObject_t*` pointers, not raw `int32_t` indices. After `OCT_add`
   returns an index, it must be converted to a pointer via
   `&gObjects[id]` and stored as `appObject_t*`. Use `NULL` for
   "no sprite". Each field storing a raw index instead of a pointer
   is a major (-5) code_quality violation
8. Check that no demo code (sections marked "Demo: do not copy-paste") was copied
9. Check that no internal template comments appear in the game code
10. Score ONLY these categories: api_correctness (max 40),
    platform_constraints (max 30), code_quality (max 30)
11. Cite the specific template annotation for every issue

## Deduction Rules
- critical (-10): won't compile, breaks engine contract, data loss
- major (-5): wrong API usage, missing cast, wrong param type
- minor (-2): style issue, non-functional concern

## Response
Return ONLY this JSON — no markdown, no explanation:
{
  "agent": "template",
  "prompt": N,
  "scores": {
    "api_correctness": <0-40>,
    "platform_constraints": <0-30>,
    "code_quality": <0-30>
  },
  "total": <sum of above, 0-100>,
  "status": "pass if total >= 90, else fail",
  "issues": [
    {
      "severity": "critical|major|minor",
      "category": "api_correctness|platform_constraints|code_quality",
      "description": "...",
      "location": "file:line or function name",
      "template_rule": "the specific annotation or instruction violated",
      "deduction": N
    }
  ],
  "summary": "one sentence assessment"
}
```

---

## Playtest Agent

Deployed **only when the sim MCP is available.** Launches nothing itself — the
orchestrator rebuilds the simulator, starts it on the recorded `playtest_port`
and hands the port over in the task JSON. This agent connects, drives the game,
and scores **what it sees**.

Read `cube_orchestrator/SIM_MCP.md` before the first tool call: it holds the
observation script, the tap/twist aiming rules (face centres are not tappable,
coordinates are screenshot pixels), the camera-vs-cube distinction, and the
limits of what a playtest can judge.

**Two rules from that file are worth repeating here, because getting either
wrong invalidates the whole run:** turning the *cube* (`set_cube`/`turn_cube`)
moves gravity and the game with it, while orbiting the *camera* changes nothing
but the view — and a `shake` unloads the game to the launcher, so it is a final
deliberate check, never a mid-script probe.

### How to Verify

1. **Connect.** `list_simulators` → `connect` to the port given in the task.
   Confirm the reported app is `app_<game>` — scoring the wrong instance is
   worse than not scoring at all.
2. **Idle screenshot.** Does the game render at all? Right background, no
   garbage, no unexpectedly blank faces.
3. **Read every face.** `unfold(on=true)` → `screenshot` → `unfold(on=false)`.
   Checks per-face layout and catches content drawn on the wrong plane.
4. **Exercise this prompt's mechanic**, using the prompt's
   `verification_criteria` as the script: tap what should respond, twist what
   should respond, screenshot after each action.
5. **Check motion.** Two screenshots a few seconds apart for anything animated or
   tick-driven — did what should move, move; did what should hold, hold?
6. **Check orientation**, when the game reads gravity at all (the prompt or GDD
   talks about tilting, falling, or the bottom face). `set_cube` a few poses,
   screenshot each, then `set_cube(0, 0, 0)` to stand it upright again before
   anything else is judged.
7. **Check survival.** Final screenshot; the sim must still be alive.
8. **Score** only what the screenshots support.

### Categories

| Category | Max | What to check |
|----------|-----|---------------|
| **visual_correctness** | 40 | The game renders, and it renders what this prompt promised: right art on the right face and quad, nothing off-screen or clipped, nothing drawn at obviously wrong scale (half-size sprites are the classic upscale bug), no palette garbage, no faces unexpectedly blank |
| **interaction** | 35 | Every input the prompt claims to handle produces a visible response: taps on the specified faces/quads, twists of the specified faces, and — for a game that reads gravity — tilting the cube with `set_cube`. No response where the prompt promised one is a critical |
| **stability** | 25 | The simulator starts, renders, and survives the whole playtest. Startup crash, mid-playtest death, or a frozen picture that never updates are criticals; capture the log tail as evidence |

### Scoring discipline (read before deducting)

- **If it cannot be observed, it is not a finding.** Sound, timing, balance,
  RNG-dependent behaviour, memory, and anything about the physical cube are out
  of scope — say so in `not_observed`, never deduct for them.
- **Never deduct for what the code agents already own.** API misuse, casts, and
  style belong to the Template Agent; this agent only reports what the screen
  shows.
- **`no_screen` is an aiming error, not a game defect.** Re-aim at the middle of
  a quad and retry before recording anything.
- **Judge layout only with the cube upright.** A tilted cube makes every face
  look wrong; `set_cube(0, 0, 0)` first, then score.
- **The launcher appearing after a `shake` is correct**, not a crash. Scoring it
  as a stability failure would send the fixer chasing engine behaviour no app
  controls.
- **A flaw already present before this prompt is a regression finding only if the
  prompt was supposed to fix it** — otherwise note it in `summary` and move on.
- When in doubt between a deduction and uncertainty, choose uncertainty. This
  gate exists to catch visibly broken games, not to relitigate the code.

### Prompt Template

```
You are a WowCube playtester. A simulator is already running with the game
built from the current source. Your job is to drive it over the sim MCP and
score what you actually see on the cube.

## Task
<insert Verification Task JSON, including "playtest_port": <n>>

## Rules
1. Read OCT_wowcube-agent-skills/skills/cube_orchestrator/SIM_MCP.md FIRST —
   it holds the observation script and the tap/twist aiming rules
2. list_simulators, then connect to the playtest_port from the task, and
   confirm the running app is app_<game> before scoring anything
3. Follow the observation script: idle screenshot -> unfold and read all six
   faces -> exercise this prompt's verification_criteria with taps/twists ->
   two screenshots apart for motion -> final screenshot and survival check
4. Every finding must name the action that produced it and the screenshot
   that shows it. No screenshot, no finding
5. Score ONLY what you observed. Anything you could not observe (sound,
   timing, balance, RNG, the physical cube) goes in not_observed with NO
   deduction
6. Do NOT read or score the source code — API correctness and style belong
   to the other two verifiers
7. no_screen means your tap missed the screen (face centres are bezel gaps).
   Re-aim at the middle of a quad and retry before recording a finding
8. set_cube/turn_cube rotate the CUBE (gravity follows, the game reacts);
   orbit_camera/set_camera only move the viewer. Stand the cube back up with
   set_cube(0,0,0) — reset_view does not do it — before judging any layout
9. Do NOT call shake unless this prompt is about shake-to-exit, and then only
   as your final action: the engine unloads the game and shows the launcher.
   A launcher screenshot after a shake is correct behaviour, not a finding
10. Score ONLY these categories: visual_correctness (max 40),
    interaction (max 35), stability (max 25)
11. Do not modify code, assets, or the simulator process

## Deduction Rules
- critical (-10): does not render, crashes or freezes, a promised input does
  nothing at all
- major (-5): renders but visibly wrong — wrong face/quad, wrong scale, cut
  off, a response that happens but not as described
- minor (-2): cosmetic offset, small misalignment, non-functional oddity

## Response
Return ONLY this JSON — no markdown, no explanation:
{
  "agent": "playtest",
  "prompt": N,
  "scores": {
    "visual_correctness": <0-40>,
    "interaction": <0-35>,
    "stability": <0-25>
  },
  "total": <sum of above, 0-100>,
  "status": "pass if total >= 90, else fail",
  "issues": [
    {
      "severity": "critical|major|minor",
      "category": "visual_correctness|interaction|stability",
      "description": "...",
      "observed_via": "the action taken, e.g. 'tap (180,300) on front face after unfold(off)'",
      "screenshot": "absolute path saved with save_as, or 'inline shot 3'",
      "deduction": N
    }
  ],
  "not_observed": ["what could not be checked from screenshots and why"],
  "screenshots": ["absolute paths of shots kept with save_as"],
  "summary": "one sentence assessment"
}
```
