# Visual gate (cube_orchestrator reference)

Code reviewers read code; nobody looked at the screen. On a shipped game, prompt 1
passed both code verifiers with a black cross across all 24 screens (a packer pivot
bug); on the next one a 2-px background cross on every face (full-screen art placed at
+-120 instead of +-119.5) passed code review at 100/100 and was found only on the frames. So after **every coder and every fixer run** the orchestrator builds the
simulator, runs it hidden, dumps all 24 screens, and **looks at the frames itself**
before the prompt counts as done. The same gate runs at the infra gate, in Mod mode
and for balance runs. It is mandatory in every run mode.

## Rules

- **Hidden and muted, always** (`references/AGENT_SAFETY.md`). Windows: the repo's
  `<skills>/tools/sim_headless` (window never shown, killed by PID if one ever becomes
  visible, no audio device, crash dialogs suppressed, runs without activation).
  Linux: a virtual display with audio off (below). A visible simulator only when the
  user asks to play.
- **One hidden instance at a time.** Gate runs and playtests are never parallel.
- **No input injection.** Interaction goes through the control socket (`SIM_MCP.md`)
  or the game's own test hooks.
- **Not observed = not claimed.** If the gate could not run, record it
  (`not_checked_visually` in the context) and say so; never describe frames you did
  not open.

## Test hooks

Stage 2 adds them to the game header early (one of the first prompts); the prefix is
recorded in the context (`test_hooks`).

| Define | Default | Test value | Effect |
|---|---|---|---|
| `<GAME>_DEBUG_AUTOPLAY` | `0` | `1` | the game starts by itself and a scripted bot plays it (input from a script instead of taps, twists and tilt) |
| `<GAME>_MUTE` | `0` | `1` | every sound call compiles to nothing (one play helper) |
| `<GAME>_DEBUG_ROOM_PLANE` | `-1` | `0..5` | pins the playfield to one face, so frames show it without tilting the cube |

Which build sets what:

| Build | `_DEBUG_AUTOPLAY` | `_MUTE` | `_DEBUG_ROOM_PLANE` |
|---|---|---|---|
| visual gate (frames) | `1` | `1` | `0..5` for tilt games, else `-1` |
| Playtest Agent (interactive) | `0`: the agent's taps, twists and tilts are the only input | `1` | `-1`: the playfield follows the real tilt |
| audio check (sound-event log) | `1` | `0` | as for the visual gate |
| device / shipped | `0` | `0` | `-1` (Stage 5 checks) |

Before the hooks exist, run without them: the hidden tool opens no audio device anyway.

**Audio check** (prompts that add sound): its own build, autoplay on and `<GAME>_MUTE=0` (every gate build is
muted, so its log has no sound starts); start it with `run.ps1 ... -EveryMs 0 -McpPort <port> -AllowEarlyStop` and
take ONE continuous `record <n> <ms>` that spans the whole stretch to judge (a round end, the misses): two
back-to-back `record` calls leave a gap of many seconds while the first writes its PNGs, and a sound in that gap
looks missing. The `<prefix>meta.txt` lists one `snd`/`sndq` line per sound start; stops and mixer cuts
(`SND_set_mixer`) are not logged, so they are judged from the code.

## Windows: build, run, look

