# Party Bombs: Бомбокуб Дефьюз — Implementation Prompts

## Overview
- Source GDD: `plans/party_bombs_gdd.md`
- Total prompts: 23
- Estimated total sprites: ~64 unique assets (44 bomb states + explosion frames + UI)
- Max sprites on screen simultaneously: ~60 (well within SPRITES_CAP = 400)
- API reference: `OCT_wowcube-agent-skills/templates/app_ai_template.h`

---

## Prompt 1: Foundation — Data Structures and Engine Init

### Category
foundation

### Dependencies
none

### Current State
None — fresh project. Copy skeleton from `OCT_wowcube-agent-skills/src/app_structure_example.h` to `src/app_party_bombs.h`.

### Goal
Set up the game data structures, game state enum, and engine initialization with black background on all 24 screens.

### Instructions

1. Create `src/app_party_bombs.h` based on the skeleton in `OCT_wowcube-agent-skills/src/app_structure_example.h`.

2. Define constants at the top of the file:
   ```
   #define BOMB_TYPES 11        // number of distinct bomb types
   #define BOMB_COUNT 22        // total bombs on cube (2 per type)
   #define SERVICE_QUAD_TIMER 0 // top face, quad index 0 = timer screen
   #define SERVICE_QUAD_STATUS 1 // top face, quad index 1 = status/pass screen
   #define TIMER_START_SECS 180 // 3 minutes
   #define TWIST_FAST_MS 3000   // if disconnected_ms < this = fast twist
   #define CALM_TICKS (3 * OCT_1SEC_TICKS) // 3 seconds to calm down
   ```

3. Define game state enum:
   ```
   typedef enum {
       STATE_TITLE,
       STATE_PLAYING,
       STATE_PASS_PROMPT,  // waiting for player to tap PASS button
       STATE_PASSING,      // cube being physically passed
       STATE_NEXT_CONFIRM, // next player taps to confirm receipt
       STATE_WIN,
       STATE_LOSE,
       STATE_PAUSE
   } GameState;
   ```

4. Define bomb anger level enum:
   ```
   typedef enum {
       ANGER_CALM = 0,
       ANGER_ANGRY = 1,
       ANGER_FURIOUS = 2,
       ANGER_LOVED = 3    // successfully merged — neutralized
   } AngerLevel;
   ```

5. Define the `appObject_t` struct extending `octSprite_t`:
   ```
   typedef struct _appObject_t: octSprite_t {
       int bombType;      // 0-10 = bomb type index; -1 = not a bomb (UI element)
       AngerLevel anger;  // current anger state
       int quadIndex;     // which of the 24 quads this bomb occupies (0-23); -1 = merged/removed
   } appObject_t;
   ```

6. Define the `appvars_t` struct:
   ```
   typedef struct {
       GameState state;
       uint32_t tick;
       int timerSecs;          // countdown seconds remaining
       uint32_t lastTickSec;   // tick when last second was decremented
       int angerLevel;         // global anger level affecting all bombs (0-2)
       uint32_t lastAngerTick; // tick of last rage event (for calm-down timer)
       bool angerPending;      // set true on fast twist, false after 3 sec
       int roundNumber;        // increases each time a player is eliminated
       int penaltyBombType;    // bomb type index that starts angry this round (-1 = none)
       // Board state: which bomb type is in each quad (-1 = empty)
       int board[24];          // bombType per quad; -1 = empty or service quad
       int boardAnger[24];     // AngerLevel per quad
   } appvars_t;
   ```

7. In `on_init()`:
   - Call `OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t))`
   - Call `OCT_viewports_layout(SCHEME_CUBE, GAP, GAP)`
   - Call `OCT_background(0x0000)` — black background
   - Set `vars.state = STATE_TITLE`
   - Set `vars.tick = 0`
   - Set `vars.timerSecs = TIMER_START_SECS`
   - Set `vars.roundNumber = 0`
   - Set `vars.penaltyBombType = -1`
   - Initialize `vars.board[24]` with all -1

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `gObjects[0]` is invalid — always iterate from index 1
- All globals must use the `TL` macro: `TL static appObject_t gObjects[SPRITES_CAP]` and `TL static appvars_t vars`
- `SPRITES_CAP = 400` max objects
- `OCT_PLANES_MAX = 6` planes, `OCT_QUADS_AT_PLANE = 4` quads per plane
- Quads per plane are indexed 0-3 locally; globally: `quadId = localQuad + plane * OCT_QUADS_AT_PLANE`
- TOP plane = `OCT_PLANE_TOP = 0`

### Verification
- Game compiles without errors
- All 24 screens show black background when run in the simulator
- No sprites are visible yet

---

## Prompt 2: Title Screen — Static Layout

### Category
foundation

### Dependencies
[1]

### Current State
Engine initialized, data structures defined, black background on all 24 screens. No sprites visible.

### Goal
Display a static title screen on the front face (4 screens): show a placeholder "БОМБОКУБ ДЕФЬЮЗ" label and a "СТАРТ" label, visible when `STATE_TITLE` is active.

### Instructions

1. Add a function `initTitleScreen()`:
   - Use `OCT_add_label(layer=1, twistable=false, plane=OCT_PLANE_FRONT, x=120.f, y=60.f, angle=0, font=FONT_1, align=ALIGN_CENTER)` to create a title label. Store its index in `vars.titleLabel`.
   - Call `OCT_label_set(label, "BOMBCUBE")` to set the text.
   - Use `OCT_add_label(...)` at `x=120.f, y=180.f` to create a "СТАРТ" label. Store in `vars.startLabel`.
   - Call `OCT_label_set(startLabel, "TAP TO START")` 

2. Add a helper `showLabel(appObject_t* label, bool show)` — copy this utility from `OCT_wowcube-agent-skills/templates/app_ai_template.h` (it toggles the label and all its child glyph sprites).

3. In `on_init()`, after existing init code, call `initTitleScreen()`.

4. In `on_tap(int32_t tapid)`:
   - If `vars.state == STATE_TITLE`: call a new function `startGame()` (to be implemented in Prompt 3).

