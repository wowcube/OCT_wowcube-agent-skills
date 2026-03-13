---
name: cube_game-designer
description: >-
  Use when designing a new game for the WowCube platform, when a user provides
  a game concept or idea that needs a structured game design document, or when
  someone says "make a game", "design a game", or "create a game" for the WowCube.
---

# WowCube Game Designer

Create a non-technical Game Design Document (GDD) from a user's game idea, accounting for WowCube hardware and interaction specifics.

## When to Use

- User describes a game idea or concept for the WowCube
- User says "make a game," "design a game," or "create a game"
- User provides a genre, theme, or mechanic and expects a full game design
- An orchestrator needs a GDD before handing off to the technical prompter

## When NOT to Use

- A GDD already exists and needs implementation prompts — use `technical_prompter` instead
- User wants to modify existing code — this skill produces design documents, not code

## WowCube Device Essentials

The GDD must account for these device characteristics (expressed in player-friendly terms, never as code):

- **The cube has 6 faces**, each with **4 small screens** (24 screens total)
- **Screens are 240x240 pixels** with a **physical gap** (border) between them
- **Player interactions**: twist a face row (full or half twist), tap a face, tilt the cube
- **Twists** rotate a row of 4 screens — this is the primary input for most games
- **Half-twists** shift screens partially — useful for fine movement
- **Taps** are detected per face (not per screen)
- **Tilt/gravity** detects which face is on top or bottom
- The cube can display on all 24 screens simultaneously — not all are visible to the player at once
- **~20 frames per second** tick rate — animations should be simple and clear
- **Maximum ~400 sprites** on screen at once across all faces

## Workflow

### Step 1: Understand the Idea

Extract from the user's prompt:

1. **Core mechanic** — What does the player actually DO?
2. **Win/lose conditions** — How does the player succeed or fail?
3. **Cube interaction mapping** — Which inputs drive the game (twist, tap, tilt)?
4. **Visual style** — Art direction, color palette, theme
5. **Audio needs** — Sound effects, music, feedback sounds
6. **Progression** — Does it get harder? Levels? Scoring?

If the prompt is vague, make reasonable design decisions and document assumptions. Prefer designing a complete game over asking many clarifying questions.

### Step 2: Study the Platform

Read the API reference for technical understanding:
- `references/wowcube_api_reference.md` — clean API reference
- For advanced engine patterns, consult `templates/app_ai_template.h` (do NOT copy demo code)

Use this knowledge to inform design decisions (e.g., what's feasible with the sprite limit, how twists actually move things) but do NOT expose technical details in the GDD.

### Step 3: Write the GDD

Create a markdown file at `plans/<game_name>_gdd.md` with the following structure:

```markdown
# <Game Name> — Game Design Document

## 1. Intro

### Concept
2-3 sentences: what the game is, what makes it fun, why it works on the cube.

### Style & References
- Art style (e.g., pixel-art, minimal, cartoon)
- Genre
- Inspiration games/references

### MVP Scope
Checklist of features for the minimum viable version:
- [ ] Feature 1
- [ ] Feature 2
- ...

### Final Scope
Bullet list of features planned beyond MVP.

## 2. Core Gameplay

Per-mechanic sections, each containing:
- What the player sees and does (plain language)
- How it maps to cube interactions (twist/tap/tilt)
- Rules and edge cases
- Visual and audio feedback

Example subsections (adapt to the game):
- Match Logic
- Movement System
- Combat System
- Scoring
- etc.

## 3. Game Objects

Types of objects in the game with:
- Visual description (what it looks like)
- Behavior (what it does)
- Parameters table where relevant:

| Object | Description | Behavior |
|--------|-------------|----------|
| Red Figure | Red gem shape | Matches with other red figures |
| Rocket Booster | Firecracker icon, has direction | Clears a row when activated |

## 4. Level Design / Progression

- How levels are structured
- Difficulty scaling (what changes between levels)
- Win condition per level
- Lose condition per level
- Generation logic (if procedural)
- Balance parameters (described in game terms, not code)

## 5. Controls Summary

| Input | Action |
|-------|--------|
| Twist left/right | What happens |
| Half-twist left/right | What happens |
| Twist up/down | What happens |
| Half-twist up/down | What happens |
| Tap | What happens |
| Tilt/gravity | What happens |

## 6. UI & Feedback

- What the player sees on each face during gameplay
- Score/status display (which screens, what info)
- Menu screens (start, game over, win)
- Visual feedback (animations, color changes, effects)
- Audio feedback (when sounds play, what they convey)

## 7. Assets List

### Sprites
List every visual asset needed with a clear descriptive name:
- `<snake_case_name>` — description (e.g., "red_figure — red gem match object, 48x48px")
- `<snake_case_name>` — description
- ...

### Sounds
- `<snake_case_name>.mp3` — description (e.g., "match_success — cheerful chime when 3+ figures match")
- `<snake_case_name>.mp3` — description
- ...

### Fonts
- `<font_name>` — usage description (e.g., "score_font — displays score counter and twist count")
- ...

## 8. Game Flow

State diagram in plain language:
- MENU → PLAYING → WIN / LOSE → MENU
- What triggers each transition
- What the player sees in each state
```

### Step 4: Validate the Design

Before finalizing, verify:

1. Every player action (twist, tap, tilt) has a defined response in every game state
2. Win and lose conditions are complete — no dead-end states
3. The asset list covers every visual and audio element mentioned in the design
4. Asset names are unique, descriptive, and use `snake_case`
5. The game is feasible given the device constraints (sprite count, screen count, input types)
6. The controls summary matches the mechanics described in Core Gameplay
7. The design is understandable by someone who has never seen WowCube code

## Output

The final GDD is written to `plans/<game_name>_gdd.md`.

After writing, provide a brief summary:
- The core game mechanic
- How many assets are estimated (sprites + sounds)
- Which cube inputs are used
- Any design decisions or assumptions made

## Writing Guidelines

- **No code, no API names, no struct names** — the GDD is for designers, not programmers
- Use player-facing language: "face" not "plane", "screen" not "quad", "twist" not "twid"
- Describe behaviors, not implementations: "figures fall down when there's empty space below" not "gravity applies OCT_TM_walk"
- Be specific about visuals: describe what things look like, how they animate, what colors they use
- Be specific about audio: describe when sounds play and what mood they convey
- Asset names must be clear enough that an artist could create them from the name + description alone
