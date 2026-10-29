# Stage 5: delivery (cube_orchestrator reference)

Device `.oct`, upload to the user's cube, on-device checklist, gameplay video,
balance loop. The device build is driven through `wowcube-boilerplate`; none of the
steps below starts a simulator.

## 1. Ship-build checklist

- [ ] The last visual gate passed on the final source.
- [ ] Test hooks off in `app_<game>/src/app_<game>.h`: `<GAME>_DEBUG_AUTOPLAY 0`,
      `<GAME>_MUTE 0`, `<GAME>_DEBUG_ROOM_PLANE -1`. (The hidden tool switched them on
      only in its own snapshot.)
- [ ] The launcher icon is the game's: `app_<game>/art/icon.png` is not the template
      icon, and the last pack printed no template-icon warning.
- [ ] The pack is current (apps packed from a manifest): `python <skills>/scripts/build_pipeline.py pack-status --game <game> --workspace assets_<game> --app-dir app_<game> --manifest plans/<game>_assets.json`
      exits 0 (1 = an art, sound, font, icon or manifest change since the pack:
      repack first, `references/STAGE3_ASSETS.md` §7, then rerun the visual gate).
- [ ] Version: `src/app_metadata.h` uses `APP_VERSION OCT_APP_SEMVER(...)`. Every
      rebuild of something the user may have installed bumps `APP_VERSION_PATCH` (the
      cube compares versions on install); `<skills>/scripts/repack_app.py` bumps it
      (it also accepts the legacy integer `APP_VERSION`).
- [ ] `APP_GUID1` unchanged since the first install: it is the app's identity (an
      install replaces the pack with the same GUID and keeps its save).
- [ ] Recorded sounds have their lines in `app_<game>/sound/CREDITS.md`.

## 2. Build the device `.oct`

