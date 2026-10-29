---
name: "wowcube-html-prototype"
description: "Browser prototypes of WowCube games on the cube.js demo engine: a 3D cube and a 2D net of 24 screens, twists, pat, tilt, autopilot and a cinema layout for video recording. Use for requests like \"make an html prototype\", \"web prototype\", \"html demo of the game\", \"concept in the browser\", \"show the mechanic in html\", \"let's test the mechanic before coding on the cube\"."
---

# WowCube game HTML prototype

A prototype is a playable page where the mechanic is tested before any cube code, and from which a
video is recorded later. The cube game's logic then follows the prototype. The demo engine is in the
skill: `assets/cube.js`, `assets/cube.css`; a full prototype example with autopilot and `?cinema` is
`references/example-maze_box.html`.

## Where to put it

- **The game has a repository** `app_<game>`: `docs/<game>_prototype.html` plus a copy of the demo
  engine `docs/common/cube.js`, `docs/common/cube.css` (from this skill's `assets/`). Links use
  `common/cube.js`. Everything in `docs/` is in English and committed.
- **An idea without a repository**: ask where to put it; same structure (`<game>_prototype.html` +
  `common/`).
- A prototype from the game designer in Russian goes to `docs_ru/`.

## Page structure

One HTML file, self-contained; only `cube.js` + `cube.css` are shared.

1. `<head>`: `<title><Game> — WowCube</title>`, `cube.css`, its own `<style>` with a game class prefix
   (`mb-`, `qs-`, `lp-`): HUD chips, bottom caption (`*-cap`), big title (`*-big`), controls legend
   (`*-legend`, `*-row` with `.is-on` for the active gesture). A
   `/* Video layout (?cinema) */` block with `body.is-cinema …` rules: large cube on the left, net and
   legend on the right, 1280 x 720 (see `references/layout-html.jpg`).
2. `<script src="common/cube.js">`, then one IIFE with `'use strict'`, split by banners
   `/* ============================== Config ============================== */`:
   - **Logic**: pure logic with no DOM (`const XxLogic = (function () { … })()`): board model, rules,
     solver/hint. It is ported to C later, so it never touches the page.
   - **Levels**: level data as an array of objects (`{ id: '1-1', name: 'First Bite', par: 1, … }`).
   - **Config**: all numbers and colours in `Object.freeze({...})` UPPER_SNAKE constants (`CONFIG`,
     `VIEW`, `PALETTE`, `PHYS`): no magic numbers in code, each with a comment stating its units.
   - **State**: a single `st` object.
   - **Helpers / Drawing kit**: drawing a screen on canvas in 240 x 240 coordinates.
   - **Scenes**: `startX / tickX / paintX` for each scene (title, level, ending), **Scene control**.
   - **Autopilot**: `SCRIPT()` and `class Pilot` (below).
   - **Mount**: `CubeDemo.mount({...})` (API: `references/cubedemo-api.md`).
3. URL parameters: `?cinema` for the video layout, `?autoplay` for the autopilot after 600 ms,
   `?video` for no sound, `?level=<id>` to jump to a level. At the end,
   `window.__<abbr> = { st, startDemo, … }` for debugging from the console.

## Cube rules in the prototype

- 8 modules x 3 screens = 24 screens; a twist rotates half of the cube by 90°, a module's three screens
  always move together. A half-twist is `api.wiggle(token)` (the layer jerks and returns).
- Two `mount` modes: **puzzle**, where content lives on modules and moves with twists (`build`,
  `screen`, `evaluate`); **interactive**, where each screen is drawn by position (`paint`), twists are
  events (`onTwist`), `tick(dt)` advances animation, and gravity comes from the 3D view tilt
  (`api.gravity()`).
- Input: twist (keys U D L R F B, Shift for counter-clockwise), pat (click a screen in 3D or on the net),
  tilt (drag the cube, arrow keys). Pat applies to a whole face: highlight all 4 screens of the face.
- Texts and captions are in English, the gesture is **pat** (buttons `Pat · knock`, hints
  `Double pat to …`).
- Art is placeholders drawn in code; finished images go to `img/<game>/` next to the page.
- Sound uses `api.tone()` through a `sfx(freqs, ms, wave)` function and is silent with `?video`.
- Keep the real cube's constraints in the prototype: 240 px screens, borders between screens,
  determinism (no `Math.random()` in rules; use your own seeded RNG), and logic that can move to the
  engine's ticks (20 Hz) without changing behaviour.

## Panel and legend

`mount` takes `title`, `tagline`, `idea` (a paragraph), `howto` ("gesture — what it does" pairs),
`notes` (facts about the mechanic with numbers), `twistHelp` (what each twist does), `icon`,
`docKind: 'game concept'`. In `panel(root, api)`: a "Play" card with the main button
`▶ Watch the demo run`, buttons for manual actions and a numbered cheat sheet. The legend on the right
highlights the gesture the autopilot is currently performing (`setAct`).

## Autopilot

The scenario is an array of steps; each shows a caption and performs one action:

```js
const SCRIPT = () => [
  { big: 'MAZE BOX', sub: 'A glass house inside the WowCube', still: true, hold: 3.0 },
  { cap: 'Tilt: the ball rolls through a door…', sub: 'Gravity is real', act: 'tilt', go: [room(1, 3, 3)], until: inRoom([1, 2, 3]) },
  { cap: 'Twist the upper floors', sub: 'Twist U′ → over an open hatch', act: 'twist', twist: "U'", hold: 1.6 },
  { big: 'LEVEL COMPLETE', still: true, spin: 0.6, hold: 4.5 },
];
```

`Pilot` walks through the steps: sets `cap/sub` or `big`, highlights `act` in the legend, performs the
action (`twist`, moving towards a target, pat), waits for `until()` and `hold` seconds. At the end it
sets `window.__demoDone = true` (the recording stops on it). The autopilot runs the page's **real
rules**: no fake animations. Scenario: title card, each mechanic once with a caption, a mistake and its
fix, victory; 35–90 seconds.

## Verification

Before handing off, open the page in Playwright (Chromium is available in the cloud environment): no
console errors, `?autoplay` reaches `__demoDone`, and review screenshots of the normal layout and
`?cinema` (cube, net, captions not clipped).

## Prototype video

`scripts/record_html.mjs` records the page to mp4 frame by frame on Playwright's fake clock: a frame is
exactly 1/30 s, so the video is smooth at any machine speed and identical on every run; page errors are
printed, exit code 2. Requires `playwright` (Chromium) and `ffmpeg`, both available in the cloud
environment.

```bash
node scripts/record_html.mjs docs/<game>_prototype.html docs/demo/<game>_demo.mp4 \
     --seconds 120 --stopWhen "window.__demoDone"
```

`?cinema&autoplay` at 1280 x 720 with scale 1.5 gives 1920 x 1080. The video goes to the game's
`docs/demo/` (`docs/demo/` and `*.mp4` are in `.gitignore`); stills for documents:
`ffmpeg -ss <sec> -i <mp4> -frames:v 1 -vf scale=1280:-1 -q:v 3 docs/img/<game>_<scene>.jpg`.