1. **Build** the hidden simulator with the hooks this check needs (1–3 min). The tool
   builds from its own snapshot of the app, so the real `app_<game>/` stays untouched
   and keeps the hooks off:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\build.ps1 -AppDir <ws>\app_<game> -Define <GAME>_DEBUG_AUTOPLAY=1,<GAME>_MUTE=1
   ```

   Add `<GAME>_DEBUG_ROOM_PLANE=<plane>` for tilt games. A compile error is a
   **critical** finding: the error lines (the tool prints them; full log in its work
   folder) go straight to the fixer.

2. **Run** hidden; PNGs of all 24 screens every `-EveryMs`, exit after `-Seconds`:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\run.ps1 -AppDir <ws>\app_<game> -Seconds 20 -EveryMs 500 -OutDir <ws>\assets_<game>\qa\sim\p03-1
   ```

   Typical: prompt checks 10–20 s at 250–500 ms (the dev simulator's boot intro takes
   about 5 s, so 15 s or more); motion and animation 100 ms; the video run 50 ms (one
   frame per tick); `-FreshSaves` when saves must start empty. Frames are
   `frame_<index>_<ms>.png`: the six faces as an unfolded cross (TOP above FRONT, BOTTOM
   below, LEFT FRONT RIGHT BACK in a row); `-Face 0..5` gives one face at full size.

   **Only exit 0 counts**: the timed run completed (the simulator closed itself after
   `-Seconds`), wrote its summary (`headless_summary.txt`), and no window was ever
   visible. Every other exit means the run did not complete; its frames never pass the
   gate. (`-AllowEarlyStop` is only for playtests you stop on purpose, below.)

   | Exit | Meaning | Do |
   |---|---|---|
   | 0 | ran its full time, summary written, never visible | look at the frames |
   | 1 | usage or setup error (no exe, bad folder) | fix the command or build first |
   | 2 | a window became visible and was killed | report it; never retry visibly |
   | 3 | did not end in time, killed by PID | stability finding |
   | 4 | no frames written | tool or start-up problem; read the log tail it prints |
   | 5 | the game crashed (`headless_crash.txt`, log) | **critical** finding with the crash text |
   | 6 | the exe is older than the app | build again (step 1) |
   | 7 | ended before its time without a summary (an early exit, a kill, a crash without a marker) | **critical** stability finding with the log tail it prints |

   Every run also prints a `seams:` line for its last frame (`tools/sim_headless/seams.py`, also runnable on any
   frame: exit 1 = seams). `seams: none` is the pass. A 2-px (x2 art) or 1-px (fullsize art) line of the background
   on the inner screen edges is screen-filling art placed at +-120: **major** V1 finding, fix = `QUAD_FILL` (+-119.5,
   API.md "Coordinates"). A line the design draws on purpose (a frame around a picture) is noted as such.

3. **Look** (Read tool on the PNGs). Open at least the first frame after the boot
   intro, one from the middle and the last; for motion, a contact sheet of every 10th
   frame:

   ```powershell
   $d = '<ws>\assets_<game>\qa\sim\p03-1'
   Get-ChildItem $d -Filter 'frame_*.png' | Sort-Object Name | ForEach-Object { "file '$($_.FullName -replace '\\','/')'" } | Set-Content "$d\frames.txt" -Encoding ascii
   ffmpeg -v error -f concat -safe 0 -i "$d\frames.txt" -vf "select='not(mod(n,10))',scale=iw/3:-1,tile=3x3" -frames:v 1 "$d\sheet.png"
   ```

## Linux

There is no hidden tool: run the normal simulator on a **private** virtual display
(`xvfb-run -a` picks a free display number, so nothing lands on an existing one) with
audio off, in a separate test build so the user's build keeps the hooks off, and
collect frames over the control socket. The pattern is the one `scripts/new_app.sh`
uses for its smoke run. Run it as one script from `<ws>` (needs `xvfb-run`, `setsid`
and `simcmd` from `SIM_MCP.md`):

