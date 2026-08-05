# 🧊 WowCube AI Agent Skills Repository

A knowledge base and skill set for LLM-powered coding agents (Kilo Code, Claude Code, Cursor, GitHub Copilot, etc.) that enables them to design and implement games for the WowCube platform — a 2×2×2 puzzle cube with 24 physical screens.

`cube_orchestrator` runs the whole pipeline **autonomously by default** — one request in, a verified device `.oct` out, with no approval stops unless the user opts into stepwise/checkpoint mode (see `skills/cube_orchestrator/SKILL.md` for the run-mode rules). AI sprite generation is multi-provider: OpenRouter, OpenAI, xAI/Grok, Gemini, or a local Stable Diffusion endpoint, auto-detected from whichever key/URL is configured (falls back to agent-drawn placeholder art with none configured).

## 📂 Repository Structure

```
├── skills/
│   ├── cube_orchestrator/        # Skill: MASTER controller + entry point (routes all stages)
│   │   └── SKILL.md
│   ├── cube_game-designer/       # Stage 1 component: game concept → GDD
│   │   └── SKILL.md
│   ├── technical_prompter/       # Stage 2 component: GDD → prompts + asset manifest
│   │   └── SKILL.md
│   ├── cube_asset-builder/       # Stage 3 component: manifest → beta container + _ids.h
│   │   └── SKILL.md
│   ├── wowcube-boilerplate/      # Infra gate + Stage 5: scaffold, sim build, device .oct
│   │   └── SKILL.md
│   └── cube_verifier/            # Stage 4 component: Requirements + Template verification agents
│       └── SKILL.md
├── templates/
│   └── app_ai_template/          # Template app cloned into app_<game>/ for each project
│       ├── src/app_ai_template.h        # OctaviOS API reference template
│       ├── src/app_ai_template_ids.h    # Asset ID header (BMP enum pattern)
│       ├── art/                         # Template PSD/fonts/icon
│       └── sound/                       # Template placeholder sounds
├── src/                          # Example source files
├── context/                      # Created at runtime: JSON context files for the orchestrator (per-game state)
└── plans/                        # Output directory for generated game plans
```

### Key Files

| Path | Purpose |
|------|---------|
| `skills/cube_orchestrator/SKILL.md` | **Master controller and single entry point** — routes every stage and manages all sub-skills and subagents |
| `skills/cube_game-designer/SKILL.md` | Stage 1 component — transforms a user's game idea into a structured design document (GDD) |
| `skills/technical_prompter/SKILL.md` | Stage 2 component — converts a GDD into step-by-step implementation prompts plus the asset manifest |
| `skills/cube_asset-builder/SKILL.md` | Stage 3 component — turns the asset manifest into the packed beta container (`index.bin`, `art/packed/`, `sound/assets/`) and `_ids.h` |
| `skills/wowcube-boilerplate/SKILL.md` | Infra gate + Stage 5 component — scaffolds `app_<game>/`, verifies the simulator build, and produces the device-loadable `.oct` |
| `skills/cube_verifier/SKILL.md` | Stage 4 component — Requirements Agent + Template Agent that score a coder agent's implementation |
| `scripts/repack_app.py` | One-command "assets/code changed — repack it" cycle: repack, auto-bump `APP_VERSION`'s patch digit, rebuild + verify the device `.oct` (`--skip-device` to stop after the version bump) |
| `templates/app_ai_template/src/app_ai_template.h` | Annotated OctaviOS API reference — the authoritative guide for all WowCube C/C++ code |
| `templates/app_ai_template/src/app_ai_template_ids.h` | Asset ID header (BMP enum pattern) |
| `src/app_structure_example.h` | Clean project skeleton for new games |

## 🎮 Available Skills

**`cube_orchestrator` is the single entry point.** For any WowCube game request — at any stage — the user invokes the orchestrator. It detects which pipeline stage the project is in and drives the right component skill or subagents itself, pausing for user approval at every stage boundary. The other five skills are components the orchestrator manages, not user-facing entry points.

### Cube Orchestrator (`cube_orchestrator`) — master controller

The entry point and master controller of the entire pipeline. On every entry it runs **stage detection** and routes:

1. No GDD → drives **Stage 1** (`cube_game-designer`)
2. GDD but no prompts/manifest → drives **Stage 2** (`technical_prompter`)
3. Prompts/manifest but no packed assets → drives **Stage 3** (`cube_asset-builder`)
4. Assets packed but `app_<game>/` isn't scaffolded/building → runs the **infra gate** (`wowcube-boilerplate`)
5. All inputs present, prompts unimplemented → runs **Stage 4**: deploys coder subagents plus `cube_verifier`'s Requirements/Template agents and a fixer subagent for each prompt
6. All prompts implemented, no verified device `.oct` → drives **Stage 5** (`wowcube-boilerplate`): builds and verifies the cube-loadable package

