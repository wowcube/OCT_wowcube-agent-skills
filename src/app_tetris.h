#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_tetris_ids.h"

#ifdef LINUX
    #define APP_PNG "assets/packed"
    #define APP_SND "assets/mp3"
#else
    #define APP_PNG "..\\..\\app_ai_template\\art\\packed"
    #define APP_SND "..\\..\\app_ai_template\\art\\mp3"
#endif

#define OCT_PLANES_MAX 6
#define OCT_QUADS_AT_PLANE 4

#define SPRITES_CAP 400
#define GAP 18
#define SIM_SINGLE_THREAD


////////////////////////////////
//         CONSTANTS          //
////////////////////////////////

#define GRID_COLS 10
#define GRID_ROWS 10
#define CELL_SIZE 24
#define NUM_SIDES 4
#define NUM_PIECE_CELLS 4
#define NUM_PIECE_TYPES 7
#define NUM_ROTATIONS 4
#define FALL_INTERVAL_TICKS (OCT_1SEC_TICKS)
#define DOUBLETAP_WINDOW (OCT_1SEC_TICKS / 2)

#define STATE_MENU 0
#define STATE_CHOOSING 1
#define STATE_FALLING 2
#define STATE_LINE_CLEAR 3
#define STATE_GAME_OVER 4

static const int SIDE_PLANES[NUM_SIDES] = {OCT_PLANE_FRONT, OCT_PLANE_RIGHT, OCT_PLANE_BACK, OCT_PLANE_LEFT};

static const float CELL_X[GRID_COLS] = {-126.f, -102.f, -78.f, -54.f, -30.f, 30.f, 54.f, 78.f, 102.f, 126.f};
static const float CELL_Y[GRID_ROWS] = {-126.f, -102.f, -78.f, -54.f, -30.f, 30.f, 54.f, 78.f, 102.f, 126.f};

// Tetromino shapes: [type][rotation][cell][0=relCol, 1=relRow]
static const int pieceShapes[NUM_PIECE_TYPES][NUM_ROTATIONS][NUM_PIECE_CELLS][2] = {
    // I-piece (type 0)
    {
        {{0,1},{1,1},{2,1},{3,1}},
        {{2,0},{2,1},{2,2},{2,3}},
        {{0,2},{1,2},{2,2},{3,2}},
        {{1,0},{1,1},{1,2},{1,3}}
    },
    // O-piece (type 1)
    {
        {{1,0},{2,0},{1,1},{2,1}},
        {{1,0},{2,0},{1,1},{2,1}},
        {{1,0},{2,0},{1,1},{2,1}},
        {{1,0},{2,0},{1,1},{2,1}}
    },
    // T-piece (type 2)
    {
        {{1,0},{0,1},{1,1},{2,1}},
        {{1,0},{1,1},{2,1},{1,2}},
        {{0,1},{1,1},{2,1},{1,2}},
        {{1,0},{0,1},{1,1},{1,2}}
    },
    // S-piece (type 3)
    {
        {{1,0},{2,0},{0,1},{1,1}},
        {{1,0},{1,1},{2,1},{2,2}},
        {{1,1},{2,1},{0,2},{1,2}},
        {{0,0},{0,1},{1,1},{1,2}}
    },
    // Z-piece (type 4)
    {
        {{0,0},{1,0},{1,1},{2,1}},
        {{2,0},{1,1},{2,1},{1,2}},
        {{0,1},{1,1},{1,2},{2,2}},
        {{1,0},{0,1},{1,1},{0,2}}
    },
    // L-piece (type 5)
    {
        {{2,0},{0,1},{1,1},{2,1}},
        {{1,0},{1,1},{1,2},{2,2}},
        {{0,1},{1,1},{2,1},{0,2}},
        {{0,0},{1,0},{1,1},{1,2}}
    },
    // J-piece (type 6)
    {
        {{0,0},{0,1},{1,1},{2,1}},
        {{1,0},{2,0},{1,1},{1,2}},
        {{0,1},{1,1},{2,1},{2,2}},
        {{1,0},{1,1},{0,2},{1,2}}
    }
};


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

