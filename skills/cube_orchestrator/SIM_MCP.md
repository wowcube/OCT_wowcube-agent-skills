# Simulator MCP — agent self-playtest

Reference for `cube_orchestrator` (launches and stops the simulator) and for the
Playtest Agent defined in `cube_verifier` (drives it). Read this before the first
playtest of a session; the authoritative protocol docs live in the SDK at
`<octavios>/tools/mcp/README.md`.

The simulator opens a localhost-only TCP control socket on startup, and
`<octavios>/tools/mcp/octavios_mcp.py` bridges that socket to MCP. Through it an
agent can **see and drive the running game**: take screenshots, tap screens,
twist faces, move the camera, unfold the cube. This closes the one gap the rest
of the pipeline cannot: every other gate reads *code*, this one watches the game
actually run.

| Tool | Args | Effect |
|---|---|---|
| `screenshot` | `max_side`, `save_as` (optional) | PNG of the sim window; the only way to see the cube |
| `tap` | `x`, `y` | Tap a screen, in pixels of the **last screenshot** |
| `twist_face` | `face`, `direction` | 90° twist, blocks until the snap settles |
| `set_cube` / `turn_cube` | `yaw`, `pitch`, `roll` | Absolute / relative pose of **the cube itself** — gravity turns with it |
| `shake` | — | The shake gesture. **Read the warning below before using it** |
| `orbit_camera` / `set_camera` | `yaw`, `pitch` | Relative / absolute **camera** angles in degrees |
| `look_at_face` | `face` | Fill the view with one face |
| `unfold` | `on` | Flat 6-face cross ↔ cube |
| `reset_view` | — | Camera back to the launch pose |
| `wait_idle` | — | Block until no twist or drag is in flight |
| `list_simulators` / `connect` | —, `port` | Find running sims; point the tools at one |

Faces are `top / front / right / back / left / bottom`; CW and CCW are seen
looking at the named face **from outside** the cube.

### Moving the camera vs. moving the cube

These are different things and confusing them wastes a playtest.

- **`orbit_camera` / `set_camera` / `look_at_face` / `reset_view` walk the viewer
  around a cube that stays put.** Nothing in the game changes; only what is
  visible does. Use them to *see* another face.
- **`set_cube` / `turn_cube` rotate the cube itself**, the way a hand would.
  Gravity turns with it, so an app reading `OCT_TM_gravity_x/y/n` or
  `OCT_TM_top_side_plane` sees a new orientation and reacts.

Pose is measured from the upright cube, front face forward: yaw 90 brings the
right face to the front, pitch 90 brings the front face to the top, roll 90
brings the right face to the top. `set_cube(0, 0, 0)` stands it upright again —
**`reset_view` does not**, it only moves the camera. Both cube tools answer with
the normalized pose they ended at, read back off the scene, so a pose is never
tracked by hand.

### Shaking exits the game — use it last or not at all

A shake is not a neutral input. For any ordinary game app the engine runs
`OCT_on_shake_default`, which calls `OCT_go_home()`: **the game under test is
unloaded and the launcher comes up.** The app's own `on_shake` is not consulted
at all — that is why the coding rules forbid building gameplay on shake.

So in a playtest:

- Never shake to "see what happens" mid-script. Everything after it is scored
  against the launcher, not the game.
- Shake only as a deliberate final check, after every other observation is done.
- A screenshot after a shake showing the **launcher is correct behaviour** — a
  pass, not a crash, and not a finding. The finding would be a game that keeps
  running.

## Availability probe (run once per session, before Stage 4)

The MCP server is **optional infrastructure**. Decide once, up front, and record
the answer in `context/<game>_context.json` as `"sim_mcp": "available" | "absent"`.

Available **iff** the current tool list contains MCP tools whose names end in
`__screenshot`, `__twist_face`, `__tap` under a server whose name contains
`octavios` and `sim` — e.g. `mcp__wowcube-octavios-sim__screenshot` or
`mcp__octavios-sim__screenshot`. **Match the suffix, not the prefix:** the prefix
is whatever name the host registered the server under and differs between setups.

