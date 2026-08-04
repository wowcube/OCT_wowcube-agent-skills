---
name: wowcube-boilerplate
description: >-
  Infrastructure-and-packaging component of the WowCube pipeline, invoked by
  cube_orchestrator — not a standalone user entry point. The orchestrator routes
  here at two points: the infra gate before Stage 4 (scaffold app_<game> from the
  template, pack art, and smoke-build + launch the simulator) and Stage 5 after
  implementation (build the ARM device target and verify the cube-loadable .oct
  embeds the code). Use only when the orchestrator routes here.
---

# WowCube Boilerplate

> **This skill is the infrastructure & packaging component of the `cube_orchestrator` pipeline.** The orchestrator invokes it (via the Skill tool) at two points: the **infra gate** before Stage 4 (scaffold `app_<game>/` and prove the simulator builds and launches) and **Stage 5** after implementation (build the ARM device target and verify the cube `.oct` embeds the code). It is not a user-facing entry point — the user enters through `cube_orchestrator`, which routes here.

Prepare a clean, **verified** build environment for one WowCube game so that the
orchestrator's very first coding prompt lands in a project that already
compiles, packs, and runs in the simulator. Catching a broken toolchain here —
before any game code exists — is far cheaper than discovering it three prompts
into implementation, where it's tangled up with new code.

This component is driven by the master orchestrator, which routes to it at two
points in the pipeline:

```
cube_orchestrator (master controller)
  ├─ Stage 1: cube_game-designer     → GDD
  ├─ Stage 2: technical_prompter     → prompts.md + asset manifest
  ├─ Stage 3: cube_asset-builder     → packed assets
  ├─ infra gate: wowcube-boilerplate → verified app_<game>/     ← THIS SKILL
  ├─ Stage 4: coder/verifier/fixer   → game code (sim-tested)
  └─ Stage 5: wowcube-boilerplate    → verified cube .oct       ← THIS SKILL
```

## Cross-platform: one pack path, two build toolchains

**Asset packing is pure Python on every OS.** The art pipeline runs through the
canonical packer `scripts/pack.py` (PSD→PNG export, BMFont `.fnt` export,
palette build, packed `.raw`/`.pal` emission, kind-aware `_ids.h` generation,
and — with `--beta-app-dir`/`--app-name` — the full beta container: `index.bin`
plus `art/packed/*.raw`+`*.pal` and the launcher icon maps written straight
into the app folder) — it needs only `Pillow`, `numpy`, `pytoshop`,
`psd-tools`. There is **no** `psd.exe`, `utils.exe`, `!pack.bat`, or Wine
anywhere in this flow; those legacy Windows binaries are fully replaced.
Sound assets are synthesized WAVs encoded to beta mp3 (22050 Hz mono CBR 32k,
requires `ffmpeg`) by `scripts/gen_sounds.py`, copied into
`app_<game>/sound/assets/` by the pack step — sounds never ship as WAV.

Only the **simulator/device build** differs by OS, and this skill ships both:

| Step | Windows | Linux |
|------|---------|-------|
| Scaffold + pack + sim build | `scripts/new_app.ps1` | `scripts/new_app.sh` |
| Toolchain check/install | `scripts/check_env.ps1` | `scripts/check_env.sh` |
| Cube `.oct` device build | `scripts/build_device.ps1` | `scripts/build_device.sh` |
| Simulator binary produced | `bin/app_<game>.exe` (MSVC) | `app_<game>/build-sim/octavios_sim` (CMake + SDL3) |

Pick the script matching the host OS. The `.ps1` and `.sh` variants are
behavioural mirrors; the steps below describe both.

## When to Use

- `cube_orchestrator` routed here for the **infra gate** before Stage 4: prompts
  and assets exist, but `app_<game>/` is missing (no `*.target`, no
  `art/packed/*.raw` AND `index.bin`) or the simulator won't build/launch
