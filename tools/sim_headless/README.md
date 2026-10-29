# sim_headless: the hidden, silent Windows simulator for agent checks

Agents never start a visible simulator on the user's machine (see
`skills/cube_orchestrator/references/AGENT_SAFETY.md`). The stock Windows simulator always shows its window,
idles until that window is activated, and plays sound. This tool builds a patched **copy** of it
(`octavios` itself is only read) that:

- creates its window invisible (`WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`, no `WS_VISIBLE`) and never shows it;
  ignores window input and global key state;
- runs its loop without ever being activated (paced to about 60 fps);
- never opens an audio device (sound starts are still logged for MCP `record`);
- suppresses crash, assert, abort, invalid-parameter and WER dialogs (exit code 99 + `headless_crash.txt`),
  and logs file dialogs and message boxes instead of showing them;
- does no Bluetooth auto-connect, writes no settings, takes no global instance mutex;
- dumps PNGs of all 24 screens every N ms and exits by itself after N seconds;
- keeps the stock **MCP control socket** (`--mcp-port`), so an agent can drive the hidden instance;
- writes a `.oct` only to an explicit path (`-OctOut`), never next to an app and never deletes one.

`run.ps1` proves invisibility on every run: it polls the process's top-level windows every 50 ms and kills
the process **by PID** the moment any is visible (exit 2).

Windows only. Requirements: octavios **dev 609d5ae or later** (needs `sim\src\sim_mcp.h`), the
`wowcube/telemetry` checkout next to octavios (the dev simulator links it), Visual Studio C++ build tools
(MSVC), Python 3.

## Commands

```powershell
$T = "<skills repo>\tools\sim_headless"

# 1. build (after every code or asset change; 10-60 s, starts nothing)
powershell -NoProfile -ExecutionPolicy Bypass -File $T\build.ps1 -AppDir C:\ws\app_<game> `
    [-Octavios C:\ws\octavios] [-Telemetry C:\ws\telemetry] [-Define <GAME>_DEBUG_AUTOPLAY=1,<GAME>_MUTE=1]

# 2. hidden run: PNG of all 24 screens every 500 ms for 20 s
powershell -NoProfile -ExecutionPolicy Bypass -File $T\run.ps1 -AppDir C:\ws\app_<game> -Seconds 20 -EveryMs 500
#    -> prints "last frame: ...\frame_000039_019503.png"; open it (and a few earlier ones) with the Read tool
#    -> and "seams: none", or the screen edges that start with a 1-2 px line of one colour (below)

# 3. seam check on any frame (run.ps1 does it for the last one): exit 0 none, 1 seams, 2 unreadable
python $T\seams.py <frame.png> [--face]
```

A **seam** is a 2-px (half-res x2 art) or 1-px (fullsize art) line of the background along the inner screen edges:
screen-filling art placed at `+-120` instead of `+-119.5` (`QUAD_FILL`, template API.md "Coordinates"). Every packer
gives a full-screen sprite pivot 119.5 and the renderer rounds the corner; measured on all 24 screens of the dev
engine. `run.ps1` only prints the report, never turns it into an exit code (a line the design draws on purpose would
trip it).

Defaults: `-Octavios <AppDir>\..\octavios`, `-Telemetry <octavios>\..\telemetry`,
`-WorkDir <AppDir>\..\.sim_headless\<app>`. The work dir holds the patched sources, a snapshot of the app
(`src`, `index.bin`, `art\packed`, `sound\assets`, `out\*.bin`), `bin\sim_headless.exe`, its log
`bin\log_1.txt` (appended by every run of this work dir; `run.ps1` also copies the run's own lines to `<out dir>\log.txt`) and `frames\<timestamp>\`.

`run.ps1` parameters: `-Seconds` (lifetime, default 10), `-EveryMs` (dump period; `0` = no dumps, MCP only),
`-Face` (`-1` = the six faces as an unfolded cross: TOP above FRONT, LEFT FRONT RIGHT BACK in a row, BOTTOM
below; `0..5` = one face), `-OutDir`, `-McpPort` (default 8177, away from the stock 8077), `-FreshSaves`
(delete the simulated SD/flash images first), `-OctOut <path>`, `-AllowStale`, `-AllowEarlyStop` (accept a
run you stopped with `stop.ps1` before `-Seconds`, e.g. after an MCP playtest; only a kill's exit code -1/1 or 0
passes, a crash always fails with exit 5).

`-WorkDir` is refused when it is a drive root, the home folder, or is / contains / lies inside the app, octavios
or telemetry (the build rewrites folders under it). Paths with non-ASCII characters (e.g. Cyrillic) are passed to
MSVC, cmd.exe and the simulator in their 8.3 short form; when the volume keeps no short names the scripts stop
early and name the path: move the workspace to a Latin-only path.

Exit codes of `run.ps1`: 0 ok = the timed run completed (exit 0 after `-Seconds` and `bin\headless_summary.txt`
written), 1 setup error, 2 a window became visible (killed), 3 did not end in time (killed), 4 no frames
written, 5 crashed (exit 99), 6 the app changed after the build (rebuild), 7 ended before its timed exit (early
exit, kill, no summary) without `-AllowEarlyStop`. Only exit 0 counts as a passed visual-gate run.

### Timing on octavios dev

The dev simulator boots like a cube: white tiles, dark screens, then the engine's ~2.8 s "eyes intro" on the
face that is up (eyes, hearts, happy arcs), and only then the app. In our validation run the app had not
appeared yet at 5 s. Use `-Seconds 15` or more and judge the **last** frames. MCP `screens` returns
`map -1 -1 ...` until the layout is bound.

### Test hooks

`-Define NAME=VALUE` rewrites `#define NAME ...` lines in the snapshot (so unguarded hooks work too) or passes
`/DNAME=VALUE` when no source defines NAME. Every game carries exactly these hooks, `#ifndef`-guarded:
`<GAME>_DEBUG_AUTOPLAY` (default 0; 1 = plays itself), `<GAME>_MUTE` (default 0; 1 = every sound compiled out),
`<GAME>_DEBUG_ROOM_PLANE` (default -1; 0..5 pins the playfield to that face). Typical check build:
`-Define <GAME>_DEBUG_AUTOPLAY=1,<GAME>_MUTE=1`. The real app keeps the defaults; only the snapshot changes.