One command, no simulator; it writes `<ws>/dist/app_<game>.oct` and verifies it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\scripts\build_device.ps1 -AppDir <ws>\app_<game>
```

```bash
<skills>/scripts/build_device.sh --app-dir <ws>/app_<game>
```

- **Builder `auto`** picks the SDK's official `octpack-build` when octavios dev,
  `src/app_metadata.h`, `uv` (it brings Python 3.12), clang++ or g++, CMake, Ninja and
  the ARM GNU toolchain are there; otherwise the repo's pure-Python builder
  (`pack_beta.py --build-oct`), which stamps the save size from `APP_SAVE_SIZE` (read
  through `src/app_metadata.h` and `app_save.h`'s static_assert). `-Builder octpack|python` forces one (details in
  `wowcube-boilerplate`). `-NoUv` (`--no-uv`, env `WOWCUBE_NO_UV=1`) never starts uv: python builder + local check.
- **Never run uv from the Microsoft Store Python** (`...\WindowsApps\PythonSoftwareFoundation...`): that uv cannot
  see its own Python installs and may delete the octpacker `.venv`. `repack_app.py` detects it and refuses the uv
  step with the command to run from a normal shell; use a python.org / uv-managed Python for octpack-build.
- octpack-build compiles `src/app_metadata.h` with the host compiler, builds the ARM
  module with CMake + Ninja into `app_<game>/out/` and links the `.oct`. The first `uv`
  run downloads the packer's pinned packages once into `<ws>/.uv_octpack_venv` (`build_device`
  sets `UV_PROJECT_ENVIRONMENT`; `-UvEnv` / `--uv-env` picks another one; never inside
  octavios, which stays read-only): that download belongs to the one-time environment
  approval (`references/AGENT_SAFETY.md`, entry check 3 in SKILL.md), never a surprise
  at delivery.
- **No `art/octpack.json` in an AI-manifest app.** Without it, octpack-build uses the
  art Stage 3 packed (`index.bin`, `art/packed`, `sound/assets`). With it, it re-packs
  from the PSDs listed there and overwrites Stage 3's pack (that is the PSD path,
  `references/STAGE3_ASSETS.md` §9).
- After switching octavios checkouts delete `app_<game>/out/` (CMake refuses a cache
  from another source folder).
- `<octavios>/tools/build.ps1 <app>` runs the same official build but writes the `.oct`
  into the app folder; do not use it for delivery.

The same official build by hand, and the info dump the verification reads:

```powershell
uv run --project <ws>\octavios\octpacker octpack-build <ws>\app_<game> --out <ws>\dist\app_<game>.oct --engine <ws>\octavios
uv run --project <ws>\octavios\octpacker octpack-info <ws>\dist\app_<game>.oct
uv run --project <ws>\octavios\octpacker octpack-info <ws>\dist\app_<game>.oct --app-version
```

**Verification is mandatory.** The script verifies every `.oct` it builds, with either
builder: the ARM tail, then `scripts/pack_beta.py --verify-oct` on the header, which it
takes from `octpack-info` when that runs and otherwise reads from the `.oct` itself. Any
mismatch, and anything it cannot check (no python, an unreadable header), fails the
build: there is no "checks skipped" outcome. After a manual build, run the same check:
`python <skills>/scripts/pack_beta.py --verify-oct <ws>/dist/app_<game>.oct --app-dir <ws>/app_<game> --code <ws>/app_<game>/out/app_<game>.bin`.

| Field | Expect |
|---|---|
| magic, size, CRC32 | a well-formed `.oct` |
| `code_size`, code offset, the code tail | the size and the bytes of `app_<game>/out/app_<game>.bin` (the ARM code is in the `.oct`) |
| build id | not zero |
| title, version, GUID, categories, save size | equal to the app's defines (`src/app.h` → `app_metadata.h` → `app_save.h`) |
| assets | one `MAP` named `ico` (the launcher finds the icon only through it); the asset list equals `index.bin` |
| `octpack-info --app-version` | the semver you expect (empty = a legacy integer version) |

**Hard stop, every mode:** a missing ARM toolchain or a failed or impossible
verification. Fix the environment (`<skills>/scripts/check_env.ps1` / `check_env.sh`);
never deliver a simulator-written or unverified `.oct`.

**Only `dist/` is delivered.** The stock Windows simulator rewrites
`app_<game>/app_<game>.oct` whenever it starts with `out/app_<game>.bin` present (and
deletes it when the ARM code is missing), so that file is never the deliverable. Build
`dist/` after the last simulator run of the session.

## 3. Upload to the user's cube (only when they asked)

Before: the cube is paired in the system's Bluetooth settings (the user does that),
charged and awake; you know its Bluetooth name and the MAC of its module 0 (the only
one discoverable over SPP). Ask once and keep them in the context as `cube`. Upload only
to that cube; never touch other paired devices.

**Windows**: `<skills>/tools/cube_upload` (a patched copy of the simulator that never
shows a window, connects over Bluetooth SPP, uploads the `.oct` as software, logs the
result and exits; packs over 64 KB get the long chunk timeout). Details in its README:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\cube_upload\run_upload.ps1 -Octavios <ws>\octavios -Mac <AA:BB:CC:DD:EE:FF> -Oct <ws>\dist\app_<game>.oct -Name "<cube name>"
```

The first run builds the uploader (about a minute). Reading the MAC of a paired cube:
`Get-PnpDevice -Class Bluetooth | Where-Object FriendlyName -like 'Wow*' | Select-Object FriendlyName, InstanceId`
(the 12 hex digits after `DEV_`).

| Exit | Meaning | Do |
|---|---|---|
| 0 | success | the reboot note below, then the checklist |
| 10 | the cube refused the pack (CRC, flash, validation) | read the RESULT line; rebuild the `.oct` |
| 11 | aborted part-way (e.g. stalled at the first chunk) | run it once more; failing again → the user reboots the cube, then rerun |
| 12 | no connection | paired? on, awake, in range? the MAC of module 0? |
| 2 / 3 / 13 | a window became visible (killed) / timeout / no result | report with the log path; never retry visibly |

About 46 KB/s: a 0.5 MB pack takes 10–15 s plus a few seconds of settling.