```bash
GAME=<game>; APP="$PWD/app_$GAME"
OUT="$PWD/assets_$GAME/qa/sim/p03-1"; WORK="$PWD/.sim_headless/app_${GAME}_linux/p03-1"
mkdir -p "$OUT" "$WORK"                     # a new work folder per run: its own log and card images
printf 'sound_muted=1\n' > "$WORK/sim_user_linux.cfg"
cmake -S octavios -B "$APP/build-sim-test" -DAPP_DIR="$APP" \
      -DCMAKE_CXX_FLAGS="-D<GAME>_DEBUG_AUTOPLAY=1 -D<GAME>_MUTE=1"
cmake --build "$APP/build-sim-test" -j 4 --target octavios_sim
( cd "$WORK" && SDL_AUDIO_DRIVER=dummy SDL_AUDIODRIVER=dummy exec setsid xvfb-run -a -s "-screen 0 1280x1024x24" \
      "$APP/build-sim-test/octavios_sim" --mcp-port 8177 > "$WORK/stdout.txt" 2>&1 ) &
PGID=$!                                     # setsid: Xvfb and the simulator share this process group
cleanup() { kill -TERM -- "-$PGID" 2>/dev/null; sleep 1; kill -KILL -- "-$PGID" 2>/dev/null; }
trap cleanup EXIT INT TERM
PORT=""                                     # 8177 may be taken: read the port the simulator really opened
for i in $(seq 60); do
  PORT=$(grep -ao 'control socket listening on 127.0.0.1:[0-9]*' "$WORK/log_linux.txt" 2>/dev/null | tail -n1 | sed 's/.*://')
  [ -n "$PORT" ] && simcmd "$PORT" ping 2>/dev/null | grep -q pong && break
  PORT=""; sleep 0.5
done
[ -n "$PORT" ] || { echo "no control socket: $WORK/log_linux.txt, $WORK/stdout.txt"; exit 1; }
simcmd "$PORT" info | grep -q "app_$GAME" || { echo "port $PORT is not app_$GAME"; exit 1; }
simcmd "$PORT" record 80 250 "$OUT/f_"     # up to 100 frames per call
```

The trap stops the whole process group (Xvfb and the simulator, by group id) when the
script ends, also on an error. `-D` on the command line works because the hooks are
`#ifndef`-guarded (Stage 2 writes them that way). `record` writes `f_000.png …` (six
faces each) plus `f_meta.txt` with the pose, the layout and the sound starts.

A playtest needs the instance to outlive the script: the same lines with their own
build folder configured with `-D<GAME>_MUTE=1` only (autoplay off, plane pin -1), no
trap and no `record`; print `$PGID` and `$PORT`, hand the port to the Playtest Agent,
and when it returns stop that group: `kill -TERM -- -<PGID>` (then `-KILL` if anything
is left). Unverified on this setup: check the virtual display and the audio switch on
first use; the game's mute hook is the guarantee.

## What to look for

| # | Check | Typical cause |
|---|---|---|
| V1 | Every screen that should show something does; no black, garbage or magenta screens; no black bars or crosses between screens; `seams: none` | pivots, art at +-120 instead of +-119.5, palette alpha, missing assets, a palette backdrop |
| V2 | The right content on the right face and screen (the GDD's screen map: playfield, HUD, backdrop) | wrong plane, wrong quad |
| V3 | On-screen size as designed | the ×2 rule ignored (half-size sprites), fullsize misuse |
| V4 | Side faces upright; panoramas continuous around the four side faces; unique objects (sun, moon) exactly once on the cube | per-screen tiling, rotation |
| V5 | Clean edges: no boxes, fringes or key colour around sprites | keying, alpha |
| V6 | Text visible and spelled right | fonts not packed, label slots exhausted |
| V7 | Motion between frames: what should move moved (autoplay), what should hold held, no flicker | tick logic, sequences |
| V8 | Stability: the full run time, all frames written, no `terminate` or assert lines in the log | crashes, pool overflow |
| V9 | This prompt's Verification items that can be seen | the prompt itself |

**Verdict**: PASS, or FAIL with findings (format in `references/AGENT_BRIEFS.md`).
Critical or major findings go to the fixer together with the frames that show them;
minor ones are recorded and fixed when cheap. After the fix: build, run, look again.

## Playtest Agent (interaction)

When the hidden instance's control socket answers (`sim_mcp` is `bridge` or `wire`,
`SIM_MCP.md`), the Playtest Agent (`cube_verifier`) drives taps, twists and tilts. It
never plays the visual gate's binary: there autoplay feeds the inputs and the plane pin
overrides the tilt, so the agent's own taps, twists and tilts would prove nothing.