5. Add stub `void startGame() { vars.state = STATE_PLAYING; }` for now.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details. Do NOT copy demo code.

### Platform Reminders
- Labels use child sprites for each glyph — use `showLabel()` to toggle visibility of label + all children
- `OCT_add_label` returns an index into `gObjects`; store it for later use
- `on_tap` receives `tapid` = plane index (0-5)

### Verification
- Front face shows two text labels: "BOMBCUBE" near top and "TAP TO START" near bottom
- Other faces remain black
- Tapping any face transitions state to `STATE_PLAYING` (nothing else visible yet — that's okay)

---

## Prompt 3: Bomb Placement — Static Board

### Category
foundation

### Dependencies
[1, 2]

### Current State
Title screen shows on front face. Tapping starts the game (transitions to `STATE_PLAYING`).

### Goal
When `STATE_PLAYING` starts, place 22 placeholder bomb sprites on the 22 non-service quads. Use a single placeholder BMP constant for all bombs (real assets come later). Service quads (top face, quads 0 and 1) remain empty.

### Instructions

1. Define the service quads: top face (`OCT_PLANE_TOP = 0`) quads 0 and 1 are service. Global quad IDs: `SERVICE_QUAD_TIMER = 0` (plane 0 × 4 + 0), `SERVICE_QUAD_STATUS = 1` (plane 0 × 4 + 1).

2. Add function `initBoard()`:
   - Build an array of 22 quad IDs that are NOT service quads. These are all global quad IDs from 0 to 23, excluding 0 and 1. So valid bomb quads: {2, 3, 4, 5, 6, 7, ... 23}.
   - Populate `vars.board[24]`: set indices 0 and 1 to -1 (service), randomly assign bomb types 0-10 in pairs across the other 22 slots. Use `OCT_random(0, remaining_count)` to shuffle: create an array of 22 bomb type values (each of 11 types appearing exactly twice), then shuffle using Fisher-Yates with `OCT_random`.
   - For each of the 22 bomb quad IDs, call `OCT_add(layer=0, twistable=true, plane=quadId/4, x=XSIGN[quadId%4]*(120.f+GAP), y=YSIGN[quadId%4]*(120.f+GAP), angle=0, loop=false, bmpfrom=BMP_001, bmpto=BMP_001, framelen=0)`. Store the returned object index. Set `gObjects[idx].bombType = vars.board[quad]`. Set `gObjects[idx].quadIndex = quad`. Set `gObjects[idx].anger = ANGER_CALM`.

3. Call `initBoard()` from `startGame()`.

4. Title screen labels should be hidden when `startGame()` is called: call `showLabel(titleLabel, false)` and `showLabel(startLabel, false)`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for XSIGN/YSIGN coordinate system and `OCT_add` details. Do NOT copy demo code.

### Platform Reminders
- `XSIGN = {+1, -1, -1, +1}`, `YSIGN = {+1, +1, -1, -1}` for local quad positions 0-3
- Quad center coordinates: `x = XSIGN[localQuad] * (120.f + GAP)`, `y = YSIGN[localQuad] * (120.f + GAP)`
- `twistable=true` means the engine moves this sprite when its face row is physically twisted
- `BMP_001` is a placeholder — real bomb sprites will be assigned after assets are created

### Verification
- After tapping the title screen, 22 screens show a placeholder sprite (colored square/shape at BMP_001)
- Top face quads 0 and 1 remain empty (black background)
- Top face quads 2 and 3 also show bomb placeholders
- Twisting a face physically moves the visible sprites to adjacent faces

---

## Prompt 4: Twist — Detect Row of 8 Quads

### Category
core

### Dependencies
[1, 3]

### Current State
22 bomb placeholders are placed on quads. Physical twisting moves sprites via engine. Board state in `vars.board[]` does NOT update yet.

### Goal
In `on_twisted()`, identify which 8 quads are affected by the twist and read their current board content into an ordered row array for processing.

### Instructions

1. Define a mapping function `getRowForTwist(int twid, int row[8])` that, given a twist ID, fills `row[8]` with the 8 global quad IDs affected by that twist, in order from "source end" to "destination end" based on twist direction.

   The twist affects:
   - The 4 quads on the twisted face (in CCW or CW order around the face)
   - The 4 quads on adjacent faces that border the twisted face edge

   For each of the 12 standard twists (`twid` 0-11), define the static 8-quad row. Use the physical layout of the WowCube 2×2 cube:
   - `TOP_CCW` (twid=0): the ring of quads around the top face, ordered CCW
   - `TOP_CW` (twid=1): same ring, ordered CW
   - etc. for all 6 faces × 2 directions

   Define these as `const int TWIST_ROWS[12][8]` static lookup table.

2. In `on_twisted(int32_t twid, uint32_t disconnected_ms)`:
   - If `vars.state != STATE_PLAYING`, return early
   - If `twid >= OCT_TWIST_HALF`, treat as half-twist (same row logic, apply partial shift — for MVP, treat half-twists same as full twists with shift=2 positions instead of 4)
   - Call `getRowForTwist(twid, row)` to get the 8 quad IDs
   - Store the `disconnected_ms` value in `vars.lastTwistMs` for anger detection

3. No board state changes yet — this prompt only establishes the row lookup and saves the timing info.

4. Add `uint32_t lastTwistMs` to `appvars_t`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for twist ID constants and layout. Do NOT copy demo code.

### Platform Reminders
- `twid` 0-11 = standard twists; 12-23 = half-twists (offset by `OCT_TWIST_HALF`)
- The `disconnected_ms` parameter in `on_twisted` is the duration of the twist in milliseconds
- The physical cube layout: 6 faces, each shares edges with 4 neighbors

### Verification
- Add `OCT_trace(0, "twist row: %d %d %d %d %d %d %d %d\n", row[0], row[1], ...)` inside `on_twisted` to log the row
- Twisting each face should log 8 different quad IDs with no duplicates
- The same 8 quads should appear for both CCW and CW of the same face (in reverse order)

---

## Prompt 5: Twist — Slide Bombs Along Row (2048 Style)

### Category
core

### Dependencies
[4]

### Current State
`on_twisted` identifies the 8-quad row and saves timing. Board state still doesn't update.

### Goal
When a twist occurs, slide all bombs in the row toward the "direction end" (like tiles in 2048 sliding toward a wall), updating `vars.board[]` and repositioning sprites accordingly.

### Instructions

1. Add function `slideBombsInRow(int row[8])`:
   - Read current bomb types from `vars.board[row[0..7]]` into a local array `int slots[8]`
   - Apply 2048-style slide toward index 7 (end of row):
     - Compact non-empty values toward end: move all non-(-1) values to rightmost positions, maintaining order
   - Write the resulting `slots[]` back to `vars.board[row[0..7]]`

2. After updating `vars.board`, reposition all bomb sprites to match the new board state:
   - Iterate all `gObjects[i]` with valid `bombType >= 0`
   - For each bomb, find its new quad in the updated `vars.board[]`
   - If the quad changed: use `OCT_TM_change_plane` and set `obj->Tm.X = XSIGN[newQuad%4]*(120.f+GAP)` and `obj->Tm.Y = YSIGN[newQuad%4]*(120.f+GAP)` to move instantly to new position. Update `obj->quadIndex`.

3. Call `slideBombsInRow(row)` in `on_twisted` after getting the row.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_TM_change_plane` and coordinate system. Do NOT copy demo code.

### Platform Reminders
- `OCT_TM_change_plane(octTm_t* tm, int to)` moves a transform to a different plane
- After changing plane, manually set `tm->X` and `tm->Y` to the correct quad center
- The board slide should not move bombs from other rows — only the 8 quads in the given row

### Verification
- Twisting a face causes bombs to slide to the "far end" of the row (away from direction of push)
- A face with 4 bombs and 4 empty slots: after twist, all 4 bombs cluster at one end
- Twisting an already-compacted row does nothing visible

---

## Prompt 6: Twist — Half-Twist Partial Slide

### Category
core

### Dependencies
[5]

### Current State
Full twists slide bombs along the 8-quad row. Half-twists currently treated as full twists.

### Goal
Half-twists shift bombs by 2 positions instead of 4, enabling fine-positioning.

### Instructions

1. Modify `slideBombsInRow` to accept a `shiftAmount` parameter (4 for full twist, 2 for half-twist).

2. For half-twists (`twid >= OCT_TWIST_HALF`):
   - Use the same row lookup but apply a cyclic shift of 2 positions to `vars.board` values along the row, rather than full compaction
   - A cyclic shift of 2: the last 2 elements of the row get the first 2, and vice versa
   - After shifting, reposition sprites as in Prompt 5

3. Update `on_twisted` to pass `shiftAmount = (twid >= OCT_TWIST_HALF) ? 2 : 4`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Half-twist IDs: `twid - OCT_TWIST_HALF` gives the equivalent standard twist ID for row lookup

### Verification
- A half-twist moves bombs by 2 positions in the row
- A full-twist compacts all bombs to the end of the row
- Alternating half-twists back and forth cycles bombs between positions

---

## Prompt 7: Merge Detection — Find Matching Adjacent Pairs

### Category
core

### Dependencies
[5]

### Current State
Full twists slide bombs along rows. Board state tracks bomb positions. No merge logic yet.

### Goal
After each `slideBombsInRow`, detect if any two adjacent quads in the row contain the same bomb type, and if so, merge the pair furthest from the slide direction into one "loved" bomb.

### Instructions

1. Add function `checkMergeInRow(int row[8]) -> int`:
   - Returns the quad index of the merged bomb (-1 if no merge)
   - Scan `vars.board[row[i]]` and `vars.board[row[i+1]]` for adjacent identical types (not -1)
   - When found: set the "kept" quad (the one at the slide destination side) to `ANGER_LOVED` by setting `vars.boardAnger[keptQuad] = ANGER_LOVED`
   - Set the "removed" quad `vars.board[removedQuad] = -1`
   - Find and delete the sprite at the removed quad: iterate `gObjects`, find the one with matching `quadIndex == removedQuad`, call `OCT_del(obj)`
   - Find the sprite at the kept quad and set its anger display (will be visually updated in Prompt 8 — for now just update `vars.boardAnger`)
   - Return the `keptQuad` index

2. Call `checkMergeInRow(row)` in `on_twisted` after `slideBombsInRow`. Store the result in `vars.lastMergedQuad`.

3. Add `int lastMergedQuad` to `appvars_t`.

4. After a successful merge: set `vars.state = STATE_PASS_PROMPT`.

5. Check for win condition: if all 22 non-service quads have `vars.boardAnger[quad] == ANGER_LOVED` or `vars.board[quad] == -1` (all merged), set `vars.state = STATE_WIN`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_del`. Do NOT copy demo code.

### Platform Reminders
- Only one merge per twist (the first matching adjacent pair found from the slide-destination side)
- `OCT_del(octSprite_t* s)` removes a sprite from the scene

### Verification
- After sliding, if two identical bombs are adjacent in the row, one disappears and the other remains
- After a merge, the state changes to `STATE_PASS_PROMPT`
- If all 11 pairs have been merged, state changes to `STATE_WIN`

---

## Prompt 8: Bomb Visual States — Display Anger Per Bomb

### Category
core

### Dependencies
[3, 7]

### Current State
Bombs display as identical placeholders. Merge detection works but all bombs look the same regardless of anger state.

### Goal
Update bomb sprite's displayed BMP based on its `anger` state. Use a mapping table: for each of 11 bomb types × 4 anger states = 44 BMP slots. Since real assets don't exist yet, use placeholder BMP constants mapped sequentially.

### Instructions

1. Define a lookup table `BMP_BOMB[BOMB_TYPES][4]` where index `[type][anger]` returns the BMP constant to use:
   ```
   // Anger index: 0=CALM, 1=ANGRY, 2=FURIOUS, 3=LOVED
   // For MVP with placeholders, use 4 different BMP constants to distinguish states
   // Real asset names from GDD: bomb_round_calm, bomb_round_angry, etc.
   // Requires assets: bomb_round_calm.png, bomb_round_angry.png, ... (44 total)
   // Until assets exist, use BMP_001 (calm), BMP_002 (angry), BMP_003 (furious), BMP_004 (loved)
   const int BMP_BOMB[11][4] = {
       {BMP_001, BMP_002, BMP_003, BMP_004}, // type 0: round
       {BMP_001, BMP_002, BMP_003, BMP_004}, // type 1: grenade
       // ... same placeholders for types 2-10
   };
   ```

2. Add function `updateBombVisual(int quadIndex)`:
   - Find the `appObject_t*` whose `quadIndex == quadIndex`
   - Read `bombType` and `anger` from `vars.board[quad]` and `vars.boardAnger[quad]`
   - Call `OCT_sequence(obj, BMP_BOMB[bombType][anger], BMP_BOMB[bombType][anger], 0, OCT_SEQ_REFRESH)` to update displayed frame

3. Call `updateBombVisual(quad)` for all quads affected by a twist row in `on_twisted`, and for the merged quad after a merge.

4. Call `updateBombVisual(quad)` for all 22 bomb quads in `initBoard()` after placing them.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_sequence`. Do NOT copy demo code.

### Platform Reminders
- `OCT_sequence(spr, from, to, framelen, restart)` updates the animation range; use `OCT_SEQ_REFRESH` to keep current frame if in range
- With placeholders, all bomb types show the same 4 visuals — that's expected until real assets arrive
- Requires assets: 44 bomb state sprites named `bomb_<type>_<state>.png` (see GDD assets section)

### Verification
- All 22 bomb quads show BMP_001 (calm placeholder) initially
- After a merge event, the surviving bomb shows BMP_004 (loved placeholder)
- The anger state change will be visible once Prompt 10 adds anger escalation logic

---

## Prompt 9: Anger System — Fast Twist Detection

### Category
core

### Dependencies
[4, 8]

### Current State
Twists slide and merge bombs. Bomb visuals update based on anger state. No anger escalation yet.

### Goal
Detect fast twists using `disconnected_ms` and increment global anger level when a twist is too fast (under 3 seconds).

### Instructions

1. Add function `triggerAngerEvent()`:
   - Check current global `vars.angerLevel`:
     - If `vars.angerLevel < ANGER_FURIOUS (2)`: increment `vars.angerLevel++`
     - If `vars.angerLevel == ANGER_FURIOUS`: call `triggerExplosion()` (stub for now — Prompt 11)
   - Set `vars.lastAngerTick = vars.tick`
   - Set `vars.angerPending = true`
   - For each bomb quad with `vars.boardAnger[quad] < ANGER_LOVED`:
     - Set `vars.boardAnger[quad] = min(vars.boardAnger[quad]+1, ANGER_FURIOUS)`
     - Call `updateBombVisual(quad)` to update display

2. In `on_twisted()`, after computing slide:
   - If `disconnected_ms < TWIST_FAST_MS`: call `triggerAngerEvent()`

3. In `on_tick()`:
   - Track calm-down timer: if `vars.angerPending == true` and `vars.tick - vars.lastAngerTick >= CALM_TICKS`:
     - Set `vars.angerPending = false`
     - If `vars.angerLevel > 0`: `vars.angerLevel--`
     - For each bomb with `vars.boardAnger[quad] > 0 && boardAnger[quad] < ANGER_LOVED`:
       - `vars.boardAnger[quad]--`
       - `updateBombVisual(quad)`

4. Add stub `void triggerExplosion() { vars.state = STATE_LOSE; }` for now.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `OCT_1SEC_TICKS` is the number of ticks per second (~20)
- `CALM_TICKS = 3 * OCT_1SEC_TICKS`
- The `disconnected_ms` param in `on_twisted` measures how long the twist took

### Verification
- A slow twist (simulate as >3 sec): bombs stay at CALM (BMP_001 placeholder)
- A fast twist: all non-LOVED bombs switch to BMP_002 (angry placeholder)
- Two fast twists in a row: all non-LOVED bombs switch to BMP_003 (furious placeholder)
- After 3 seconds of no fast twists, anger drops one level (visible BMP change)

---

## Prompt 10: Anger System — Accelerometer Shake Detection During Pass

### Category
core

### Dependencies
[9]

### Current State
Fast twist detection works. Calm-down timer works. No accelerometer-based anger for passing yet.

### Goal
During `STATE_PASSING`, use the accelerometer gravity vector to detect a sharp shake/throw. If detected, call `triggerAngerEvent()`.

### Instructions

1. In `on_tick()`, add a block that runs when `vars.state == STATE_PASSING`:
   - Read gravity components: `float gX = OCT_TM_gravity_x(OCT_PLANE_TOP)`, `float gY = OCT_TM_gravity_y(OCT_PLANE_TOP)`, `float gN = OCT_TM_gravity_n(OCT_PLANE_TOP)`
   - Compute magnitude: `float mag = sqrtf(gX*gX + gY*gY + gN*gN)` OR use a simplified version: `float mag = fabsf(gX) + fabsf(gY) + fabsf(gN)` (Manhattan distance, cheaper)
   - Store previous magnitude in `vars.prevGravMag`
   - Compute delta: `float delta = fabsf(mag - vars.prevGravMag)`
   - If `delta > 1.5f` (threshold for sharp movement): call `triggerAngerEvent()`
   - Update `vars.prevGravMag = mag`

2. Add `float prevGravMag` to `appvars_t`, initialize to 1.0f in `startGame()`.

3. The anger-on-pass only applies during `STATE_PASSING` (between PASS_PROMPT tap and NEXT_CONFIRM tap).

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_TM_gravity_x/y/n`. Do NOT copy demo code.

### Platform Reminders
- `OCT_TM_gravity_x/y/n` return gravity components for a given plane — check every tick in `STATE_PASSING`
- The normal/resting magnitude is ~1.0; a throw causes rapid magnitude change

### Verification
- During `STATE_PASSING`, sharply shaking or tilting the cube triggers anger escalation (bomb visuals change)
- A gentle, steady pass does not trigger anger change
- Anger changes are visible via the bomb placeholder BMPs

---

## Prompt 11: Explosion — Chain Reaction and State Transition

### Category
core

### Dependencies
[9, 10]

### Current State
`triggerExplosion()` is a stub that sets `STATE_LOSE`. Anger system calls it correctly.

### Goal
Implement the full explosion sequence: play a 4-frame explosion animation on all bomb quads in sequence, then transition to `STATE_LOSE`.

### Instructions

1. Implement `triggerExplosion()`:
   - Set `vars.state = STATE_LOSE`
   - Set `vars.explosionStep = 0` (wave step counter for chain reaction)
   - Set `vars.explosionStartTick = vars.tick`

2. Add `int explosionStep` and `uint32_t explosionStartTick` to `appvars_t`.

3. In `on_tick()`, handle the chain explosion animation when `vars.state == STATE_LOSE`:
   - Each step activates the explosion animation on one bomb quad, with a 2-tick delay between steps
   - Compute `int step = (vars.tick - vars.explosionStartTick) / 2`
   - If `step < 22` and `step != vars.explosionStep`:
     - `vars.explosionStep = step`
     - Find the bomb sprite at the `step`-th non-service quad
     - Set its animation to the explosion sequence: `OCT_sequence(obj, BMP_001, BMP_004, 2, OCT_SEQ_RESTART)` where BMP_001-BMP_004 are placeholder frames (real: `explosion_frame_1` to `explosion_frame_4`)
     - Requires assets: `explosion_frame_1.png`, `explosion_frame_2.png`, `explosion_frame_3.png`, `explosion_frame_4.png`
   - After all 22 steps complete, show the lose screen (STATE_LOSE display handled in Prompt 19)

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_sequence`. Do NOT copy demo code.

### Platform Reminders
- `OCT_sequence(spr, from, to, framelen, OCT_SEQ_RESTART)` restarts animation from the first frame
- `framelen = 2` means each frame shows for 2 ticks (~100ms at 20 ticks/sec)

### Verification
- When a third fast twist occurs (fury-level rage), a chain explosion animation cascades across all 22 bomb screens
- Each bomb activates its explosion animation 2 ticks after the previous one
- After the last bomb explodes, the state is `STATE_LOSE`

---

## Prompt 12: Pass System — PASS_PROMPT State and Button

### Category
core

### Dependencies
[7]

### Current State
After a successful merge, state changes to `STATE_PASS_PROMPT` but nothing is displayed. Player can't indicate readiness to pass.

### Goal
In `STATE_PASS_PROMPT`, show a "PASS TO FRIEND!" label on the service status quad (top face, quad 1). Tapping top face confirms readiness and moves to `STATE_PASSING`.

### Instructions

1. Add function `showPassButton(bool visible)`:
   - Create/show a label on `OCT_PLANE_TOP` at coordinates for quad 1: `x = XSIGN[1] * (120.f+GAP)`, `y = YSIGN[1] * (120.f+GAP)`
   - Use `OCT_add_label(layer=1, twistable=false, plane=OCT_PLANE_TOP, x, y, angle=0, font=FONT_2, align=ALIGN_CENTER)`
   - Set text to "PASS!" with `OCT_label_set`
   - Store in `vars.passLabel`
   - Toggle visibility based on `visible`

2. When entering `STATE_PASS_PROMPT` (after merge in Prompt 7): call `showPassButton(true)`

3. In `on_tap(int32_t tapid)`:
   - If `vars.state == STATE_PASS_PROMPT` AND `tapid == OCT_PLANE_TOP`:
     - Call `showPassButton(false)`
     - Set `vars.state = STATE_PASSING`
     - Set `vars.prevGravMag = 1.0f` (reset for pass monitoring)

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `OCT_PLANE_TOP = 0`; tapping the top face: `tapid == 0`
- Quad 1 on `OCT_PLANE_TOP` has local coordinates: `XSIGN[1] = -1`, `YSIGN[1] = +1` → `x = -(120+GAP)`, `y = +(120+GAP)`

### Verification
- After a successful merge, a "PASS!" label appears on the top face, quad 1 area
- Tapping the top face hides the label and transitions state to `STATE_PASSING`
- While `STATE_PASS_PROMPT` is active, the bomb positions are frozen (no new twists processed)

---

## Prompt 13: Pass System — Penalty Twist and Next Player Confirm

### Category
core

### Dependencies
[12]

### Current State
`STATE_PASS_PROMPT` shows pass button. Tapping top face moves to `STATE_PASSING`. Accelerometer monitoring is active during `STATE_PASSING` (Prompt 10).

### Goal
(1) In `STATE_PASS_PROMPT`, any twist triggers immediate explosion (penalty). (2) In `STATE_PASSING`, tapping any side face confirms the next player has received the cube.

### Instructions

1. In `on_twisted(int32_t twid, ...)`:
   - Add a check at the TOP of the function: if `vars.state == STATE_PASS_PROMPT`:
     - Call `triggerExplosion()` — penalty for rotating during pass
     - Return immediately

2. In `on_tap(int32_t tapid)`:
   - If `vars.state == STATE_PASSING` AND `tapid != OCT_PLANE_TOP` AND `tapid != OCT_PLANE_BOTTOM`:
     - Set `vars.state = STATE_PLAYING` (next player's turn begins)
     - Show a brief "YOUR TURN!" label on the front face (optional for MVP — show nothing is also fine)

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `OCT_PLANE_BOTTOM = 5`; side faces are planes 1-4
- The penalty twist triggers the full chain explosion sequence from Prompt 11

### Verification
- Rotating ANY face while `STATE_PASS_PROMPT` is active immediately triggers explosion chain
- After `STATE_PASSING`, tapping a side face (not top or bottom) transitions to `STATE_PLAYING`
- The next player can then make a twist to slide bombs

---

## Prompt 14: Timer — Countdown Display

### Category
ui

### Dependencies
[1, 3]

### Current State
No timer display. `vars.timerSecs = 180` initialized but not decremented or shown.

### Goal
Show a countdown timer (MM:SS) on service quad 0 (top face, quad 0). Decrement each second during `STATE_PLAYING`. Timer changes color (placeholder: text changes) as it approaches zero.

### Instructions

1. Add function `initTimer()`:
   - Create a label at top face, quad 0: `x = XSIGN[0]*(120.f+GAP)`, `y = YSIGN[0]*(120.f+GAP)` on `OCT_PLANE_TOP`
   - `OCT_add_label(layer=1, twistable=false, plane=OCT_PLANE_TOP, x, y, angle=0, font=FONT_1, align=ALIGN_CENTER)`
   - Store in `vars.timerLabel`
   - Set text: `"3:00"` initially

2. Add function `updateTimerDisplay()`:
   - Format as `"M:SS"` using `snprintf`
   - Call `OCT_label_set(vars.timerLabel, buf)`

3. In `on_tick()`, when `vars.state == STATE_PLAYING` or `STATE_PASSING` or `STATE_PASS_PROMPT`:
   - If `vars.tick - vars.lastTickSec >= OCT_1SEC_TICKS`:
     - `vars.lastTickSec = vars.tick`
     - `vars.timerSecs--`
     - Call `updateTimerDisplay()`
     - If `vars.timerSecs <= 0`: call `triggerExplosion()`

4. Call `initTimer()` from `startGame()`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `OCT_1SEC_TICKS ≈ 20` ticks per second
- `OCT_add_label` uses fonts FONT_1, FONT_2, FONT_3 — use FONT_1 for the timer (largest)

### Verification
- Top face quad 0 shows "3:00" when `STATE_PLAYING` begins
- Every second, the number decrements: "2:59", "2:58", etc.
- When timer reaches "0:00", explosion chain triggers

---

## Prompt 15: Win Condition — Final Check and WIN State

### Category
core

### Dependencies
[7, 14]

### Current State
Merges are detected and state transitions happen. Timer decrements. No win screen shown.

### Goal
When all 11 pairs have been merged (all 22 bomb slots are either ANGER_LOVED or empty), transition to `STATE_WIN` and stop the timer.

### Instructions

1. Add function `checkWinCondition() -> bool`:
   - Count how many non-service quads have `vars.board[quad] == -1 OR vars.boardAnger[quad] == ANGER_LOVED`
   - If count == 22: return true
   - Return false

2. Call `checkWinCondition()` at the end of `checkMergeInRow()`. If it returns true, override `STATE_PASS_PROMPT` with `STATE_WIN`.

3. In `STATE_WIN`: timer stops (don't decrement in `on_tick`).

4. Win screen display (shown in Prompt 19 — for now, just ensure the state change is correct).

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Win is checked after every merge, not on every tick — this is efficient

### Verification
- When all 22 non-service quads are merged, `vars.state` becomes `STATE_WIN`
- Timer stops decrementing in `STATE_WIN`
- Twist inputs are ignored in `STATE_WIN`

---

## Prompt 16: Round System — Track Penalty Bomb Per Round

### Category
core

### Dependencies
[11, 15]

### Current State
Explosion leads to `STATE_LOSE`. Timer runs out leads to `STATE_LOSE`. Win leads to `STATE_WIN`. No round tracking.

### Goal
When `STATE_LOSE` triggers (explosion only — not timer win), begin a new round: reset board to starting positions, increase `roundNumber`, and make one bomb type start at higher anger.

### Instructions

1. Add function `startNewRound()`:
   - Increment `vars.roundNumber`
   - Determine `vars.penaltyBombType`: in round 1 no penalty, round 2+ pick a bomb type: `vars.penaltyBombType = (vars.roundNumber - 1) % BOMB_TYPES`
   - Reset `vars.timerSecs = TIMER_START_SECS`
   - Re-initialize board with `initBoard()` (same logic as first start, random arrangement)
   - For any bomb of type `vars.penaltyBombType`:
     - Advanced penalty per round: round 2 → `ANGER_ANGRY`, round 3 → `ANGER_FURIOUS`, round 4+ stays FURIOUS (next event = explosion)
     - Apply: after `initBoard()`, scan all quads, find those with `vars.board[quad] == vars.penaltyBombType`, set their `vars.boardAnger[quad]` to the appropriate level
     - Call `updateBombVisual(quad)` for each affected quad
   - Reset `vars.angerLevel = 0`, `vars.angerPending = false`
   - Set `vars.state = STATE_PLAYING`

2. In the tap handler for `STATE_LOSE`: if player taps any face → call `startNewRound()`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Each new round preserves the position randomization (random shuffle each round is fine for MVP)
- The penalty bomb type escalates: round 2 = angry, round 3 = furious (one event = explosion)

### Verification
- After an explosion and tapping, a new round starts with bombs re-arranged
- In round 2, two specific bombs (same type) start visually angry (BMP_002 placeholder)
- In round 3, those same two bombs start furious (BMP_003 placeholder) — one fast twist = explode

---

## Prompt 17: Calm Down — Per-Bomb Anger Over Time

### Category
secondary

### Dependencies
[9, 16]

### Current State
Anger system raises all bomb anger globally. Calm-down timer lowers global anger. Per-bomb tracking exists in `vars.boardAnger[]` but calm-down is global.

### Goal
Make anger calm-down work per-bomb: each bomb individually tracks ticks since last anger event and calms down independently after 3 seconds.

### Instructions

1. Add per-bomb calm-down tracking: add `uint32_t angerTick[24]` to `appvars_t`, initialized to 0 for each quad.

2. Modify `triggerAngerEvent()` to set `vars.angerTick[quad] = vars.tick` for every bomb that was angered.

3. In `on_tick()`, replace global calm-down with per-bomb calm-down:
   - For each non-service, non-empty, non-loved quad:
     - If `vars.boardAnger[quad] > 0` AND `vars.tick - vars.angerTick[quad] >= CALM_TICKS`:
       - `vars.boardAnger[quad]--`
       - `vars.angerTick[quad] = vars.tick` (reset so it takes another 3 sec to calm further)
       - `updateBombVisual(quad)`

4. Remove the old global anger calm-down code from `on_tick`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Per-bomb tracking means each bomb can be at a different anger level simultaneously
- The penalty bomb type from rounds still starts at higher anger at round start (Prompt 16)

### Verification
- Two fast twists: some bombs reach FURIOUS
- After 3 seconds of gentle handling (no fast twists), furious bombs calm to angry
- After another 3 seconds, angry bombs calm to calm
- Calm-down happens per bomb independently (not all at once)

---

## Prompt 18: Calm Meter UI — Stress Indicator on Status Screen

### Category
ui

### Dependencies
[9, 17]

### Current State
Anger system works. Bomb visuals reflect per-bomb anger. No aggregate "stress" indicator visible.

### Goal
Display a "calm meter" on service quad 1 (top face, quad 1) during `STATE_PLAYING`: show a text representation of the current overall stress level (0=CALM, 1=NERVOUS, 2=DANGER).

### Instructions

1. Add function `initCalmMeter()`:
   - Create a label on top face, quad 1: `x = XSIGN[1]*(120.f+GAP)`, `y = YSIGN[1]*(120.f+GAP)`, `OCT_PLANE_TOP`, `FONT_2`, `ALIGN_CENTER`
   - Store in `vars.calmMeterLabel`
   - Set initial text: `"CALM"`
   - This label is shown during `STATE_PLAYING`, hidden during `STATE_PASS_PROMPT` (replaced by pass button label)

2. Add function `updateCalmMeter()`:
   - Compute global stress: find the max `vars.boardAnger[quad]` across all non-loved, non-empty bomb quads
   - If max == 0: text = "CALM"
   - If max == 1: text = "NERVOUS"
   - If max == 2: text = "DANGER!"
   - Call `OCT_label_set(vars.calmMeterLabel, text)`

3. Call `updateCalmMeter()` from `on_tick()` every `OCT_1SEC_TICKS / 2` ticks (10 times per second is sufficient).

4. Call `initCalmMeter()` from `startGame()`.

5. In `showPassButton()`: call `showLabel(vars.calmMeterLabel, !visible)` — hide calm meter when pass button shows, show it otherwise.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Requires assets: `ui_status_calm.png`, `ui_status_warning.png`, `ui_status_danger.png` (for visual version)
- For MVP with text labels only, no image assets needed

### Verification  
- Top face quad 1 shows "CALM" initially
- After a fast twist: shows "NERVOUS" or "DANGER!" depending on resulting anger levels
- After 3 seconds of calm: resets to "CALM"
- When pass button is visible, calm meter text is hidden

---

## Prompt 19: Game Over and Win Screens

### Category
ui

### Dependencies
[11, 15]

### Current State
`STATE_WIN` and `STATE_LOSE` are set correctly. No visual feedback for these states.

### Goal
Show win and lose screens on the front face when `STATE_WIN` or `STATE_LOSE` is reached.

### Instructions

1. Add function `showWinScreen()`:
   - Hide all bomb sprites: iterate `gObjects`, hide any with `bombType >= 0`
   - Show `showLabel(vars.timerLabel, false)` and `showLabel(vars.calmMeterLabel, false)`
   - Create label on `OCT_PLANE_FRONT` at `x=120.f, y=80.f`: `OCT_add_label(layer=2, false, OCT_PLANE_FRONT, 120.f, 80.f, 0, FONT_1, ALIGN_CENTER)`; set text `"DEFUSED!"`
   - Create second label at `y=160.f`: set text `"CUBE SAFE!"`. Store in `vars.winLabel`.
   - Requires assets: `screen_win.png` (optional background image — for MVP, labels only)

2. Add function `showLoseScreen()`:
   - Hide all bomb sprites
   - Create label on `OCT_PLANE_FRONT` at `y=80.f`: text `"BOOM!"`
   - Create label at `y=160.f`: text `"TAP RETRY"`. Store in `vars.loseLabel`.
   - Requires assets: `screen_lose.png` (optional)

3. Call `showWinScreen()` when `vars.state` transitions to `STATE_WIN` and call `showLoseScreen()` when `vars.state` transitions to `STATE_LOSE` and explosion animation completes.

4. In `on_tap()`:
   - `STATE_WIN` → any tap → call `resetGame()` (which calls `initBoard()`, resets timer, sets `STATE_PLAYING`)
   - `STATE_LOSE` → any tap → call `startNewRound()`

5. Add `void resetGame()` which resets `vars.roundNumber = 0`, `vars.penaltyBombType = -1`, and calls `startNewRound()`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `obj->Hidden = true` hides a sprite without deleting it; use `showLabel()` for labels
- The win/lose UI labels use `layer=2` to appear above bombs

### Verification
- When all 11 pairs merged: front face shows "DEFUSED!" and "CUBE SAFE!"
- When timer reaches 0 or explosion occurs: front face shows "BOOM!" and "TAP RETRY"
- Tapping from win screen starts a fresh game; tapping from lose screen starts next round

---

## Prompt 20: Title and Pause Screens

### Category
ui

### Dependencies
[2, 19]

### Current State
Title screen has basic labels. No pause screen. Game flows: Title → Playing → Win/Lose → Playing/Title.

### Goal
Add a functional pause screen (tapping the bottom face during play shows pause options) and polish the title screen layout.

### Instructions

1. Add function `showPauseScreen()`:
   - Set `vars.state = STATE_PAUSE`
   - Create labels on `OCT_PLANE_FRONT`:
     - `y=60.f`: text `"PAUSED"`
     - `y=120.f`: text `"TAP: RESUME"` — store in `vars.pauseResumeLabel`
     - `y=180.f`: text `"HOLD: MENU"` — store in `vars.pauseMenuLabel`
   - Stop timer (don't decrement in `STATE_PAUSE`)

2. Add function `hidePauseScreen()`:
   - Delete pause labels with `OCT_del`
   - Set `vars.state = STATE_PLAYING`

3. In `on_tap()`:
   - `STATE_PLAYING` or `STATE_PASS_PROMPT`: if `tapid == OCT_PLANE_BOTTOM` → call `showPauseScreen()`
   - `STATE_PAUSE`: if tap on any face → call `hidePauseScreen()`

4. Improve title screen (from Prompt 2):
   - Add a third label with `y=210.f`: text `"GO SLOW!"` as a hint
   - Requires assets: `screen_title.png` (optional background)

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- `OCT_PLANE_BOTTOM = 5`
- Pause should freeze the timer and all game logic

### Verification
- Tapping the bottom face during play shows "PAUSED", "TAP: RESUME", "HOLD: MENU" on front face
- Tapping any face while paused resumes the game
- Title screen shows all three text lines

---

## Prompt 21: Audio — Core Sound Effects

### Category
audio

### Dependencies
[9, 11, 7]

### Current State
No sound effects. All game events are silent.

### Goal
Add sound effects for: successful merge, bomb anger escalation, and explosion.

### Instructions

1. In `checkMergeInRow()`, after a successful merge: play `merge_success.mp3`:
   - `int32_t sndId = SND_getAssetId("merge_success.mp3")`
   - `SND_play(sndId, 80)`
   - Requires asset: `merge_success.mp3`

2. In `triggerAngerEvent()`, when anger escalates: play `bomb_angry.mp3`:
   - `SND_play(SND_getAssetId("bomb_angry.mp3"), 70)`
   - Requires asset: `bomb_angry.mp3`

3. In `triggerExplosion()`: play `explosion.mp3`:
   - `SND_play(SND_getAssetId("explosion.mp3"), 100)`
   - Requires asset: `explosion.mp3`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `SND_getAssetId` and `SND_play`. Do NOT copy demo code.

### Platform Reminders
- `SND_getAssetId("filename.mp3")` returns an ID for the sound file
- `SND_play(id, volume)` plays the sound; volume range 0-100
- All MP3s are created manually by a human — this prompt only adds the `SND_play` calls

### Verification
- Merging two bombs plays a sound (you should hear it)
- A fast twist plays an anger sound
- An explosion (three fast twists or timer zero) plays a loud explosion sound

---

## Prompt 22: Audio — Timer Tick and Win/Lose Jingles

### Category
audio

### Dependencies
[14, 19, 21]

### Current State
Merge, anger, and explosion sounds work. Timer is silent. Win/lose screens are silent.

### Goal
Add countdown ticking in the last 10 seconds, and win/lose jingles.

### Instructions

1. In `on_tick()`, inside the timer countdown block when `vars.state == STATE_PLAYING`:
   - If `vars.timerSecs <= 10` AND `vars.timerSecs > 0`:
     - Every `OCT_1SEC_TICKS` ticks, play `timer_tick.mp3`: `SND_play(SND_getAssetId("timer_tick.mp3"), 60)`
   - Requires asset: `timer_tick.mp3`

2. In `showWinScreen()`: play `jingle_win.mp3`:
   - `SND_play(SND_getAssetId("jingle_win.mp3"), 90)`
   - Requires asset: `jingle_win.mp3`

3. In `showLoseScreen()`: play `jingle_lose.mp3`:
   - `SND_play(SND_getAssetId("jingle_lose.mp3"), 90)`
   - Requires asset: `jingle_lose.mp3`

4. In `showPassButton(true)`: play `pass_unlock.mp3`:
   - `SND_play(SND_getAssetId("pass_unlock.mp3"), 60)`
   - Requires asset: `pass_unlock.mp3`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h`. Do NOT copy demo code.

### Platform Reminders
- Assets required: `timer_tick.mp3`, `jingle_win.mp3`, `jingle_lose.mp3`, `pass_unlock.mp3`

### Verification
- In the final 10 seconds, a tick sound plays once per second
- Winning plays an upbeat jingle
- Losing plays a down/fail jingle
- Pass button appearance plays a small unlock sound

---

## Prompt 23: Polish — Merge Animation and Bomb Slide Smoothness

### Category
polish

### Dependencies
[5, 7, 8]

### Current State
Bomb slides are instant (teleport to new position). Merge is instant (one bomb disappears). All visuals are functional but abrupt.

### Goal
Add smooth slide animation for bomb movement and a merge flash effect when two bombs neutralize.

### Instructions

1. **Smooth bomb slide animation**:
   - Instead of instantly repositioning bombs in `slideBombsInRow`, use `OCT_TM_lerp` over ~5 ticks (0.25 sec):
     - Before changing position, store the source transform: `OCT_TM_copy(&obj->animStart, &obj->Tm)`
     - Compute destination transform: copy to `animEnd`, then `OCT_TM_change_plane` and set X/Y
     - Store `vars.slideAnimStartTick = vars.tick` and `vars.isSliding = true`
   - In `on_tick()` during slide animation:
     - `float progress = (vars.tick - vars.slideAnimStartTick) / 5.0f`
     - `OCT_TM_lerp(&obj->Tm, &obj->animStart, &obj->animEnd, progress)`
     - When `progress >= 1.0f`: finalize position, set `vars.isSliding = false`, then check for merges
   - Block new twists while `vars.isSliding == true`

2. **Merge flash effect**:
   - When merge detected: before deleting the removed bomb sprite, briefly set its BMP to `BMP_004` (loved/heart placeholder) for 5 ticks
   - Store `vars.mergeFlashTick = vars.tick` and `vars.mergeFlashQuad = removedQuad`
   - In `on_tick()`: after 5 ticks, delete the removed sprite and fully update the kept sprite to ANGER_LOVED visual

3. Add `bool isSliding` and `uint32_t slideAnimStartTick` to `appvars_t`. Add `appObject_t animStart` and `appObject_t animEnd` per-bomb (or global temporary storage for the sliding bomb objects).

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for `OCT_TM_lerp`, `OCT_TM_copy`. Do NOT copy demo code.

### Platform Reminders
- `OCT_TM_lerp(tm, a, b, t)` interpolates between two transforms including cross-plane handling
- `OCT_TM_copy(dst, src)` copies a full transform
- While sliding, block `on_twisted` processing to prevent mid-animation input

### Verification
- Twisting a face: bombs smoothly slide to their new positions over ~0.25 seconds instead of teleporting
- When two bombs merge: a brief flash/glow appears before one disappears
- The animation does not block faster testers — confirm it runs in ~5 ticks total