typedef struct _appObject_t: octSprite_t {

} appObject_t;

typedef struct {
    uint32_t tick;
    int gameState;
    int score;
    bool grid[NUM_SIDES][GRID_COLS][GRID_ROWS];
    int32_t gridSpriteIds[NUM_SIDES][GRID_COLS][GRID_ROWS];
    int pieceType;
    int pieceRotation;
    int pieceSide;
    int pieceCol;
    int pieceRow;
    int32_t pieceSpriteIds[NUM_PIECE_CELLS];
    uint32_t lastFallTick;
    uint32_t lastTapTick;
    int lastTapPlane;
    appObject_t* scoreLabel;
    appObject_t* titleLabel;
    int clearRows[GRID_ROWS];
    int clearRowCount;
    int blinkCount;
    uint32_t blinkTick;
    int32_t arrowSpriteId;
    uint32_t lastTiltMoveTick;
} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////

void showLabel(appObject_t* label, bool show);
void updateScoreLabel(void);
int getPiecePlane(int sideIdx);
void getCellCoords(int sideIdx, int col, int row, int* plane, float* x, float* y);
void spawnPiece(void);
void createPieceSprites(void);
void deletePieceSprites(void);
void updatePieceSprites(void);
bool canPieceFit(int side, int col, int row, int type, int rotation);
void fixPiece(void);
void movePiece(int direction);
void rotatePiece(void);
void checkAndClearLines(void);
void hardDrop(void);
int detectTiltDirection(void);

////////////////////////////////
//            MAPS            //
////////////////////////////////

// [NOTE]: All global variables should be defined with TL macro
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;


////////////////////////////////
//       IMPLEMENTATION       //
////////////////////////////////

void showLabel(appObject_t* label, bool show) {
    label->Hidden = !show;

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if (obj->Idx != i) continue;

        if (obj->Parent == label->Idx) {
            obj->Hidden = !show;
        }
    }
}

void updateScoreLabel(void) {
    char buf[12];
    snprintf(buf, 12, "%d", vars.score);
    OCT_label_set(vars.scoreLabel, buf);
}

int getPiecePlane(int sideIdx) {
    return SIDE_PLANES[sideIdx];
}

void getCellCoords(int sideIdx, int col, int row, int* plane, float* x, float* y) {
    *plane = SIDE_PLANES[sideIdx];
    *x = CELL_X[col];
    *y = CELL_Y[row];
}

void createPieceSprites(void) {
    for (int i = 0; i < NUM_PIECE_CELLS; i++) {
        int relCol = pieceShapes[vars.pieceType][vars.pieceRotation][i][0];
        int relRow = pieceShapes[vars.pieceType][vars.pieceRotation][i][1];
        int col = vars.pieceCol + relCol;
        int row = vars.pieceRow - relRow;
        int plane;
        float x, y;
        getCellCoords(vars.pieceSide, col, row, &plane, &x, &y);
        vars.pieceSpriteIds[i] = OCT_add(1, false, plane, x, y, 0, false, BMP_001, BMP_001, 0);
    }
    vars.lastFallTick = vars.tick;
}

void deletePieceSprites(void) {
    for (int i = 0; i < NUM_PIECE_CELLS; i++) {
        if (vars.pieceSpriteIds[i] != 0) {
            OCT_del(&gObjects[vars.pieceSpriteIds[i]]);
            vars.pieceSpriteIds[i] = 0;
        }
    }
}

void updatePieceSprites(void) {
    deletePieceSprites();
    createPieceSprites();
}

bool canPieceFit(int side, int col, int row, int type, int rotation) {
    for (int i = 0; i < NUM_PIECE_CELLS; i++) {
        int c = col + pieceShapes[type][rotation][i][0];
        int r = row - pieceShapes[type][rotation][i][1];
        if (c < 0 || c >= GRID_COLS || r < 0 || r >= GRID_ROWS) return false;
        if (vars.grid[side][c][r] == true) return false;
    }
    return true;
}

