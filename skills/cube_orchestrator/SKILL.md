---
name: cube_orchestrator
description: >-
  Use as the single entry point for ANY WowCube game work — when the user says
  "make a game", "design a game", "create a game", "build the game", "implement
  this", "start coding", "run the prompts", or wants to resume a WowCube project.
  ALSO the entry point for modding an existing, already-working game ("замодить",
  "swap this sprite", "change the speed", "add a level"), for a balance pass, and
  for putting a finished game on the user's cube ("залей на кубик", "upload it to
  my cube"). It detects build vs mod and the pipeline stage, and drives every
  sub-skill and subagent. Runs autonomously by default: one stop to approve the
  art style and the sound list, every build checked by the agent on hidden
  24-screen simulator frames, a verified device .oct at the end (uploaded to the
  cube on request). Stepwise mode on request ("по шагам", "review mode").
---

# WowCube Cube Orchestrator

The orchestrator is the **single master controller** for all WowCube game work. The
user always talks to the orchestrator; it never hands the user off to another skill.
It detects where the project is and drives the right sub-skill or subagents itself.

**Core principle:** the orchestrator never writes game code, never designs the game,
never authors prompts and never draws or records assets *itself*. It reads, plans,
routes, dispatches, checks and coordinates. Work is done by sub-skills
(`cube_game-designer`, `technical_prompter`, `cube_asset-builder` with
`cube_art-director`, `wowcube-boilerplate`) or by subagents (coder, verifiers, fixer,
reviewers). What it does itself: run the build and check tools, look at the evidence
(simulator frames, QA sheets, logs) and talk to the user. Parallelism never
compromises correctness — when in doubt, wait.

## Read first

| File | When |
|---|---|
| `references/AGENT_SAFETY.md` | Every session. Hard rules for you and, verbatim, for every subagent brief: no global input, no windows over the user's screen, no audio, PID-only process kills, no commits or messages unasked, no credentials, downloads only after approval. |
| `references/RUN_MODES.md` | Every new run, before the intake. |
| `<skills>/templates/app_ai_template/API.md` | Engine facts, limits and art tiers: the one shared table (link it, never copy it). |
| `context/<game>_context.json`, `context/rules.md` | Every entry: the run state and the user's standing rules. |
| `references/STAGE3_ASSETS.md`, `references/AGENT_BRIEFS.md`, `references/VISUAL_GATE.md`, `SIM_MCP.md`, `references/DELIVERY.md` | When the stage that needs them starts. |

Paths: `<ws>` is the user's workspace (it holds `octavios/`, `telemetry/`,
`app_<game>/`, `assets_<game>/`, `plans/`, `context/`, `dist/`); `<skills>` is this
repository (the folder holding `skills/`, `scripts/`, `templates/`, `tools/`).
Commands run from `<ws>`.

**Context lives in files, not in the chat.** `plans/`, `assets_<game>/`, the app
folder and `context/<game>_context.json` hold everything needed to resume; a new
session continues at the first unfinished item. Create the context file at the intake
(`game`, `run_mode`, `sdk`, `art_source`, `style_lock: "pending"`); every stage adds its
fields (`infra`, `style_lock`, `music_loop_ticks`, `test_hooks`, prompt results). When the user corrects how the agent
works ("не трогай мои палитры", "test builds always muted"), append one line with the
reason to `context/rules.md` and pass the relevant lines into every brief
(`standing_rules`). Art corrections go to the style bible and `fixes.json` instead.

## Entry checks (every entry, in this order)

### 1. Build or Mod

