---
name: wowcube-boilerplate
description: >-
  Use to prepare and verify the build infrastructure for a WowCube game BEFORE
  any implementation begins. Run this right after `technical_prompter` produces
  the prompts file and BEFORE `cube_orchestrator` executes the first prompt.
  It scaffolds the app folder (app_<game>) from the template, renames every
  name-bearing file, packs the art assets, and smoke-builds + launches the
  simulator so the orchestrator never starts coding against broken infra.
  Trigger whenever a prompts file is ready and the app folder does not exist
  yet, when someone says "set up the project", "prepare the boilerplate",
  "scaffold the app", or "make sure it builds before we start coding", or when
  cube_orchestrator reports a missing app_<game> folder / .target / packed assets.
---

# WowCube Boilerplate

Prepare a clean, **verified** build environment for one WowCube game so that the
orchestrator's very first coding prompt lands in a project that already
compiles, packs, and runs in the simulator. Catching a broken toolchain here —
before any game code exists — is far cheaper than discovering it three prompts
into implementation, where it's tangled up with new code.

This skill sits between the planning skills and the implementation skill:

```
cube_game-designer  ->  technical_prompter  ->  [ wowcube-boilerplate ]  ->  cube_orchestrator
   (GDD)                  (prompts.md)            (verified app_<game>/)        (writes code)
```

## When to Use

- `plans/<game>_prompts.md` exists and the `app_<game>/` folder does not yet
- The orchestrator is about to run, but the project hasn't been scaffolded
- `cube_orchestrator` reports a missing prerequisite: no `app_<game>` folder,
  no `*.target`, no `art/packed/*.raw`, or a simulator that won't build/launch
- User says "prepare the project / boilerplate / infra", "scaffold the app",
  or "make sure it builds before we start"

## When NOT to Use

- No prompts file yet — run `technical_prompter` first
- The app folder already exists and the simulator already builds and runs — the
  infra is ready; go straight to `cube_orchestrator`

The infra **gate** verifies the **simulator** build (fast iteration). Producing
the cube-loadable **`.oct`** (the ARM device build) is a separate step this skill
also supports — see "Producing the cube `.oct`" — but it's run at delivery time,
not as part of the pre-implementation gate.

## Expected Workspace Layout

This skill assumes the standard WowCube dev workspace, where the SDK, the skills
repo, and each app are siblings under one root:

```
<workspace>/
├── octavios/                       # SDK: engine/, sim/, apps/build_sim.cmd, utils/
├── OCT_wowcube-agent-skills/       # this skills repo (templates/, scripts/, skills/)
│   └── templates/app_ai_template/  # the template app cloned for each game
└── app_<game>/                     # created BY this skill
    ├── app_<game>.target           # marker; build scripts derive the app name from it
    ├── src/  art/  sound/  bin/
```

If your root differs, pass explicit paths to the script (below).

## Core Procedure