## Driving the hidden instance over MCP

Start the run in the background with a lifetime that covers the session and no periodic dumps:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $T\run.ps1 -AppDir C:\ws\app_<game> -Seconds 300 -EveryMs 0 -AllowEarlyStop
# prints: started hidden: pid 6864 ... / mcp: listening on 127.0.0.1:8177
# <out dir>\run_info.json also carries pid and mcp_port
```

Then either use the stdlib bridge `<octavios>\tools\mcp\octavios_mcp.py --port 8177` (registered as an MCP
server, see `skills/cube_orchestrator/SIM_MCP.md`) or the wire protocol directly:

```powershell
powershell -NoProfile -File $T\mcp.ps1 -Port 8177 ping info "screens faces C:\ws\shots\p3_faces.png"
powershell -NoProfile -File $T\mcp.ps1 -Port 8177 "twist 3" "record 40 50 C:\ws\shots\p3_twist_"
```

| Wire command | Use |
|---|---|
| `screens faces <png>` | six faces 3x2 in scene orientation, byte-exact (gap pixels RGB 1,1,1) |
| `screens <png>` | raw 4x6 atlas + `map` of which face/quad each screen shows |
| `record <n 1..100> <ms 20..2000> <prefix>` | n frames + `<prefix>meta.txt` (pose, gravity, layout, sound starts `snd`/`sndq`) |
| `twist <0..23>` | twid = 2*plane (CCW) or 2*plane+1 (CW), planes top 0 front 1 right 2 back 3 left 4 bottom 5; 12..23 half twists |
| `tap <x> <y>` | window pixels of the 3D view (aim with `face <n>` first; a miss returns `err no_screen`) |
| `cube <yaw> <pitch> <roll>` / `turn ...` | rotate the cube itself (gravity follows); `cube 0 0 0` stands it upright |
| `camera` / `orbit` / `face <0..5>` / `unfold <0|1>` / `reset` | view only, the game does not change |
| `shake` | leaves the game to the launcher: last action only |
| `shot <max_side> <png>` | the 3D window; worked on a never-shown window in our validation, but prefer `screens` |
| `log` | path of `log_1.txt` + offset of this run (engine/app `WLOG` records included) |
| `ping`, `info`, `idle` | liveness, port/app/title, wait for twists to settle |

There is no quit command: stop early with `stop.ps1 -RunInfo <out dir>\run_info.json` (it stops that PID only
when it still runs the same exe started at the recorded time, so a reused PID is never hit; never by name),
otherwise the instance closes itself after `-Seconds`. A run you mean to stop early is started with `-AllowEarlyStop`;
without it the stopped run reports exit 7 (not a completed run).

Gameplay video for the user (no audio): from `record` frames
`ffmpeg -framerate 20 -i <prefix>%03d.png -pix_fmt yuv420p out.mp4` (period 50 ms = 20 fps); from the periodic
dumps (named `frame_<index>_<ms>.png`) through a concat list:

```powershell
Get-ChildItem <out dir>\frame_*.png | Sort-Object Name | ForEach-Object { "file '$($_.FullName)'"; "duration 0.5" } | Set-Content <out dir>\list.txt
ffmpeg -f concat -safe 0 -i <out dir>\list.txt -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -pix_fmt yuv420p <out dir>\play.mp4
```

## The visible simulator (for the user only)

`build.ps1 -Visible` builds a normal simulator from the same copy: `<WorkDir>\<app>\bin\<app>.exe`. It opens a
window and plays sound; agents never start it, they give the user the path. It exists because the stock
`octavios\apps\build_sim.cmd` does not compile under MSVC at dev 609d5ae: `engine\oct_mp3.h` uses
`__attribute__((noinline))` (C2065). `patch.py` fixes that line in its engine copy only and skips the fix once
upstream has it.

## Maintenance

`python patch.py --octavios <dir> --check` counts every anchor (each must match once). When the simulator
sources change, update the anchors in `patch.py`; the build fails loudly instead of patching half a file.
Verified against octavios dev 609d5ae (2026-10-21): 23/23 anchors, MSVC build, one hidden 5 s run with
`max_visible=0`, 10 PNGs and MCP `ping`/`info`/`screens`/`shot`/`log` answered.
