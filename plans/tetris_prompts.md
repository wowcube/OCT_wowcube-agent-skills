# CubeTetris — Implementation Prompts

## Overview
- Source GDD: `plans/tetris_gdd.md`
- Total prompts: 16
- Estimated total sprites: ~380 worst case (360 filled cells + 4 active piece + labels + arrow)
- API reference: `OCT_wowcube-agent-skills/templates/app_ai_template.h`

### Assets required (created manually by humans)
- `cell_filled` — white square 24×24px with 1px black border (filled cell on side face)
- `cell_active` — white square 24×24px with 2px white outline on black (active falling piece cell)
- `arrow_indicator` — white arrow 48×48px (direction indicator on top face)
- Fonts: `font_1` already available in template assets

### Architecture Notes

**Grid representation:** The game board uses a boolean array `grid[4][10][10]` for collision checks and a parallel sprite ID array `gridSpriteIds[4][10][10]` for visual management. Side index 0=FRONT, 1=RIGHT, 2=BACK, 3=LEFT.

**Sprite strategy:** Filled cells and active piece cells are individual sprites (`twistable=false`). This approach keeps logic simple. Worst-case sprite count is ~380, within the 400 limit.

**Coordinate system for grid:** Each side face has a 10×10 grid. 5 columns per quad horizontally, 5 rows per quad vertically. Cell center coordinates:
- `CELL_X[10] = {-126, -102, -78, -54, -30, 30, 54, 78, 102, 126}`
- `CELL_Y[10] = {-126, -102, -78, -54, -30, 30, 54, 78, 102, 126}`
- Column 0 at X=-126 (leftmost), Column 9 at X=126 (rightmost)
- Row 0 at Y=-126 (bottom), Row 9 at Y=126 (top)
- Formula: `coordinate = (GAP + 12 + 24 * index) * sign`, where sign is -1 for indices 0-4, +1 for indices 5-9, and index within the half is `i % 5`

**Piece representation:** Each tetromino has 4 cells defined as relative offsets `(relCol, relRow)` from the piece origin `(pieceCol, pieceRow)`. Grid position of each cell: `gridCol = pieceCol + relCol`, `gridRow = pieceRow - relRow` (relRow increases downward in bounding box, gridRow increases upward on screen).

**Side face plane mapping:** `SIDE_PLANES[4] = {OCT_PLANE_FRONT, OCT_PLANE_RIGHT, OCT_PLANE_BACK, OCT_PLANE_LEFT}`

---

## Prompt 1: Foundation — Scaffold, Data Structures, Engine Init

### Category
foundation

### Dependencies
none

### Current State
None — fresh project. Skeleton copied from `OCT_wowcube-agent-skills/src/app_structure_example.h` to `src/app_tetris.h`.

### Goal
Create the project scaffold with all data structures, constants, tetromino shape definitions, and engine initialization. The cube should display a black background on all 24 screens.

### Instructions

1. Copy `src/app_structure_example.h` to `src/app_tetris.h`. Change the include from `app_test_ids.h` to `app_tetris_ids.h`.

2. Define constants:
   ```
   #define GRID_COLS 10
   #define GRID_ROWS 10
   #define CELL_SIZE 24
   #define NUM_SIDES 4
   #define NUM_PIECE_CELLS 4
   #define NUM_PIECE_TYPES 7
   #define NUM_ROTATIONS 4
   #define FALL_INTERVAL_TICKS (OCT_1SEC_TICKS)  // 1 second per drop
   #define DOUBLETAP_WINDOW (OCT_1SEC_TICKS / 2) // 0.5 sec for double-tap
   ```

3. Define game state constants:
   ```
   #define STATE_MENU 0
   #define STATE_CHOOSING 1
   #define STATE_FALLING 2
   #define STATE_LINE_CLEAR 3
   #define STATE_GAME_OVER 4
   ```

4. Define side-to-plane mapping:
   ```
   static const int SIDE_PLANES[NUM_SIDES] = {OCT_PLANE_FRONT, OCT_PLANE_RIGHT, OCT_PLANE_BACK, OCT_PLANE_LEFT};
   ```

5. Define coordinate lookup arrays:
   ```
   static const float CELL_X[GRID_COLS] = {-126.f, -102.f, -78.f, -54.f, -30.f, 30.f, 54.f, 78.f, 102.f, 126.f};
   static const float CELL_Y[GRID_ROWS] = {-126.f, -102.f, -78.f, -54.f, -30.f, 30.f, 54.f, 78.f, 102.f, 126.f};
   ```

6. Define the 7 tetromino shapes as a 4D array `pieceShapes[7][4][4][2]` where dimensions are: [type][rotation][cell][0=relCol, 1=relRow]. Use standard SRS rotation. The shapes within a bounding box (relRow 0 = top of bounding box, increases downward):

   **I-piece (type 0):**
   - Rot 0: (0,1)(1,1)(2,1)(3,1)
   - Rot 1: (2,0)(2,1)(2,2)(2,3)
   - Rot 2: (0,2)(1,2)(2,2)(3,2)
   - Rot 3: (1,0)(1,1)(1,2)(1,3)

   **O-piece (type 1):** all rotations same:
   - (1,0)(2,0)(1,1)(2,1)

   **T-piece (type 2):**
   - Rot 0: (1,0)(0,1)(1,1)(2,1)
   - Rot 1: (1,0)(1,1)(2,1)(1,2)
   - Rot 2: (0,1)(1,1)(2,1)(1,2)
   - Rot 3: (1,0)(0,1)(1,1)(1,2)

   **S-piece (type 3):**
   - Rot 0: (1,0)(2,0)(0,1)(1,1)
   - Rot 1: (1,0)(1,1)(2,1)(2,2)
   - Rot 2: (1,1)(2,1)(0,2)(1,2)
   - Rot 3: (0,0)(0,1)(1,1)(1,2)

   **Z-piece (type 4):**
   - Rot 0: (0,0)(1,0)(1,1)(2,1)
   - Rot 1: (2,0)(1,1)(2,1)(1,2)
   - Rot 2: (0,1)(1,1)(1,2)(2,2)
   - Rot 3: (1,0)(0,1)(1,1)(0,2)

   **L-piece (type 5):**
   - Rot 0: (2,0)(0,1)(1,1)(2,1)
   - Rot 1: (1,0)(1,1)(1,2)(2,2)
   - Rot 2: (0,1)(1,1)(2,1)(0,2)
   - Rot 3: (0,0)(1,0)(1,1)(1,2)

   **J-piece (type 6):**
   - Rot 0: (0,0)(0,1)(1,1)(2,1)
   - Rot 1: (1,0)(2,0)(1,1)(1,2)
   - Rot 2: (0,1)(1,1)(2,1)(2,2)
   - Rot 3: (1,0)(1,1)(0,2)(1,2)

