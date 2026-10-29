# cube.js: demo engine API

Source: `../assets/cube.js` (≈1300 lines) and `cube.css` in this skill. Read the file itself when in
doubt: its header describes the model, and the `Exports` section lists what is visible from outside.

## Model

- 8 modules (corners), 3 screens each = 24 screens (`CONFIG.SCREENS`), each screen 240 x 240 units.
- Faces `FACE_IDS = ['U', 'L', 'F', 'R', 'B', 'D']`; cross-shaped net: U on top, L F R B in a row, D at the bottom.
- Slot = screen position: `slotIndex(face, row, col)`, `slotInfo(slot) -> { face, row, col }`,
  `faceSlots(face)`, `ringSlots(...)`.
- A twist is a token `U`, `U'`, `R2`…; `parseMoves('U R\' F')`, `invertToken`, `twistSign`.
- `SurfaceGrid`: a grid over the whole surface that is stitched across edges (waves, lava, particles).

## CubeDemo.mount(game) -> api

Common `game` fields:

| Field | Purpose |
|---|---|
| `mode` | `CubeDemo.MODE.PUZZLE` (default) or `MODE.INTERACTIVE` |
| `title`, `tagline`, `icon`, `docKind` | page header and right panel header (`docKind: 'game concept'`) |
| `idea`, `howto`, `notes`, `twistHelp` | right panel text: idea, "gesture — action", facts, twists |
| `backHref` | "back" link to a list page, if there is one |
| `viewPresets`, `orientView`, `viewElev` | 3D view angles; `orientView: true` allows free cube orientation |
| `twistMs` | twist animation duration |
| `packs` | content sets (pack selector) |
| `panel(root, api)` | your own card in the right column |
| `onReset(api)` | level reset; also store `api` here |
| `onPat({ sticker, slot, face, row, col, hud }, api)` | pat; return `true` if handled |
| `evaluate(api)` | `{ badge, solved, html }`: status line |

Puzzle: `build(packId, api)` lays content out on stickers, `screen(ctx)` returns a screen's SVG,
`hud(slot, api, model)` provides HUD screens, `scramble`.

Interactive: `paint(g, ctx)` draws a screen on canvas (`ctx.slot`, `ctx.face`, `ctx.row`, `ctx.col`),
`tick(dt, api)` advances animation and returns `true` if screens changed; `onTwist(token, api)`,
`onTilt(api)`.

## api

`model`, `packId`, `refresh()`, `redraw()`, `flash(sid, kind)`, `flashSlot(slot, kind)`,
`tone(freq, ms, delayMs, wave)`, `audio()`, `gravity()`, `setView(pitch, yaw, roll)`,
`orientation()`, `setOrientation(R)`, `twist(tokens)`, `twisting()`, `wiggle(token)`, `reset()`,
`lock(on)`, `isLocked()`, `hudAt(slot)`, plus `CONFIG, FACES, FACE_IDS, EDGE, ROW, V, SVG, M3,
slotInfo, slotIndex, faceSlots, ringSlots, quarterInFace, twistSign`.

## Animation and time

Twists and `tick` run through `requestAnimationFrame` and `performance.now()`, which is why recording
video on Playwright's fake clock (`page.clock`) gives even frames. Do not add your own `setInterval`
with real time or CSS animations the game depends on: CSS transitions are disabled during recording.
