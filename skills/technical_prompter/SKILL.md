---
name: technical_prompter
description: >-
  Use when a WowCube game design document or GDD already exists and needs to be
  decomposed into step-by-step implementation prompts, or when someone says
  "implement this plan", "build this game", or "start coding" after a GDD is ready.
---

# WowCube Technical Prompter

Decompose a Game Design Document into the smallest possible vertical-slice implementation prompts, where each prompt produces a testable increment.

## When to Use

- A GDD exists in `plans/` and implementation needs to begin
- User says "implement this," "build this game," or "start coding" after design is complete
- An orchestrator needs to break a game plan into implementable agent tasks

## When NOT to Use

- No GDD exists yet — use `cube_game-designer` first
- User wants to modify existing running code — this produces fresh implementation prompts

## Core Principle

**Each prompt = the smallest testable vertical slice.**

The first prompt produces something visible. Every subsequent prompt adds exactly one testable behavior. An agent executing any single prompt can verify their work before moving to the next.

## Workflow

### Step 1: Read the GDD

Locate and read the game design document (typically `plans/<game_name>_gdd.md`).

Extract:
1. **Game objects** — types, behaviors, visual descriptions
2. **Game states** — flow between menu, playing, win, lose
3. **Mechanics** — each gameplay mechanic described
4. **Controls** — what each input does
5. **Assets** — full sprite and sound list
6. **UI elements** — score display, menus, feedback
7. **Progression** — levels, difficulty, generation

### Step 2: Study the API

Read both references to understand what's technically possible:
- `references/wowcube_api_reference.md` — clean API reference (primary)
- `templates/app_ai_template.h` — advanced patterns and working examples (do NOT copy demo code)

### Step 3: Plan the Decomposition

Break the game into the smallest logical vertical slices. Follow this ordering principle:

1. **Foundation** — project scaffold, data structures, engine init, background color
2. **First visual** — something appears on screen (even one sprite on one face)
3. **Static layout** — all faces show their initial state
4. **First input** — one input type produces a visible response
5. **Core mechanic** — the primary gameplay loop, one piece at a time
6. **Secondary mechanics** — boosters, blockers, special behaviors
7. **Game states** — win/lose detection, state transitions
8. **UI** — score display, menus, game over screen
9. **Audio** — sound effects tied to events
10. **Polish** — animations, edge cases, balance tuning

**Decomposition rules:**
- Each slice must produce something the agent can SEE or HEAR when testing
- If a mechanic has sub-parts, split them (e.g., "gravity" = "detect empty space" + "move figures down" + "spawn new figures" as 3 prompts)
- Never combine unrelated behaviors in one prompt
- If a prompt takes more than ~100 lines of code to implement, split it further

### Step 4: Write the Prompts

Create the output file at `plans/<game_name>_prompts.md` with this structure:

```markdown
# <Game Name> — Implementation Prompts

## Overview
- Source GDD: `plans/<game_name>_gdd.md`
- Total prompts: N
- Estimated total sprites: X
- API reference: `references/wowcube_api_reference.md`

---

## Prompt 1: <Descriptive Name>

### Current State
None — fresh project starting from `templates/app_ai_template.h` structure.

### Goal
<One sentence: what this prompt adds. Must be testable.>

### Instructions
<Step-by-step technical instructions:>
1. Define the `appObject_t` struct extending `octSprite_t` with fields: ...
2. Define the `appvars_t` struct with fields: ...
3. In `on_init()`:
   - Call `OCT_restart(...)` with ...
   - Call `OCT_viewports_layout(SCHEME_CUBE, GAP, GAP)`
   - Call `OCT_background(0x____)` for color ...
   - Add sprite using `OCT_add(layer, twistable, plane, x, y, ...)` at ...
4. ...

<Include exact API function calls, parameter values, coordinates.>
<Reference: "See `references/wowcube_api_reference.md` for API details. For advanced patterns, consult `templates/app_ai_template.h` but do NOT copy demo code.">

### Platform Reminders
<Only include constraints relevant to THIS prompt, e.g.:>
- gObjects[0] is invalid — start iteration from index 1
- All globals must use the `TL` macro
- SPRITES_CAP = 400 max objects

### Verification
<Exactly what the agent should see/hear when this prompt is correctly implemented:>
- "You should see a blue background on all 24 screens"
- "A red sprite should appear at the center of the top-right screen on the front face"
- "Twisting the front face clockwise should move the sprite to the right face"

---

## Prompt 2: <Descriptive Name>

### Current State
<Brief summary of what exists after all previous prompts:>
- Project initialized with black background
- appObject_t has fields: type, ...
- One sprite visible on front face top-right quad
- No input handling yet

### Goal
<What this prompt adds>

### Instructions
...

### Platform Reminders
...

### Verification
...

---

(continue for all prompts)
```

### Step 5: Validate the Prompts

Before finalizing, verify:

1. **Complete coverage** — every GDD section is covered by at least one prompt
2. **Asset coverage** — every sprite and sound from the GDD asset list appears in at least one prompt
3. **Dependency order** — no prompt references code/objects that weren't created in a previous prompt
4. **Self-contained context** — each prompt's "Current State" accurately summarizes prior work
5. **Testable verification** — every prompt has a concrete "you should see/hear" verification
6. **No gaps** — executing all prompts in order produces the complete game described in the GDD
7. **Smallest slices** — no prompt could be reasonably split into two smaller testable prompts
8. **Correct API usage** — all referenced functions match `references/wowcube_api_reference.md`

## Prompt Writing Rules

1. **Be explicit** — specify exact API calls, parameter values, coordinates, colors. No ambiguity.
2. **Include coordinates** — when placing sprites, provide exact plane, x, y using XSIGN/YSIGN.
3. **One behavior per prompt** — each prompt has a single clear goal.
4. **Hybrid context** — each prompt has a "Current State" summary so a fresh agent can understand what exists, plus only new instructions for what to add.
5. **Reference the API** — every prompt must include: "See `references/wowcube_api_reference.md` for API details. For advanced patterns, consult `templates/app_ai_template.h` but do NOT copy demo code."
6. **Remind constraints** — include only the platform constraints relevant to the current prompt (don't repeat everything every time).
7. **Verification is mandatory** — every prompt must end with exactly what the agent should observe.

## Output

The final prompts file is written to `plans/<game_name>_prompts.md`.

After writing, provide a summary:
- Total number of prompts generated
- Rough grouping (e.g., "Prompts 1-3: foundation, 4-7: core mechanic, 8-10: UI")
- Any GDD gaps or ambiguities resolved with assumptions
- Estimated complexity (sprite count, function count)