7. Define `appObject_t` extending `octSprite_t` — no extra fields needed.

8. Define `appvars_t` with fields:
   ```
   uint32_t tick;
   int gameState;
   int score;

   // Board: filled cell flags and sprite IDs
   bool grid[NUM_SIDES][GRID_COLS][GRID_ROWS];
   int32_t gridSpriteIds[NUM_SIDES][GRID_COLS][GRID_ROWS];

   // Active piece
   int pieceType;       // 0-6
   int pieceRotation;   // 0-3
   int pieceSide;       // 0-3 (FRONT/RIGHT/BACK/LEFT)
   int pieceCol;        // column of bounding box origin
   int pieceRow;        // row of bounding box top-left (in grid coords)
   int32_t pieceSpriteIds[NUM_PIECE_CELLS];

   // Fall timer
   uint32_t lastFallTick;

   // Double-tap detection
   uint32_t lastTapTick;
   int lastTapPlane;

   // Labels
   appObject_t* scoreLabel;
   appObject_t* titleLabel;

   // Line clear animation
   int clearRows[GRID_ROWS];
   int clearRowCount;
   int blinkCount;
   uint32_t blinkTick;
   ```

9. In `on_init()`:
   - Call `OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t))`
   - Call `OCT_viewports_layout(SCHEME_CUBE, GAP, GAP)`
   - Call `OCT_background(0x0000)` — black background
   - Set `vars.tick = 0`
   - Set `vars.gameState = STATE_MENU`
   - Set `vars.score = 0`
   - Initialize all `vars.grid[s][c][r] = false` and `vars.gridSpriteIds[s][c][r] = 0`

10. In `on_tick()`: increment `vars.tick++`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- All globals must use the `TL` macro
- gObjects[0] is invalid — start iteration from index 1
- SPRITES_CAP = 400 max objects

### Verification
- You should see a black background on all 24 screens (6 faces × 4 quads each)
- No sprites visible, no errors in console

---

## Prompt 2: Score Label on Top Face

### Category
foundation

### Dependencies
[1]

### Current State
Project scaffold exists with all data structures and black background. No visual elements yet.

### Goal
Display the score as a text label centered on the top face. The label should show "0" initially.

### Instructions

1. Add a utility function `showLabel(appObject_t* label, bool show)` — copy from API template. It iterates `gObjects[1..SPRITES_CAP-1]`, finds children where `obj->Parent == label->Idx`, and sets `Hidden = !show` on label and all children.

2. In `on_init()`, after engine setup, create the score label:
   ```
   int32_t id = OCT_add_label(1, false, OCT_PLANE_TOP, 0.f, 0.f, 0, FONT_1, ALIGN_CENTER);
   vars.scoreLabel = &gObjects[id];
   OCT_label_set(vars.scoreLabel, "0");
   ```

3. Add a helper function `updateScoreLabel()`:
   - Format `vars.score` into a char buffer using `snprintf(buf, 12, "%d", vars.score)`
   - Call `OCT_label_set(vars.scoreLabel, buf)`

