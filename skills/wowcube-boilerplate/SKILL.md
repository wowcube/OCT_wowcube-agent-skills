---
name: wowcube-boilerplate
description: >-
  Infrastructure-and-packaging component of the WowCube pipeline, invoked by
  cube_orchestrator — not a standalone user entry point. The orchestrator routes
  here at two points: the infra gate (scaffold app_<game> from the template in the
  octavios dev layout, pack the template art, build the hidden simulator and look
  at a hidden 24-screen dump) and Stage 5 after implementation (build the device
  .oct with octpack-build into dist/, verify it, and upload it to the user's cube
  when they ask). Use only when the orchestrator routes here.
---

# WowCube Boilerplate

> **This skill is the infrastructure & packaging component of the `cube_orchestrator` pipeline.** The orchestrator invokes it at two points: the **infra gate** (scaffold `app_<game>/` and prove the hidden simulator builds and renders) and **Stage 5** (build, verify and, on request, upload the cube `.oct`). It is not a user-facing entry point.

Prepare a verified build environment for one game, so the first coding prompt lands
in a project that already packs, compiles and renders; and at the end turn the
finished game into a verified `.oct` on the user's cube. A broken toolchain found
here costs minutes; found three prompts into implementation it is tangled up with
new code.

```
cube_orchestrator (master controller)
  ├─ Stage 1: cube_game-designer      → GDD
  ├─ Stage 2: technical_prompter      → prompts + asset manifest
  ├─ infra gate: wowcube-boilerplate  → app_<game>/ (dev layout), hidden simulator proven   ← THIS SKILL
  ├─ Stage 3: cube_asset-builder      → packed assets (the pack writes into app_<game>/)
  ├─ Stage 4: coder/verifier/fixer    → game code, visual gate after every prompt
  └─ Stage 5: wowcube-boilerplate     → dist/app_<game>.oct, verified; upload on request    ← THIS SKILL
```

## Safety (hard rules)

`skills/cube_orchestrator/references/AGENT_SAFETY.md` binds every step here. In short:

- **No window over the user's screen, no audio.** The agent starts a simulator only
  through `tools/sim_headless` (Windows: window never shown, killed by PID if one
  ever becomes visible, no audio device) or on a virtual display with audio off
  (Linux). The visible simulator is built for the user and started by the user.
- **No global input** (SendInput, keybd_event, SetForegroundWindow); the simulator is
  driven only through its control socket or the game's test hooks.
- **Kill only by PID**, only processes you started.
- **Installs and downloads only after the user agreed, as one approval**: the toolchain
  installs (`check_env.ps1 -Install`: quiet winget installs, no installer windows;
  Linux: the distro package manager or pipx, never `curl … | sh`), the first `uv` run of
  the SDK packer (it downloads its pinned Python packages once into `<ws>/.uv_octpack_venv`,
  never inside octavios) and a newer octavios are asked for together in the
  orchestrator's environment message (`AGENT_SAFETY.md`); afterwards the checks and
  builds use what is installed.
- **Upload only when the user asked, only to the cube they named.** Pairing is theirs.
- No commits, pushes or messages unless asked.

## Minimum SDK and workspace

**octavios dev ≥ 609d5ae (2026-10-21).** It brings `src/app_metadata.h` +
`OCT_APP_SEMVER`, `octpack-build`, the 6-voice mixer with `SND_play_quad` /
`SND_set_mixer`, the save API, `OCT_tap_source` and the simulator's MCP socket. The
dev simulator also needs **wowcube/telemetry checked out next to octavios**. Check
with `scripts/check_env.*` (or `templates/app_ai_template/API.md` → Minimum SDK); if
the SDK is older, the user updates it (`git -C <ws>/octavios pull --ff-only origin dev`,
then delete every `app_*/out` and `app_*/build-sim`, whose CMake caches point at the
old checkout). Never patch octavios.

```
<ws>/                                  keep this path short (Python and cl.exe fail past 260 chars)
├── octavios/       telemetry/         SDK + the telemetry library the simulator links
├── plans/          assets_<game>/     GDD, prompts, manifest / per-game art and sound workspace
├── app_<game>/                        created HERE: <app>.target, src/, art/, sound/, index.bin, out/
├── dist/                              the deliverable: dist/app_<game>.oct
├── .sim_headless/  .cube_upload/      work folders of the repo's tools (snapshots, exes, logs, frames)
└── <skills>/                          this plugin: scripts/, tools/, templates/, skills/
```

