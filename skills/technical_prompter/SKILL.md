---
name: technical_prompter
description: >-
  WowCube technical prompt generator. This skill should be used when a game design
  document (GDD) or game plan already exists and needs to be translated into
  precise technical prompts for code and architect agents. It reads the GDD,
  studies the OctaviOS API template (src/app_ai_template.h), and produces
  structured, actionable technical prompts that other agents consume to implement
  WowCube games step by step.
modes:
  - orchestrator
  - architect
---

# Technical Prompter for WowCube

This skill converts existing game design documents into precise technical prompts for implementation agents. It does NOT create game designs — it assumes a GDD or game plan already exists (typically in `plans/`) and focuses on producing clear, actionable instructions that code and architect agents follow to build the game.

## When to Use

- A game design document or plan already exists in `plans/` and implementation needs to begin
- An orchestrator needs to delegate coding tasks based on an existing game plan
- A user says "implement this plan," "build this game," or "start coding" after a GDD is ready
- Technical prompts are needed to break a game plan into implementable agent tasks

## Workflow

### Step 1: Read the Game Design Document

To begin, locate and read the game design document. Typical locations:

- `plans/<game_name>_plan.md` — structured game plan
- Any markdown file the user references as the game design

Extract from the GDD:

1. **Data structures** — `appObject_t` fields, `appvars_t` fields, enums, constants
2. **Asset list** — all BMP_XXX sprites and sound files referenced
3. **Initialization logic** — what happens in `on_init()`
4. **Game loop logic** — what happens in `on_tick()`
5. **Input handlers** — twist and tap behavior
6. **Helper functions** — utility functions described in the plan
7. **Game states** — state machine transitions
8. **Technical constraints** — sprite limits, performance notes

### Step 2: Read the API Template

To understand the available API and coding patterns, read `src/app_ai_template.h` from the project workspace. This file serves as the authoritative reference for:

- OctaviOS API function signatures and usage patterns
- Sprite management (`OCT_add`, `OCT_del`, `OCT_restart`)
- Event handler signatures (`on_init`, `on_tick`, `on_tap`, `on_twisted`, `on_pretwisted`)
- Transform and coordinate system (`octTm_t`, `OCT_TM_quad`, planes, quads)
- Sound playback (`SND_getAssetId`, `SND_play`)
- Gravity/accelerometer (`OCT_TM_gravity_x/y/n`, `OCT_TM_top_plane/bottom_plane`)
- The `getQuadContent()` utility pattern

When `app_ai_template.h` is not available, reference `references/wowcube_platform.md` bundled with this skill.

### Step 3: Generate Technical Prompts

To produce the output, create a set of technical prompts organized by agent role and implementation phase. Write the output to `plans/<game_name>_prompts.md`.

The output file must follow this structure:

```
# <Game Name> — Technical Prompts

## Prompt 1: Project Setup (architect)

Target agent: architect
Goal: Set up the project structure and define data types.

### Instructions

<Precise instructions for the architect agent to:>
- Define appObject_t with exact fields, types, and comments
- Define appvars_t with exact fields, types, and comments
- Define all enums and constants
- Define function forward declarations
- Define global variables with TL macro
- Reference app_ai_template.h for struct inheritance pattern

### Expected Output
<Description of what files/code the agent should produce>

---

## Prompt 2: Asset Preparation (code)

Target agent: code
Goal: Prepare the asset ID header and list required assets.

### Instructions

<Precise instructions to:>
- List all BMP_XXX constants needed in app_*_ids.h
- List all sound files needed in assets/mp3/
- Specify sprite dimensions and descriptions

### Expected Output
<Description of what the agent should produce>

---

## Prompt 3: Initialization (code)

Target agent: code
Goal: Implement on_init() and initial game setup.

### Instructions

<Precise, step-by-step instructions for implementing on_init():>
- OCT_restart call with correct parameters
- OCT_viewports_layout with SCHEME_CUBE and GAP
- OCT_background with specific color
- Initial game state variable values
- Initial sprite placement with exact OCT_add calls
  (specify: layer, twistable, plane, x, y, angle, animation params)

### Expected Output
<The complete on_init() function>

---

## Prompt 4: Game Loop (code)

Target agent: code
Goal: Implement on_tick() with all per-frame logic.

### Instructions

<Precise, step-by-step instructions for implementing on_tick():>
- Tick counter increment
- Movement logic with exact formulas/speeds
- Collision detection algorithm
- Spawning logic with timing
- State checks (win/lose conditions)
- Animation updates

### Expected Output
<The complete on_tick() function>

---

## Prompt 5: Input Handling (code)

Target agent: code
Goal: Implement on_tap(), on_twisted(), on_pretwisted().

### Instructions

<Precise instructions for each handler:>
- on_tap: what happens for each plane tap
- on_twisted: what happens for each twist ID
- on_pretwisted: any pre-twist preparation

### Expected Output
<The complete input handler functions>

---

## Prompt 6: Helper Functions (code)

Target agent: code
Goal: Implement all utility/helper functions.

### Instructions

<For each helper function:>
- Function signature
- Step-by-step algorithm
- When/where it's called
- Edge cases to handle

### Expected Output
<All helper function implementations>
```

### Prompt Writing Rules

When writing each technical prompt, follow these rules:

1. **Be explicit** — Specify exact API function calls, parameter values, and variable names. Do not leave room for interpretation.
2. **Reference the template** — Every prompt must instruct the agent to read `src/app_ai_template.h` as the API reference. Include the instruction: "Read `src/app_ai_template.h` for API reference and coding patterns. Do NOT copy demo code — use it only as a guide."
3. **Include constraints** — Remind agents of platform limits: SPRITES_CAP=400, GAP=18, TL macro for globals, gObjects[0] is invalid.
4. **Specify coordinates** — When placing sprites, provide exact plane, x, y values using the XSIGN/YSIGN system.
5. **One responsibility per prompt** — Each prompt should have a single, clear goal. Do not combine unrelated tasks.
6. **Order matters** — Prompts must be ordered so that each builds on the output of previous prompts. Data structures before initialization, initialization before game loop.
7. **Self-contained** — Each prompt must contain enough context for the target agent to work independently, including relevant struct definitions and function signatures from earlier prompts.

### Step 4: Validate the Prompts

Before finalizing, verify:

1. Every section of the GDD is covered by at least one prompt
2. All BMP_XXX and sound assets referenced in prompts are listed in the asset prompt
3. All helper functions referenced in game loop/input prompts are defined in the helper functions prompt
4. Prompt ordering respects dependencies (structs → assets → init → loop → input → helpers)
5. Each prompt specifies the target agent (architect or code)
6. No prompt assumes knowledge that wasn't provided in a previous prompt or in the GDD
7. The total set of prompts, if executed in order, would produce a complete working game

## Output Format

The final output is always written to `plans/<game_name>_prompts.md`. After writing the prompts file, provide a brief summary to the user:

- How many prompts were generated
- The implementation order
- Any GDD gaps or ambiguities that were resolved with assumptions
- Estimated complexity (number of functions, sprite count, state count)