4. Call `updateScoreLabel()` from `on_init()` after creating the label.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_add_label` returns index in gObjects; store pointer as `&gObjects[id]`
- `OCT_label_set` skips update if text hasn't changed
- Label child glyphs need to be toggled separately for visibility (use `showLabel`)
- Font options: FONT_1, FONT_2, FONT_3

### Verification
- You should see "0" displayed in white text at the center of the top face
- All other screens remain black

---

## Prompt 3: Spawn Active Piece on Side Face

### Category
core

### Dependencies
[1, 2]

### Current State
Black background on all faces, "0" score label on top face. Data structures defined but no gameplay logic yet.

### Goal
Spawn a random tetromino at the top of the FRONT side face, visible as 4 white sprites. For now, the piece is static — it does not fall or respond to input.

### Instructions

1. Create a helper function `int getPiecePlane(int sideIdx)` that returns `SIDE_PLANES[sideIdx]`.

2. Create a helper function `void getCellCoords(int sideIdx, int col, int row, int* plane, float* x, float* y)`:
   - Set `*plane = SIDE_PLANES[sideIdx]`
   - Set `*x = CELL_X[col]`
   - Set `*y = CELL_Y[row]`

3. Create function `void spawnPiece()`:
   - Set `vars.pieceType = OCT_random(0, NUM_PIECE_TYPES)` — random piece type
   - Set `vars.pieceRotation = 0`
   - Set `vars.pieceSide = 0` — FRONT face for now (hardcoded)
   - Set `vars.pieceCol = 3` — centered horizontally
   - Set `vars.pieceRow = 9` — top of grid
   - Call `createPieceSprites()`

4. Create function `void createPieceSprites()`:
   - For each cell `i` in 0..3:
     - Get relative offsets: `relCol = pieceShapes[vars.pieceType][vars.pieceRotation][i][0]`, `relRow = pieceShapes[vars.pieceType][vars.pieceRotation][i][1]`
     - Compute grid position: `col = vars.pieceCol + relCol`, `row = vars.pieceRow - relRow`
     - Get screen coordinates: call `getCellCoords(vars.pieceSide, col, row, &plane, &x, &y)`
     - Create sprite: `vars.pieceSpriteIds[i] = OCT_add(1, false, plane, x, y, 0, false, BMP_001, BMP_001, 0)`
       - Note: `BMP_001` is a placeholder. Requires asset: `cell_active` (24×24px white square with outline)
   - Set `vars.lastFallTick = vars.tick`

5. Create function `void deletePieceSprites()`:
   - For each cell `i` in 0..3:
     - If `vars.pieceSpriteIds[i] != 0`:
       - `OCT_del(&gObjects[vars.pieceSpriteIds[i]])`
       - `vars.pieceSpriteIds[i] = 0`

6. Create function `void updatePieceSprites()`:
   - Call `deletePieceSprites()`
   - Call `createPieceSprites()`

7. Call `spawnPiece()` in `on_init()` after score label setup. Set `vars.gameState = STATE_FALLING`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_add` returns index in gObjects (int32_t); store this ID for later deletion
- Use `twistable=false` — game logic controls piece position, not the twist engine
- `OCT_random(dmin, dmax)` returns random int in [dmin, dmax)
- gObjects[0] is invalid — do not use index 0

### Verification
- You should see 4 white squares near the top of the FRONT side face, forming one of the 7 tetromino shapes
- The "0" score label remains visible on the top face
- Restarting the app should show a different random shape each time

---

## Prompt 4: Piece Gravity — Falling

### Category
core

### Dependencies
[1, 2, 3]

### Current State
A static tetromino is visible at the top of the FRONT face. Score "0" on top face.

### Goal
The active piece falls downward by one cell at a regular interval (every `FALL_INTERVAL_TICKS` ticks). The piece will fall past the bottom of the grid (no collision yet).

### Instructions

1. In `on_tick()`, after `vars.tick++`, add game logic:
   - If `vars.gameState == STATE_FALLING`:
     - If `vars.tick - vars.lastFallTick >= FALL_INTERVAL_TICKS`:
       - Decrement `vars.pieceRow` by 1
       - Call `updatePieceSprites()`
       - Set `vars.lastFallTick = vars.tick`

Note: At this stage, the piece will fall indefinitely past row 0 and eventually the sprites will be placed off-screen with invalid coordinates. This is expected — collision is added in Prompt 5.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_1SEC_TICKS` is the number of ticks in one second (~20 ticks at 50ms per tick)
- All game logic in `on_tick()` runs every frame

### Verification
- You should see the tetromino piece on the FRONT face move downward by one cell approximately every 1 second
- The piece eventually disappears below the visible grid area (this is expected)
- Score "0" remains on the top face

---

## Prompt 5: Floor Collision + Piece Landing + Respawn

### Category
core

### Dependencies
[1, 2, 3, 4]

### Current State
Piece falls downward at regular intervals on the FRONT face, but passes through the floor.

### Goal
The piece stops when it reaches the bottom of the grid (row 0). It "fixes" — its cells are recorded in the grid array, filled cell sprites are created, and a new piece spawns at the top.

### Instructions

1. Create a collision check function `bool canPieceFit(int side, int col, int row, int type, int rotation)`:
   - For each cell `i` in 0..3:
     - Compute: `c = col + pieceShapes[type][rotation][i][0]`, `r = row - pieceShapes[type][rotation][i][1]`
     - If `c < 0 || c >= GRID_COLS || r < 0 || r >= GRID_ROWS` → return false (outside bounds)
     - If `vars.grid[side][c][r] == true` → return false (cell occupied)
   - If all cells pass → return true

2. Modify the fall logic in `on_tick()`:
   - Before decrementing `vars.pieceRow`, check: `if (!canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow - 1, vars.pieceType, vars.pieceRotation))`
   - If the piece CANNOT fit one row lower → call `fixPiece()` then `spawnPiece()`
   - If it CAN fit → decrement `vars.pieceRow`, call `updatePieceSprites()`, update `vars.lastFallTick`

3. Create function `void fixPiece()`:
   - For each cell `i` in 0..3:
     - Compute grid position: `c = vars.pieceCol + pieceShapes[vars.pieceType][vars.pieceRotation][i][0]`, `r = vars.pieceRow - pieceShapes[vars.pieceType][vars.pieceRotation][i][1]`
     - Set `vars.grid[vars.pieceSide][c][r] = true`
     - Get screen coords: `getCellCoords(vars.pieceSide, c, r, &plane, &x, &y)`
     - Create filled cell sprite: `vars.gridSpriteIds[vars.pieceSide][c][r] = OCT_add(0, false, plane, x, y, 0, false, BMP_001, BMP_001, 0)`
       - Note: `BMP_001` is placeholder. Requires asset: `cell_filled` (24×24px white square with black border)
       - Use layer 0 for filled cells (below active piece on layer 1)
   - Call `deletePieceSprites()` to remove active piece sprites

4. Modify `spawnPiece()` to set `vars.lastFallTick = vars.tick` for the newly spawned piece.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- Use layer 0 for filled cells and layer 1 for active piece — this ensures the active piece renders on top
- `OCT_add` returns 0 if the scene is full (SPRITES_CAP reached) — handle gracefully
- Each active piece sprite must be deleted before creating filled cell sprites to avoid exceeding the budget

### Verification
- You should see the piece fall down the FRONT face and stop at the bottom row
- After stopping, the piece's cells remain visible as filled cells (static sprites)
- A new random piece appears at the top of the FRONT face and begins falling
- Multiple pieces should stack up over time, with each piece stopping at the bottom or on top of previous pieces

---

## Prompt 6: Horizontal Movement + Wall Collision

### Category
core

### Dependencies
[1, 2, 3, 4, 5]

### Current State
Pieces fall on the FRONT face, land at the bottom, fix, and new pieces spawn. No player input yet.

### Goal
Horizontal half-twists (left/right) move the active piece by one column. The piece cannot move past the grid edges (columns 0-9).

### Instructions

1. Create function `void movePiece(int direction)` where direction is -1 (left) or +1 (right):
   - If `vars.gameState != STATE_FALLING` → return
   - Compute new column: `newCol = vars.pieceCol + direction`
   - Check: `if (canPieceFit(vars.pieceSide, newCol, vars.pieceRow, vars.pieceType, vars.pieceRotation))`
     - If valid: set `vars.pieceCol = newCol`, call `updatePieceSprites()`

2. In `on_twisted(int32_t twid, uint32_t disconnected_ms)`, decode the twist:
   - Half-twists have `twid >= OCT_TWIST_HALF` (twid 12-23)
   - Compute: `int halfId = twid - OCT_TWIST_HALF` → gives range 0-11
   - `int twistPlane = halfId / 2` → which plane's ring was twisted
   - `int twistDir = halfId % 2` → 0 = CCW, 1 = CW
   - For horizontal movement of a piece on a side face, the relevant half-twists are those that rotate the horizontal ring (TOP or BOTTOM plane twists):
     - If `twistPlane == OCT_PLANE_TOP || twistPlane == OCT_PLANE_BOTTOM`:
       - CW → `movePiece(1)` (move right)
       - CCW → `movePiece(-1)` (move left)

Note: This mapping works correctly for the FRONT face. For other side faces, the CW/CCW direction may need adjustment relative to the player's perspective. For MVP, this simplified mapping is acceptable.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_TWIST_HALF` = 12 (offset for half-twist IDs)
- Twist IDs: 0-11 = full twists, 12-23 = half twists
- Twist enumeration: plane*2 + direction (0=CCW, 1=CW)
- twid range: TOP_CCW=0, TOP_CW=1, FRONT_CCW=2, FRONT_CW=3, RIGHT_CCW=4, RIGHT_CW=5, BACK_CCW=6, BACK_CW=7, LEFT_CCW=8, LEFT_CW=9, BOTTOM_CCW=10, BOTTOM_CW=11