**Linux**: `spptest` from octavios (built by the octavios root CMake project, BlueZ;
WSL2 has no Bluetooth; check the binary's location in your build folder):

```bash
spptest --mac AA:BB:CC:DD:EE:FF --software <ws>/dist/app_<game>.oct --long-timeout
```

**Manual fallback** (the user does it; the agent never presses keys): in the user's
visible simulator, Shift+C → pick the cube's SPP device (1–9) → Shift+S (hold
Right-Ctrl for the long chunk timeout) → choose `dist\app_<game>.oct` → read the
result box. Unverified alternative: the `wowcube_flash` (MTK DevTool) Python API.

**After the upload** tell the user to restart the cube: the next Bluetooth connection
after an upload often fails until a reboot (octavios `BLUETOOTH.md`), and a new version
may not show in the launcher before it. The game then appears with its icon and title.

## 4. On-device checklist (give it to the user)

- The launcher shows the game's icon and title; the game starts.
- Controls on the real hardware: taps on each face (and per screen where designed),
  twists both ways, half twists ignored, tilt.
- Sound: music and effects together, balanced; positional sounds come from the right
  place (the simulator plays only module 0, so the cube is the first real test of the
  mix).
- Orientation: the HUD is upright on the side faces; the playfield follows the face
  that is up.
- Smoothness: animations at their speed, no hiccups on full-screen animations.
- Saves (if any): progress survives a shake back to the launcher and a relaunch.
- Idle: after about 60 s without input the game pauses; waking the cube relaunches to
  home (expected).
- Five minutes of play without a freeze.

Problems go back through Mod mode (T1–T3) with the user's notes; a correction that is a
standing preference goes to `context/rules.md`.

## 5. Gameplay video (optional)

Offered in the final report, made when the user wants it (or when the request asked
for one); a GDD may say what it should show. From the last long autoplay run (frames
every 50 ms = one per tick; ~300 KB per 24-screen PNG, so 80 s is ~470 MB: delete the
frames once the video is made). To cut it to the GDD's length (say 30-40 s with a round
end), keep only the frames in that window: their names carry the time in ms
(`frame_<index>_<ms>.png`), e.g. `Where-Object { [int]($_.BaseName -split '_')[2] -ge 38000 }`
before the `ForEach-Object`:

```powershell
$d = '<frames dir>'
Get-ChildItem $d -Filter 'frame_*.png' | Sort-Object Name | ForEach-Object { "file '$($_.FullName -replace '\\','/')'"; 'duration 0.05' } | Set-Content "$d\video.txt" -Encoding ascii
ffmpeg -v error -f concat -safe 0 -i "$d\video.txt" -vf "fps=20,pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p -crf 18 "<ws>\dist\app_<game>_gameplay.mp4"
```

Linux `record` frames: `ffmpeg -framerate 20 -i <prefix>%03d.png -vf "pad=ceil(iw/2)*2:ceil(ih/2)*2" -c:v libx264 -pix_fmt yuv420p out.mp4`.
The video is silent (no audio is ever captured). Give the user the path; do not open
it. A presentation video in the team's standard format (1920x1080: 3D cube, unfolded net, controls legend,
captions) comes from the `wowcube-demo-video` skill: method A records the HTML prototype, methods B/C
capture the real game with a bot (Node + Playwright or a host g++ build: a one-time install the user approves).

## 6. Balance loop (after the first playable build)

Expect two or three passes ("slow the heroine down 4x", then "a bit livelier").

1. Every pace number lives in one tunables block of named constants at the top of the
   game header, mirrored by the GDD's tunables table.
2. **Measure**: hidden autoplay runs of 60–120 s (`references/VISUAL_GATE.md`) with the
   game logging its key numbers through `OCT_trace` (time to the first hit, enemies on
   screen, score per minute); read them from the simulator log.
3. **Ask** the user a short questionnaire: too fast or slow, too hard or easy, which
   moment. Offer the visible simulator (built with `build.ps1 -Visible`) or a fresh
   upload to the cube.
4. **Change only the tunables** (Mod mode T1), run the visual gate, build, upload if
   asked. Record each pass in the context (`balance_passes`: values before and after,
   why).

Autonomous runs do not tune beyond the GDD's numbers on their own: feel needs a human.

## 7. Report

Finish with the end-of-run report from `references/RUN_MODES.md`.