- `cube_orchestrator` routed here for **Stage 5**: all prompts are implemented
  and there is no verified device `.oct` yet (or it was last touched by a sim run)

Do not trigger this skill directly for "scaffold the app" / "prepare the infra" /
"build for the cube" requests — those are owned by `cube_orchestrator`, which
routes here at the two points above.

## When NOT to Use

- No prompts/assets yet — the orchestrator will route to the earlier stages first
- Infra already verified and not at delivery time — the orchestrator proceeds to
  Stage 4 (implementation)

The infra **gate** verifies the **simulator** build (fast iteration). Producing
the cube-loadable **`.oct`** (the ARM device build) is the separate **Stage 5**
step this skill also performs — see "Producing the cube `.oct`" — run at delivery
time, not as part of the pre-implementation gate.

## Expected Workspace Layout

This skill assumes the standard WowCube dev workspace, where the SDK, the skills
repo, and each app are siblings under one root:

```
<workspace>/
├── octavios/                       # SDK: engine/, sim/, CMakeLists.txt (Linux), apps/build_sim.cmd (Windows), utils/
├── OCT_wowcube-agent-skills/       # this skills repo (templates/, skills/)
│   ├── scripts/pack.py   # the canonical pure-Python packer (all platforms)
│   └── templates/app_ai_template/  # the template app cloned for each game
└── app_<game>/                     # created BY this skill
    ├── app_<game>.target           # marker; build scripts derive the app name from it
    ├── src/  art/  sound/  bin/  build-sim/
```

If your root differs, pass explicit paths to the script (below).

## Core Procedure

The whole flow is bundled as a script — **prefer running it** over doing the
steps by hand, because the manual path has easy-to-miss gotchas (see Gotchas).
Drive the script (`.ps1` on Windows, `.sh` on Linux); only fall back to manual
steps if the script can't run (e.g. you need to adapt a path it doesn't expose).

### Step 0: Verify the toolchain is installed

Before scaffolding, confirm the machine has the tools the build needs. Packing
is Python-only on both OSes; the two build targets need:

- **Simulator build** — Windows: **MSVC** (Visual Studio C++ tools). Linux:
  **CMake ≥ 3.13, gcc/g++ ≥ 12, SDL3** (and `bluez`/`libsystemd` for the BT
  upload path).