### Verification
- While a piece is falling on the FRONT face, performing a horizontal half-twist (TOP face half-twist) should move the piece one column left or right
- The piece should NOT move past the left edge (column 0) or right edge (column 9)
- The piece should NOT overlap with existing filled cells when moving horizontally
- Movement should be instant (one column per half-twist)

---

## Prompt 7: Piece Rotation + Collision Check

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6]

### Current State
Pieces fall, can be moved horizontally with half-twists, land, fix, and respawn. No rotation yet.

### Goal
Vertical half-twists and full horizontal twists rotate the active piece 90° clockwise. Rotation is blocked if the rotated piece would overlap walls or filled cells.

### Instructions

1. Create function `void rotatePiece()`:
   - If `vars.gameState != STATE_FALLING` → return
   - If `vars.pieceType == 1` → return (O-piece does not rotate)
   - Compute new rotation: `newRot = (vars.pieceRotation + 1) % NUM_ROTATIONS`
   - Check: `if (canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow, vars.pieceType, newRot))`
     - If valid: set `vars.pieceRotation = newRot`, call `updatePieceSprites()`

2. In `on_twisted()`, add rotation triggers:
   - For half-twists (`twid >= OCT_TWIST_HALF`):
     - If `twistPlane` is a side face (FRONT, RIGHT, BACK, LEFT) — these are "vertical" half-twists:
       - Call `rotatePiece()`
   - For full twists (`twid < OCT_TWIST_HALF`):
     - Compute: `int fullPlane = twid / 2`, `int fullDir = twid % 2`
     - If `fullPlane == OCT_PLANE_TOP || fullPlane == OCT_PLANE_BOTTOM` — horizontal full twist:
       - Call `rotatePiece()`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- O-piece (type 1) should not rotate — all rotations are identical
- `canPieceFit` already checks both bounds and filled cells, so rotation collision is handled
- Full twists are twid 0-11, half twists are twid 12-23

### Verification
- While a piece is falling, a vertical half-twist (e.g., FRONT face half-twist) should rotate the piece 90° clockwise
- A full horizontal twist (TOP face full twist) should also rotate the piece
- The O-piece (square) should not visually change when a rotation is attempted
- Rotation should be blocked if the rotated shape would go outside the grid or overlap filled cells
- The piece should snap to its new rotated position instantly

---

## Prompt 8: Cell Collision — Stacking

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6, 7]

### Current State
Pieces fall, move horizontally, rotate, and land at the bottom of FRONT face. `canPieceFit` already checks filled cells, but stacking behavior needs verification and testing.

### Goal
Confirm and test that falling pieces correctly stop when landing on top of previously fixed pieces, building stacks. This prompt ensures the full stacking loop works reliably.

### Instructions

1. The collision logic in `canPieceFit()` from Prompt 5 already handles cell collision — when `vars.grid[side][c][r] == true`, the piece cannot move there. Verify this works for:
   - Piece landing directly on top of another piece
   - Piece landing next to another piece (side by side)
   - Piece filling a gap between existing cells

