# 🧊 WowCube AI Agent Skills Repository

A knowledge base and skill set for LLM-powered coding agents (Kilo Code, Claude Code, Cursor, GitHub Copilot, etc.) that enables them to design and implement games for the WowCube platform — a 2×2×2 puzzle cube with 24 physical screens.

## 📂 Repository Structure

```
├── skills/                       # each contains a SKILL.md (+ scripts/ where noted)
│   ├── cube_orchestrator/        # MASTER controller + entry point (routes all stages)
│   ├── cube_game-designer/       # Stage 1 component: game concept → GDD
│   ├── technical_prompter/       # Stage 2 component: GDD → prompts + asset manifest
│   ├── cube_asset-builder/       # Stage 3 component: manifest → packed assets + _ids.h (+ scripts/, tests/)
│   ├── cube_verifier/            # Stage 4 component: scores coder output (requirements + template agents)
│   └── wowcube-boilerplate/      # Infra gate (pre-Stage 4) + Stage 5: scaffold, build & verify .oct (+ scripts/)
├── scripts/                      # Shared asset-pipeline tools (pack.py, unpack.py, build_psd.py, requirements.txt)
├── templates/
│   └── app_ai_template/          # Template app cloned per game (art/, sound/, src/, *.target)
│       └── src/app_ai_template.h # Annotated OctaviOS API reference — source of truth for all C/C++
├── src/                          # Example source (app_structure_example.h skeleton)
├── context/                      # JSON context files for orchestrator (per-game state)
└── plans/                        # Output directory for generated GDDs, prompts, and asset manifests
```

### Key Files

| Path | Purpose |
|------|---------|
| `skills/cube_orchestrator/SKILL.md` | **Master controller and single entry point** — routes every stage and manages all sub-skills and subagents |
| `skills/cube_game-designer/SKILL.md` | Stage 1 component — transforms a user's game idea into a structured design document (GDD) |
| `skills/technical_prompter/SKILL.md` | Stage 2 component — converts a GDD into step-by-step implementation prompts plus the asset manifest |
| `skills/cube_asset-builder/SKILL.md` | Stage 3 component — turns the asset manifest into packed sprites/sounds and `_ids.h` |
| `skills/cube_verifier/SKILL.md` | Stage 4 component — scores each coder result against requirements and the API template (two verifier agents) |
| `skills/wowcube-boilerplate/SKILL.md` | Infra gate (before Stage 4) + Stage 5 — scaffolds `app_<game>/`, verifies the simulator build, and produces the verified cube `.oct` |
| `templates/app_ai_template/src/app_ai_template.h` | Annotated OctaviOS API reference — the authoritative guide for all WowCube C/C++ code |
| `templates/app_ai_template/` | Template app cloned per game by `wowcube-boilerplate` (art, sound, src, `.target` marker) |
| `src/app_structure_example.h` | Clean project skeleton the orchestrator copies to `src/app_<game>.h` |

## 🎮 Available Skills

**`cube_orchestrator` is the single entry point.** For any WowCube game request — at any stage — the user invokes the orchestrator. It detects which pipeline stage the project is in and drives the right component skill or subagents itself, pausing for user approval at every stage boundary. The other five skills (`cube_game-designer`, `technical_prompter`, `cube_asset-builder`, `cube_verifier`, `wowcube-boilerplate`) are components the orchestrator manages, not user-facing entry points.

### Cube Orchestrator (`cube_orchestrator`) — master controller

The entry point and master controller of the entire pipeline. On every entry it runs **stage detection** and routes:

1. No GDD → drives **Stage 1** (`cube_game-designer`)
2. GDD but no prompts/manifest → drives **Stage 2** (`technical_prompter`)
3. Prompts/manifest but no packed assets → drives **Stage 3** (`cube_asset-builder`)
4. All inputs present, prompts unimplemented → runs **Stage 4**: deploys coder, verifier, and fixer subagents for each prompt
5. All prompts implemented, no verified device `.oct` → drives **Stage 5** (`wowcube-boilerplate`): builds and verifies the cube-loadable package

Stages 1–3 and Stage 5 run in the main context via the Skill tool; Stage 4 dispatches subagents via the Agent tool. All inter-agent communication uses JSON. Pipeline parallelism where safe (prepare next task while verifying current). Scores below 90 trigger automatic rework (up to 5 attempts). Context accumulates in `context/<game>_context.json`. The orchestrator checkpoints with the user at every stage boundary and after every prompt.

### Stage 1 — Game Designer (`cube_game-designer`)

Component invoked by the orchestrator. Takes a game concept and produces a non-technical Game Design Document at `plans/<game_name>_gdd.md` through a discovery interview with the user.

### Stage 2 — Technical Prompter (`technical_prompter`)

Component invoked by the orchestrator. Reads the GDD and decomposes it into the smallest possible vertical-slice implementation prompts at `plans/<game_name>_prompts.md`, plus the asset manifest `plans/<game_name>_assets.json`. Each prompt produces a testable increment.

### Stage 3 — Asset Builder (`cube_asset-builder`)

Component invoked by the orchestrator. Turns the validated asset manifest into placeholder PNGs and MP3s, pauses for user review, then packs them into `assets/packed/`, `assets/mp3/`, and `src/app_<game>_ids.h`.

### Stage 4 — Verifier (`cube_verifier`)

Component invoked by the orchestrator during the implementation loop. After each coder agent finishes a prompt, the orchestrator dispatches two `cube_verifier` agents sequentially — a **requirements agent** (completeness, GDD alignment, no regressions, verification criteria) and a **template agent** (API correctness, platform constraints, code quality) — which together score the result out of 100. A score below the threshold triggers automatic fix-and-re-verify cycles.

### Stage 5 — Device Package (`wowcube-boilerplate`)

Component invoked by the orchestrator. Also provides the **infrastructure gate** before Stage 4 (scaffolds `app_<game>/`, verifies the simulator builds and launches). At completion it runs the mandatory device build (`build_device.ps1`): compiles the ARM target and verifies the cube-loadable `app_<game>/app_<game>.oct` actually embeds the ARM code — a passing simulator build alone is **not** shippable.

## 🤖 How to Use

**You only ever talk to the orchestrator.** Describe your game idea (or ask to continue an existing one) and the orchestrator figures out where you are in the pipeline and drives the right stage:

> "I want to make a WowCube game where the player catches falling stars by twisting the cube. Stars appear on random faces and fall toward the bottom plane. The player twists to move a basket between faces to catch them."

The **Cube Orchestrator** runs stage detection, sees there is no GDD yet, and drives **Stage 1** (Game Designer) to interview you and produce the GDD. After you approve it at the stage checkpoint, the orchestrator drives **Stage 2** (Technical Prompter) for prompts + asset manifest, then **Stage 3** (Asset Builder) for placeholder assets, then **Stage 4** (coder/verifier/fixer subagents) to implement the prompts one at a time (tested in the simulator), and finally **Stage 5** (Device Package) to build and verify the cube-loadable `.oct`.

### Resuming

Just ask the orchestrator to continue:

> "Continue building the star catcher game."

The orchestrator re-runs stage detection against `plans/`, `assets/`, and `context/<game>_context.json` and resumes from the first incomplete stage. You never invoke the component skills directly — the orchestrator routes into them and checkpoints with you at every stage boundary and after every implemented prompt.

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