- **Cube `.oct` deliverable** additionally needs the **ARM device toolchain** on
  both OSes: the ARM GNU embedded compiler (`arm-none-eabi-gcc`), CMake, and
  Ninja — because the loadable `.oct` embeds ARM machine code (see "Producing
  the cube `.oct`").
- **Packer deps** (both OSes): `pip install Pillow numpy pytoshop psd-tools`.

Run the bundled check, which installs missing tools where it can:

```powershell
# Windows
powershell -File OCT_wowcube-agent-skills/scripts/check_env.ps1
```
```bash
# Linux
bash OCT_wowcube-agent-skills/scripts/check_env.sh
```

On Windows the check installs the winget-available tools unattended:

```
# Simulator build (MSVC C++ build tools + Windows 11 SDK):
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override `
  "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools `
   --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended"
# Cube .oct device toolchain:
winget install ARM.GnuArmEmbeddedToolchain   # arm-none-eabi-gcc
winget install Kitware.CMake                 # cmake
winget install Ninja-build.Ninja             # ninja
```

On Linux it checks for `cmake`, `gcc/g++`, `sdl3`, `bluez`, `libsystemd`,
`arm-none-eabi-gcc`, `ninja`, and the Python packer deps, and prints the distro
install line for whatever's missing (e.g. on Arch:
`sudo pacman -S cmake gcc sdl3 bluez bluez-libs systemd-libs arm-none-eabi-gcc ninja`).

The Windows MSVC install is a large download (several GB) but runs unattended
(`--passive`); pass `-SkipMsvc` if it's being installed separately. Note: a
freshly installed tool may not appear on `PATH` until a **new shell** is opened.
`new_app.*` runs this check automatically as its first step (skip with
`-SkipEnvCheck` / `--skip-env-check`).

### Step 1: Determine the app name

The orchestrator and prompts use a `<game>` name (e.g. `tetris`). The app folder
is always `app_<game>`. If the name isn't already established by the GDD/prompts
filenames, **ask the user** — this name is baked into the marker file, headers,
asset paths, and the output binary, so getting it right now avoids a rename later.

### Step 2: Run the scaffold-and-verify script

```powershell
# Windows
powershell -File OCT_wowcube-agent-skills/scripts/new_app.ps1 `
    -Name <game> -Workspace <workspace_root> -Run
```
```bash
# Linux
bash OCT_wowcube-agent-skills/scripts/new_app.sh \
    --name <game> --workspace <workspace_root> --run
```

What it does, in order (this is the procedure distilled from real runs):

1. **Clone** `templates/app_ai_template/` → `<workspace>/app_<game>/`
2. **Rename** the `.target` marker and the `app_ai_template.h` / `app_ai_template_ids.h`
   headers to `app_<game>*`
3. **Patch** every embedded reference to the template name in `src/app.h` and
   `src/app_<game>.h` (the `#include`, `APP_DIR`)
4. **Guarantee the full beta define set** (`APP_VERSION`, `APP_TITLE`, `APP_GUID1`,
   `APP_CATEGORIES`, `APP_COLORS`) is present in `src/app.h` and `APP_GUID1` is
   randomized — the template already ships all six defines, so this is a
   self-healing backstop (re-adds any that go missing, replaces the template's
   zero placeholder GUID) rather than a required repair; see Gotchas
5. **Pack** art assets with the Python packer — `scripts/pack.py --export
   --build-palette --build-ids --beta-app-dir <AppDir> --app-name
   app_<game>` (plus `--icon art/icon.png` when present) — which writes the
   legacy `art/packed/*.png` intermediates AND the beta container
   (`app_<game>/index.bin`, `art/packed/*.raw`+`*.pal`, launcher icon maps)
   directly into the app folder, and emits `app_<game>_ids.h` straight into
   `src/` (`--ids-output`) so compiled sprite indices match the packed assets
6. **Build the simulator** — Windows: `octavios/apps/build_sim.cmd` (MSVC/PC
   target). Linux: `cmake -S <octavios> -B app_<game>/build-sim -DAPP_DIR=app_<game>`
   then `cmake --build app_<game>/build-sim` → `build-sim/octavios_sim`. **Never**
   the ARM build here.
7. With `-Run` / `--run`: **launch** the simulator for a few seconds and confirm
   it stays alive (a crash here usually means assets weren't packed)

Exit code `0` means **infrastructure verified**. A non-zero exit names the failed
step — fix it (or report it) before handing off to the orchestrator.

Useful switches (both variants): scaffold+pack only (`-SkipBuild` /
`--skip-build`), override the template or build-script locations
(`-Template`/`--template`, `-BuildScript`/`--build-script`).

### Step 3: Report readiness and hand off

On success, report to the user what was verified and where:

- `app_<game>/app_<game>.target` (marker)
- `app_<game>/src/app_<game>.h` — **the file the orchestrator will write game code into**
- `app_<game>/art/packed/*.raw` + `*.pal` (packed assets) and
  `app_<game>/index.bin` (the beta asset index — the gate that actually matters:
  both `*.raw` AND `index.bin` must exist, not `*.raw` alone)
- The built simulator that launches without crashing — `app_<game>/bin/app_<game>.exe`
  (Windows) or `app_<game>/build-sim/octavios_sim` (Linux)

Then **return control to `cube_orchestrator`**, which checkpoints with the user
and runs its first Stage 4 prompt against the known-good project. The orchestrator
overwrites `src/app_<game>.h` with the game skeleton on its first prompt — that's
expected; this skill's job is to prove the *surrounding* infra (folder, marker,
assets, toolchain) works, not to preserve the demo game.

## Producing the cube `.oct` (Stage 5)

The simulator binary is for PC testing. The file you actually load onto the
physical WowCube is **`app_<game>/app_<game>.oct`**. It is assembled by the
**simulator at launch**, which packs the art `.raw` assets + the sounds +
(if present) the ARM device code from `app_<game>/out/app_<game>.bin`.

> **The footgun:** the engine treats the ARM `.bin` as *optional* when packing
> (see `octavios/sim/src/sim.h`: *"it's optional because app running in
> simulator has own code"*). So if you just build and run the simulator, the
> sim still writes an `app_<game>.oct` — but it contains **assets only, no ARM
> code**. That package runs fine on the PC (the sim executes its own compiled
> code) and is **completely dead on the cube**. Worse, the sim **rewrites the
> `.oct` as asset-only on every launch**, so a good package gets clobbered if
> you run the sim again afterward. This is why "it works in the sim" is never
> proof the cube build is done.

The cube `.oct` therefore **must** be produced by the ARM build, and the device
build **must be the last step** — after any simulator testing. Both steps are
bundled in `build_device.ps1` (Windows) / `build_device.sh` (Linux):

```powershell
# Windows
powershell -File OCT_wowcube-agent-skills/scripts/build_device.ps1 -AppDir <workspace>/app_<game>
```
```bash
# Linux
bash OCT_wowcube-agent-skills/scripts/build_device.sh --app-dir <workspace>/app_<game>
```

1. **ARM device build** → `app_<game>/out/app_<game>.bin`
   (`cmake -G Ninja -S octavios/apps -B out` then `cmake --build out`, run from
   the app folder — this is the ARM target from `octavios/apps/CMakeLists.txt`,
   needing the Step 0 device toolchain). Fails if the `.bin` is missing or empty.
2. **Pack** → launches the sim once, which writes `app_<game>/app_<game>.oct`
   (assets + sounds + ARM code).
3. **Verify** → confirms the ARM code is actually embedded in the `.oct` (the
   final `.bin`-sized bytes of the pack must match the `.bin` byte-for-byte). It
   fails loudly on an asset-only pack, so you can never ship a `.oct` that would
   silently die on the cube.
4. **Warn** → both `build_device.ps1` and `build_device.sh` flag any stray
   timestamped `<app>_*.oct` files sitting in the app root. The **Linux**
   simulator deletes root `.oct` files at startup, so a leftover
   `app_<game>_20250101.oct` can silently vanish the next time anyone runs the
   sim (Linux or Windows dev machine, doesn't matter where it was created) —
   this is a warning only, not a failure, but keep deliverables named
   `app_<game>.oct` (no timestamp suffix) to avoid losing them.

This is the final deliverable the orchestrator runs (mandatorily) as **Stage 5**
on completion. After it exits 0, return control to `cube_orchestrator`, which
checkpoints with the user and reports the absolute path to the verified `.oct`.

## Gotchas (why the script exists)

These are the failures observed when doing this by hand. The scripts handle them;
if you ever scaffold manually, watch for them.

1. **`app.h` must define `APP_VERSION` itself.** The simulator's `sim.h` only
   defines a fallback `APP_VERSION` when `SIM_APP_HEADER` is *not* set — but the
   build always sets it, so a hand-rolled `app.h` missing the define dies with
   `error C2065: 'APP_VERSION': undeclared identifier`. The shipped template
   already includes `#define APP_VERSION 100`; this is called out because the
   scaffolder's step 4 guarantee exists specifically to catch it if a manual
   edit ever drops it, not because the template ships broken.

2. **Pack before you build.** The packer (`scripts/pack.py
   --beta-app-dir <AppDir> --app-name app_<game>`) must run first so
   `art/packed/*.raw` AND `index.bin` exist — the simulator loads the beta
   container at launch and a missing pack shows up as an early crash, not a
   compile error. Judge pack success by **both** the `art/packed/*.raw` files
   produced AND `index.bin` existing (and the `_ids.h` written), not by
   console noise — `*.raw` alone is not a complete pack.

3. **The generated `_ids.h` must be synced into `src/`.** The packer writes
   `app_<game>_ids.h`, but the build compiles against `src/app_<game>_ids.h`. If
   the packed asset order changes and the fresh ids header isn't copied into
   `src/`, sprite indices silently mismatch. The scripts pass
   `--ids-output src/app_<game>_ids.h` so it lands in the right place directly;
   if you pack by hand, always sync it.

Also remember: the infra **gate uses the simulator build only.** The ARM device
build (`octavios/apps/CMakeLists.txt`, `arm-none-eabi-gcc`) is reserved for
producing the final cube `.oct` (`build_device.*`) — don't run it as part of the
pre-implementation gate, only at delivery.

## Manual pack command (both platforms)

If you must pack by hand, run from the app folder:

```bash
python <workspace>/OCT_wowcube-agent-skills/scripts/pack.py \
    --export --build-palette --build-ids \
    --art-dir art --exported-dir art/exported \
    --packed-dir art/packed --output-dir art/packed \
    --ids-output src/app_<game>_ids.h --assets assets \
    --beta-app-dir . --app-name app_<game> --icon art/icon.png
```

This is exactly what `new_app.ps1`/`new_app.sh` run (from inside the app
folder, so `--beta-app-dir .`) — drop `--icon art/icon.png` if the app has no
launcher icon yet. It exports `art/assets.psd` and the `*.fnt` fonts to PNGs,
builds the palette, writes the legacy `art/packed/*.png` intermediates,
generates `src/app_<game>_ids.h`, and — because `--beta-app-dir` is set — also
emits the beta container the simulator/`.oct` actually load: `index.bin`,
`art/packed/*.raw`+`*.pal`, and the launcher icon maps. `--emit-raw` (with
`--raw-dir`) is legacy-optional: it writes legacy-format `.raw` files that only
the pre-beta Linux sim reads — the beta sim never does — and if combined with
`--beta-app-dir` into the same folder, the beta `.raw` files overwrite the
legacy ones. Add `--manifest
plans/<game>_assets.json` if any sprite uses `color: "full"` (so it gets
RAW565-encoded instead of run through the palette codec) or carries flags
like `fullsize` (so they reach the packed palette-sprite header). Identical on Windows
and Linux — Python only, no `.exe`/`.bat`/Wine.

**Packing plain-PNG palette sprites by hand (no PSD): drop `--export`, keep
`--build-palette`.** `--export` exists solely to regenerate the exported dir
from PSD/FNT *sources* in `--art-dir` — as its first act it DELETES every
pre-placed PNG in `--exported-dir` (it warns loudly and the pack then fails
with exit 1, but the PNGs are already gone). If your sprites are plain PNGs
(the AI-asset workflow — nothing was ever authored in Photoshop), put one
`<name>.png` per sprite in `--exported-dir` and run the same command WITHOUT
`--export`:

```bash
python <workspace>/OCT_wowcube-agent-skills/scripts/pack.py \
    --build-palette --build-ids \
    --art-dir art --exported-dir art/exported \
    --packed-dir art/packed --output-dir art/packed \
    --ids-output src/app_<game>_ids.h --assets assets \
    --beta-app-dir . --app-name app_<game> \
    --manifest plans/<game>_assets.json --icon art/icon.png
```

(That said, the normal PNG route is not this manual command at all — it is
`build_pipeline.py pack`, which takes the PNGs from `<workspace>/art/`,
atlases them into a throwaway PSD internally, and runs `pack.py` itself; see
`cube_asset-builder` Step 4.)