2. Test the spawn-fall-fix-respawn loop:
   - Let 5+ pieces fall and accumulate at the bottom of the FRONT face
   - Verify each piece stops at the correct height (on top of previously fixed cells)
   - Verify pieces can be moved horizontally to avoid stacking in the same column

3. Edge case: if a newly spawned piece immediately overlaps filled cells at the spawn position (`canPieceFit` returns false for spawn position), this is a game-over condition. For now, if `canPieceFit` fails at spawn, simply do not spawn (the game will freeze). Game Over handling is added in Prompt 11.

4. Review and fix any bugs in the vertical stacking behavior:
   - Ensure that when a piece is fixed, its cells are correctly recorded in `vars.grid[side][col][row]`
   - Ensure that `canPieceFit` correctly checks the position one row below during fall

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- gObjects[0] is invalid — ensure sprite IDs stored in gridSpriteIds are not 0 for valid sprites
- Maximum filled cells on one side face: 100 (10×10). With 4 faces: 400 filled cells. Budget is tight. Active piece adds 4 more sprites.

### Verification
- Drop 5+ pieces on the FRONT face — each piece should land precisely on top of the previous ones, building a stack from the bottom up
- Moving a piece horizontally and dropping it should land it in the correct column, filling the appropriate row height
- No visual artifacts: filled cells should align perfectly on the grid
- The game loop continues to spawn new pieces after each landing

---

## Prompt 9: Line Detection + Clearing + Score Update

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6, 7, 8]

### Current State
Pieces fall, move, rotate, and stack on the FRONT face. Score displays "0" on top face. No line clearing.

### Goal
After each piece is fixed, check if any horizontal row is completely filled across ALL 4 side faces simultaneously. If so, clear those rows, drop all cells above down by one row per cleared row, and update the score.

### Instructions

1. Create function `void checkAndClearLines()`:
   - For each row `r` from 0 to GRID_ROWS-1:
     - Check if row `r` is full on ALL 4 side faces:
       - For each side `s` in 0..3, for each column `c` in 0..9: `vars.grid[s][c][r]` must be `true`
     - If ALL 4 faces have row `r` completely filled → mark row `r` for clearing
   - Count marked rows (`linesCleared`)
   - If `linesCleared > 0`:
     - Clear each marked row:
       - For each side `s`, for each column `c`:
         - Delete sprite: `OCT_del(&gObjects[vars.gridSpriteIds[s][c][r]])`, set `vars.gridSpriteIds[s][c][r] = 0`
         - Set `vars.grid[s][c][r] = false`
     - Drop cells above cleared rows:
       - Process rows from bottom to top. For each cleared row, shift all rows above it down by 1:
         - For each side `s`, for each column `c`, for rows above the cleared row:
           - Copy `vars.grid[s][c][r+1]` to `vars.grid[s][c][r]`
           - Move sprite: update the sprite's Y coordinate from `CELL_Y[r+1]` to `CELL_Y[r]` by modifying `gObjects[spriteId].Tm.Y`
           - Copy sprite ID reference
         - Clear the topmost row that was shifted out
     - Update score: add points based on `linesCleared`:
       - 1 line = 100, 2 lines = 300, 3 lines = 500, 4 lines = 800
       - `vars.score += {100, 300, 500, 800}[linesCleared - 1]`
     - Call `updateScoreLabel()`

2. Important: when dropping cells, handle the case where multiple non-adjacent rows are cleared simultaneously. Process cleared rows from bottom to top to avoid shifting issues.

3. Call `checkAndClearLines()` in the fix-and-respawn flow: after `fixPiece()` and before `spawnPiece()`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- A row is only cleared when it is full on ALL 4 side faces simultaneously — not just one face
- When moving sprites for the drop animation, modify `gObjects[id].Tm.Y` directly
- If a sprite's Y changes from positive to negative (crossing the quad boundary), the sprite automatically moves to the correct quad based on its coordinates
- Remember that CELL_Y[0] = -126 (bottom) and CELL_Y[9] = 126 (top)

### Verification
- Fill an entire row across all 4 side faces (row 0 on all faces). For initial testing, you may temporarily hardcode all 4 faces' grid rows as filled.
- When the last cell is placed to complete the row, the entire row should disappear on all 4 faces
- All cells above the cleared row should drop down by one row
- The score should update: "100" for one line, "300" for two simultaneous lines
- The score label on the top face should reflect the new score

---

## Prompt 10: Hard Drop — Double-Tap

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6, 7, 8, 9]

### Current State
Full gameplay loop on FRONT face: pieces fall, move, rotate, stack, lines clear, score updates. No hard drop yet.

### Goal
Double-tapping any face instantly drops the active piece to the lowest valid position and fixes it.

### Instructions

1. Create function `void hardDrop()`:
   - If `vars.gameState != STATE_FALLING` → return
   - While `canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow - 1, vars.pieceType, vars.pieceRotation)`:
     - Decrement `vars.pieceRow`
   - Call `updatePieceSprites()` (show piece at final position briefly)
   - Call `fixPiece()`
   - Call `checkAndClearLines()`
   - Call `spawnPiece()`

2. Implement double-tap detection in `on_tap(int32_t tapid)`:
   - If `vars.tick - vars.lastTapTick < DOUBLETAP_WINDOW && vars.lastTapPlane == tapid`:
     - Double-tap detected → call `hardDrop()`
     - Reset: `vars.lastTapTick = 0`
   - Else:
     - `vars.lastTapTick = vars.tick`
     - `vars.lastTapPlane = tapid`

3. Initialize `vars.lastTapTick = 0` in `on_init()`.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `on_tap(int32_t tapid)` receives the plane ID where the tap occurred
- `DOUBLETAP_WINDOW` should be about half a second (~OCT_1SEC_TICKS / 2)
- The hard drop should be immediate — no animation, piece goes straight to final position

