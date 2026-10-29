# Simulator control socket (MCP): agent self-check and playtest

Reference for `cube_orchestrator` (starts and stops the hidden simulator) and for the
Playtest Agent in `cube_verifier` (drives it). The protocol's own documentation lives
in the SDK: `<octavios>/tools/mcp/README.md`. Safety rules: `references/AGENT_SAFETY.md`.

Every other gate reads code. Through this socket the agent sees and drives the running
game (24-screen dumps, frame recordings with sound starts, twists, taps, cube tilt), so
an iteration is checked the way a player would check it.

## What it is

Every octavios dev simulator, Windows and Linux, opens a control socket at start-up:

- bound to `127.0.0.1` only; port 8077 by default, or the next free port up to +15;
  `--mcp-port N` sets the first port tried;
- log line `[mcp] control socket listening on 127.0.0.1:<port> (<app>)` (Windows:
  `log_1.txt` in the simulator's working folder, appended across runs; Linux:
  `log_linux.txt`);
- a text protocol: one request per line, one reply per line; commands run on the
  simulator's main thread once per frame; no reply within 15 s → `err timeout`
  (recordings get a longer budget);
- the bridge `<octavios>/tools/mcp/octavios_mcp.py` (Python stdlib only, MCP over stdio,
  server name `wowcube-octavios-sim`, `--port` default 8077) turns it into MCP tools.

Clients without the bridge. Windows: the repo's `mcp.ps1` (one connection, one reply
line per command, exit 1 on any `err`):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <skills>\tools\sim_headless\mcp.ps1 -Port <port> ping info "screens faces C:\abs\p03_idle.png" "twist 3"
```

Linux: a shell function (keep the heredoc lines at column 0):

```bash
simcmd() { python3 - "$@" <<'EOF'
import socket, sys
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), 300)
s.sendall((" ".join(sys.argv[2:]) + "\n").encode())
print(s.makefile().readline().strip())
EOF
}
# start-up: poll until it answers
for i in $(seq 60); do simcmd 8177 ping 2>/dev/null | grep -q pong && break; sleep 0.5; done
```

## Hard rules

1. **Hidden and muted only.** The stock Windows simulator always shows its window, idles
   until the window is activated (a never-activated window answers nothing) and always
   plays audio. Agent runs therefore use `<skills>/tools/sim_headless` (window never
   shown, killed by PID if one ever becomes visible, no audio device, crash dialogs
   suppressed, runs without activation; `references/VISUAL_GATE.md`). Linux: a virtual
   display and audio off. A visible simulator only when the user asks to play.
2. **Never inject global input**: no SendInput, keybd_event, SetForegroundWindow; no
   SPACE for the unfold view (a synthetic SPACE once unmuted the user's call
   microphone). Interaction is socket commands or the game's test hooks.
3. **Never touch the user's instance.** 8077 belongs to whatever the user runs; agent
   instances start at 8177 (`run.ps1 -McpPort`, recorded as `playtest_port`), and `info`
   confirms the app before anything is scored.
4. **One instance per check, stopped by its PID.** There is no quit command; the hidden
   tool's `-Seconds` lifetime is the watchdog. An instance you will stop before its time
   (a playtest) is started with `run.ps1 -AllowEarlyStop`; without it the stop ends the
   run with exit 7 (`references/VISUAL_GATE.md`). Never kill by process name.
5. **Playtests run their own build**: autoplay off, plane pin -1, muted
   (`references/VISUAL_GATE.md`, Playtest Agent). The visual gate's autoplay binary would
   override every tap, twist and tilt the agent sends.
6. **Never claim a playtest that did not happen**, never describe frames you did not open.

## Availability probe (once per session, before Stage 4)

Record `sim_mcp` in `context/<game>_context.json`:

| Value | Meaning |
|---|---|
| `bridge` | MCP tools whose names end in `__screens`, `__twist_face` and `__tap` exist under a server whose name contains `octavios` and `sim` (match the suffix; the prefix depends on how the host registered it) |
| `wire` | no bridge tools, but a hidden instance answers `ping` with `ok pong` (`mcp.ps1` / `simcmd`) |
| `absent` | no answer: an SDK older than dev, or the instance died at start-up (a finding by itself) |

With the dev SDK `wire` is the floor, so the Playtest Agent normally runs. With
`absent` the visual gate still runs on the hidden frames and every summary says
nobody drove the game.

### Enabling the bridge (tell the user once, then move on)

A `.mcp.json` in the workspace:

```json
{"mcpServers": {"wowcube-octavios-sim": {
  "command": "C:\\full\\path\\to\\python.exe",
  "args": ["C:\\ws\\octavios\\tools\\mcp\\octavios_mcp.py", "--port", "8177"]}}}