The whole flow is bundled as a script — **prefer running it** over doing the
steps by hand, because the manual path has three easy-to-miss gotchas (see
Gotchas). Drive the script; only fall back to manual steps if the script can't
run (e.g. you need to adapt a path it doesn't expose).

### Step 0: Verify the toolchain is installed

Before scaffolding, confirm the machine has the tools the build needs. Two
targets, two toolchains:

- **Simulator build** (fast PC iteration) needs **MSVC** (Visual Studio C++ tools).
- **Cube `.oct` deliverable** additionally needs the **ARM device toolchain**:
  the ARM GNU embedded compiler, CMake, and Ninja — because the loadable `.oct`
  embeds ARM machine code (see "Producing the cube `.oct`").

Run the bundled check, which installs every missing winget-available tool:

```powershell
powershell -File OCT_wowcube-agent-skills/skills/wowcube-boilerplate/scripts/check_env.ps1
```

It verifies and, where missing, installs **all** of these — so the user is
guaranteed the full toolchain at infra-setup time:

```
# Simulator build (MSVC C++ build tools + Windows 11 SDK), installed unattended:
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override `
  "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools `
   --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended"

# Cube .oct device toolchain:
winget install ARM.GnuArmEmbeddedToolchain   # arm-none-eabi-gcc
winget install Kitware.CMake                 # cmake
winget install Ninja-build.Ninja             # ninja
```

The MSVC install is a large download (several GB) but runs unattended
(`--passive`). Pass `-SkipMsvc` if it's being installed separately. Note: a
freshly installed tool may not appear on `PATH` until a **new shell** is opened —
if a tool reads as missing right after install, re-check in a fresh terminal.
`new_app.ps1` runs this check automatically as its first step (skip with
`-SkipEnvCheck`).

### Step 1: Determine the app name

The orchestrator and prompts use a `<game>` name (e.g. `tetris`). The app folder
is always `app_<game>`. If the name isn't already established by the GDD/prompts
filenames, **ask the user** — this name is baked into the marker file, headers,
asset paths, and the output `.exe`, so getting it right now avoids a rename later.

### Step 2: Run the scaffold-and-verify script

```powershell
powershell -File OCT_wowcube-agent-skills/skills/wowcube-boilerplate/scripts/new_app.ps1 `
    -Name <game> -Workspace <workspace_root> -Run
```

What it does, in order (this is the procedure distilled from real runs):

1. **Clone** `templates/app_ai_template/` → `<workspace>/app_<game>/`
2. **Rename** the `.target` marker and the `app_ai_template.h` / `app_ai_template_ids.h`
   headers to `app_<game>*`
3. **Patch** every embedded reference to the template name in `src/app.h`,
   `src/app_<game>.h`, and `art/!pack.bat` (the `#include`, `APP_DIR`, `APP_PNG`,
   `APP_SND`, and the pack `set app=` line)
4. **Guarantee `APP_VERSION`** is defined in `src/app.h` (the template omits it —
   see Gotchas)
5. **Pack** art assets via `art/!pack.bat` and **sync** the generated
   `app_<game>_ids.h` into `src/` so compiled sprite indices match the packed `.raw` files
6. **Build the simulator** via `octavios/apps/build_sim.cmd` — the MSVC/PC target,
   **never** the ARM build
7. With `-Run`: **launch** the `.exe` for a few seconds and confirm it stays alive
   (a crash here usually means assets weren't packed)

Exit code `0` means **infrastructure verified**. A non-zero exit names the failed
step — fix it (or report it) before handing off to the orchestrator.

Useful switches:
- `-SkipBuild` — scaffold + pack only (e.g. MSVC isn't installed on this machine)
- `-Template <path>` / `-BuildScript <path>` — override autodetected locations

### Step 3: Report readiness and hand off

On success, report to the user what was verified and where:

- `app_<game>/app_<game>.target` (marker)
- `app_<game>/src/app_<game>.h` — **the file the orchestrator will write game code into**
- `app_<game>/art/packed/*.raw` + `pal.raw` (packed assets)
- `app_<game>/bin/app_<game>.exe` (built, launches without crashing)

Then the orchestrator can run its first prompt against a known-good project. The
orchestrator overwrites `src/app_<game>.h` with the game skeleton on its first
prompt — that's expected; this skill's job is to prove the *surrounding* infra
(folder, marker, assets, toolchain) works, not to preserve the demo game.

## Producing the cube `.oct`

The simulator `.exe` is for PC testing. The file you actually load onto the
physical WowCube is **`app_<game>/app_<game>.oct`**. It is assembled by the
**simulator at launch**, which packs the art `.raw` assets + the sounds +
(if present) the ARM device code from `app_<game>/out/app_<game>.bin`. So a
*loadable* `.oct` requires the ARM build to have produced the `.bin` first —
otherwise the `.oct` carries assets only and won't run on the cube.

Two steps, bundled in `scripts/build_device.ps1`:

```powershell
powershell -File OCT_wowcube-agent-skills/skills/wowcube-boilerplate/scripts/build_device.ps1 -AppDir <workspace>/app_<game>
```

1. **ARM device build** → `app_<game>/out/app_<game>.bin`
   (`cmake -G Ninja -S octavios/apps -B out` then `cmake --build out`, run from
   the app folder — this is the ARM target from `octavios/apps/CMakeLists.txt`,
   needing the Step 0 device toolchain)
2. **Pack** → launches the sim once, which writes `app_<game>/app_<game>.oct`
   (assets + sounds + ARM code)

The script fails loudly if the ARM `.bin` is missing, so you never ship an
asset-only `.oct` by accident. This is the final deliverable the orchestrator
points the user to on completion.

## Gotchas (why the script exists)

These are the failures observed when doing this by hand. The script handles all
three; if you ever scaffold manually, watch for them.

1. **`APP_VERSION` is missing from the template's `app.h`.** The simulator's
   `sim.h` only defines a fallback `APP_VERSION` when `SIM_APP_HEADER` is *not*
   set — but the build always sets it, so `app.h` must define `APP_VERSION`
   itself. Without it the build dies with
   `error C2065: 'APP_VERSION': undeclared identifier`. Fix: ensure
   `#define APP_VERSION 100` sits in `src/app.h`.

2. **`!pack.bat` won't launch as a bare name.** The leading `!` means
   `cmd /c "!pack.bat"` fails with "not recognized". Invoke it with an explicit
   path: `cmd /c 'call ".\!pack.bat"'` from inside the `art/` folder. Its legacy
   `del`/`xcopy` lines also print harmless "file not found" noise and return a
   non-zero code on a clean first run — judge success by the packed `.raw` files
   it produces, not by its exit code.

3. **The generated `_ids.h` must be synced into `src/`.** `pack.bat` writes
   `app_<game>_ids.h` next to the art and (via a legacy step) to a stale path,
   but the build compiles against `src/app_<game>_ids.h`. If the packed asset
   order changes and you don't copy the fresh ids header into `src/`, sprite
   indices silently mismatch. Always sync `art/app_<game>_ids.h` → `src/`.

Also remember: the infra **gate uses the simulator build only.**
`octavios/apps/build_sim.cmd` is the PC/MSVC build — that's what proves the
project is ready before coding starts. The ARM device build
(`octavios/apps/CMakeLists.txt`, `arm-none-eabi-gcc`) is reserved for producing
the final cube `.oct` (`build_device.ps1`) — don't run it as part of the
pre-implementation gate, only at delivery.

## Cross-platform note

The simulator build (`build_sim.cmd`, MSVC) and `!pack.bat` are Windows-only.
On non-Windows machines you can still scaffold and pack using the pure-Python
packer at `OCT_wowcube-agent-skills/scripts/pack.py` (`pip install -r
scripts/requirements.txt`), but the simulator build/launch verification requires
Windows + Visual Studio C++ tools. If you can't build, run with `-SkipBuild` and
clearly tell the user the infra was scaffolded but **not** build-verified.