### Verification
- While a piece is falling on the FRONT face, double-tapping any face should instantly drop the piece to the lowest valid position
- The piece should land correctly: on the floor or on top of existing cells
- After hard drop, a new piece spawns immediately
- Line clearing should trigger if the hard-dropped piece completes a row

---

## Prompt 11: Game Over Detection

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

### Current State
Complete gameplay loop on FRONT face: fall, move, rotate, stack, clear lines, hard drop, score. No game over detection.

### Goal
Detect when the game should end: if a newly spawned piece cannot fit at the spawn position because the top rows are occupied. Transition to game-over state.

### Instructions

1. Modify `spawnPiece()`:
   - After setting spawn position (type, rotation, col=3, row=9, side), check:
     - `if (!canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow, vars.pieceType, vars.pieceRotation))`
     - If the piece cannot fit → set `vars.gameState = STATE_GAME_OVER`, do NOT create piece sprites, return

2. When `vars.gameState == STATE_GAME_OVER`:
   - In `on_tick()`: skip all game logic (no falling, no input processing)
   - The filled cells remain visible on screen (frozen state)
   - For now, the only way to restart is to relaunch the app. Restart via double-tap is added in Prompt 14.

3. Optionally, use `OCT_trace` to log "GAME OVER" to the console for debugging:
   ```
   OCT_trace(0, "GAME OVER! Score: %d\n", vars.score);
   ```

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- Game over occurs when the spawn position is blocked — check happens in spawnPiece()
- The GDD specifies game over when "top row occupied on any side" — since we currently only use FRONT, check on FRONT. This extends to all sides once tilt-direction is added.
- Do not delete filled cell sprites on game over — they should remain visible

### Verification
- Fill the FRONT face nearly to the top by playing the game normally
- When cells in the top row prevent a new piece from spawning, the game should freeze
- No new pieces should spawn after game over
- The filled cells remain visible on screen in their final positions
- Console should show a "GAME OVER" trace message

---

## Prompt 12: Tilt Direction Choosing + Transfer to Side Face

### Category
core