```

On Windows give the full path of a real Python 3.10+ (`python` may be the Microsoft
Store alias, `py` may be missing); on Linux `"command": "python3"`. New tools appear
after the agent session restarts: do not wait for them, use `wire` meanwhile.

## Commands

| Wire request | Reply / effect | Bridge tool |
|---|---|---|
| `ping` | `ok pong` | — |
| `info` | `ok info <port> <w> <h> <app_folder> <app_title>` | `list_simulators`, `connect(port)` |
| `screens faces <png>` | six faces 3×2 in scene orientation, byte-exact from the 24 framebuffers, gaps RGB(1,1,1) | `screens(save_as?)` |
| `screens <png>` | the raw 960×1440 atlas of the 24 displays plus the layout map | `screens(save_as?, raw=true)` |
| `record <n 1..100> <ms 20..2000> <prefix>` | frames `<prefix>000.png …` and `<prefix>meta.txt`: pose, gravity, layout and sound starts (`snd <ms> frame module id vol`, `sndq … quad owner id`) | `record_frames(frames, period_ms, save_prefix)` |
| `shot <max_side> <png>` | the 3D window; **unreliable on a hidden window**, use `screens` | `screenshot(max_side, save_as?)` |
| `twist <0..23>` | replies after the snap settles; twid = 2·plane (CCW) or 2·plane+1 (CW), +12 = half twist; planes top 0, front 1, right 2, back 3, left 4, bottom 5 | `twist_face(face, cw/ccw/half_cw/half_ccw)` |
| `tap <x> <y>` | `ok tap` or `err no_screen`; window pixels | `tap(x, y)` (last-screenshot pixels) |
| `cube <yaw> <pitch> <roll>` / `turn …` | rotates the **cube**: gravity and the IMU follow | `set_cube`, `turn_cube` |
| `camera <yaw> <pitch>` / `orbit …` / `face <0..5>` / `reset` | moves the **viewer** only | `set_camera`, `orbit_camera`, `look_at_face`, `reset_view` |
| `unfold <0\|1>` | the six-face cross in the 3D view | `unfold(on)` |
| `idle` | replies once no twist or drag is in flight | `wait_idle` |
| `shake` | the game exits to the launcher (below) | `shake` |
| `log` | `ok log <run-start offset> <abs log path>`; includes `OCT_trace` and telemetry lines | `read_log(since?, max_bytes?)` |

Give absolute paths (the simulator's working folder is its own). There is no pause,
step, speed, mute or quit command.

## Observation script (Playtest Agent)

Short and scripted: every image costs tokens.

1. **Identity**: `info` names `app_<game>`; otherwise stop, wrong instance.
2. **Idle**: `screens faces` → does it render, right backdrop, no garbage, no blank
   faces where art belongs?
3. **This prompt's mechanic**, with `verification_criteria` as the script: `twist` the
   faces it names, `tap` where it says (aiming below), `cube` poses when it reads
   gravity; `screens faces` after each action.
4. **Motion**: `record 20 100 <prefix>` and compare frames: what should move moved, what
   should hold held. `meta.txt` shows **whether and when sounds started** (`snd` /
   `sndq` lines), never how they sound.
5. **Orientation** (games that read gravity): `cube 0 0 0`, `cube 0 0 90`, `cube 0 90 0`,
   `screens faces` each, then `cube 0 0 0` again before anything else is judged.
6. **Survival**: `ping` still answers, a final `screens faces`, the log tail has no
   `terminate` or assert lines.
7. **Shake** only when the prompt is about shake-to-exit, and only as the last action.

### Moving the camera vs moving the cube

- `camera`, `orbit`, `face`, `reset` walk the viewer around a cube that stays put.
  Nothing in the game changes.
- `cube` and `turn` rotate the cube itself, as a hand would. Gravity turns with it, so
  a game reading `OCT_TM_gravity_*` or `OCT_TM_top_side()` reacts. Pose is measured from
  the upright cube, front face forward: yaw 90 brings the right face to the front, pitch
  90 the front face to the top, roll 90 the right face to the top. `cube 0 0 0` stands
  it upright again; `reset` does not (it only moves the camera).

### Aiming taps and twists

- Twists need no aiming.
- Taps take window pixels. `face <n>` points the camera at face n; `info` gives the
  window size; aim at the middle of one quad, about a quarter of the face's width off
  the centre (the centre of a face is a bezel gap). `err no_screen` means the aim
  missed, not that the game ignored the tap: re-aim and retry. Check the effect with
  `screens faces`.
- Long scripted sequences belong to the visual gate's autoplay run; the playtest build
  has autoplay off, so every input you send reaches the game and nothing else plays.
- Turning the cube or the camera while unfolded does nothing: `unfold 0` first.
- Leave the cube upright when done: `cube 0 0 0`.

### Shaking exits the game

For an ordinary game the engine runs its default shake handler and **returns to the
launcher**; the app's `on_shake` is never consulted. A screenshot after a shake that
shows the launcher is correct behaviour, not a crash. Never shake mid-script.

## What a playtest can and cannot judge

**Can**: does it render; the right art on the right face and screen; scale; the
response to taps, twists and tilt; gravity handling; motion; survival; whether and when
sounds start.

**Cannot**: how anything sounds, feel and exact timing on hardware, balance,
RNG-dependent outcomes, memory, and anything about the physical cube (the simulator runs
PC-compiled code; ARM code is Stage 5's job). **If it cannot be observed, it is not a
finding.** Say what was not observable and move on.

## Simulator state and the `.oct` clobber note

- Each simulator keeps per-module SD-card and flash images in its working folder
  (`e<m>_<inst>.raw`, `i<m>_<inst>.raw`), so saves survive restarts. For a clean run use
  `run.ps1 -FreshSaves` (it deletes only the hidden tool's own images; never touch the
  user's).
- **The stock Windows simulator rewrites `app_<game>/app_<game>.oct` whenever it starts
  with `out/app_<game>.bin` present** (and deletes it when the ARM code is missing); the
  Linux simulator writes `<app>_<date>_<time>.oct` when the ARM build is newer than
  `src/`. The hidden tool writes no `.oct` unless asked (`-OctOut`, diagnostics only).
  So the deliverable is built last, by Stage 5, into `dist/`; never hand over
  `app_<game>/app_<game>.oct`.
