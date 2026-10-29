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
  final report. Say "stepwise" (in any language) to approve every stage, batch and prompt.
- **Art**: `cube_art-director` drives the Codex CLI (ChatGPT subscription, no API key)
  with a style lock and a strict QA loop: every rule must pass, every fix is recorded,
  a fresh agent reviews consistency before you see a batch. Codex must be logged in
  with ChatGPT; it never sees an API key from your environment. Without Codex the
  pipeline draws temporary placeholders; a paid image API is used only when you ask for
  one and agree to pay (`WOWCUBE_ALLOW_PAID_IMAGES=1` / `--allow-paid`).
- **Sound**: CC0 recordings (downloaded only after you approve the list), layered and
  mastered by `scripts/sound_kit.py` into the engine's mp3 format, a looping music bed,
  licences in `sound/CREDITS.md`. Synthesis is the fallback. Nothing is ever played on
  your machine; sounds are judged by numbers.
- **Design**: a GDD checked against the game-feel lessons; optionally a playable
  browser prototype of the mechanic (`wowcube-html-prototype`) before any cube code.
- **Code**: one coder per prompt; two code reviewers (≥ 90 each; a critical issue fails,
  an open major is a fix round); a mandatory visual gate (the agent builds a hidden,
  muted simulator, dumps all 24 screens, looks at them, and an automatic seam check
  catches background lines between screens); a playtest over the simulator's control
  socket; a fixer (up to 5 rounds; later rounds re-check the fixer's diff). A prompt that still fails is rescoped and must then pass every gate:
  nothing is marked done with a failing check.
- **Delivery**: the official `octpack-build` writes `dist/app_<game>.oct` (header and ARM
  code verified, an unverifiable build fails; no simulator involved); upload to your cube
  on request; an on-device checklist; an optional gameplay video (the team's 1920x1080
  format via `wowcube-demo-video`); balance passes.
- **Safety**: no windows over your screen, no audio from test runs, no global keyboard
  or mouse input, processes stopped only by PID, no commits, pushes or messages unless
  you ask, no credentials, no paid API without your explicit yes, downloads only after
  you approve them (`skills/cube_orchestrator/references/AGENT_SAFETY.md`).

## Requirements

| What | Needed |
|---|---|
| SDK | `octavios` dev from 2026-10-21 (commit `609d5ae`) or later, with `wowcube/telemetry` checked out next to it |
| Simulator | Windows: Visual Studio 2022 C++ build tools. Linux: SDL3 (+ BlueZ and libsystemd), Xvfb for hidden runs |
| Device build | ARM GNU toolchain, CMake, Ninja; `uv` and clang++ (or g++) for `octpack-build` |
| Art | Codex CLI, logged in with ChatGPT (`codex login`) |
| Sound, video | ffmpeg |
| Python | 3.11+ from python.org (the pinned NumPy 2.4 needs it; not the Microsoft Store build, its `uv` cannot see managed Pythons) with `scripts/requirements.txt` |
| Prototype, video (optional) | Node.js with Playwright + Chromium for `wowcube-html-prototype` / `wowcube-demo-video` (a one-time install you approve) |

`scripts/check_env.ps1` / `check_env.sh` check the toolchain; on Windows
`check_env.ps1 -Install` adds what is missing with quiet winget installs, only after you
agree (together with the SDK packer's one-time package download into
`<workspace>/.uv_octpack_venv`; octavios itself stays read-only). The orchestrator
checks the SDK on entry and tells you the exact update commands; it never updates your
SDK itself.

## Workspace layout

```
<workspace>/
├── octavios/          the SDK (dev, 609d5ae or later)
├── telemetry/         wowcube/telemetry (every simulator build needs it next to octavios)
├── app_<game>/        the game: <app>.target, src/ (app.h, app_metadata.h, app_<game>.h, _ids.h), art/, sound/, index.bin
├── assets_<game>/     art workspace: style/ (style bible, anchors), raw/, art/, qa/, review.html, fixes.json, sound_src/, wav/
├── plans/             <game>_gdd.md, <game>_prompts.md, <game>_assets.json, optional <game>_prototype.html (+ common/)
├── context/           <game>_context.json (run state), rules.md (your standing rules)
├── dist/              app_<game>.oct (the deliverable), app_<game>_gameplay.mp4
├── .sim_headless/     hidden-simulator builds and frames (tools/sim_headless)
└── .uv_octpack_venv/  the official packer's Python environment (created once)
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
├── cube_verifier/              Requirements, Template and Playtest agents
├── wowcube-html-prototype/     optional browser prototype of the mechanic (Alex Poshivalov)
└── wowcube-demo-video/         standard-format demo videos (Alex Poshivalov)
scripts/                        packer (build_pipeline, pack, pack_beta), manifest validator, sound_kit,
                                device build, repack_app, new_app, check_env
tools/
├── sim_headless/               hidden, muted Windows simulator: build.ps1, run.ps1 (24-screen PNGs, seam
│                               report, per-run log), mcp.ps1 (control socket), seams.py, stop.ps1
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
| `wowcube-html-prototype` | Optional, after the GDD: a playable browser prototype of the mechanic on a cube model (author: Alex Poshivalov) |
| `wowcube-demo-video` | Demo videos in the team's standard format from the prototype or the real game (author: Alex Poshivalov) |

## Pipeline

| Stage | What happens | Output |
|---|---|---|
| Entry | build or mod, run mode, SDK and Codex checks | `context/<game>_context.json` |
| 1. Design | GDD from the concept (stepwise: a short interview); optional HTML prototype of the mechanic | `plans/<game>_gdd.md` (`plans/<game>_prototype.html`) |
| 2. Prompts | prompts + asset manifest | `plans/<game>_prompts.md`, `plans/<game>_assets.json` |
| Infra gate | scaffold, simulators build, hidden smoke run | `app_<game>/` |
| 3. Assets | **style lock (your approval)**, Codex art with the QA loop, sounds, icon, fonts, pack | `assets_<game>/`, `app_<game>/index.bin`, `art/packed/`, `sound/assets/`, `_ids.h` |
| 4. Implement | per prompt: coder → code reviewers + visual gate (+ seam check) → playtest → fixer → re-check | `app_<game>/src/app_<game>.h` |
| 5. Deliver | hooks off, version bump, `octpack-build`, verification; upload, video, balance on request | `dist/app_<game>.oct` |

Details: `docs/pipeline-flow.md` and `skills/cube_orchestrator/SKILL.md`.

## How to use

> "Make a cube game: catch falling stars by twisting the faces."

The orchestrator asks at most what it cannot decide, shows you the style frame, the
in-game mock and the sound list once, then works until the `.oct` is ready.

> "Continue the star catcher game." — resumes at the first unfinished step (stage detection
> reads `plans/`, `assets_<game>/`, `app_<game>/` and `context/`).
>
> "Stepwise: make a game about ..." — stepwise mode.
>
> "Make the hero a cat" / "make the enemies slower" — Mod mode, smallest change.
>
> "Upload it to the cube" — builds if needed and uploads `dist/app_<game>.oct` to your cube.
>
> "Make an HTML prototype of the mechanic" / "Record a video of the game" — the browser prototype and the
> demo video in the team's format.
>
> Artists can use `cube_art-director` on its own: "Here is my reference, draw a sprite set
> in this style" — style lock from the reference, Codex drawing, QA and a review page.

## Platform in one paragraph

Eight modules with three 240×240 RGB565 screens each (24 screens, six faces), twists
and taps as input plus an IMU, 20 ticks per second, an app written as one C++ header and
run as eight lockstep copies. Engine facts, limits and art tiers live in one place:
`templates/app_ai_template/API.md`; API usage is annotated in
`templates/app_ai_template/src/app_ai_template.h`. Measured on the simulator and worth
knowing before the first line of code: screen-filling art goes at `±119.5`
(`QUAD_FILL`), not `±120`; text draws at twice the font size; follow the up face with
`topWithHysteresis()`, not `OCT_TM_top_side()`.

## Development

```bash
pip install -r scripts/requirements.txt
python -m pytest -q -m "not slow"          # pytest.ini sets tests/ and scripts/ on the path
```

Tests never reach a network or a paid API and never open a window.