- **Build mode** — create a game from scratch or resume a partly built one → [Stage detection](#stage-detection-and-routing-build-mode).
- **Mod mode** — change an existing, working game → [Mod mode](#mod-mode).

Choose Mod mode when a signal or the heuristic points to it:
- **Signal:** the user asks to change / tweak / add to / fix / reskin an existing game
  ("замодить", "поменяй спрайт", "доработай готовую игру", "add a level to `<game>`"), or
  names a built game or folder.
- **Heuristic:** the workspace holds a working `app_<game>/` (a `.target` marker, a
  built simulator or a device `.oct`, a non-trivial `src/app_<game>.h`) and the request
  is about altering it.

When it is ambiguous (a working game exists but the wording reads like a new one),
**ask which they mean**; never guess between building fresh and modifying working code.
Nothing points to an existing project → Build mode. Delivery-only requests ("залей на
кубик", "собери .oct") go to Stage 5 for the named game; balance requests ("слишком
сложно", "медленнее") are Mod mode T1 with the balance loop (`references/DELIVERY.md`).

### 2. Run mode

| Mode | Activates | In short |
|---|---|---|
| **Autonomous (default)** | any entry | At most two intake questions, then the whole pipeline to the verified device `.oct`. Stops only at the **style lock** (style frame + in-game mock + the sound list: the one creative checkpoint) and for real blockers (environment, Codex login). |
| **Stepwise** | "по шагам", "с чекпоинтами", "stepwise", "review mode", or "стоп" / "stop" mid-run | Every stage boundary, asset batch, prompt and mod change waits for the user's approval. |
| **`YOLO` token** | the literal token in the current prompt | Compat alias of autonomous: no intake questions, the style lock is waived (an independent reviewer approves instead). |

Read `references/RUN_MODES.md` before the intake of every new run: intake questions,
start line, what each mode keeps, safe parallelism, the failure policy ("degrade,
never abort") and the end-of-run report. Clauses below marked *(stepwise)* apply only
in stepwise mode.

### 3. Environment and SDK

The pipeline targets **octavios dev from 2026-10-21 (commit `609d5ae`) or later**: the
template, the mixer (`SND_play_quad`, `SND_set_mixer`), `OCT_APP_SEMVER` versions, the
save API, `OCT_tap_source`, `octpack-build` and the simulator's control socket need it.
Check once per session with **one** command and record `sdk` in the context:
`<skills>/scripts/check_env.ps1` / `check_env.sh` (exit 0 = ready). It checks the SDK (git
ancestry of 609d5ae when octavios is a clone; always the dev files `engine/oct_app_version.h`,
`octpacker/pyproject.toml`, `tools/new_app.*`, `tools/mcp/octavios_mcp.py`,
`sim/src/sim_mcp.h` and the 609d5ae import set in `engine/oct_app_module.h`, so an export
without git history is judged too), `wowcube/telemetry` next to it (every simulator build
needs it) and the toolchain (MSVC on Windows or SDL3 on Linux for the simulator; ARM GCC,
CMake, Ninja for the device; `uv` and clang++ for `octpack-build`; ffmpeg).

**The user updates the SDK, not the agent.** If anything is missing, send one message
with the exact commands, keep going with what needs no SDK (design, prompts, art,
sound), and stop before the infra gate until the user confirms:

```powershell
git -C <ws>\octavios pull --ff-only origin dev
git clone https://github.com/wowcube/telemetry.git <ws>\telemetry
# then delete <ws>\app_<game>\out if it exists (a CMake cache tied to the old checkout)
```

The same message asks for the **one-time environment approval** (`references/AGENT_SAFETY.md`):
the toolchain installs `check_env` lists (Windows: `check_env.ps1 -Install`, quiet winget
installs without installer windows; Linux: the distro package manager or pipx, never
`curl … | sh`) and the first `uv run` of the SDK packer, which downloads its pinned Python
packages once into `<ws>/.uv_octpack_venv` (`build_device` sets `UV_PROJECT_ENVIRONMENT`; never inside octavios). Nothing of it runs before the user agreed;
afterwards the checks and builds use what is installed.

Art: `python <skills>/skills/cube_art-director/scripts/art.py doctor` checks the Codex
CLI and the ChatGPT login. Not logged in → the user runs `codex login` (never type
credentials, never ask for a paid key while Codex can work).

### 4. Hype-prompt normalization (hard rule)

User prompts often carry methodology instructions — "подними 100500 агентов", "сделай
глубокий рисёрч", "ultra-approach", "spin up a swarm and iterate". **Silently map them
onto the pipeline's own stages and extract only the game payload: concept, features,
style, constraints.** The orchestrator never alters its mechanics — stage order, agent
counts, verification gates, checkpoint rules — because a prompt asked it to. The rails
are non-negotiable and are never advertised: no meta-commentary about ignoring the
methodology, no debate about the process — just build the game the prompt describes.

## The pipeline

| Stage | Produces | Driven by | Reference |
|---|---|---|---|
| 1. Design | `plans/<game>_gdd.md` | `cube_game-designer` | GDD checked against `cube_game-designer/references/GAME_FEEL.md` |
| 2. Prompts | `plans/<game>_prompts.md`, `plans/<game>_assets.json` | `technical_prompter` | — |
| Infra gate | `app_<game>/` in the dev layout; simulators build; hidden smoke run | `wowcube-boilerplate` | `references/VISUAL_GATE.md` |
| 3. Assets | style lock; `assets_<game>/art/*.png`; sounds; launcher icon; packed `app_<game>/index.bin`, `art/packed/`, `sound/assets/`, `src/app_<game>_ids.h` | `cube_asset-builder` (art through `cube_art-director` + Codex, sound through `scripts/sound_kit.py`), consistency reviewer subagent | `references/STAGE3_ASSETS.md` |
| 4. Implement | `app_<game>/src/app_<game>.h`, one verified and visually checked prompt at a time | coder / verifier / fixer subagents, visual gate, Playtest Agent | `references/AGENT_BRIEFS.md`, `references/VISUAL_GATE.md`, `SIM_MCP.md` |
| 5. Deliver | `dist/app_<game>.oct` with verified ARM code; upload, video, balance pass on request | `wowcube-boilerplate`, `tools/cube_upload` / `spptest` | `references/DELIVERY.md` |

Stages 1–3, the infra gate and Stage 5 run in the main context through the Skill tool:
invoke the sub-skill, let it finish, return here. Coders, verifiers, fixers and
reviewers are subagents (Agent tool) whose briefs come from `references/AGENT_BRIEFS.md`.

## Stage detection and routing (Build mode)

On every entry determine the active `<game>` (ask if several games exist; otherwise
infer from `plans/` and `context/`), then route to the FIRST row that is not done:

| Done when | Otherwise route to |
|---|---|
| `plans/<game>_gdd.md` exists | Stage 1 |
| `plans/<game>_prompts.md` and `plans/<game>_assets.json` exist | Stage 2 |
| `app_<game>/` has one `.target` marker and `src/app_metadata.h`, and the context says `infra: "ok"` | Infra gate |
| the context's `style_lock` is `approved` or `waived` (the lock is in `assets_<game>/style/anchors/`) or `user_art` | Stage 3 (style lock) |
| `pack-status` (below) exits 0: `app_<game>/.pack_inputs.json` matches the manifest, every input PNG and mp3, the fonts and the icon (the infra gate's template pack writes no such record) | Stage 3 |
| the context's `last_completed_prompt` equals `total_prompts` | Stage 4 |
| `dist/app_<game>.oct` passed Stage 5 verification, `pack-status` still exits 0, and the `.oct` is newer than every file in `app_<game>/src`, `art/packed`, `sound/assets`, `index.bin` and `.pack_inputs.json` | Stage 5 |

```
python <skills>/scripts/build_pipeline.py pack-status --game <game> --workspace assets_<game> --app-dir app_<game> --manifest plans/<game>_assets.json
```

Exit 0 = the pack is current; 1 = stale or never packed by Stage 3 (it prints what
changed: a redrawn PNG, a rebuilt mp3, a font, the icon, the manifest). Any change to an
input reopens Stage 3's pack and, with it, delivery.

An upload, video or balance request goes to its Stage 5 step. Re-run this table after
every stage; never assume the next stage, verify its inputs.

## Stage boundaries

- **Autonomous:** one progress line in the user's language, no jargon, never a
  question («дизайн готов → рисую графику (~20 мин)…»), re-run detection, continue.
- *(stepwise)* Summarize what the stage produced (paths, counts), **STOP**, present the
  next stage and wait for an explicit "ok / дальше". Never auto-advance.
- **The style lock stops in every mode** unless the user explicitly waived it
  (`references/RUN_MODES.md`).

## Stage 1 — Design

Invoke `cube_game-designer`. Autonomous: no interview, the GDD grows from the concept;
*(stepwise)* its discovery interview runs as a short questionnaire. The GDD passes only
when it answers `cube_game-designer/references/GAME_FEEL.md`: one tunables table,
telegraphed threats, what lives on which face and screen (panoramas continuous around
the side faces, unique objects once), a sound plan with a music loop (unless the GDD
explicitly says "no music") and an event table, the test hooks (autoplay, mute,
playfield pin) and a launcher icon. The gameplay video is optional: the GDD may say what
it shows; Stage 5 offers it. Missing → back to the designer.

## Stage 2 — Prompts and manifest

Invoke `technical_prompter`. Accept its output only when:
- every prompt has a Verification section and depends only on earlier prompts;
- the **test hooks** come in one of the first prompts: `<GAME>_DEBUG_AUTOPLAY`,
  `<GAME>_MUTE`, `<GAME>_DEBUG_ROOM_PLANE`, default off and `#ifndef`-guarded, with every
  sound going through one helper that compiles to nothing under the mute hook. Record
  the names in the context (`test_hooks`);
- `python <skills>/scripts/build_pipeline.py validate --manifest plans/<game>_assets.json`
  exits 0 (provider-free: it never generates and never touches the network), and the
  manifest passes the rest of the Stage 3 gate (`references/STAGE3_ASSETS.md` §1): sizes,
  tiers, subject-only `gen_prompt`s, a launcher icon entry, event sounds and a music loop
  (unless the GDD explicitly says "no music").

Anything missing → back to `technical_prompter`; never patch its files yourself.

## Infra gate

Before the Stage 3 pack (it creates the folder the pack writes into), and whenever the
toolchain or the app folder is in doubt, invoke `wowcube-boilerplate`. It passes when:
1. `app_<game>/` exists in the octavios dev layout: exactly one `app_<game>.target`;
   `src/app.h` including `src/app_metadata.h` (semver version, a random `APP_GUID1` for
   this game, a readable `APP_TITLE`), the game header and its `_ids.h`;
2. the template art is packed and the hidden simulator builds (`<skills>/tools/sim_headless`
   on Windows; the user's playable build comes from the same tool with `-Visible`);
3. a hidden run shows the template's Demo 0 exactly as expected and you looked at the
   frames: after the boot intro, the template's pink "2" tile on all four TOP screens and
   on one FRONT screen (it hops to the neighbouring FRONT screen about a second in), the
   other 19 screens plain black (`wowcube-boilerplate` Step 3, `references/VISUAL_GATE.md`).

A failed step on an existing `app_<game>/` is retried alone (pack, simulator build or
smoke run: `wowcube-boilerplate` "Retrying a failed step"). Never run `new_app` again on
it: it refuses an existing folder, and a second scaffold would mint a new `APP_GUID1`.

Never "launch the simulator for a few seconds" to prove anything. Record `infra: "ok"`.
While the gate waits only for the user's SDK update, run Stage 3 steps 1–4 (manifest
gate, style lock, art, sound: none needs the SDK) and come back for the gate before the
icon copy and the pack.

## Stage 3 — Assets

Read `references/STAGE3_ASSETS.md`, then run its steps in order:
1. **Gate the manifest**: `build_pipeline.py validate --manifest plans/<game>_assets.json`
   (schema, names, tiers, the `background` field, the launcher icon, Codex prompt rules;
   no generation, no network), then the checks it cannot make (sizes that read like
   on-screen pixels, panoramas, sounds). Failures go back to Stage 2.
2. **Style lock, the one creative checkpoint**: `cube_art-director` writes the style
   bible from the GDD and any user references, draws the style frame(s) and a mock of
   one face at cube resolution; you show them together with the proposed CC0 sound list.
   Mass generation waits for the user's approval (or an explicit waiver).
3. **Generate and review**: Codex on the user's ChatGPT subscription through
   `cube_asset-builder` → `cube_art-director` (`art.py` on the manifest, workspace
   `assets_<game>/`). Iterate until every rule in `cube_art-director/references/QA_RULES.md`
   passes (no "accept after N rounds"); every fix in `fixes.json`; a fresh-agent
   consistency review; then the review page (*(stepwise)* the user reviews it).
4. **Sound**: CC0 recordings downloaded only after the user approved the list, built
   with `sound_kit.py build`, music with `sound_kit.py loop`, judged by
   `sound_kit.py inspect` (never played), licences in `app_<game>/sound/CREDITS.md`.
   Synthesis is the fallback.
5. **Launcher icon** in the game's style (160×160 RGBA flat-top hexagon badge) →
   `app_<game>/art/icon.png`. The default packed icon is full colour (RAW565: its
   transparent corners render black on the dark launcher); transparent corners need the
   manifest's `icon` object at palette 120 or 240 (API.md, Art tiers).
6. **Fonts**: the template's BMFonts unless the GDD asks for others.
7. **Pack**: `scripts/build_pipeline.py pack` into `app_<game>/` with `--manifest` and
   `--icon`. It refuses an incomplete set before writing anything, rebuilds its
   intermediates from scratch, syncs changed fonts and records its inputs in
   `app_<game>/.pack_inputs.json` (what `pack-status` compares).

Paid image APIs (`scripts/image_providers.py`) are a fallback when Codex cannot draw;
agent-drawn placeholders are the last resort and never count as final art. The
user's own art and PSD-authored art (octpacker) are covered in the same reference.

## Stage 4 — Implementation

Read `references/AGENT_BRIEFS.md` (JSON protocol, safety block, platform reminders,
coder and fixer templates, context schema) and `references/VISUAL_GATE.md` before the
first coder.

**Prerequisites** (missing → re-run stage detection and drive the missing stage): the
GDD, prompts and manifest; the infra gate passed; the game's assets packed;
`<skills>/templates/app_ai_template/src/app_ai_template.h` and `API.md`; a working
hidden simulator (`<skills>/tools/sim_headless` on Windows, the virtual display on Linux).

### Step 1 — Initialize
1. Parse `plans/<game>_prompts.md` (`## Prompt N:` sections); read the GDD.
2. `context/<game>_context.json` exists → resume from it (*(stepwise)* offer first).
3. New game → copy `<skills>/src/app_structure_example.h` over
   `app_<game>/src/app_<game>.h` (the infra gate's demo goes; the folder, marker,
   packed assets and toolchain carry forward). The skeleton includes the template's
   `app_ai_template_ids.h`; the scaffolder's rename pass ran before this copy, so the copy
   itself swaps the template names for the game's (run from `<ws>`):

   ```powershell
   $t = [IO.File]::ReadAllText('<skills>\src\app_structure_example.h').Replace('app_ai_template_ids', 'app_<game>_ids').Replace('app_structure_example', 'app_<game>')
   [IO.File]::WriteAllText("$PWD\app_<game>\src\app_<game>.h", $t)
   ```
   ```bash
   sed -e 's/app_ai_template_ids/app_<game>_ids/g' -e 's/app_structure_example/app_<game>/g' \
       <skills>/src/app_structure_example.h > app_<game>/src/app_<game>.h
   ```

   Then `#include "app_<game>_ids.h"` must be in the copy (`Select-String` / `grep -n
   '_ids.h'`). The test-hook prefix `GAME_` is renamed by Prompt 1's coder.
4. Build the prompt dependency graph (foundational vs cosmetic/isolated).
   *(stepwise)* Present the execution plan and wait.

### Step 2 — Validate prompts
Each prompt is a testable build: a clear Verification section, no dependency on a later
prompt, self-contained instructions. Failures → back to `technical_prompter`.

### Step 3 — The prompt cycle (repeat per prompt)
1. **Brief**: Coding Task JSON with the safety block, platform reminders, standing rules
   and test hooks (`references/AGENT_BRIEFS.md`).
2. **Coder** subagent writes `app_<game>/src/app_<game>.h` (plus `app_metadata.h` /
   `app_save.h` when the prompt adds saves or optional callbacks).
3. **Checks, in parallel**: the Requirements Agent and the Template Agent
   (`cube_verifier`; read-only, code), and the **visual gate**, which you run yourself:
   build the hidden simulator with the test hooks, run it with 24-screen frame dumps,
   LOOK at the frames, write findings (`references/VISUAL_GATE.md`). A build error is a
   critical finding.
4. **Playtest Agent** (`cube_verifier`) when the hidden instance's control socket
   answers (`SIM_MCP.md`): taps, twists, tilts, scored on what it sees. It needs only the
   simulator, so start it as soon as the gate run has ended, while the code reviewers are
   still reading (one simulator at a time; stop it by PID afterwards).
5. **Evaluate.** Pass = Requirements ≥ 90, Template ≥ 90, no unresolved critical
   finding from any check (a critical issue fails its agent whatever the total), no
   critical or major visual finding, Playtest ≥ 90 without a critical issue when
   deployed, and **no open major from any agent**: a 93 with a major (music that never
   stops, art at ±120) is a fix round, not a pass. A major is left open only with a
   reason recorded in the context (`accepted_majors: [{"finding", "reason"}]`) and
   named in the report. Otherwise ONE fixer gets the union of all issues plus the frames that show
   them, then every gate runs again (a fix that satisfies the code reviewers can still
   break the picture). From the second round on the code reviewers re-check against
   their previous report and the fixer's diff (`recheck` in the brief, `cube_verifier`
   "Re-check rounds"); the visual gate and the playtest always run in full.
   **Budget** (measured on a foundation prompt): coder ~12 min, each code reviewer
   6-10 min, playtest 13-20 min, fixer ~20 min; ~1.5 h and ~2M subagent tokens with one
   full fix round. A smaller model for the reviewers did not make them faster. Max **5** fix rounds per prompt, then the failure policy:
   *(stepwise)* ask "rescope / retry / stop?"; autonomous: degrade = rescope the prompt
   (`references/RUN_MODES.md`). Either way the prompt completes only when the gates pass
   on its final scope; it is never marked done with a failing gate.
6. **Save context** (schema in `references/AGENT_BRIEFS.md`): scores, visual verdict and
   frame folder, fix rounds, cuts.
7. **Transition.** Autonomous → next prompt. *(stepwise)* STOP with: what was added, the
   scores, the frames sheet, what nothing could judge (how it sounds, how it feels,
   balance, the real cube); offer the user the visible simulator (theirs to start); wait
   for "дальше / вот баги: … / меняем дизайн / стоп".

**Pipelining** (one game file, so one coder at a time):

| Situation | Decision |
|---|---|
| N+1 does not depend on N's checked code | prepare N+1's brief while N is checked |
| N+1 builds on N, N is being fixed, or N is foundational (scaffold, data, core init) | wait |
| N is cosmetic or isolated (audio, polish, UI text) | its checks may overlap the next brief |
| Any prompt | the next coder starts only after N passed every gate (the visual gate builds from that file) |
| Simulator runs and playtests | never in parallel: one instance, one port |

**Errors and resume.** A coder error → fixer with the error, then the gates. Source and
context disagree → re-read the source, update the context, adapt the remaining prompts.
Resume → read the context, check `last_completed_prompt` against the source, continue
with the next prompt.

### Step 4 — Complete
After the last prompt run one long autoplay gate (50 ms frames; they feed the report and
the video), then Stage 5. A good-looking simulator is not a shippable result: the
simulator runs PC-compiled code, so only Stage 5's verified device `.oct` proves the game
runs on the cube.

## Stage 5 — Delivery

Read `references/DELIVERY.md`. In short:
1. **Ship build**: test hooks off, version patch bumped when the user may have an
   older install, then `scripts/build_device.ps1` / `.sh` writes `dist/app_<game>.oct`
   with the official `octpack-build` (fallback: the pure-Python builder); no simulator
   is involved. Verification is mandatory and done by the script (`pack_beta.py
   --verify-oct` on the header from `octpack-info`, or read locally when `octpack-info`
   is unavailable or fails): ARM code embedded, non-zero build id, the `ico` map, and
   title, version, GUID, categories and save size equal to the app's defines. A
   mismatch, or no way to verify, fails the build. **Required in every mode**; a missing
   ARM toolchain is the one hard stop.
2. **Deliver from `dist/` only.** The stock Windows simulator rewrites
   `app_<game>/app_<game>.oct` whenever it starts with `out/app_<game>.bin` present, so
   that file is never the deliverable; build `dist/` after the session's last simulator
   run.
3. **Upload to the user's cube when they ask**: Windows `<skills>/tools/cube_upload`
   (Bluetooth SPP, hidden), Linux octavios `spptest`. Then tell them to restart the cube
   and give the on-device checklist.
4. Optional, offered in the report: the gameplay video from the hidden frames (ffmpeg,
   made when the user wants it) and, after the first playable build, the balance loop
   (tunables table, autoplay runs, a short loop with the user).

Then the end-of-run report (`references/RUN_MODES.md`).

## Mod mode

### Prime directive — the working project is the source of truth

**Make the smallest change that satisfies the request.** Do not rewrite, refactor,
re-architect, or restructure code, assets, or data beyond what the change strictly
needs. Structural or design-level changes are allowed **only when the user explicitly
asks for them**; in every other case, solve it минимально — "малой кровью". A working
game the user is happy with is far more valuable than a "cleaner" one that now behaves
differently, so when a change *can* be done as a small local edit, it MUST be.

This mode adds no new agents or sub-skills: it reuses `cube_asset-builder` /
`cube_art-director`, the coder/verifier/fixer subagents, the visual gate and
`wowcube-boilerplate` at the smallest scope that does the job.

### M1 — Analyze the target
1. Locate `app_<game>/`. Several games → ask which. Not there → stop and say so.
2. Read the baseline (the source of truth): `src/app_<game>.h`,
   `src/app_<game>_ids.h`, and when present `plans/<game>_assets.json`,
   `plans/<game>_gdd.md`, `assets_<game>/style/`. A hand-dropped project may have only
   the code; that is enough to mod.
3. Run the environment check (entry check 3), then a baseline hidden run
   (`references/VISUAL_GATE.md`): it must build and render. Keep its frames for M5.

### M2 — Classify (the cheapest type that covers the request)

| Type | What | Minimal path |
|---|---|---|
| **T1 Logic / parameters** | speed, timing, balance numbers, small behaviour | one scoped coder task → gates → fixer |
| **T2 Sprite** | replace or add an image | user-supplied → fit to the manifest entry and `art.py qa`; generated → `cube_art-director` for that sprite only, held to the game's style lock (no `assets_<game>/style/` yet → make 2–3 of the game's own sprites the anchors first) → repack → a new `BMP_*` gets one scoped coder edit |
| **T3 Sound** | replace or add a sound | the user's file, or a CC0 source the user approved → `sound_kit.py build` → repack |
| **T4 Structural** | new mechanic, refactor, design change | only when the user explicitly asked; otherwise propose the smallest alternative and ask |

Asset work on an app packed from `plans/<game>_assets.json` edits just that asset's
entry. An app **without** a manifest (hand-made, PSD-authored or from the older
pipeline) never gets a one-entry manifest: `build_pipeline.py pack` rebuilds the whole
`index.bin` and `_ids.h` from the manifest, so every asset missing from it would vanish.
Change the asset in the sources the app is packed from (its PNG folder, PSD layer or
`art/octpack.json` input) and repack with the app's own command
(`<skills>/scripts/repack_app.py` detects it, `wowcube-boilerplate`). A full manifest
covering every asset in `_ids.h` is a T4 change (ask first).

### M3 — Mini-plan
The type, the exact files and assets, why it is minimal. Autonomous: composed and
auto-approved (resources were settled at intake). *(stepwise)* Present it, ask for any
missing resource (Codex login, approval of a sound download), STOP until approved.

### M4 — Execute at minimal scope
Code: one coder subagent whose task is only the requested edit; `prior_context`
describes the existing structures so it extends, never rewrites. Assets:
`cube_asset-builder` for the specific sprite or sound, then its pack step (refreshes
`index.bin`, `art/packed`, `sound/assets`, `_ids.h`).

### M5 — Verify
The Stage 4 gates (90/90 with no critical issue and no open major, the visual gate, Playtest when
available), framed for a mod:
(a) the change is there, (b) nothing else moved compared with the M1 baseline frames
(`no_regressions` weighs most; `gdd_alignment` only when a GDD exists). Fixer max 5
rounds, then the run mode's failure policy. Autonomous: independent mods back to back,
reported once. *(stepwise)* A per-change checkpoint with before/after frames; one mod at
a time, never batched.

### M6 — Repackage and deliver
A mod is not done until the device package is rebuilt: Stage 5 (version patch bump,
`dist/app_<game>.oct`, upload if asked). An older app without `src/app_metadata.h` is
built with the fallback builder; moving it to the dev layout is a T4 change (ask first).

## Configuration

| Setting | Default | Notes |
|---|---|---|
| Verification threshold | 90 | per deployed agent (Requirements, Template, Playtest); any unresolved critical issue fails regardless of score |
| Max fix rounds | 5 | per prompt or mod change |
| Visual gate | always | after every coder and fixer run (`references/VISUAL_GATE.md`) |
| Playtest Agent | when the hidden instance's socket answers | ports from 8177 (`playtest_port`); 8077 stays the user's |
| Run mode | autonomous | stepwise on request; `YOLO` is the compat alias (`references/RUN_MODES.md`) |
| Failure policy (autonomous) | degrade, never abort | degrade = rescope the prompt; the rescoped version must pass every gate; every cut in the final report |
| Art source | Codex on the ChatGPT subscription | then a paid image API if the user configured one, then temporary placeholders |
| Sound source | CC0 recordings (approved list) + `sound_kit.py` | synthesis as the fallback |
| Deliverable | `dist/app_<game>.oct` | `scripts/build_device.*`: `octpack-build`, fallback the pure-Python builder |
| Start from | 1 | the first prompt to run (resume) |
