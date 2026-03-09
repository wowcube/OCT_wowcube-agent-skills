# 🧊 WowCube AI Agent Skills Repository

A knowledge base and skill set for LLM-powered coding agents (Kilo Code, Claude Code, Cursor, GitHub Copilot, etc.) that enables them to design and implement games for the WowCube platform — a 2×2×2 puzzle cube with 24 physical screens.

## 📂 Repository Structure

```
├── skills/
│   ├── cube_game-designer/       # Skill: game concept → technical plan
│   │   ├── SKILL.md
│   │   └── references/
│   │       └── wowcube_platform.md
│   └── technical_prompter/       # Skill: game plan → implementation prompts
│       ├── SKILL.md
│       └── references/
│           └── wowcube_platform.md
├── templates/
│   ├── app_ai_template.h         # OctaviOS API reference template
│   └── app_test_ids.h            # Example sprite/asset ID definitions
├── plans/                        # Output directory for generated game plans
└── docs/                         # Documentation (reserved)
```

### Key Files

| Path | Purpose |
|------|---------|
| `skills/cube_game-designer/SKILL.md` | Transforms a user's game idea into a structured technical plan (GDD) |
| `skills/technical_prompter/SKILL.md` | Converts an existing game plan into step-by-step implementation prompts for code agents |
| `templates/app_ai_template.h` | Annotated OctaviOS API reference — the authoritative guide for all WowCube C/C++ code |
| `templates/app_test_ids.h` | Example asset ID header showing BMP enum pattern |
| `skills/*/references/wowcube_platform.md` | Condensed API quick-reference for when the full template is unavailable |

## 🎮 Available Skills

### 1. Game Designer (`cube_game-designer`)

**Modes:** orchestrator, architect

Takes a game concept or idea and produces a detailed technical plan at `plans/<game_name>_plan.md`. The plan covers data structures, asset requirements, initialization, game loop, input handling, helper functions, game flow, and technical notes — all mapped to WowCube hardware constraints.

### 2. Technical Prompter (`technical_prompter`)

**Modes:** orchestrator, architect

Reads an existing game design document from `plans/` and generates a sequence of precise, actionable technical prompts at `plans/<game_name>_prompts.md`. Each prompt targets a specific agent role (architect or code) and covers one implementation phase: project setup → assets → initialization → game loop → input handling → helper functions.

## 🤖 How to Use

### Designing a New Game

Point your AI agent to this repository and describe your game idea:

> "I want to make a WowCube game where the player catches falling stars by twisting the cube. Stars appear on random faces and fall toward the bottom plane. The player twists to move a basket between faces to catch them."

The agent will use the **Game Designer** skill to analyze your concept, read the API template, and produce a complete technical plan in `plans/`.

### Implementing a Game Plan

Once a plan exists in `plans/`, ask the agent to implement it:

> "Read the game plan at `plans/star_catcher_plan.md` and generate technical prompts for implementation."

The agent will use the **Technical Prompter** skill to break the plan into ordered, self-contained prompts that code agents execute sequentially.

## 🧊 WowCube Platform Summary

| Property | Value |
|----------|-------|
| Faces (planes) | 6 — TOP, FRONT, RIGHT, BACK, LEFT, BOTTOM |
| Screens per face | 4 quads (240×240 px each), 24 total |
| Display gap | 18 px physical border between screens |
| Input | Twists (full/half, CW/CCW per face) and taps (per face) |
| Sensors | Accelerometer (gravity, orientation) |
| Max sprites | 400 (SPRITES_CAP) |
| Tick rate | 20 ticks/sec (50 ms per tick) |
| Architecture | Single `.h` file, header-only, globals via `TL` macro |
| Object model | `appObject_t` extends `octSprite_t`; pool in `gObjects[]` |

For the full API reference, see `templates/app_ai_template.h` or `skills/*/references/wowcube_platform.md`.

---

*Built to help AI agents write correct, hardware-aware WowCube games — no zero-index loops, no memory leaks, and proper twist synchronization.*
