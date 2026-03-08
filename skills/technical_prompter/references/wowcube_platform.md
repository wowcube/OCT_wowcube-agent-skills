# WowCube Platform — API Quick Reference

## Hardware

- **Form factor**: 2×2×2 puzzle cube (like a Rubik's cube but with screens)
- **Displays**: 24 screens (240×240 pixels each), 4 per face
- **Faces (planes)**: 6 — TOP(0), FRONT(1), RIGHT(2), BACK(3), LEFT(4), BOTTOM(5)
- **Input**: Physical twists (rows/columns rotate) and taps (accelerometer-based per face)
- **Sensors**: Accelerometer (gravity detection, orientation)

## Coordinate System

- Each plane has 4 quads (physical displays)
- Quad ID = local_quad [0–3] + plane_id × 4
- Quads [0–3] start from top-right center and rotate counter-clockwise
- Quad center coordinates: (±(120 + GAP), ±(120 + GAP)) where GAP = 18
- XSIGN[4] = {+1, -1, -1, +1}
- YSIGN[4] = {+1, +1, -1, -1}
- Each display is 240×240 pixels, coordinate range per quad: roughly ±120 from center

## Core API Functions

### Engine
- `OCT_restart(int32_t* objects, int cap, int objSize)` — Clear scene, initialize object pool
- `OCT_viewports_layout(int scheme, int gapX, int gapY)` — Set viewport layout (use SCHEME_CUBE)
- `OCT_background(uint16_t color)` — Set background color (RGB565 format)

### Sprites
- `int OCT_add(int layer, bool twistable, int plane, float x, float y, int a, bool loop, int bmpfrom, int bmpto, int framelen)` — Add sprite to scene, returns index in gObjects
  - `layer`: rendering layer (higher = on top)
  - `twistable`: if false, engine auto-resets position after twist
  - `plane`: which face (0–5)
  - `x, y`: position on the plane
  - `a`: angle (relative to plane)
  - `loop, bmpfrom, bmpto, framelen`: animation params (framelen = ticks per frame)
- `void OCT_del(octSprite_t* s)` — Delete sprite from scene

### Transform (octTm_t)
- Every `octSprite_t` has a `.Tm` property of type `octTm_t`
- Fields: `.Plane` (int), `.X` (float), `.Y` (float), `.A` (int angle)
- `int OCT_TM_quad(const octTm_t* tm)` — Get quad ID for a transform

### Sound
- `int SND_getAssetId(const char* name)` — Get asset ID for sound file
- `int SND_play(int id, int volume)` — Play sound (volume 0–100)

### Utility
- `int OCT_random(int dmin, int dmax)` — Random integer in [dmin, dmax)

### Gravity / Orientation
- `float OCT_TM_gravity_x(int plane)` — Gravity X component for plane
- `float OCT_TM_gravity_y(int plane)` — Gravity Y component for plane
- `float OCT_TM_gravity_n(int plane)` — Gravity normal (Z) component for plane
- `int OCT_TM_top_plane()` — Current top plane based on accelerometer
- `int OCT_TM_bottom_plane()` — Current bottom plane based on accelerometer

### Logging
- `OCT_trace(int level, const char* fmt, ...)` — Debug logging

## Event Handlers (WASM_EXPORT)

- `void on_init()` — Called once at app start. Initialize engine, load resources, set up scene.
- `void on_tick()` — Called every frame (~20 FPS, 50ms/tick). Game loop logic.
- `void on_tap(int32_t tapid)` — Called on face tap. tapid = plane index.
- `void on_pretwisted(int32_t twid)` — Called when twist begins. Prepare state.
- `void on_twisted(int32_t twid, uint32_t disconnected_ms)` — Called when twist completes.
  - twid 0–11: full twists (plane × 2 + direction)
  - twid 12–23: half twists (OCT_TWIST_HALF offset)

## Architecture Rules

- All game code lives in a single `.h` file (header-only)
- Game objects struct `appObject_t` extends `octSprite_t`
- Game state struct `appvars_t` holds global variables
- All globals must use the `TL` macro: `TL static appObject_t gObjects[SPRITES_CAP];`
- `gObjects[0]` is reserved/invalid (validation: `obj.Idx == index`)
- Maximum sprites: SPRITES_CAP = 400
- Tick rate: OCT_1SEC_TICKS = 20 ticks/second
- Asset paths: `assets/packed` (sprites), `assets/mp3` (sounds)
- Sprite IDs defined in `app_*_ids.h` as BMP_XXX constants

## Twist Reference

Full twists (twid 0–11):
| twid | Twist |
|------|-------|
| 0 | TOP_CCW |
| 1 | TOP_CW |
| 2 | FRONT_CCW |
| 3 | FRONT_CW |
| 4 | RIGHT_CCW |
| 5 | RIGHT_CW |
| 6 | BACK_CCW |
| 7 | BACK_CW |
| 8 | LEFT_CCW |
| 9 | LEFT_CW |
| 10 | BOTTOM_CCW |
| 11 | BOTTOM_CW |

Half twists: twid 12–23 (same order, offset by OCT_TWIST_HALF)

## Plane Constants

- OCT_PLANE_TOP = 0
- OCT_PLANE_FRONT = 1
- OCT_PLANE_RIGHT = 2
- OCT_PLANE_BACK = 3
- OCT_PLANE_LEFT = 4
- OCT_PLANE_BOTTOM = 5