| Step | Windows | Linux |
|---|---|---|
| Toolchain report | `scripts/check_env.ps1` | `scripts/check_env.sh` |
| Scaffold + pack + simulator build (+ hidden smoke run) | `scripts/new_app.ps1` | `scripts/new_app.sh` |
| Hidden simulator for agent checks | `tools/sim_headless/build.ps1`, `run.ps1`, `mcp.ps1` | `build-sim/octavios_sim` on a virtual display (`cube_orchestrator/references/VISUAL_GATE.md`) |
| Simulator for the user to play | `tools/sim_headless/build.ps1 -Visible` | `app_<game>/build-sim/octavios_sim` |
| Device `.oct` | `scripts/build_device.ps1` | `scripts/build_device.sh` |
| Repack + version bump + device build | `scripts/repack_app.py` | same |
| Upload to the cube | `tools/cube_upload/run_upload.ps1` | octavios `spptest` |

## When to use

- Infra gate: no `app_<game>/` in the dev layout yet (one `.target`, `src/app_metadata.h`),
  or the toolchain or the app folder is in doubt.
- Stage 5: every prompt passed its gates and there is no verified `dist/app_<game>.oct`
  of the current source; or a mod or repack needs a new device build; or the user asks
  for an upload.

Not for game code (Stage 4) or asset generation (Stage 3).

## Infra gate

### Step 0: toolchain report

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\scripts\check_env.ps1 -Octavios <ws>\octavios
```
```bash
bash <skills>/scripts/check_env.sh --octavios <ws>/octavios
```

It reports, and changes nothing: octavios dev (`engine/oct_app_version.h`,
`octpacker/`, `tools/mcp/`, `sim/src/sim_mcp.h`, `tools/new_app.*`; a git checkout must
contain 609d5ae), telemetry next to octavios, `uv` and a uv-managed Python 3.12,
clang++ or g++ (octpack compiles small probes; MSVC `cl` is not enough), CMake, Ninja,
`arm-none-eabi-g++`, MSVC (Windows simulator), python with Pillow/numpy/pytoshop/psd-tools,
ffmpeg (sound encoding); for information the Codex CLI login (image generation) and
long-path risk. Linux adds SDL3, BlueZ, libsystemd and `xvfb-run` (hidden smoke runs).
Exit 0 = ready, 2 = something missing (the line says how to fix it).
`check_env.ps1 -Install` runs quiet winget installs (no installer windows) for the
missing tools (uv, LLVM, CMake, Ninja, Arm GNU toolchain, FFmpeg, VS 2022 Build Tools,
several GB): only after the user agreed (the one-time environment approval). A fresh
install needs a new shell before it is on PATH. `check_env.sh` installs nothing: it
prints the distro package line (pipx or the package manager for Python tools such as
`uv`), never a download piped into a shell.

### Step 1: the app name

`app_<game>`, lowercase letters, digits and `_` (the SDK requires 3 lowercase letters,
`_`, then `[A-Za-z0-9_]`). Take `<game>` from the plans' file names; ask if it is not
settled: it is baked into the marker, headers, ids and outputs.

### Step 2: scaffold, pack, build, hidden smoke run

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\scripts\new_app.ps1 -Name <game> -Workspace <ws> -Smoke [-WithSave] [-Title "<Title>"]
```
```bash
bash <skills>/scripts/new_app.sh --name <game> --workspace <ws> --smoke [--with-save] [--title "<Title>"]
```

What it does, in order:

1. Toolchain report (Step 0; installs nothing).
2. Copies `templates/app_ai_template` to `<ws>/app_<game>`, renames the marker and the
   `app_ai_template*` headers, replaces the template name in every text file (`APP_DIR`,
   includes). A template `art/octpack.json`, if any, is set aside: AI-art apps are packed
   by the repo's python packer.
3. **Dev metadata** in `src/app_metadata.h`: a **random non-zero `APP_GUID1`** (the game's
   permanent identity), `APP_TITLE` from the name (`app_my_game` → "My Game") or
   `-Title`, `APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, MINOR, PATCH)`. `src/app.h`
   includes `app_metadata.h` first and defines none of its macros. `-WithSave` enables
   `src/app_save.h` (the save area, `APP_SAVE_SIZE`) with a `SAVE_MAGIC` from the name.
   `SIM_SINGLE_THREAD` is never defined (it would run the app on one module only and hide
   lockstep bugs). An old-layout template is migrated (defines moved out of `app.h`).
