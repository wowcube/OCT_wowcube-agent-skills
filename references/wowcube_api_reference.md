# WowCube OctaviOS — API Reference

## Hardware Overview

- **Form factor**: 2x2x2 puzzle cube with screens on every segment
- **Displays**: 24 screens (240x240 pixels each), 4 per face
- **Faces (planes)**: 6 — TOP(0), FRONT(1), RIGHT(2), BACK(3), LEFT(4), BOTTOM(5)
- **Input**: Physical twists (full and half), taps (per face), accelerometer (gravity/orientation)
- **Physical gap**: 18px border between adjacent displays (GAP = 18)

## Coordinate System

- Each face has 4 quads (physical displays), numbered 0-3
- Quad ID = local_quad [0-3] + plane_id * 4 (total 24 quads)
- Quads [0-3] start from top-right center and rotate counter-clockwise
- Quad center coordinates use XSIGN/YSIGN arrays:
  - XSIGN[4] = {+1, -1, -1, +1}
  - YSIGN[4] = {+1, +1, -1, -1}
  - Center of quad = ((120 + GAP) * XSIGN[q], (120 + GAP) * YSIGN[q])
- Each display covers ~240x240 pixels, coordinate range roughly -120 to +120 from quad center

## Plane Constants

| Constant | Value |
|----------|-------|
| OCT_PLANE_TOP | 0 |
| OCT_PLANE_FRONT | 1 |
| OCT_PLANE_RIGHT | 2 |
| OCT_PLANE_BACK | 3 |
| OCT_PLANE_LEFT | 4 |
| OCT_PLANE_BOTTOM | 5 |
| OCT_PLANES_MAX | 6 |
| OCT_QUADS_AT_PLANE | 4 |

## Architecture Rules

- All game code lives in a single `.h` file (header-only)
- Game objects struct `appObject_t` extends `octSprite_t` via C struct inheritance
- Game state struct `appvars_t` holds all global game variables
- All globals must use the `TL` macro: `TL static appObject_t gObjects[SPRITES_CAP];`
- `gObjects[0]` is reserved/invalid — validation pattern: `obj->Idx == index`
- Maximum sprites: SPRITES_CAP = 400
- Tick rate: OCT_1SEC_TICKS = 20 ticks/second (50ms per tick)
- Asset paths: `assets/packed` (sprites), `assets/mp3` (sounds)
- Sprite IDs defined in `app_*_ids.h` as BMP_XXX constants
- Font constants: FONT_1, FONT_2, FONT_3
- Alignment constants: ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT

## Engine Initialization

```c
// Clear scene and initialize object pool
void OCT_restart(int32_t* objects, int cap, int objSize);

// Set viewport layout — always use SCHEME_CUBE with GAP
void OCT_viewports_layout(int scheme, int gapX, int gapY);

// Set background color in RGB565 format
void OCT_background(uint16_t color);
```

**Typical init pattern:**
```c
OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t));
OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
OCT_background(0x0000); // BLACK
```

## Sprite Management

```c
// Add sprite to scene, returns index in gObjects
int OCT_add(int layer, bool twistable, int plane, float x, float y, int a, bool loop, int bmpfrom, int bmpto, int framelen);
```
- `layer`: rendering layer (higher = on top)
- `twistable`: if true, sprite follows physical twists; if false, engine auto-resets position after twist
- `plane`: which face (0-5)
- `x, y`: position on the plane
- `a`: angle in degrees (relative to plane)
- `loop`: true = looping animation
- `bmpfrom, bmpto`: sprite frame range for animation
- `framelen`: ticks per animation frame (0 = no animation)

```c
// Delete sprite from scene
void OCT_del(octSprite_t* s);
```

## Label Management

```c
// Add text label to scene, returns index in gObjects
int OCT_add_label(int layer, bool twistable, int side, float x, float y, int a, int font_idx, int align);

// Update label text (recreates child glyph sprites), returns text length
// Supports '\n' for multi-line. Skips update if text unchanged.
int OCT_label_set(octSprite_t* label, const char* text);
```
- Each glyph is a separate child sprite with `Parent` set to label's `Idx`
- To toggle label visibility, must also toggle all child glyphs (iterate gObjects, check `obj->Parent == label->Idx`)

## Transform (octTm_t)

Every `octSprite_t` has a `.Tm` property of type `octTm_t`.

**Fields:** `.Plane` (int), `.X` (float), `.Y` (float), `.A` (int angle)

```c
// Get quad ID for a transform's current position
int OCT_TM_quad(const octTm_t* tm);

// Move transform forward along direction angle, with optional lateral offset
// Returns old plane. wrap=true for automatic cross-plane transitions.
int OCT_TM_walk(octTm_t* tm, int forward_direction_angle, float forward_distance, float left_distance, bool wrap);

// Copy full transform from src to dst
void OCT_TM_copy(octTm_t* dst, const octTm_t* src);

// Linearly interpolate between transforms a and b by factor t [0-1]
// Handles cross-plane transitions. Result written to tm.
void OCT_TM_lerp(octTm_t* tm, octTm_t* a, octTm_t* b, float t);

// Move transform to a different plane, adjusting coordinates and angle
void OCT_TM_change_plane(octTm_t* tm, int to);
```

