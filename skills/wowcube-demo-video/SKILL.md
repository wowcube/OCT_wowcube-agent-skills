---
name: "wowcube-demo-video"
description: "WowCube game demo videos in the standard format: 1920 x 1080, the 3D cube on the left, the same 24 screens as a 2D net plus the controls legend on the right, captions per scene, the game played by a bot or autopilot on the real rules. Three methods: recording an HTML prototype, capturing sprites from the game, rendering screens with the engine. Use for requests like \"make a video\", \"record a demo\", \"gameplay video\", \"record a clip\", \"demo for the game designer\"."
---

# WowCube game demo video

Everything needed is in this skill: scripts, templates and examples.

```
scripts/record_html.mjs      records an HTML prototype on a fake clock (method A)
scripts/render_demo.py       video from a game capture: 3D cube, net, legend, twist rotations (B, C)
templates/capture.h          capture harness: frames.jsonl, frame by frame (B, C)
templates/shot.h             renders all 24 screens with the real engine into a PNG net (C)
templates/capture_demo.sh    builds and runs the capture with host g++ against the engine (folder next to the game)
templates/demo.json          clip styling: title, subtitle, legend, font, paths
examples/breakout/           method B example: capture.cpp (scenario), bot.h (bot), demo.json
examples/chemistry/          method C example: capture.cpp (scenario with twists), demo.json
references/layout-*.jpg      what a frame looks like
```

## Where things go

- The video goes to `docs/demo/<game>_demo.mp4` in the game repository, together with intermediates
  (`frames.jsonl`, `sprites/`, `net/`). `docs/demo/` and `*.mp4` are in `.gitignore`.
- Stills from the finished video are illustrations for documents: the GDD cover (Intro section), scene
  frames in the game description. They go to `docs/img/<game>_<scene>.jpg` and are committed:
  `ffmpeg -ss <sec> -i docs/demo/<game>_demo.mp4 -frames:v 1 -vf scale=1280:-1 -q:v 3 docs/img/<game>_<scene>.jpg`.

## What it looks like

Frame: `references/layout-engine-capture.jpg` (game capture) and `references/layout-html.jpg`
(HTML prototype). The same for every game:

- 1920 x 1080, dark background, two rounded panels.
- **Left**: a small-caps header with the game's gestures (`3D · TILT ROLLS THE PADDLE · PAT · TWIST`); a
  large 3D cube, slightly tilted following gravity, twists rotate half of the cube; a caption plate at the
  bottom: a bold line and a short explanation.
- **Right**: `NET (2D) · SAME SCREENS, UNFOLDED`, a cross-shaped net (U on top, L F R B, D at the bottom)
  with face letters; the game title in two colours, subtitle `WowCube game · <tagline>`; a legend
  "icon + gesture + what it does", with the current gesture's row highlighted.
- Gesture icons are the game's own sprites (its twist, pat, tilt icons); the font is the game's font.
- 35-90 s; 20 fps for an engine game (frame = tick), 30 fps for HTML. `libx264`, `yuv420p`, crf 18-20.

## Scenario

Each scene is one idea with one caption (`capShot` / autopilot step):

1. Title, 2-3 s.
2. The first level with tutorial hints.
3. Each mechanic once: the caption names the gesture and the result.
4. A mistake and its fix (an extra twist → restart with a double pat, losing a life).
5. A late level that uses the whole cube.
6. Victory, results, selector, game over or the ending.

The game is played by a bot or autopilot **on the real rules**: no fake animations.

## Method A: HTML prototype

Any page works if it can do two things: a video layout via `?cinema` (1280 x 720 CSS px: cube on the
left, net and legend on the right, as in `references/layout-html.jpg`) and an autopilot via `?autoplay`
that runs the page's real rules, shows scene captions and sets `window.__demoDone = true` at the end.
Recording in the cloud environment (Chromium and ffmpeg are available there):

```bash
node scripts/record_html.mjs docs/<game>_prototype.html docs/demo/<game>_demo.mp4 \
     --seconds 120 --stopWhen "window.__demoDone"
```

Frame = exactly 1/30 s on Playwright's fake clock: the video is smooth and identical on every run.
Page errors are printed, exit code 2.

## Methods B and C: engine game

Common ground: the game runs headless on the host with the real rules and rendering; the scenario is
the game's file `tests/capture.cpp`; `capture.h` writes every frame as a JSON line to
`docs/demo/frames.jsonl`; `render_demo.py` assembles the video. Work directly in the game folder on the
developer's machine (g++, uv, ffmpeg and the engine are there).

1. Copy into the game: `templates/capture.h` → `tests/`, `templates/capture_demo.sh` → `scripts/`,
   `templates/demo.json` → `docs/demo/demo.json` (fill it in); for C also `templates/shot.h` → `tests/`.
2. Write `tests/capture.cpp` following an example (`examples/breakout` or `examples/chemistry`):
   - includes: `oct_test_shim.h`, `oct.h`, **`capture.h` before `app.h`**, `app.h`, (`shot.h` after `app.h`);
   - `tick()` = bot input → `on_tick()` → `capFrame()`;
   - `capShot(caption, sub, legendRow, yaw, pitch, yawSpeed)` before each scene;
   - twist: `on_pretwisted` → `OCT_twist_sprites` → `on_twisted` → `capTwist(t)`;
   - the bot (`bot.h`), as in the Breakout example, moves gravity `Gf` and pats through `vars`,
     never touching the rules; if needed, reuse the same bot as in the host tests.
3. Capture: `scripts/capture_demo.sh` (B) or `CAPTURE_NET=1 scripts/capture_demo.sh` (C).
4. Video:

```bash
uv run --python 3.12 --with numpy==2.5.4 --with pillow==12.3.0 <skill>/scripts/render_demo.py docs/demo/demo.json
# quick preview: --every 4; single frame: --still <frame>
```

**B: sprites** (regular sprite games): `capture.h` writes all live sprites of the frame;
`render_demo.py` draws them from the art dump (`gen_art.py --dump docs/demo/sprites`) and the game's font.
Label texts must be passed through a hook: in the game's `render.h`, next to label creation,
`RENDER_LABEL_HOOK(id, text, font, color, align);` with a default `#define RENDER_LABEL_HOOK(...) ((void)0)`
under `#ifndef`. In `demo.json`: `ids` (pack header), `sprites`, `labelFonts` (font number → size, style).

**C: engine rendering** (games with `on_proc_draw`, or when pixel-exact engine output is needed): `shot.h`
loads the pack like the simulator does (run `art\!pack.bat` first) and on every frame renders all 24
screens to `docs/demo/net/NNNNN.png`. Legend icons are PNG paths.

**Twists** in B and C: the renderer precedes the frame after `capTwist` with a rotation of half the cube
(8 frames, `--twist-frames`). Which half and which direction is found by comparing screens before and
after; the engine's twist table is not needed. If the screens are fully redrawn after a twist (the twist
is a command, not a rotation), no rotation is shown, which is expected.

## Verification

- `ffprobe`: 1920 x 1080, fps, duration.
- Look at 4-6 frames at scene changes (`--still` or `ffmpeg -ss`): 3D and net match, captions are not
  clipped, the right gesture is highlighted, the twist rotates the right half, no empty screens.
- For HTML: no console errors, `stopWhen` fired before the limit.
