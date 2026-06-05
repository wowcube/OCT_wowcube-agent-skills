# 🧊 WowCube AI Agent Skills Repository

A knowledge base and skill set for LLM-powered coding agents (Kilo Code, Claude Code, Cursor, GitHub Copilot, etc.) that enables them to design and implement games for the WowCube platform — a 2×2×2 puzzle cube with 24 physical screens.

## 📂 Repository Structure

```
├── skills/
│   ├── cube_game-designer/       # Skill: game concept → GDD
│   │   └── SKILL.md
│   ├── technical_prompter/       # Skill: GDD → implementation prompts
│   │   └── SKILL.md
│   ├── wowcube-boilerplate/      # Skill: scaffold + verify build infra (app folder, assets, sim build)
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── check_env.ps1     #   verify/install toolchain (ARM GCC, CMake, Ninja, MSVC)
│   │       ├── new_app.ps1       #   scaffold app_<game>, pack assets, build+launch simulator
│   │       └── build_device.ps1  #   ARM build + pack the cube-loadable .oct
│   └── cube_orchestrator/        # Skill: orchestrate implementation from prompts
│       └── SKILL.md
├── templates/
│   ├── app_ai_template.h         # OctaviOS API reference template
│   └── app_test_ids.h            # Example sprite/asset ID definitions
├── src/                          # Example source files
├── context/                      # JSON context files for orchestrator (per-game state)
└── plans/                        # Output directory for generated game plans
```

### Key Files

| Path | Purpose |
|------|---------|
| `skills/cube_game-designer/SKILL.md` | Transforms a user's game idea into a structured technical plan (GDD) |
| `skills/technical_prompter/SKILL.md` | Converts an existing game plan into step-by-step implementation prompts for code agents |
| `templates/app_ai_template.h` | Annotated OctaviOS API reference — the authoritative guide for all WowCube C/C++ code |
| `templates/app_ai_template_ids.h` | Asset ID header (BMP enum pattern) |
| `src/app_structure_example.h` | Clean project skeleton for new games |

## 🎮 Available Skills

### 1. Game Designer (`cube_game-designer`)

Takes a game concept or idea and produces a non-technical Game Design Document at `plans/<game_name>_gdd.md` through a discovery interview with the user.

### 2. Technical Prompter (`technical_prompter`)

Reads an existing GDD from `plans/` and decomposes it into the smallest possible vertical-slice implementation prompts at `plans/<game_name>_prompts.md`. Each prompt produces a testable increment.

### 3. WowCube Boilerplate (`wowcube-boilerplate`)

Runs **after** the technical prompter and **before** the orchestrator. First verifies the toolchain (`check_env.ps1` — installs everything missing via winget: the MSVC C++ build tools + Windows 11 SDK for the simulator, plus ARM GCC, CMake, and Ninja for the device build). Then scaffolds the `app_<game>/` folder from the template, renames every name-bearing file, packs the art assets, and smoke-builds + launches the simulator (`new_app.ps1`, exit 0 = infra ready). This guarantees the first implementation prompt executes against known-good infrastructure instead of failing on a missing folder, an unpacked asset, or a broken toolchain. The infra **gate** verifies the **simulator** build; the final cube-loadable **`.oct`** is produced at delivery time via `build_device.ps1` (ARM build → `out/app_<game>.bin`, then the sim packs assets + sounds + ARM code into `app_<game>/app_<game>.oct`).

### 4. Cube Orchestrator (`cube_orchestrator`)

Deploys coder, verifier, and fixer subagents for each prompt. All inter-agent communication uses JSON. Pipeline parallelism where safe (prepare next task while verifying current). Orchestrator decides when to wait vs. pipeline based on prompt dependencies. Scores below 90 trigger automatic rework (up to 5 attempts). Context accumulates in `context/<game>_context.json`.

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

For the full API reference, see `templates/app_ai_template.h`.

---

*Built to help AI agents write correct, hardware-aware WowCube games — no zero-index loops, no memory leaks, and proper twist synchronization.*