Stages 1–3 and Stage 5 run in the main context via the Skill tool; Stage 4 dispatches subagents via the Agent tool. All inter-agent communication uses JSON. Pipeline parallelism where safe (prepare next task while verifying current). Scores below 90 trigger automatic rework (up to 5 attempts). Context accumulates in `context/<game>_context.json`. The orchestrator checkpoints with the user at every stage boundary and after every prompt.

### Stage 1 — Game Designer (`cube_game-designer`)

Component invoked by the orchestrator. Takes a game concept and produces a non-technical Game Design Document at `plans/<game_name>_gdd.md` through a discovery interview with the user.

### Stage 2 — Technical Prompter (`technical_prompter`)

Component invoked by the orchestrator. Reads the GDD and decomposes it into the smallest possible vertical-slice implementation prompts at `plans/<game_name>_prompts.md`, plus the asset manifest `plans/<game_name>_assets.json`. Each prompt produces a testable increment.

### Stage 3 — Asset Builder (`cube_asset-builder`)

Component invoked by the orchestrator. Turns the validated asset manifest into AI-generated PNGs plus synthesized WAVs encoded to beta mp3, pauses for user review, then packs them into the beta container — `app_<game>/index.bin`, `art/packed/*.raw`+`*.pal`, `sound/assets/*.mp3` — and `src/app_<game>_ids.h`.

### Infra Gate — Boilerplate (`wowcube-boilerplate`)

Component invoked by the orchestrator before Stage 4. Scaffolds `app_<game>/` from `templates/app_ai_template/`, packs the assets, and verifies the simulator builds and launches — before any game code exists.

### Stage 4 — Implementation + Verifier (`cube_verifier`)

The orchestrator deploys a coder subagent per prompt, then `cube_verifier`'s two agents: a Requirements Agent (completeness, GDD alignment, regressions) and a Template Agent (API correctness against `templates/app_ai_template/src/app_ai_template.h`), each scored out of 100. Both must score ≥ 90 or the orchestrator's fixer agent reworks the code (up to 5 attempts).

### Stage 5 — Device Package (`wowcube-boilerplate`)

Component invoked by the orchestrator. At completion it runs the mandatory device build (`build_device.ps1`): compiles the ARM target and verifies the cube-loadable `app_<game>/app_<game>.oct` actually embeds the ARM code — a passing simulator build alone is **not** shippable.

## 🤖 How to Use

**You only ever talk to the orchestrator.** Describe your game idea (or ask to continue an existing one) and the orchestrator figures out where you are in the pipeline and drives the right stage:

> "I want to make a WowCube game where the player catches falling stars by twisting the cube. Stars appear on random faces and fall toward the bottom plane. The player twists to move a basket between faces to catch them."

By default this runs **autonomously**: the **Cube Orchestrator** runs stage detection, sees there is no GDD yet, and drives **Stage 1** (Game Designer) straight through to a GDD from your one-sentence concept (no interview). It then drives **Stage 2** (Technical Prompter) for prompts + asset manifest, **Stage 3** (Asset Builder) for AI-generated (or placeholder) art and sound, the **infra gate** (Boilerplate) to scaffold `app_<game>/` and verify the simulator, **Stage 4** (coder/verifier/fixer subagents) to implement the prompts one at a time (tested in the simulator), and finally **Stage 5** (Device Package) to build and verify the cube-loadable `.oct` — printing a one-way progress line at each stage boundary instead of stopping for approval. Ask for **«по шагам»** (or "review mode") to get the checkpointed walkthrough instead, where you approve the GDD, prompts, and each asset/prompt batch before the orchestrator proceeds.

### Resuming

Just ask the orchestrator to continue:

> "Continue building the star catcher game."

The orchestrator re-runs stage detection against `plans/`, `assets/`, and `context/<game>_context.json` and resumes from the first incomplete stage. You never invoke the component skills directly — the orchestrator routes into them, running straight through with progress lines by default, or checkpointing with you at every stage boundary and after every implemented prompt when you've asked for «по шагам».

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

For the full API reference, see `templates/app_ai_template/src/app_ai_template.h`.

---

*Built to help AI agents write correct, hardware-aware WowCube games — no zero-index loops, no memory leaks, and proper twist synchronization.*
