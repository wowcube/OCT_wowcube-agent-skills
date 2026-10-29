# WowCube AI agent skills

Skills for coding agents (built for Claude Code; the markdown reads fine in other agents)
that design, draw, build and ship games for WowCube, a 2×2×2 cube with 24 screens, on
the current OctaviOS SDK.

Ask for a game. `cube_orchestrator` writes the design, draws the art with Codex on your
ChatGPT subscription, sources real CC0 sounds, implements and verifies the code prompt by
prompt while looking at every build on hidden 24-screen simulator frames, and hands you
a verified `.oct`, uploaded to your cube over Bluetooth when you ask.

## What a run looks like

- **Autonomous by default.** At most two intake questions (the concept if you gave
  none; a Codex login if it is missing), one stop to approve the art style (a style
  frame plus an in-game mock) and the list of sounds to download, progress lines, a
  final report. Say «по шагам» / "stepwise" to approve every stage, batch and prompt.
- **Art**: `cube_art-director` drives the Codex CLI (ChatGPT subscription, no API key)
  with a style lock and a strict QA loop: every rule must pass, every fix is recorded,
  a fresh agent reviews consistency before you see a batch. Paid image APIs and
  agent-drawn placeholders are fallbacks only.
- **Sound**: CC0 recordings (downloaded only after you approve the list), layered and
  mastered by `scripts/sound_kit.py` into the engine's mp3 format, a looping music bed,
  licences in `sound/CREDITS.md`. Synthesis is the fallback. Nothing is ever played on
  your machine; sounds are judged by numbers.
- **Code**: one coder per prompt; two code reviewers (≥ 90 each, and any critical issue
  fails); a mandatory visual gate (the agent builds a hidden, muted simulator, dumps all
  24 screens and looks at them); a playtest over the simulator's control socket; a fixer
  (up to 5 rounds). A prompt that still fails is rescoped and must then pass every gate:
  nothing is marked done with a failing check.
- **Delivery**: the official `octpack-build` writes `dist/app_<game>.oct` (header and ARM
  code verified, an unverifiable build fails; no simulator involved); upload to your cube
  on request; an on-device checklist; an optional gameplay video; balance passes.
- **Safety**: no windows over your screen, no audio from test runs, no global keyboard
  or mouse input, processes stopped only by PID, no commits, pushes or messages unless
  you ask, no credentials, downloads only after you approve them
  (`skills/cube_orchestrator/references/AGENT_SAFETY.md`).

## Requirements

| What | Needed |
|---|---|
| SDK | `octavios` dev from 2026-10-21 (commit `609d5ae`) or later, with `wowcube/telemetry` checked out next to it |
| Simulator | Windows: Visual Studio 2022 C++ build tools. Linux: SDL3 (+ BlueZ and libsystemd), Xvfb for hidden runs |
| Device build | ARM GNU toolchain, CMake, Ninja; `uv` and clang++ (or g++) for `octpack-build` |
| Art | Codex CLI, logged in with ChatGPT (`codex login`) |
| Sound, video | ffmpeg |
| Python | 3.10+ with `scripts/requirements.txt`; Pillow and NumPy for the art director |