**Cross-display movement:** To move a sprite to the next display, use distance = `240.0f + 2.0f * GAP`.

## Animation

```c
// Set up animation sequence for a sprite
// restart modes: OCT_SEQ_RESTART (from start), OCT_SEQ_REVERSE (from end), OCT_SEQ_REFRESH (keep position)
void OCT_sequence(octSprite_t* spr, int from, int to, int framelen, octSeqRestart_t restart);
```
- `sprite->Paused`: bool to pause/resume animation (default false)
- `sprite->Loop`: bool for looping animation

## Virtual Twist

```c
// Perform a virtual twist of all twistable sprites
void OCT_twist_sprites(octTwistId_t twid);
```

## Sound

```c
// Get asset ID for a sound file by name
int SND_getAssetId(const char* name);

// Play sound by asset ID with volume [0-100]
int SND_play(int id, int volume);
```

## Gravity / Orientation

```c
// Gravity vector components for a given plane
float OCT_TM_gravity_x(int plane);
float OCT_TM_gravity_y(int plane);
float OCT_TM_gravity_n(int plane);  // Normal (Z-axis) component

// Current top/bottom plane based on accelerometer
int OCT_TM_top_plane();
int OCT_TM_bottom_plane();
```

## Utility

```c
// Random integer in range [dmin, dmax)
int OCT_random(int dmin, int dmax);

// Debug logging
void OCT_trace(int level, const char* fmt, ...);
```

## Event Handlers (WASM_EXPORT)

```c
// Called once at app start. Initialize engine, load resources, set up scene.
WASM_EXPORT void on_init();

// Called every frame (~20 FPS, 50ms/tick). Game loop logic.
WASM_EXPORT void on_tick();

// Called on face tap. tapid = plane index [0-5].
WASM_EXPORT void on_tap(int32_t tapid);

// Called when twist begins. Prepare state for incoming twist.
WASM_EXPORT void on_pretwisted(int32_t twid);

// Called when twist completes.
// twid 0-11: full twists, twid 12-23: half twists (offset by OCT_TWIST_HALF)
// disconnected_ms: time elapsed since last connection during twist
WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms);
```

## Twist Reference

**Full twists (twid 0-11):**

| twid | Constant | Direction |
|------|----------|-----------|
| 0 | TOP_CCW | Top face counter-clockwise |
| 1 | TOP_CW | Top face clockwise |
| 2 | FRONT_CCW | Front face counter-clockwise |
| 3 | FRONT_CW | Front face clockwise |
| 4 | RIGHT_CCW | Right face counter-clockwise |
| 5 | RIGHT_CW | Right face clockwise |
| 6 | BACK_CCW | Back face counter-clockwise |
| 7 | BACK_CW | Back face clockwise |
| 8 | LEFT_CCW | Left face counter-clockwise |
| 9 | LEFT_CW | Left face clockwise |
| 10 | BOTTOM_CCW | Bottom face counter-clockwise |
| 11 | BOTTOM_CW | Bottom face clockwise |

**Half twists:** twid 12-23, same order, offset by `OCT_TWIST_HALF`.

## Sprite Properties Quick Reference

| Property | Type | Description |
|----------|------|-------------|
| `Idx` | int | Object ID (equals index in gObjects when valid) |
| `Tm` | octTm_t | Transform (Plane, X, Y, A) |
| `Hidden` | bool | Visibility flag |
| `Paused` | bool | Animation pause flag |
| `Loop` | bool | Animation looping flag |
| `Parent` | int | Parent object Idx (used by label glyphs) |
| `Layer` | int | Rendering layer |

## Common Patterns

### Object validation
```c
if (obj->Idx != i) continue; // Skip invalid objects
```

### Iterating all valid objects
```c
for (size_t i = 1; i < SPRITES_CAP; i++) { // Start at 1, gObjects[0] is invalid
    appObject_t* obj = &gObjects[i];
    if (obj->Idx != i) continue;
    // ... use obj
}
```

### Finding object in a specific quad
```c
for (size_t i = 1; i < SPRITES_CAP; i++) {
    appObject_t* obj = &gObjects[i];
    if (obj->Idx != i) continue;
    if ((size_t)OCT_TM_quad(&obj->Tm) == targetQuad) return obj;
}
```

### Placing sprite at quad center
```c
int16_t localQuad = quad % OCT_QUADS_AT_PLANE;
int16_t plane = quad / OCT_QUADS_AT_PLANE;
float x = (120.f + GAP) * XSIGN[localQuad];
float y = (120.f + GAP) * YSIGN[localQuad];
OCT_add(layer, twistable, plane, x, y, 0, false, bmp, bmp, 0);
```

## Performance Notes

- Keep total sprite count well under SPRITES_CAP (400)
- All game logic must complete within one tick (~50ms)
- Iterating all 400 gObjects slots is acceptable but avoid doing it many times per tick
- For games needing frequent spatial queries, consider maintaining a quad-indexed lookup array