1. Build the playtest binary in its own work folder (the gate's autoplay build stays
   where it is): autoplay off, plane pin -1, still muted.

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\build.ps1 -AppDir <ws>\app_<game> -WorkDir <ws>\.sim_headless\app_<game>_play -Define <GAME>_DEBUG_AUTOPLAY=0,<GAME>_DEBUG_ROOM_PLANE=-1,<GAME>_MUTE=1
   ```

2. Start the instance in the background with no periodic frames and a lifetime that
   covers the playtest. You will stop it by PID before its time on purpose, so pass
   `-AllowEarlyStop` (without it the stopped run ends with exit 7; crashes, a visible
   window and timeouts still fail with it).

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\run.ps1 -AppDir <ws>\app_<game> -WorkDir <ws>\.sim_headless\app_<game>_play -Seconds 300 -EveryMs 0 -McpPort 8177 -AllowEarlyStop -OutDir <ws>\assets_<game>\qa\sim\p03-play
   ```

3. Read `run_info.json` in that folder: `pid` at once, `mcp_port` once the socket listens
   (written as `null` first, filled about a second later; wait for it):

   ```powershell
   $info = "<ws>\assets_<game>\qa\sim\p03-play\run_info.json"
   for ($i = 0; $i -lt 60; $i++) { $j = Get-Content $info -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json; if ($j.mcp_port) { break }; Start-Sleep -Milliseconds 500 }
   "pid $($j.pid) port $($j.mcp_port)"
   ```

   Check `ping` → `ok pong` and that `info` names `app_<game>`.
4. Dispatch the Playtest Agent with the Verification Task JSON plus `playtest_port`
   and `frames_dir`, using a subagent type that has the bridge's MCP tools or a shell
   (for `mcp.ps1`). It follows `SIM_MCP.md`'s observation script and returns its JSON
   (pass at 90 with no critical issue). Read its `criteria_observed`: below about half,
   the score does not cover the prompt; when the game starts a round at boot, give the
   playtest build a title or a paused start (a test hook) so the agent connects before
   anything is decided.
5. Stop the instance by its PID (`Stop-Process -Id <pid>`) as soon as the agent
   returns, also on failure.

## Evidence

- Frames stay in `assets_<game>/qa/sim/p<NN>-<attempt>/`; the context stores the
  folder, the verdict and the findings per prompt.
- *(stepwise)* The checkpoint shows the sheet and names what nothing could judge: how
  it sounds, how it feels, balance, the real cube.
- The last Stage 4 run (long autoplay at 50 ms) feeds the gameplay video
  (`references/DELIVERY.md`).

## Infra gate, Mod mode, balance

- **Infra gate**: the template's Demo 0 exactly as it should look after the boot intro
  (V1, V2, V5, V8): the pink "2" tile on all four TOP screens and on one FRONT screen (it
  hops to the neighbouring FRONT screen about a second in); the other 19 screens are
  plain black, which is correct there. A missing, cut, offset or fringed tile, garbage,
  a flat magenta (key colour) screen, black bars across a tile's screen, or the intro
  still showing in the last frames fails it. Demo 0 draws no text: the fonts are checked by the pack
  (`BMP_font_*` in the ids header), not on these frames. The same tool builds
  the user's playable simulator: `build.ps1 -AppDir <ws>\app_<game> -Visible` (the
  stock `apps\build_sim.cmd` does not compile under MSVC at octavios dev `609d5ae`;
  the tool patches its engine copy). Give the user the printed path; it opens a
  window and plays sound, so it is theirs to start.
- **Mod mode**: M1 keeps baseline frames; M5 repeats the run with the same hooks and
  timings and compares side by side: the change is visible, nothing else moved.
- **Balance runs**: 60–120 s of autoplay with the game logging its key numbers through
  `OCT_trace` (it prints to the simulator log); read them from the log, not from the
  pictures.