void fixPiece(void) {
    deletePieceSprites();
    for (int i = 0; i < NUM_PIECE_CELLS; i++) {
        int c = vars.pieceCol + pieceShapes[vars.pieceType][vars.pieceRotation][i][0];
        int r = vars.pieceRow - pieceShapes[vars.pieceType][vars.pieceRotation][i][1];
        vars.grid[vars.pieceSide][c][r] = true;
        int plane;
        float x, y;
        getCellCoords(vars.pieceSide, c, r, &plane, &x, &y);
        vars.gridSpriteIds[vars.pieceSide][c][r] = OCT_add(0, false, plane, x, y, 0, false, BMP_001, BMP_001, 0);
    }
}

void movePiece(int direction) {
    if (vars.gameState != STATE_FALLING) return;
    int newCol = vars.pieceCol + direction;
    if (canPieceFit(vars.pieceSide, newCol, vars.pieceRow, vars.pieceType, vars.pieceRotation)) {
        vars.pieceCol = newCol;
        updatePieceSprites();
    }
}

void rotatePiece(void) {
    if (vars.gameState != STATE_FALLING) return;
    if (vars.pieceType == 1) return; // O-piece does not rotate
    int newRot = (vars.pieceRotation + 1) % NUM_ROTATIONS;
    if (canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow, vars.pieceType, newRot)) {
        vars.pieceRotation = newRot;
        updatePieceSprites();
    }
}

void hardDrop(void) {
    if (vars.gameState != STATE_FALLING) return;
    while (canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow - 1, vars.pieceType, vars.pieceRotation)) {
        vars.pieceRow--;
    }
    updatePieceSprites();
    fixPiece();
    checkAndClearLines();
    spawnPiece();
}

void checkAndClearLines(void) {
    // Step 1: Find rows that are full on ALL 4 sides
    bool rowFull[GRID_ROWS];
    int linesCleared = 0;

    for (int r = 0; r < GRID_ROWS; r++) {
        rowFull[r] = true;
        for (int s = 0; s < NUM_SIDES; s++) {
            for (int c = 0; c < GRID_COLS; c++) {
                if (!vars.grid[s][c][r]) {
                    rowFull[r] = false;
                    break;
                }
            }
            if (!rowFull[r]) break;
        }
        if (rowFull[r]) linesCleared++;
    }

    if (linesCleared == 0) return;

    // Collect cleared row indices sorted ascending (bottom to top)
    int clearedRows[GRID_ROWS];
    int clearedCount = 0;
    for (int r = 0; r < GRID_ROWS; r++) {
        if (rowFull[r]) {
            clearedRows[clearedCount++] = r;
        }
    }

    // Step 2: Clear each marked row - delete sprites and reset grid
    for (int i = 0; i < clearedCount; i++) {
        int r = clearedRows[i];
        for (int s = 0; s < NUM_SIDES; s++) {
            for (int c = 0; c < GRID_COLS; c++) {
                if (vars.gridSpriteIds[s][c][r] != 0) {
                    OCT_del(&gObjects[vars.gridSpriteIds[s][c][r]]);
                    vars.gridSpriteIds[s][c][r] = 0;
                }
                vars.grid[s][c][r] = false;
            }
        }
    }

    // Step 3: Drop cells above cleared rows
    // Process cleared rows from bottom to top; adjust index for prior shifts
    for (int i = 0; i < clearedCount; i++) {
        int clearRow = clearedRows[i] - i;
        for (int r = clearRow; r < GRID_ROWS - 1; r++) {
            for (int s = 0; s < NUM_SIDES; s++) {
                for (int c = 0; c < GRID_COLS; c++) {
                    vars.grid[s][c][r] = vars.grid[s][c][r + 1];
                    vars.gridSpriteIds[s][c][r] = vars.gridSpriteIds[s][c][r + 1];
                    int32_t spriteId = vars.gridSpriteIds[s][c][r];
                    if (spriteId != 0) {
                        gObjects[spriteId].Tm.Y = CELL_Y[r];
                    }
                }
            }
        }
        // Clear the topmost row that was shifted out
        for (int s = 0; s < NUM_SIDES; s++) {
            for (int c = 0; c < GRID_COLS; c++) {
                vars.grid[s][c][GRID_ROWS - 1] = false;
                vars.gridSpriteIds[s][c][GRID_ROWS - 1] = 0;
            }
        }
    }

    // Step 4: Update score
    static const int scoreTable[4] = {100, 300, 500, 800};
    if (linesCleared >= 1 && linesCleared <= 4) {
        vars.score += scoreTable[linesCleared - 1];
    }
    updateScoreLabel();
}