### Dependencies
[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

### Current State
Full gameplay on FRONT face only. Pieces spawn directly on FRONT. All core mechanics work.

### Goal
Change the piece spawn flow: pieces now appear on the TOP face first. The player tilts the cube to choose which of the 4 side faces the piece falls to. The piece slides toward the tilted edge and transfers to the chosen side face.

### Instructions

1. Modify `spawnPiece()`:
   - Set `vars.gameState = STATE_CHOOSING` (instead of STATE_FALLING)
   - Do NOT set `vars.pieceSide` yet
   - Place piece sprites on `OCT_PLANE_TOP` at center position (x=0, y=0) using 4 sprites
   - The piece is displayed on the top face, centered, awaiting direction choice

2. Create helper function `int detectTiltDirection()`:
   - Read gravity on top face: `float gX = OCT_TM_gravity_x(OCT_PLANE_TOP)`, `float gY = OCT_TM_gravity_y(OCT_PLANE_TOP)`
   - Define a tilt threshold (e.g., `0.3f`) — below this, no tilt detected
   - Determine dominant axis: if `|gX| > |gY|` → horizontal tilt, else vertical tilt
   - Map gravity direction to side face:
     - Positive gX → one side face
     - Negative gX → opposite side face
     - Positive gY → one side face
     - Negative gY → opposite side face
   - The exact mapping depends on the OctaviOS coordinate system. Test empirically:
     - Tilt cube toward FRONT and check which gravity component changes
     - Map accordingly: e.g., +gY → FRONT (0), -gY → BACK (2), +gX → RIGHT (1), -gX → LEFT (3)
   - Return side index (0-3) or -1 if no significant tilt

3. Add a direction indicator arrow on the top face:
   - Add field `int32_t arrowSpriteId` to `appvars_t`
   - In `spawnPiece()`, create the arrow sprite (hidden initially):
     `vars.arrowSpriteId = OCT_add(2, false, OCT_PLANE_TOP, 0.f, -80.f, 0, false, BMP_001, BMP_001, 0)`
     - Note: `BMP_001` is placeholder. Requires asset: `arrow_indicator` (48×48px white arrow)
     - Use layer 2 (above piece sprites on layer 1)
     - Set `gObjects[vars.arrowSpriteId].Hidden = true`
   - When tilt direction is detected, show arrow and set angle:
     - Side 0 FRONT: `Tm.A = 180` (pointing toward front edge)
     - Side 1 RIGHT: `Tm.A = 270`
     - Side 2 BACK: `Tm.A = 0`
     - Side 3 LEFT: `Tm.A = 90`
     - Set `gObjects[vars.arrowSpriteId].Tm.A = angle` and `Hidden = false`
   - When piece transfers to side face, delete arrow: `OCT_del(&gObjects[vars.arrowSpriteId])`

4. In `on_tick()`, add STATE_CHOOSING logic:
   - If `vars.gameState == STATE_CHOOSING`:
     - Call `int dir = detectTiltDirection()`
     - If `dir >= 0` and tilt is strong enough (transfer threshold, e.g., `0.5f`):
       - Set `vars.pieceSide = dir`
       - Delete piece sprites from top face
       - Delete arrow sprite: `OCT_del(&gObjects[vars.arrowSpriteId])`
       - Set `vars.pieceCol = 3`, `vars.pieceRow = 9` (top of chosen side face)
       - Call `createPieceSprites()` — now on the side face
       - Set `vars.gameState = STATE_FALLING`
       - Set `vars.lastFallTick = vars.tick`
     - Else if `dir >= 0` (tilt detected but below transfer threshold):
       - Update arrow direction and show it (pointing toward tilted side)

5. Check game-over on all 4 side faces: in `spawnPiece()`, check if ANY side face's top row (row 9) has filled cells that would block spawning. Since the player chooses the face, we defer the game-over check to when the piece transfers: in step 3, after choosing `dir`, check `canPieceFit(dir, 3, 9, vars.pieceType, vars.pieceRotation)`. If blocked, try other sides or trigger game over if all 4 sides are blocked.

5. Update `movePiece` and `rotatePiece` to also work when the piece is on different side faces (not just FRONT). The collision checks already use `vars.pieceSide`, so this should work automatically.

6. Add tilt-based horizontal movement on side faces (GDD: "tilt on side face moves piece left/right"):
   - In `on_tick()`, when `vars.gameState == STATE_FALLING`:
     - Read gravity for the piece's current side face: `float gX = OCT_TM_gravity_x(SIDE_PLANES[vars.pieceSide])`
     - If `|gX|` exceeds a movement threshold (e.g., `0.4f`) and enough time has passed since last tilt-move (rate limit to ~4 moves/sec):
       - `gX > 0` → `movePiece(1)` (move right on that face)
       - `gX < 0` → `movePiece(-1)` (move left on that face)
     - Add `uint32_t lastTiltMoveTick` to `appvars_t` for rate limiting

7. Update twist mapping in `on_twisted()` for pieces on different side faces:
   - For a piece on side `s`, horizontal movement comes from twists that rotate the "horizontal ring" relative to that face
   - Simplified approach for MVP: keep the same twist mapping (TOP/BOTTOM half-twists → horizontal movement) for all side faces. Note in comments that this may need refinement per face.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_TM_gravity_x(plane)` and `OCT_TM_gravity_y(plane)` return gravity components for the given plane
- Gravity values range from approximately -1.0 to +1.0
- When the cube is level, gravity_x and gravity_y on the top face are near 0; gravity_n is near -1
- The exact gravity-to-direction mapping must be tested on the actual cube or simulator

### Verification
- When a new piece spawns, it should appear on the TOP face (not directly on a side face)
- Tilting the cube slightly should show a white arrow on the top face pointing toward the tilted side
- Tilting further should transfer the piece to that side face; the arrow disappears
- After transfer, the piece falls normally with all existing mechanics (horizontal movement, rotation, landing, etc.)
- Pieces can now be directed to different side faces — fill cells on multiple sides
- If all 4 sides are blocked at the top, the game should end

---

## Prompt 13: Menu State

### Category
ui

### Dependencies
[1, 2, 3, 12]

### Current State
Full gameplay with direction choosing on all 4 side faces. The game starts directly in playing state.

### Goal
Add a menu screen that shows "TETRIS" on the top face. The game starts when the player double-taps. Empty grids visible on side faces.

### Instructions

1. Create a title label in `on_init()`:
   ```
   int32_t titleId = OCT_add_label(1, false, OCT_PLANE_TOP, 0.f, 40.f, 0, FONT_1, ALIGN_CENTER);
   vars.titleLabel = &gObjects[titleId];
   OCT_label_set(vars.titleLabel, "TETRIS");
   ```

2. Modify `on_init()`:
   - Set `vars.gameState = STATE_MENU`
   - Show title label, hide score label:
     - `showLabel(vars.titleLabel, true)`
     - `showLabel(vars.scoreLabel, false)`
   - Do NOT call `spawnPiece()`

3. Create function `void startGame()`:
   - Reset all game state:
     - Clear all grids: `vars.grid[s][c][r] = false` for all s, c, r
     - Delete all filled cell sprites: iterate gridSpriteIds, delete non-zero sprites, set to 0
     - Set `vars.score = 0`
   - Show score label, hide title label:
     - `showLabel(vars.scoreLabel, true)`
     - `showLabel(vars.titleLabel, false)`
   - Call `updateScoreLabel()`
   - Call `spawnPiece()`

4. In `on_tap()`, modify double-tap handling:
   - On double-tap:
     - If `vars.gameState == STATE_MENU` → call `startGame()`
     - If `vars.gameState == STATE_FALLING` → call `hardDrop()`

5. In `on_tick()`:
   - If `vars.gameState == STATE_MENU` → skip game logic (just increment tick)

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- Labels persist across game state changes — use showLabel to toggle visibility
- When starting a new game, all previous sprites (filled cells) must be deleted to avoid hitting SPRITES_CAP

### Verification
- On app launch, you should see "TETRIS" in white text on the top face
- All side faces should show black background (empty)
- The score label should NOT be visible
- Double-tapping should start the game: the title disappears, score "0" appears, and a piece spawns on the top face

---

## Prompt 14: Game Over State

### Category
ui

### Dependencies
[1, 2, 3, 11, 13]

### Current State
Game starts from menu, full gameplay with all mechanics. Game over freezes the game but shows nothing to the player.

### Goal
When the game ends, display "GAME OVER" and the final score on the top face. Double-tap returns to the menu.

### Instructions

1. Modify the game-over trigger (in `spawnPiece()` or wherever game over is set):
   - Set `vars.gameState = STATE_GAME_OVER`
   - Hide score label: `showLabel(vars.scoreLabel, false)`
   - Show title label with "GAME OVER" text:
     - `OCT_label_set(vars.titleLabel, "GAME\nOVER")`
     - `showLabel(vars.titleLabel, true)`
   - Create or reuse a secondary label to show final score, OR use a two-line format:
     - Change format to include score: format string as `"GAME OVER\n%d"` using `snprintf`, then `OCT_label_set(vars.titleLabel, buf)`
     - Or simpler: repurpose score label at a different position. For MVP, just show "GAME OVER" on the title label. The score was visible during gameplay.

2. In `on_tap()` double-tap handling:
   - If `vars.gameState == STATE_GAME_OVER`:
     - Reset to menu: call `resetToMenu()`

3. Create function `void resetToMenu()`:
   - Delete all filled cell sprites from all sides
   - Clear all grids
   - Delete any active piece sprites
   - Set `vars.gameState = STATE_MENU`
   - Show title label with "TETRIS": `OCT_label_set(vars.titleLabel, "TETRIS")`
   - `showLabel(vars.titleLabel, true)`
   - `showLabel(vars.scoreLabel, false)`

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- `OCT_label_set` supports `\n` for multi-line labels
- Delete ALL game sprites before returning to menu to avoid memory leaks (sprite budget)
- The filled cells on side faces should remain visible during game-over state (frozen grid)

### Verification
- When the game ends (top rows full), "GAME OVER" should appear on the top face
- The filled cells on the side faces should remain visible (frozen state)
- Double-tapping should return to the menu: "TETRIS" appears, all side faces are cleared
- From the menu, double-tapping should start a fresh game with score reset to 0

---

## Prompt 15: Line Clear Blink Animation

### Category
polish

### Dependencies
[1, 9]

### Current State
Line clearing works but is instantaneous — rows disappear without visual feedback.

### Goal
Before clearing completed rows, play a blink animation: the filled row blinks 3 times (approximately 0.5 seconds total), then disappears.

### Instructions

1. Modify `checkAndClearLines()`:
   - Instead of immediately clearing rows, store which rows are full in `vars.clearRows[]` and `vars.clearRowCount`
   - If `vars.clearRowCount > 0`:
     - Set `vars.gameState = STATE_LINE_CLEAR`
     - Set `vars.blinkCount = 0`
     - Set `vars.blinkTick = vars.tick`
     - Do NOT clear rows yet — the animation will handle it

2. In `on_tick()`, add STATE_LINE_CLEAR logic:
   - If `vars.gameState == STATE_LINE_CLEAR`:
     - Define blink interval: `BLINK_INTERVAL = OCT_1SEC_TICKS / 6` (~3 blinks in 0.5 seconds at 20 ticks/sec → ~3 ticks per blink phase)
     - If `vars.tick - vars.blinkTick >= BLINK_INTERVAL`:
       - Toggle visibility of all cells in `vars.clearRows[]`:
         - For each side `s`, each column `c`, each clear row `r`:
           - Get sprite: `gObjects[vars.gridSpriteIds[s][c][r]]`
           - Toggle `Hidden` field: `obj.Hidden = !obj.Hidden`
       - Increment `vars.blinkCount`
       - Update `vars.blinkTick = vars.tick`
     - If `vars.blinkCount >= 6` (3 full on/off cycles):
       - Actually clear the rows (delete sprites, update grid, drop cells above)
       - Update score based on `vars.clearRowCount`
       - Call `updateScoreLabel()`
       - Set `vars.gameState = STATE_FALLING` (or spawn next piece)
       - Call `spawnPiece()`

3. During STATE_LINE_CLEAR, ignore player input (no movement, no rotation, no hard drop).

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- The `Hidden` field on `octSprite_t` controls visibility — set to `true` to hide, `false` to show
- Blink timing: at 20 ticks/sec, 3 ticks per phase = ~150ms per phase, 6 phases = ~0.9 seconds (3 full on/off cycles). Adjust as needed for 0.5s target.

### Verification
- When a complete row is cleared, the row should blink 3 times (visible → invisible → visible → invisible → visible → invisible) before disappearing
- The blinking should be visible on all 4 side faces simultaneously for the cleared row
- After blinking, the row should be removed and cells above should drop down
- Score should update after the animation completes
- A new piece should spawn after the animation

---

## Prompt 16: Game Over Blink Animation

### Category
polish

### Dependencies
[1, 11, 14]

### Current State
Game over shows "GAME OVER" text on top face with filled cells frozen on side faces. No visual emphasis on the overflow.

### Goal
When game over occurs, the filled cells on the overflowed side face blink several times to visually indicate which face caused the loss.

### Instructions

1. When game over is triggered, record which side face caused it:
   - In the game-over logic, store `vars.gameOverSide = vars.pieceSide` (or the side where the spawn failed)
   - Add `int gameOverSide` field to `appvars_t`
   - Set `vars.blinkCount = 0` and `vars.blinkTick = vars.tick`

2. In `on_tick()`, during `STATE_GAME_OVER`:
   - If `vars.blinkCount < 6`:
     - Define `BLINK_INTERVAL = OCT_1SEC_TICKS / 4`
     - If `vars.tick - vars.blinkTick >= BLINK_INTERVAL`:
       - Toggle visibility of ALL filled cells on `vars.gameOverSide`:
         - For each column `c`, each row `r`:
           - If `vars.gridSpriteIds[vars.gameOverSide][c][r] != 0`:
             - Toggle `gObjects[id].Hidden`
       - Increment `vars.blinkCount`, update `vars.blinkTick`
   - After blinking (blinkCount >= 6): ensure all cells are visible (Hidden = false)

3. The blink animation plays once when entering game-over state, then stops. The player can double-tap to return to menu at any time.

See `OCT_wowcube-agent-skills/templates/app_ai_template.h` for API details and engine patterns. Do NOT copy demo code.

### Platform Reminders
- The blink only affects the overflowed face, not all faces
- Ensure cells are left visible (Hidden = false) after the blink animation completes
- The double-tap to restart should work even during the blink animation

### Verification
- When the game ends, the side face where the top row was filled should blink 3 times
- Other side faces should not blink — their filled cells remain static
- "GAME OVER" text should be visible on the top face during the blink animation
- After blinking stops, all cells should be visible
- Double-tap should still return to menu/restart the game
