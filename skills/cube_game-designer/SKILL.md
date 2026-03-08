---
name: cube_game-designer
description: >-
  WowCube game design skill. This skill should be used when users want to design
  a new game for the WowCube platform, or when a user provides a game concept/idea
  that needs to be translated into a structured technical plan for implementation
  by other agents. It analyzes the user's game prompt, studies the OctaviOS API
  template, and produces detailed technical specifications that architect and code
  agents use to build WowCube games.
modes:
  - orchestrator
  - architect
---

# WowCube Game Designer

This skill transforms user game concepts into structured technical plans for the WowCube platform. It bridges the gap between a creative game idea and the technical implementation by producing detailed specifications that other agents consume.

## When to Use

- A user describes a game idea or concept intended for the WowCube
- A user asks to "make a game," "create a game," or "design a game" for the cube
- A user provides a game name or genre and expects a full design breakdown
- An orchestrator needs a technical plan before delegating implementation tasks

## Platform Constraints

Before designing any game, internalize these WowCube hardware constraints:

- **6 planes** (faces): TOP, FRONT, RIGHT, BACK, LEFT, BOTTOM (indices 0–5)
- **4 quads per plane** (physical 240×240 pixel displays), total 24 screens
- **GAP = 18px** between displays (physical border)
- **Quad coordinate system**: quads [0–3] start from top-right center (120+GAP, 120+GAP) and rotate CCW
- **XSIGN**: {+1, -1, -1, +1} / **YSIGN**: {+1, +1, -1, -1} for quad local coordinates
- **Input**: twists (full 0–11, half 12–23) and taps (per plane)
- **Gravity/accelerometer**: per-plane gravity vectors, top/bottom plane detection
- **Sprite limit**: SPRITES_CAP = 400 objects max
- **Tick rate**: OCT_1SEC_TICKS = 20 ticks/sec (50ms per tick)
- **All code in a single .h file** (header-only architecture)
- **Global variables** must use the `TL` macro
- **Sprites** inherit from `octSprite_t` via `appObject_t`

## Workflow

### Step 1: Analyze the User Prompt

To begin, carefully extract the following from the user's game description:

1. **Core mechanic** — What is the primary gameplay loop?
2. **Win/lose conditions** — How does the player succeed or fail?
3. **Input mapping** — Which WowCube inputs (twist, tap, gravity) drive the game?
4. **Visual elements** — What sprites, backgrounds, text, or animations are needed?
5. **Audio elements** — What sound effects or music are needed?
6. **Difficulty/progression** — Does the game get harder? Are there levels or scores?

If the user prompt is vague, make reasonable design decisions and document assumptions. Do not ask excessive clarifying questions — prefer to design a complete game and let the user iterate.

### Step 2: Read the API Template

To understand the available API, read the file `src/app_ai_template.h` from the project workspace. This file contains:

- OctaviOS API function declarations and usage patterns
- Sprite management (`OCT_add`, `OCT_del`, `OCT_restart`)
- Event handlers (`on_init`, `on_tick`, `on_tap`, `on_twisted`, `on_pretwisted`)
- Transform and coordinate system (`octTm_t`, `OCT_TM_quad`, planes, quads)
- Sound playback (`SND_getAssetId`, `SND_play`)
- Gravity/accelerometer (`OCT_TM_gravity_x/y/n`, `OCT_TM_top_plane/bottom_plane`)
- Random number generation (`OCT_random`)
- Utility function `getQuadContent()` for quad-based object lookup

Reference the `references/wowcube_platform.md` file bundled with this skill for a condensed API reference when `app_ai_template.h` is not available.

### Step 3: Map Game Mechanics to Platform

To translate the game concept to WowCube mechanics, determine:

1. **Spatial layout** — Which planes/quads are used for gameplay vs. UI (score, lives, etc.)?
2. **Object model** — What fields does `appObject_t` need beyond `octSprite_t`? (e.g., type, health, speed, direction)
3. **Game state** — What fields does `appvars_t` need? (e.g., score, level, game_over flag, timers)
4. **Twist handling** — What happens on each twist type? Does the game use twist for movement, rotation, or special actions?
5. **Tap handling** — What happens on tap? Selection, shooting, toggling?
6. **Tick logic** — What updates every frame? Movement, collision detection, spawning, animation?
7. **Collision system** — How are collisions detected? Quad-based? Coordinate-based?
8. **Cross-plane mechanics** — Do objects move between planes? How do twists affect game objects?

### Step 4: Generate the Technical Plan

To produce the output, create a markdown file at `plans/<game_name>_plan.md` with the following structure:

```
# <Game Name> — Technical Plan for WowCube

## 1. Game Overview
Brief description of the game, core mechanic, and how it maps to the cube.

## 2. Data Structures

### appObject_t
Fields to add to the game object struct (extending octSprite_t).

### appvars_t
Fields for global game state.

### Enums / Constants
Game-specific enums (object types, game states, directions, etc.).

## 3. Asset Requirements

### Sprites
List of all BMP assets needed with descriptions and suggested sizes.
Format: BMP_XXX — description (WxH pixels)

### Sounds
List of all sound files needed with descriptions.
Format: filename.mp3 — description

## 4. Initialization (on_init)
Step-by-step description of what happens at startup:
- Engine setup (OCT_restart, OCT_viewports_layout, OCT_background)
- Initial game state
- Initial object placement (which planes, which quads, which sprites)

## 5. Game Loop (on_tick)
Detailed per-tick logic:
- Timer/counter updates
- Object movement and physics
- Collision detection
- Spawning logic
- Win/lose condition checks
- Animation updates

## 6. Input Handling

### Twists (on_twisted)
For each relevant twist type, describe the game response.

### Taps (on_tap)
For each plane tap, describe the game response.

### Pre-twist (on_pretwisted)
Any preparation needed before twist animation.

## 7. Helper Functions
List of utility functions needed with signatures and descriptions:
- Function name, parameters, return type
- What it does
- When it's called

## 8. Game Flow
State machine or flow description:
- INIT → PLAYING → GAME_OVER
- Transitions between states
- What triggers each transition

## 9. Technical Notes
- Performance considerations (sprite count limits, tick budget)
- Edge cases (what happens at cube boundaries, during rapid twists)
- Assumptions made during design
```

### Step 5: Review and Validate

Before finalizing the plan, verify:

1. Total sprite count stays within SPRITES_CAP (400)
2. All referenced BMP/SND assets are listed in Section 3
3. Every event handler (init, tick, tap, twisted) has defined behavior
4. The coordinate system usage is correct (XSIGN/YSIGN, quad numbering)
5. Cross-plane object movement accounts for the GAP between displays
6. Game state transitions are complete (no dead-end states)
7. The plan is self-contained — a code agent can implement it without additional context

## Output Format

The final output is always a markdown plan file written to `plans/<game_name>_plan.md`. After writing the plan, provide a brief summary to the user explaining:

- The core game mechanic as designed
- How many sprites/assets are estimated
- Which cube inputs are used
- Any design decisions or assumptions made