- **Present** → the playtest gate is ON for this session (Stage 4, Mod mode M5,
  and the infra gate's launch check).
- **Absent** → the playtest gate is skipped, `"sim_mcp": "absent"` goes into the
  context, and every per-prompt summary says so explicitly, so the user knows
  nobody watched the game run. Mention **once** per session how to enable it
  (below) — then stop mentioning it.

Never claim a playtest happened when the tools were absent, and never invent
screenshot contents.

### Enabling it (tell the user once, then move on)

Register the bridge with the agent host, e.g. a `.mcp.json` in the working project:

```json
{
  "mcpServers": {
    "wowcube-octavios-sim": {
      "command": "python3",
      "args": ["<octavios>/tools/mcp/octavios_mcp.py"]
    }
  }
}
```

On Windows use `"command": "py"` or the full path to `python.exe`. The bridge is
stdlib-only — no install step. A newly registered server usually needs the agent
session restarted before its tools appear, so do not block the pipeline waiting
for it: run this prompt's cycle with the gate skipped.

### Degraded fallback (no MCP registration)

If the MCP tools are absent but the simulator itself is built, its wire protocol
is still reachable and is enough for a **smoke check** — launch the sim, then:

```bash
printf 'shot 0 /tmp/octsim_<game>.png\n' | nc -w2 127.0.0.1 <port>   # -> ok shot <w> <h> <nw> <nh>
```

and open `/tmp/octsim_<game>.png` with the Read tool. This proves the game
renders, but scoring gameplay this way is slow and error-prone — treat it as a
stability check only, not as the playtest gate, and still record
`"sim_mcp": "absent"`.

## Running a playtest

### 1. Build first

The simulator runs the binary, not the source. Always rebuild before a playtest
or the screenshots show the *previous* prompt's game:

```bash
cmake --build <workspace>/app_<game>/build-sim        # Linux
```

### 2. Pick and record a port

Leave the default `8077` to whatever instance the user may have open. Pick a free
port in **8078–8092** for the pipeline's own sim, record it in
`context/<game>_context.json` as `"playtest_port": <n>`, and reuse it for the
whole session. A simulator whose port is taken silently moves to the next free
one, so always confirm the port from the log line rather than assuming it.

### 3. Launch in the background

```bash
<workspace>/app_<game>/build-sim/octavios_sim --mcp-port <port> \
    > /tmp/octsim_<game>.log 2>&1 &
```

Then poll `/tmp/octsim_<game>.log` for:

```
[mcp] control socket listening on 127.0.0.1:<port> (app_<game>)
```

Wait for that line (a second or two) before the first tool call — connecting
sooner just fails the call. If the line never appears, or the process exits
early, that is itself a **critical** finding: the game crashed at startup,
almost always missing or unpacked assets. Capture the log tail as evidence.

The simulator is an SDL3 window and **needs a display** — on a headless host it
cannot start, which is an environment problem, not a game defect. Report it as
"playtest unavailable" rather than as a failing gate.

With more than one sim up, call `list_simulators`, then `connect` to the port
recorded above before anything else.

### 4. Drive the game, then stop it

Run the observation script (below), then **always** kill the process:

```bash
kill <pid> 2>/dev/null || true
```

One sim per prompt cycle: launch → playtest → kill. Never leave an instance
dangling between prompts — a stale sim serves stale pixels and steals the port.

## The `.oct` clobber rule (non-negotiable)

**The simulator rewrites `app_<game>/app_<game>.oct` as an asset-only pack on
every launch.** A playtest is a sim launch, so:

- Every playtest happens **before** Stage 5 / M6, never after.
- If a sim is launched for any reason after the device build, the device build
  **must be re-run** before the `.oct` is handed to the user.
- Never deliver an `.oct` whose last writer was a playtest.

## Observation script

A playtest is a scripted observation, not free exploration. Keep it short — every
screenshot costs tokens.

1. **Idle state.** `screenshot`. Does anything render at all? Correct background,
   no garbage pixels, no all-black faces where art is expected?
2. **All six faces.** `unfold(on=true)` → `screenshot` reads the whole cube in one
   shot. This is the cheapest way to check per-face layout and to catch content
   drawn on the wrong plane. `unfold(on=false)` before any interaction.
3. **The prompt's own mechanic.** Exercise exactly what this prompt added, using
   the prompt's `verification_criteria` as the script — tap where the prompt says
   a tap does something, twist the face the prompt says responds, screenshot
   after each action.
4. **Motion.** For anything animated or tick-driven, take two screenshots a few
   seconds apart and compare: did the thing that should move, move? Did the thing
   that should stay put, stay?
5. **Orientation**, when the game reads gravity at all (`OCT_TM_gravity_*`,
   `OCT_TM_top_side_plane` / `OCT_TM_bottom_plane` in the code, or a GDD that
   talks about tilting, falling, or "the bottom face"). `set_cube` a few poses —
   e.g. `(0,0,0)`, `(0,0,90)`, `(0,90,0)` — screenshotting each: does what should
   fall, fall the right way; does the game agree with the new bottom face?
   **Then `set_cube(0, 0, 0)` before anything else**, or every later screenshot
   is read at the wrong angle.
6. **Survival.** A final `screenshot` plus a check that the process is still
   alive. A sim that died mid-playtest is a **critical** finding, with the log
   tail as evidence.
7. **Shake**, only if this prompt is about shake-to-exit, and only as the very
   last action — see the warning above.

Save shots worth comparing with `save_as` (absolute path, e.g.
`/tmp/playtest_<game>_p<N>_<step>.png`) — the default buffer is overwritten by
the next shot.

## Aiming taps and twists

- **Tap coordinates are pixels of the most recent screenshot.** Take a shot,
  read the point off it, then tap. The bridge rescales to native pixels itself.
- **The centre of a face is not tappable.** Each face is four 240×240 quads with
  a bezel cross between them; a tap at the exact centre lands in the gap and
  returns `no_screen`. Aim at the middle of a quad.
- `no_screen` means the aim was wrong, **not** that the game ignored the tap.
  Re-aim and retry before recording anything as a finding.
- **Orbiting or turning the cube while unfolded does nothing** — the cross always
  faces the camera. Fold back first.
- **Leave the cube upright when done tilting.** `set_cube(0, 0, 0)`, not
  `reset_view`. A "sprite on the wrong face" finding recorded against a cube that
  is still lying on its side is a wasted fix cycle.
- `twist_face` already blocks until the snap settles; `wait_idle` is only needed
  after motion the agent did not start.

## What a playtest can and cannot judge

**Can:** does it render; is the art on the right face/quad; does a tap, twist, or
tilt produce the response the prompt promised; does the game read gravity the way
the design says; does anything move that should move; does it survive a few
seconds of play; obvious visual breakage (half-size sprites, off-screen objects,
overlap, wrong palette).

**Cannot:** sound, exact timing and frame rates, long-run balance, RNG-dependent
behaviour, memory/leak behaviour, and **anything about the physical cube** — the
sim runs PC-compiled code, so a perfect playtest still says nothing about whether
the `.oct` contains ARM code. That remains Stage 5's job.

**If it cannot be observed, it is not a finding.** Uncertainty from a screenshot
is never a deduction — say what was not observable and move on. The Playtest
Agent's job is to catch games that are visibly broken, not to re-check what the
Requirements and Template agents already read in the code.