`scripts/check_env.ps1` / `check_env.sh` check the toolchain; on Windows
`check_env.ps1 -Install` adds what is missing with quiet winget installs, only after you
agree (together with the SDK packer's one-time package download). The orchestrator
checks the SDK on entry and tells you the exact update commands; it never updates your
SDK itself.

## Workspace layout

```
<workspace>/
├── octavios/          the SDK (dev, 609d5ae or later)
├── telemetry/         wowcube/telemetry (every simulator build needs it next to octavios)
├── app_<game>/        the game: <app>.target, src/ (app.h, app_metadata.h, app_<game>.h, _ids.h), art/, sound/, index.bin
├── assets_<game>/     art workspace: style/ (style bible, anchors), raw/, art/, qa/, review.html, fixes.json, sound_src/, wav/
├── plans/             <game>_gdd.md, <game>_prompts.md, <game>_assets.json
├── context/           <game>_context.json (run state), rules.md (your standing rules)
├── dist/              app_<game>.oct (the deliverable), app_<game>_gameplay.mp4
└── .sim_headless/     hidden-simulator builds and frames (tools/sim_headless)
```

## Repository layout

```
.claude-plugin/plugin.json      plugin manifest
skills/
├── cube_orchestrator/          the entry point
│   ├── SKILL.md                modes, stage routing, the five stages, Mod mode
│   ├── SIM_MCP.md              the simulator's control socket: probe, commands, playtest script
│   └── references/             RUN_MODES, STAGE3_ASSETS, AGENT_BRIEFS, VISUAL_GATE, DELIVERY, AGENT_SAFETY
├── cube_game-designer/         Stage 1: concept -> GDD (references/GAME_FEEL.md)
├── technical_prompter/         Stage 2: GDD -> implementation prompts + asset manifest
├── cube_art-director/          style-locked Codex art with strict QA (also standalone, for artists)
├── cube_asset-builder/         Stage 3: art, sound, icon, fonts -> packed app assets
├── wowcube-boilerplate/        infra gate (scaffold, simulator builds) and Stage 5 (device .oct)
└── cube_verifier/              Requirements, Template and Playtest agents
scripts/                        packer (build_pipeline, pack, pack_beta), manifest validator, sound_kit,
                                device build, repack_app, new_app, check_env
tools/
├── sim_headless/               hidden, muted Windows simulator: build.ps1, run.ps1 (24-screen PNGs), mcp.ps1
└── cube_upload/                Bluetooth upload of an .oct to a cube from Windows
templates/app_ai_template/      the app template; src/app_ai_template.h (annotated API), API.md (engine facts,
                                limits, art tiers)
src/app_structure_example.h     the clean skeleton a new game header starts from
tests/                          pytest suite for the scripts
docs/pipeline-flow.md           the pipeline as a diagram
docs/history/                   past plans, specs and the packer parity report
```

## Skills

You only talk to `cube_orchestrator`; it drives the others.

| Skill | Role |
|---|---|
| `cube_orchestrator` | Single entry point: build vs mod, run modes, stage routing, subagent dispatch, visual gate, delivery |
| `cube_game-designer` | Stage 1: a GDD from the concept, checked against the game-feel lessons |
| `technical_prompter` | Stage 2: small testable implementation prompts (with test hooks) and the asset manifest with Codex-ready prompts |
| `cube_art-director` | Style bible, anchors, Codex generation, strict QA, review page; usable on its own by artists |
| `cube_asset-builder` | Stage 3: drives the art director, builds sounds, the launcher icon and fonts, packs the app |
| `wowcube-boilerplate` | Scaffolds the app in the octavios dev layout, builds the simulators, builds the device `.oct` |
| `cube_verifier` | Requirements and Template agents (code) and the Playtest Agent (the running game) |

## Pipeline

| Stage | What happens | Output |
|---|---|---|
| Entry | build or mod, run mode, SDK and Codex checks | `context/<game>_context.json` |
| 1. Design | GDD from the concept (stepwise: a short interview) | `plans/<game>_gdd.md` |
| 2. Prompts | prompts + asset manifest | `plans/<game>_prompts.md`, `plans/<game>_assets.json` |
| Infra gate | scaffold, simulators build, hidden smoke run | `app_<game>/` |
| 3. Assets | **style lock (your approval)**, Codex art with the QA loop, sounds, icon, fonts, pack | `assets_<game>/`, `app_<game>/index.bin`, `art/packed/`, `sound/assets/`, `_ids.h` |
| 4. Implement | per prompt: coder → code reviewers + visual gate → playtest → fixer | `app_<game>/src/app_<game>.h` |
| 5. Deliver | hooks off, version bump, `octpack-build`, verification; upload, video, balance on request | `dist/app_<game>.oct` |

Details: `docs/pipeline-flow.md` and `skills/cube_orchestrator/SKILL.md`.

## How to use

> "Сделай игру для кубика: ловить падающие звёзды, поворачивая грани."

The orchestrator asks at most what it cannot decide, shows you the style frame, the
in-game mock and the sound list once, then works until the `.oct` is ready.

> "Продолжи игру star catcher." — resumes at the first unfinished step (stage detection
> reads `plans/`, `assets_<game>/`, `app_<game>/` and `context/`).
>
> "По шагам: сделай игру про ..." — stepwise mode.
>
> "Поменяй героя на кота" / "сделай врагов медленнее" — Mod mode, smallest change.
>
> "Залей на кубик" — builds if needed and uploads `dist/app_<game>.oct` to your cube.

## Platform in one paragraph

Eight modules with three 240×240 RGB565 screens each (24 screens, six faces), twists
and taps as input plus an IMU, 20 ticks per second, an app written as one C++ header and
run as eight lockstep copies. Engine facts, limits and art tiers live in one place:
`templates/app_ai_template/API.md`; API usage is annotated in
`templates/app_ai_template/src/app_ai_template.h`.