int detectTiltDirection(void) {
    float gX = OCT_TM_gravity_x(OCT_PLANE_TOP);
    float gY = OCT_TM_gravity_y(OCT_PLANE_TOP);
    float absGX = gX > 0 ? gX : -gX;
    float absGY = gY > 0 ? gY : -gY;
    float tiltThreshold = 0.3f;
    float maxTilt = absGX > absGY ? absGX : absGY;
    if (maxTilt < tiltThreshold) return -1;

    if (absGX > absGY) {
        // Horizontal tilt
        if (gX > 0) return 1; // RIGHT
        else return 3;         // LEFT
    } else {
        // Vertical tilt
        if (gY > 0) return 0; // FRONT
        else return 2;         // BACK
    }
}

void spawnPiece(void) {
    vars.pieceType = OCT_random(0, NUM_PIECE_TYPES);
    vars.pieceRotation = 0;

    // Game over check: if no side face can accept the piece, game over
    bool anyFit = false;
    for (int s = 0; s < NUM_SIDES; s++) {
        if (canPieceFit(s, 3, 9, vars.pieceType, vars.pieceRotation)) {
            anyFit = true;
            break;
        }
    }
    if (!anyFit) {
        vars.gameState = STATE_GAME_OVER;
        OCT_trace(0, "GAME OVER! Score: %d\n", vars.score);
        return;
    }

    // Place piece sprites on TOP face at center as visual indicator
    for (int i = 0; i < NUM_PIECE_CELLS; i++) {
        vars.pieceSpriteIds[i] = OCT_add(1, false, OCT_PLANE_TOP, 0.f, 0.f, 0, false, BMP_001, BMP_001, 0);
    }

    // Create arrow sprite on TOP face (hidden initially)
    vars.arrowSpriteId = OCT_add(2, false, OCT_PLANE_TOP, 0.f, -80.f, 0, false, BMP_001, BMP_001, 0);
    gObjects[vars.arrowSpriteId].Hidden = true;

    vars.gameState = STATE_CHOOSING;
}

// Handlers
WASM_EXPORT void on_init() {
    OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t));
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
    OCT_background(0x0000);

    vars.tick = 0;
    vars.gameState = STATE_MENU;
    vars.score = 0;
    vars.lastTapTick = 0;

    for (int s = 0; s < NUM_SIDES; s++) {
        for (int c = 0; c < GRID_COLS; c++) {
            for (int r = 0; r < GRID_ROWS; r++) {
                vars.grid[s][c][r] = false;
                vars.gridSpriteIds[s][c][r] = 0;
            }
        }
    }

    // Score label on top face
    int32_t id = OCT_add_label(1, false, OCT_PLANE_TOP, 0.f, 0.f, 0, FONT_1, ALIGN_CENTER);
    vars.scoreLabel = &gObjects[id];
    OCT_label_set(vars.scoreLabel, "0");
    updateScoreLabel();

    vars.arrowSpriteId = 0;
    vars.lastTiltMoveTick = 0;

    // Spawn initial piece
    spawnPiece();
}