4. **Pack** with `scripts/pack.py` (beta container): fonts are staged into `art/fonts/`
   first, then `index.bin`, `art/packed/*.raw|*.pal`, `src/app_<game>_ids.h` and the
   launcher map `ico` from `art/icon.png`. It fails without `.raw` files, `index.bin`, the
   `ico` map, or the `BMP_font_*` glyphs (without them every label draws nothing).
5. **Builds the hidden simulator** (Windows: `tools/sim_headless/build.ps1`, MSVC, the
   telemetry library, 10-60 s; Linux: `cmake -S octavios -B app_<game>/build-sim
   -DAPP_DIR=app_<game>`). This proves the toolchain and that the app compiles.
   `-VisibleSim` also builds the user's playable simulator; nothing is started.
6. **`-Smoke` / `--smoke`**: one hidden, silent run of 15 s (`-SmokeSeconds`) with a PNG
   of all 24 screens every second (Windows: `tools/sim_headless/run.ps1`, which polls
   the windows every 50 ms, kills by PID if one is visible, and exits non-zero unless the
   timed run completed and wrote its summary; Linux: `xvfb-run -a`, `sound_muted=1`, SDL
   dummy audio, one MCP `screens faces` dump). Without `xvfb-run` the Linux smoke run is
   skipped and says so. `-Run` / `--run` are the old names of this switch; they never
   open a window any more.

Exit 0 = infrastructure verified. A non-zero exit names the failed step: retry that
step alone (below), or report it, before Stage 3 packs into the folder.

Other switches: `-SkipBuild` (scaffold + pack only), `-SkipEnvCheck`, `-Octavios`,
`-Template`.

### Step 3: look at the frames (this is the gate)

Open the last frames the run printed (Read tool; Windows:
`<ws>/.sim_headless/app_<game>/frames/<time>/frame_*.png`, the six faces as an unfolded
cross: TOP above FRONT; LEFT, FRONT, RIGHT, BACK in a row; BOTTOM below; Linux:
`<ws>/.sim_headless/app_<game>_linux/smoke_faces.png`). The dev simulator first shows
white tiles, dark screens and the engine's eyes intro on the face that is up (about
5 s); judge the frames after it. The template starts in **Demo 0**, which draws exactly
this:

| Where | Expected |
|---|---|
| TOP, all 4 screens | the template's pink "2" tile, centred on each screen |
| FRONT, 1 screen of its top row | the same tile; about a second after the demo starts it hops to the neighbouring top-row screen, so either one is right |
| the other 19 screens | plain black (the template's `OCT_background(0x0000)`): correct here, not a failure |

Pass when:

- `max_visible=0` was printed (no window ever appeared) and the run ended by itself
  (exit 0);
- the five tiles are there, whole, centred and clean: no garbage, no flat magenta (key
  colour) screen, no fringes or offsets, no black bar or cross across a tile's screen;
  the other 19 screens plain black;
- the last frames no longer show the intro (the app started).

Demo 0 draws no text: the fonts are checked by the pack step (it fails without
`BMP_font_*` glyphs in the ids header), not on these frames. A failure is fixed before
Stage 3. If the smoke run cannot happen (an SDK older than dev, Linux without
`xvfb-run`), record `not_checked_visually`, say so, and never fall back to a visible run.
Record `infra: "ok"` in the context only after you looked.

### Retrying a failed step (existing app)

`new_app` creates the folder once. When a later step failed (pack, simulator build,
smoke run), fix the cause and rerun **only that step** on the existing `app_<game>/`.
Never run `new_app` on it again: it refuses an existing folder, and a second scaffold
would mint a new `APP_GUID1` (the game's permanent identity). Only when `new_app` failed
before it wrote `src/app_metadata.h` (nothing to keep yet) is the half-made folder moved
aside (renamed, e.g. `app_<game>.failed`; never deleted) and `new_app` run again.

**Pack** (the template art; fonts staged into `art/fonts/` first, as `new_app` does):

```powershell
New-Item -ItemType Directory -Force <ws>\app_<game>\art\fonts | Out-Null
Copy-Item <ws>\app_<game>\art\font_* <ws>\app_<game>\art\fonts\ -Force
cd <ws>\app_<game>
python <skills>\scripts\pack.py --export --build-palette --build-ids --art-dir art --exported-dir art\exported --packed-dir art\packed --output-dir art\packed --ids-output src\app_<game>_ids.h --assets assets --beta-app-dir <ws>\app_<game> --app-name app_<game> --icon <ws>\app_<game>\art\icon.png
```
```bash
mkdir -p <ws>/app_<game>/art/fonts && cp -f <ws>/app_<game>/art/font_* <ws>/app_<game>/art/fonts/
cd <ws>/app_<game> && python3 <skills>/scripts/pack.py --export --build-palette --build-ids --art-dir art --exported-dir art/exported --packed-dir art/packed --output-dir art/packed --ids-output src/app_<game>_ids.h --assets assets --beta-app-dir <ws>/app_<game> --app-name app_<game> --icon <ws>/app_<game>/art/icon.png
```

Then check what `new_app` checks: `.raw` files in `art/packed/`, `index.bin` with the
`ico` map, `BMP_font_*` glyphs in `src/app_<game>_ids.h`.

**Simulator build**: `powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\build.ps1 -AppDir <ws>\app_<game> -Octavios <ws>\octavios`;
Linux `cmake -S <ws>/octavios -B <ws>/app_<game>/build-sim -DAPP_DIR=<ws>/app_<game>` then
`cmake --build <ws>/app_<game>/build-sim -j 4 --target octavios_sim` (after switching
octavios checkouts delete `out/` and `build-sim/` first, gotcha 7).

**Smoke run**: `powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\run.ps1 -AppDir <ws>\app_<game> -Seconds 15 -EveryMs 1000 -FreshSaves`;
Linux: the script in `cube_orchestrator/references/VISUAL_GATE.md` "Linux" on the
existing `build-sim` (skip its two cmake lines and the `-D` flags) with
`record 5 1000 ...`. Then Step 3.

### Step 4: report and hand off

Tell the orchestrator (and, in stepwise mode, the user): `app_<game>/app_<game>.target`;
`src/app_metadata.h` (GUID, title, version); `src/app_<game>.h` (where the game code
goes; the first prompt replaces the template demo); `index.bin` + `art/packed`; the
simulator exe; the frame folder you looked at. Then return to `cube_orchestrator`.

### Gotchas (why the script exists)

1. **The pack-header defines live only in `src/app_metadata.h`.** octpack-build compiles
   it alone with a host compiler, so it may include only `oct_app_version.h`,
   `oct_app_categories.h` and `app_save.h`. A second, different definition in `app.h`
   fails the `-Werror` ARM build.
2. **`APP_GUID1` is random per game and never changes after the first install**: an
   install replaces any pack with the same GUID and the save area is keyed by it.
3. **Pack before building**: the simulator loads `index.bin` + `art/packed` at start-up and
   the code compiles against `src/app_<game>_ids.h`; all three come from one pack.
4. **Fonts are packed only from `art/fonts/`** (scaffold) or `assets_<game>/fonts/`
   (Stage 3); otherwise labels silently draw nothing.
5. **The stock `octavios/apps/build_sim.cmd` cannot build the Windows simulator at
   609d5ae**: `engine/oct_mp3.h` uses `__attribute__((noinline))`, which MSVC rejects
   (C2065). `tools/sim_headless` fixes that line in its own engine copy (and skips the fix
   once upstream has it); use it for agent checks and `-Visible` for the user.
6. **The stock Windows simulator rewrites `app_<game>/app_<game>.oct` at every start**
   (and deletes it without `out/app_<game>.bin`). The deliverable is only ever
   `dist/app_<game>.oct`. The hidden tool writes no `.oct`.
7. **After switching octavios checkouts** delete `app_<game>/out` and `build-sim`.

## The hidden simulator (agent checks)

Used by the visual gate after every prompt and by the Playtest Agent; the procedure and
what to look for are in `cube_orchestrator/references/VISUAL_GATE.md`, the tool's details
in `tools/sim_headless/README.md`.

```powershell
# build from a snapshot of the app with test hooks on (the real app keeps them off)
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\build.ps1 -AppDir <ws>\app_<game> -Define <GAME>_DEBUG_AUTOPLAY=1,<GAME>_MUTE=1
# hidden run: PNG of the 24 screens every 500 ms for 20 s
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\run.ps1 -AppDir <ws>\app_<game> -Seconds 20 -EveryMs 500 -OutDir <ws>\assets_<game>\qa\sim\p03-1
```

- Test hooks (exact names, `#ifndef`-guarded in the game header): `<GAME>_DEBUG_AUTOPLAY`
  (default 0), `<GAME>_MUTE` (default 0), `<GAME>_DEBUG_ROOM_PLANE` (default -1; 0..5 pins the
  playfield to a face). `-Define` rewrites the snapshot's `#define` lines or passes `/D`.
- `run.ps1` exits 0 only when the timed run completed and wrote its summary, no window
  ever visible; 1 usage/setup error, 2 a window became visible (killed), 3 did not end in
  time, 4 no frames, 5 crashed (`headless_crash.txt`), 6 the app changed after the build
  (rebuild), 7 ended before its time without a summary (an early exit or a kill). Only
  exit 0 counts as a run.
- MCP on the hidden instance (playtests): build a separate binary with autoplay off, plane
  pin -1 and mute on (`build.ps1 ... -WorkDir <ws>\.sim_headless\app_<game>_play -Define
  <GAME>_DEBUG_AUTOPLAY=0,<GAME>_DEBUG_ROOM_PLANE=-1,<GAME>_MUTE=1`), start it in the
  background with `run.ps1 ... -WorkDir <same> -Seconds 300 -EveryMs 0 -McpPort 8177
  -AllowEarlyStop` (you stop it by PID when done; crashes and visible windows still fail);
  `run_info.json` in its out folder
  carries `pid` and `mcp_port`; drive it with
  `tools/sim_headless/mcp.ps1 -Port <port> "screens faces <abs.png>" "twist 3"` or the
  octavios bridge (`cube_orchestrator/SIM_MCP.md`); stop it with `tools\sim_headless\stop.ps1 -RunInfo <out dir>\run_info.json` (never a bare `Stop-Process -Id`).
  Procedure: `cube_orchestrator/references/VISUAL_GATE.md` "Playtest Agent".
- Capture with `screens faces` / `record` (byte-exact framebuffers); `shot` reads the
  window's back buffer.

## Stage 5: device .oct, upload, on-device check

### Step 1: ship-build checklist

`cube_orchestrator/references/DELIVERY.md` §1: last visual gate passed on the final
source; test hooks at their defaults in the real header; the launcher icon is the
game's (`art/icon.png` is not the template's); the pack is current
(`build_pipeline.py pack-status ...` exits 0 for a manifest app); `APP_VERSION_PATCH`
bumped for any build the user may have installed; `APP_GUID1` unchanged since the first
install.

### Step 2: build and verify (no simulator)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\scripts\build_device.ps1 -AppDir <ws>\app_<game> [-Builder auto|octpack|python] [-Out <path>.oct]
```
```bash
bash <skills>/scripts/build_device.sh --app-dir <ws>/app_<game> [--builder auto|octpack|python] [--out <path>.oct]
```

- **`auto` (default) uses the SDK's official build when it can** (octavios dev,
  `src/app_metadata.h`, `uv`):
  `uv run --frozen --project <ws>/octavios/octpacker octpack-build <ws>/app_<game> --out <ws>/dist/app_<game>.oct --engine <ws>/octavios`.
  It compiles `app_metadata.h` for the header (title, GUID, semver, categories, colours,
  save size, build id from the ELF), packs `art/octpack.json` if present, builds the ARM
  module (`cmake -G Ninja -S octavios/apps -B app_<game>/out -DAPP_TELEMETRY=OFF`) and
  writes the `.oct`. An AI-art app has **no** `art/octpack.json`: the art Stage 3 packed
  (`index.bin`, `art/packed`, `sound/assets`) goes in as it is. The first `uv` run creates
  octpacker's environment in `<ws>/.uv_octpack_venv` (`build_device` sets `UV_PROJECT_ENVIRONMENT`; `-UvEnv` /
  `--uv-env` picks another; never inside octavios) and downloads the packer's pinned packages once.
- **`python` (fallback)**: the same ARM build, then `scripts/pack_beta.py --build-oct`. It
  stamps the save size (header offset 184) from `APP_SAVE_SIZE` reached through
  `src/app_metadata.h` (`sizeof(record)` is read from `app_save.h`'s static_assert of the
  wire size, so keep that assert). For an app without saves its output was byte-identical
  to octpack-build's in our validation.
- **Verification is mandatory** (both builders; the script fails on any mismatch and also
  when it cannot verify): the `.oct` ends with the bytes of `out/app_<game>.bin` (the ARM
  code is in it); then `scripts/pack_beta.py --verify-oct` checks the header, taken from
  `octpack-info` when it runs and otherwise read locally from the `.oct`: magic, size,
  CRC32, `code_size` and offset, a non-zero build id, title, version, GUID, categories and
  save size equal to the app's defines (`src/app.h` → `app_metadata.h` → `app_save.h`), a
  MAP asset named `ico` (the launcher finds the icon only through it), and the asset list
  equal to `index.bin`. There is no "checks skipped" outcome: unverified means failed
  (python must be on PATH).
- **Only `dist/` is delivered**, never `app_<game>/app_<game>.oct`. Build it after the
  last simulator run of the session.
- A missing ARM toolchain or a failed verification is a hard stop: fix the environment
  (Step 0), never ship a simulator-written `.oct`.

### Repacking after asset or code changes: `repack_app.py`

```bash
python <skills>/scripts/repack_app.py --app-dir <ws>/app_<game> [--skip-device] [--builder auto|octpack|python] [--out <path>.oct]
```

One command for "I changed the art/code, rebuild": it re-runs the app's own pack command,
detected from disk in this order: `app_<game>/art/octpack.json` (PSD-authored art) → the
SDK's official `uv run --project <ws>/octavios/octpacker octpack-pack <app>`;
`<ws>/assets_<game>/art/*.png` → the asset stage's `build_pipeline.py pack --workspace
assets_<game>` from `<ws>` (manifest from `<ws>/plans/<game>_assets.json`; it refuses an
incomplete set and refreshes `.pack_inputs.json`); an app-local `assets/art/` → the older
pipeline command; otherwise the scaffold's `pack.py` call (fonts staged into
`art/fonts/`). Then it
**bumps the patch version**: `APP_VERSION_PATCH` in `src/app_metadata.h`, else a literal
`OCT_APP_SEMVER(a, b, c)`, else a legacy integer `APP_VERSION` (+1; a patch of 255 needs a
manual minor bump). Then, unless `--skip-device`, it runs `build_device` into
`dist/app_<game>.oct` and prints the path and `major.minor.patch`. The cube compares
versions on install, so an un-bumped rebuild may not replace the installed one.

### Step 3: upload (only when the user asked)

Before: the cube is paired in the system's Bluetooth settings (the user does that), on
and awake; you know its Bluetooth name and the MAC of its **module 0** (the only one
discoverable over SPP). Windows, a paired cube's MAC:
`Get-PnpDevice -Class Bluetooth | Where-Object FriendlyName -like 'Wow*' | Select-Object FriendlyName, InstanceId`
(the 12 hex digits after `DEV_`; check them on the device's properties page).

**Windows**: `tools/cube_upload` (a patched copy of the simulator: no window, no sound,
SOFTWARE upload over SPP with the long chunk timeout for packs over 64 KB, result logged,
exits; builds itself on first use, about a minute):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\cube_upload\run_upload.ps1 -Octavios <ws>\octavios -Mac <AA:BB:CC:DD:EE:FF> -Oct <ws>\dist\app_<game>.oct -Name "<cube name>"
```

| Exit | Meaning | Do |
|---|---|---|
| 0 | uploaded | reboot note, checklist |
| 10 | the cube refused it (CRC, flash, validation) | read the RESULT line; rebuild the `.oct` |
| 11 | stopped part-way (e.g. stalled at the first chunk) | rerun once; failing again → the user reboots the cube, then rerun |
| 12 | no SPP link within 60 s | paired? on, awake, in range? MAC of module 0? |
| 2 / 3 / 13 | window became visible (killed) / timeout / no result | report with `<ws>/.cube_upload/bin/log_1.txt`; never retry visibly |

About 46 KB/s: a 0.5 MB pack takes 10-15 s plus 3 s of settling before and after. Details
and the stalled-chunk history: `tools/cube_upload/README.md`.

**Linux**: octavios' `spptest` (BlueZ; WSL has no Bluetooth):
`cmake -S <ws>/octavios -B <ws>/octavios/build && cmake --build <ws>/octavios/build --target spptest`, then
`<ws>/octavios/build/spptest --mac AA:BB:CC:DD:EE:FF --software <ws>/dist/app_<game>.oct --long-timeout`.

**Manual fallback, done by the user** (the agent never presses keys): in their visible
simulator Shift+C picks the cube (1-9), Shift+S picks `dist/app_<game>.oct`; holding
Right-Ctrl while confirming gives the long chunk timeout.

### Step 4: reboot note and on-device checklist

Tell the user: **restart the cube after the upload** if the game does not appear in the
launcher or the next upload cannot connect (octavios `BLUETOOTH.md`: the next SPP
connection after an upload often fails until a reboot; the owner reboots after every
upload). Then give them the on-device checklist (`DELIVERY.md` §4): the icon and title in
the launcher; taps on each face (and per screen where designed), twists both ways, half
twists ignored, tilt; music and effects together and positional sounds from the right
place (the simulator plays only module 0, so the cube is the first real test of the mix);
HUD upright on the side faces; animations smooth; saves survive a shake to the launcher
and a relaunch; idle pause after ~60 s; five minutes without a freeze.

### Step 5: report

The absolute `dist/app_<game>.oct` path, its size and version, the builder used, the
verification lines, and the upload result if there was one. Then return to
`cube_orchestrator`.

## PSD-authored art (human artists): octpacker

For art made in Photoshop the SDK's own packer is the official path: `art/octpack.json`
lists fonts, asset PSDs, map PSDs (an `ico` map for the launcher) and `raw` PNG folders;
`art/!pack.txt` holds the palette groups and their tokens (`<FULLSIZE>`, `<ARGB>`,
`<SOFTKEY>`, `<HALF>` ...). `uv run --project <ws>/octavios/octpacker octpack-pack <app>`
packs it (sound sources in `sound/*.wav|mp3` are converted too), and `octpack-build`
re-packs it at Stage 5. The shape to copy is `octavios/app_template`; the team's
Confluence page "Migrating a game to octpack" covers porting an older app. No adapter from
the AI manifest to `octpack.json` exists (open item); AI-manifest apps stay on
`build_pipeline.py pack`.

## Legacy apps on the repo's python packer

Hand-authored apps ported from `psd.exe` + `utils.exe` can still be packed by
`scripts/pack.py` (it reproduces the legacy tools' output; measurements in
`docs/history/part3-parity-report.md`):

- **`art/!pack.txt`** is auto-detected: one palette per block at exactly the declared size
  (symbol bitness `ceil(log2(size))`), the block's tags (`<FULLSIZE> <ALPHA> <OPAQUE> <ADD>
  <BG> <BUMP> <DUDV> <REFL>`) OR'd into every member's header. `<ALPHA>` lowers the
  anti-aliasing threshold to zero instead of forcing the bit; `<OPAQUE>` is the only
  unconditional override (§12.3 of the parity report). `--pack-config <path>` points
  elsewhere, `--no-pack-config` opts out.
- **`art/!pack.bat` wins over filename heuristics**: it names the PSDs that are exported at
  all, which of them are `-map` documents, which palette config `utils.exe` consumed, and
  the ids header name. `--no-pack-bat` / `--pack-bat <path>`. Apps without it are unaffected.
- **`$name` layers** (`$score!font2`) are NAME_ declarations, not sprites; a `$` after a
  base name (`hero$player`) still annotates a sprite.
- **`!marker` suffixes and the layer colour swatch carry data**: `!rateN` and the swatch
  (`Rate = colour + 1`) set `octBmp_t.Rate`; `!font`/`!label` make a map place a text label;
  `!pingpong !loop !once !hide !pause !twistable !fliph !flipv !ccw !cwcw !cw` set place
  flags (§12 of the parity report).
- **`--manifest` wins** over an auto-detected `!pack.txt` (printed note); an explicit
  `--pack-config` is still honoured alongside it.
- Palettes are **population-weighted** (a rare accent colour survives), so a repack can
  grow (+12.9 % on a real corpus) without a regression; alpha-flagged groups write `.pal`
  in the alpha-spread format `OCT_BLEND_alpha` reads. Check decoded pixels before
  treating either as a bug.