WASM_EXPORT void on_pretwisted(int32_t twid) {
    twid;
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    disconnected_ms;

    if (twid >= OCT_TWIST_HALF) {
        // Half-twists (twid 12-23)
        int halfId = twid - OCT_TWIST_HALF;
        int twistPlane = halfId / 2;
        int twistDir = halfId % 2;

        if (twistPlane == OCT_PLANE_TOP || twistPlane == OCT_PLANE_BOTTOM) {
            // Horizontal half-twist → move piece left/right
            if (twistDir == 1) {
                movePiece(1);   // CW → move right
            } else {
                movePiece(-1);  // CCW → move left
            }
        }

        if (twistPlane == OCT_PLANE_FRONT || twistPlane == OCT_PLANE_RIGHT ||
            twistPlane == OCT_PLANE_BACK  || twistPlane == OCT_PLANE_LEFT) {
            // Vertical half-twist → rotate piece
            rotatePiece();
        }
    } else {
        // Full twists (twid 0-11)
        int fullPlane = twid / 2;
        int fullDir = twid % 2;
        (void)fullDir;

        if (fullPlane == OCT_PLANE_TOP || fullPlane == OCT_PLANE_BOTTOM) {
            // Horizontal full twist → rotate piece
            rotatePiece();
        }
    }
}

WASM_EXPORT void on_tap(int32_t tapid) {
    if (vars.tick - vars.lastTapTick < DOUBLETAP_WINDOW && vars.lastTapPlane == tapid) {
        hardDrop();
        vars.lastTapTick = 0;
    } else {
        vars.lastTapTick = vars.tick;
        vars.lastTapPlane = tapid;
    }
}

WASM_EXPORT void on_tick() {
    vars.tick++;

    if (vars.gameState == STATE_CHOOSING) {
        int dir = detectTiltDirection();
        if (dir >= 0) {
            float gX = OCT_TM_gravity_x(OCT_PLANE_TOP);
            float gY = OCT_TM_gravity_y(OCT_PLANE_TOP);
            float absGX = gX > 0 ? gX : -gX;
            float absGY = gY > 0 ? gY : -gY;
            float maxTilt = absGX > absGY ? absGX : absGY;

            if (maxTilt >= 0.5f) {
                // Transfer piece to chosen side face
                vars.pieceSide = dir;

                // Delete piece sprites from top face
                deletePieceSprites();
                // Delete arrow sprite
                OCT_del(&gObjects[vars.arrowSpriteId]);

                vars.pieceCol = 3;
                vars.pieceRow = 9;

                // Check if piece fits on chosen side, try others if not
                if (!canPieceFit(dir, 3, 9, vars.pieceType, vars.pieceRotation)) {
                    bool placed = false;
                    for (int s = 0; s < NUM_SIDES; s++) {
                        if (s == dir) continue;
                        if (canPieceFit(s, 3, 9, vars.pieceType, vars.pieceRotation)) {
                            vars.pieceSide = s;
                            placed = true;
                            break;
                        }
                    }
                    if (!placed) {
                        vars.gameState = STATE_GAME_OVER;
                        OCT_trace(0, "GAME OVER! Score: %d\n", vars.score);
                        return;
                    }
                }

                createPieceSprites();
                vars.gameState = STATE_FALLING;
                vars.lastFallTick = vars.tick;
            } else {
                // Show arrow pointing toward tilted side
                static const int arrowAngles[4] = {180, 270, 0, 90};
                gObjects[vars.arrowSpriteId].Tm.A = arrowAngles[dir];
                gObjects[vars.arrowSpriteId].Hidden = false;
            }
        }
    }

    if (vars.gameState == STATE_FALLING) {
        // Tilt-based horizontal movement
        {
            float gX = OCT_TM_gravity_x(SIDE_PLANES[vars.pieceSide]);
            float absGX = gX > 0 ? gX : -gX;
            if (absGX > 0.4f && (vars.tick - vars.lastTiltMoveTick >= OCT_1SEC_TICKS / 4)) {
                if (gX > 0) {
                    movePiece(1);
                } else {
                    movePiece(-1);
                }
                vars.lastTiltMoveTick = vars.tick;
            }
        }

        // Gravity fall
        if (vars.tick - vars.lastFallTick >= FALL_INTERVAL_TICKS) {
            if (!canPieceFit(vars.pieceSide, vars.pieceCol, vars.pieceRow - 1, vars.pieceType, vars.pieceRotation)) {
                fixPiece();
                checkAndClearLines();
                spawnPiece();
            } else {
                vars.pieceRow--;
                updatePieceSprites();
                vars.lastFallTick = vars.tick;
            }
        }
    }
}
