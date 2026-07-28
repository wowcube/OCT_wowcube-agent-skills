#pragma once
#include "oct_api.h"
#include "oct_consts.h"
#include <math.h>

#include "app_ai_template_ids.h"

#ifdef _WIN32
#define APP_PNG "..\\..\\app_ai_template\\art\\packed"
#define APP_SND "..\\..\\app_ai_template\\art\\mp3"
#else
#define APP_PNG "assets/packed"
#define APP_SND "assets/mp3"
#endif

#define OCT_PLANES_MAX 6 // max planes on cube
#define OCT_QUADS_AT_PLANE 4 // max quads at plane

#define SPRITES_CAP 400 // scene capacity - maximum objects count possible
#define GAP 18 // width of physical border between wowcube's display in pixels
#define SIM_SINGLE_THREAD

#define BOMB_TYPES 11
#define BOMB_COUNT 22
#define SERVICE_QUAD_TIMER 0
#define SERVICE_QUAD_STATUS 1
#define TIMER_START_SECS 180
#define TWIST_FAST_MS 3000
#define CALM_TICKS (3 * OCT_1SEC_TICKS)


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

typedef enum {
    STATE_TITLE,
    STATE_PLAYING,
    STATE_PASS_PROMPT,
    STATE_PASSING,
    STATE_NEXT_CONFIRM,
    STATE_WIN,
    STATE_LOSE,
    STATE_PAUSE
} GameState;

typedef enum {
    ANGER_CALM = 0,
    ANGER_ANGRY = 1,
    ANGER_FURIOUS = 2,
    ANGER_LOVED = 3
} AngerLevel;

// game specific data
typedef struct _appObject_t: octSprite_t {
    int bombType;    // 0-10 = bomb type index; -1 = not a bomb (UI element)
    AngerLevel anger;
    int quadIndex;   // which of the 24 quads this bomb occupies; -1 = merged/removed
} appObject_t;

// game specific vars
typedef struct {
    GameState state;
    uint32_t tick;
    int timerSecs;
    uint32_t lastTickSec;
    int angerLevel;
    uint32_t lastAngerTick;
    bool angerPending;
    int roundNumber;
    int penaltyBombType;
    int board[24];        // bombType per quad; -1 = empty or service quad
    int boardAnger[24];   // AngerLevel per quad
    int32_t titleLabel;   // index of the title text label
    int32_t startLabel;   // index of the 'TAP TO START' label
    int32_t timerLabel;   // index of the timer countdown label; -1 if not created
    uint32_t lastTwistMs; // disconnected_ms from last twist
    int lastMergedQuad;   // quad id of the last merged bomb; -1 if none
    // PART A: accelerometer shake detection
    float prevGravMag;    // previous gravity magnitude for shake delta
    // PART B: explosion animation
    int explosionStep;
    uint32_t explosionStartTick;
    // PART C: pass button labels
    int32_t passLabel;    // index of the "PASS!" label; -1 if not shown
    int32_t passLabel2;   // reserved for second pass label; -1 if not shown
    // PART D: per-bomb calm down tracking
    uint32_t angerTick[24]; // tick when anger was last set for each quad
    // PART E (Prompts 18-23): new fields
    int32_t calmMeterLabel; // index of the calm meter label; -1 if not created
    int32_t winLabel;       // index of the win screen second label ("CUBE SAFE!"); -1 if not created
    int32_t winLabel2;      // index of the win screen first label ("DEFUSED!"); -1 if not created
    int32_t loseLabel;      // index of the lose screen second label ("TAP RETRY"); -1 if not created
    int32_t loseLabel2;     // index of the lose screen first label ("BOOM!"); -1 if not created
    int32_t pauseLabel;     // index of the pause label; -1 if not shown
    bool winShown;          // whether win screen has been shown already
    bool loseShown;         // whether lose screen has been shown already
} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////

void showLabel(appObject_t* label, bool show);
void initTitleScreen(void);
void initBoard(void);
void startGame(void);
appObject_t* getBombAtQuad(int quadId);
void slideBombs(int row[8], int shiftAmount);
int checkMergeInRow(int row[8]);
void updateBombVisual(int quadId);
void triggerAngerEvent();
void triggerExplosion();
void showPassButton(bool visible);
void initTimer(void);
void updateTimerDisplay(void);
void resetGame(void);
void startNewRound(void);
// PART A (Prompt 18): calm meter
void initCalmMeter(void);
void updateCalmMeter(void);
// PART B (Prompt 19): win/lose screens
void showWinScreen(void);
void showLoseScreen(void);

////////////////////////////////
//            MAPS            //
////////////////////////////////

//[NOTE]: All global variables should be defined with TL macro
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;


// Requires assets: bomb_<type>_<state>.png (44 total) — see GDD assets section
static const int BMP_BOMB[11][4] = {
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004},
    {BMP_001, BMP_002, BMP_003, BMP_004}
};

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

void initTitleScreen(void) {
    vars.titleLabel = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 60.0f, 0, FONT_1, ALIGN_CENTER);
    OCT_label_set(&gObjects[vars.titleLabel], "BOMBCUBE");

    vars.startLabel = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 180.0f, 0, FONT_2, ALIGN_CENTER);
    OCT_label_set(&gObjects[vars.startLabel], "TAP TO START");
}

// PART A: timer countdown label
void initTimer(void) {
    float x = XSIGN[0] * (120.0f + GAP);
    float y = YSIGN[0] * (120.0f + GAP);
    vars.timerLabel = OCT_add_label(1, false, OCT_PLANE_TOP, x, y, 0, FONT_1, ALIGN_CENTER);
    char buf[8];
    snprintf(buf, 8, "3:00");
    OCT_label_set(&gObjects[vars.timerLabel], buf);
}

void updateTimerDisplay(void) {
    if (vars.timerLabel < 0) return;
    int m = vars.timerSecs / 60;
    int s = vars.timerSecs % 60;
    char buf[8];
    snprintf(buf, 8, "%d:%02d", m, s);
    OCT_label_set(&gObjects[vars.timerLabel], buf);
}

// PART E (Prompt 18): calm meter at top plane quad 1
void initCalmMeter(void) {
    float x = XSIGN[1] * (120.0f + GAP);
    float y = YSIGN[1] * (120.0f + GAP);
    vars.calmMeterLabel = OCT_add_label(1, false, OCT_PLANE_TOP, x, y, 0, FONT_2, ALIGN_CENTER);
    OCT_label_set(&gObjects[vars.calmMeterLabel], "CALM");
}

void updateCalmMeter(void) {
    if (vars.calmMeterLabel < 0) return;
    int maxAnger = 0;
    for (int q = 2; q <= 23; q++) {
        if (vars.board[q] == -1) continue;
        if (vars.boardAnger[q] == ANGER_LOVED) continue;
        if (vars.boardAnger[q] > maxAnger) maxAnger = vars.boardAnger[q];
    }
    const char* text;
    if (maxAnger == 0) text = "CALM";
    else if (maxAnger == 1) text = "NERVOUS";
    else if (maxAnger == 2) text = "DANGER!";
    else text = "CALM";
    OCT_label_set(&gObjects[vars.calmMeterLabel], text);
}

void initBoard(void) {
    // a. Delete existing bomb sprites
    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if (obj->Idx == i && obj->bombType >= 0) {
            OCT_del(obj);
        }
    }

    // b. Build shuffled array of 22 bomb types (types 0..10, each twice)
    int bombTypes[22];
    for (int i = 0; i < 22; i++) {
        bombTypes[i] = i / 2;
    }
    // Fisher-Yates shuffle
    for (int i = 21; i >= 1; i--) {
        int j = OCT_random(0, i + 1);
        int tmp = bombTypes[i];
        bombTypes[i] = bombTypes[j];
        bombTypes[j] = tmp;
    }

    // c. Reset board and boardAnger
    for (int i = 0; i < 24; i++) {
        vars.board[i] = -1;
        vars.boardAnger[i] = ANGER_CALM;
    }

    // d. Place bomb sprites on quads 2..23
    for (int quadId = 2; quadId <= 23; quadId++) {
        int plane = quadId / OCT_QUADS_AT_PLANE;
        int localQuad = quadId % OCT_QUADS_AT_PLANE;
        float x = XSIGN[localQuad] * (120.0f + GAP);
        float y = YSIGN[localQuad] * (120.0f + GAP);
        int32_t idx = OCT_add(0, true, plane, x, y, 0, false, BMP_001, BMP_001, 0);
        gObjects[idx].bombType = bombTypes[quadId - 2];
        gObjects[idx].quadIndex = quadId;
        gObjects[idx].anger = ANGER_CALM;
        vars.board[quadId] = bombTypes[quadId - 2];
        vars.boardAnger[quadId] = ANGER_CALM;
        updateBombVisual(quadId);
    }
}

void startGame(void) {
    showLabel(&gObjects[vars.titleLabel], false);
    showLabel(&gObjects[vars.startLabel], false);
    vars.state = STATE_PLAYING;
    initBoard();
    initTimer();
    initCalmMeter();
}

appObject_t* getBombAtQuad(int quadId) {
    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if (obj->Idx != i) continue;
        if (obj->quadIndex == quadId && obj->bombType >= 0) return obj;
    }
    return NULL;
}

void updateBombVisual(int quadId) {
    appObject_t* obj = getBombAtQuad(quadId);
    if (obj == NULL) return;
    int bombType = obj->bombType;
    int anger = (int)obj->anger;
    int bmpId = BMP_BOMB[bombType][anger];
    OCT_sequence(obj, bmpId, bmpId, 0, OCT_SEQ_REFRESH);
}

void slideBombs(int row[8], int shiftAmount) {
    // a. Read current bomb types into slots[] and anger into angerSlots[]
    int slots[8];
    int angerSlots[8];
    for (int i = 0; i < 8; i++) {
        appObject_t* bomb = getBombAtQuad(row[i]);
        slots[i] = (bomb != NULL) ? bomb->bombType : -1;
        angerSlots[i] = vars.boardAnger[row[i]];
    }

    if (shiftAmount == 4) {
        // Full twist: compact non-empty values toward index 7 (2048 slide toward end)
        int result[8];
        int angerResult[8];
        for (int i = 0; i < 8; i++) { result[i] = -1; angerResult[i] = ANGER_CALM; }
        int writePos = 7;
        for (int i = 7; i >= 0; i--) {
            if (slots[i] != -1) {
                result[writePos] = slots[i];
                angerResult[writePos] = angerSlots[i];
                writePos--;
            }
        }

        // c. If result equals slots, nothing to do
        bool changed = false;
        for (int i = 0; i < 8; i++) {
            if (result[i] != slots[i]) { changed = true; break; }
        }
        if (!changed) return;

        // d. Delete all existing bomb sprites in the row
        for (int i = 0; i < 8; i++) {
            appObject_t* bomb = getBombAtQuad(row[i]);
            if (bomb != NULL) {
                OCT_del(bomb);
            }
            vars.board[row[i]] = -1;
        }

        // e. Recreate sprites for result[]
        for (int i = 0; i < 8; i++) {
            int quadId = row[i];
            if (result[i] != -1) {
                int plane = quadId / OCT_QUADS_AT_PLANE;
                int localQuad = quadId % OCT_QUADS_AT_PLANE;
                float x = XSIGN[localQuad] * (120.0f + GAP);
                float y = YSIGN[localQuad] * (120.0f + GAP);
                int32_t idx = OCT_add(0, true, plane, x, y, 0, false, BMP_001, BMP_001, 0);
                gObjects[idx].bombType = result[i];
                gObjects[idx].quadIndex = quadId;
                gObjects[idx].anger = (AngerLevel)angerResult[i];
                vars.board[quadId] = result[i];
                vars.boardAnger[quadId] = angerResult[i];
            } else {
                vars.boardAnger[quadId] = ANGER_CALM;
            }
        }
    } else if (shiftAmount == 2) {
        // Half twist: cyclic shift of 2 positions toward high end
        int shiftedSlots[8];
        int shiftedAnger[8];
        for (int i = 0; i < 8; i++) {
            shiftedSlots[(i + 2) % 8] = slots[i];
            shiftedAnger[(i + 2) % 8] = angerSlots[i];
        }

        // If shiftedSlots equals slots, nothing to do
        bool changed = false;
        for (int i = 0; i < 8; i++) {
            if (shiftedSlots[i] != slots[i]) { changed = true; break; }
        }
        if (!changed) return;

        // Delete all existing bomb sprites in the row
        for (int i = 0; i < 8; i++) {
            appObject_t* bomb = getBombAtQuad(row[i]);
            if (bomb != NULL) {
                OCT_del(bomb);
            }
            vars.board[row[i]] = -1;
        }

        // Recreate sprites at new positions using shiftedSlots[]/shiftedAnger[]
        for (int i = 0; i < 8; i++) {
            int quadId = row[i];
            if (shiftedSlots[i] != -1) {
                int plane = quadId / OCT_QUADS_AT_PLANE;
                int localQuad = quadId % OCT_QUADS_AT_PLANE;
                float x = XSIGN[localQuad] * (120.0f + GAP);
                float y = YSIGN[localQuad] * (120.0f + GAP);
                int32_t idx = OCT_add(0, true, plane, x, y, 0, false, BMP_001, BMP_001, 0);
                gObjects[idx].bombType = shiftedSlots[i];
                gObjects[idx].quadIndex = quadId;
                gObjects[idx].anger = (AngerLevel)shiftedAnger[i];
                vars.board[quadId] = shiftedSlots[i];
                vars.boardAnger[quadId] = shiftedAnger[i];
            } else {
                vars.boardAnger[quadId] = ANGER_CALM;
            }
        }
    }
}

int checkMergeInRow(int row[8]) {
    for (int i = 6; i >= 0; i--) {
        int qa = row[i];
        int qb = row[i + 1];
        if (vars.board[qa] != -1 && vars.board[qb] != -1 && vars.board[qa] == vars.board[qb]) {
            int keptQuad = qb;
            int removedQuad = qa;

            vars.boardAnger[keptQuad] = ANGER_LOVED;

            vars.board[removedQuad] = -1;
            vars.boardAnger[removedQuad] = ANGER_CALM;
            appObject_t* removedBomb = getBombAtQuad(removedQuad);
            if (removedBomb != NULL) {
                OCT_del(removedBomb);
            }

            appObject_t* keptBomb = getBombAtQuad(keptQuad);
            if (keptBomb != NULL) {
                keptBomb->anger = ANGER_LOVED;
                updateBombVisual(keptQuad);
            }

            vars.lastMergedQuad = keptQuad;

            // PART D (Prompt 21): merge sound
            SND_play(SND_getAssetId("digit_merge0.mp3"), 80);

            // Check win condition
            int lovedOrEmpty = 0;
            for (int q = 2; q <= 23; q++) {
                if (vars.board[q] == -1 || vars.boardAnger[q] == ANGER_LOVED) {
                    lovedOrEmpty++;
                }
            }
            if (lovedOrEmpty == 22) {
                vars.state = STATE_WIN;
            } else {
                vars.state = STATE_PASS_PROMPT;
                showPassButton(true);
            }

            return keptQuad;
        }
    }
    return -1;
}

// PART B: full explosion implementation
void triggerExplosion() {
    vars.state = STATE_LOSE;
    vars.explosionStep = 0;
    vars.explosionStartTick = vars.tick;
    // PART D (Prompt 21): explosion sound
    SND_play(SND_getAssetId("digit_merge2.mp3"), 100);
}

void triggerAngerEvent() {
    // a. Check if any bomb is already at ANGER_FURIOUS and NOT ANGER_LOVED
    for (int quad = 2; quad <= 23; quad++) {
        if (vars.board[quad] == -1) continue;
        if (vars.boardAnger[quad] == ANGER_LOVED) continue;
        if (vars.boardAnger[quad] == ANGER_FURIOUS) {
            triggerExplosion();
            return;
        }
    }

    // b. Escalate anger for all non-LOVED bombs
    for (int quad = 2; quad <= 23; quad++) {
        if (vars.board[quad] == -1) continue;
        if (vars.boardAnger[quad] == ANGER_LOVED) continue;
        vars.boardAnger[quad] += 1;
        appObject_t* obj = getBombAtQuad(quad);
        if (obj != NULL) {
            obj->anger = (AngerLevel)vars.boardAnger[quad];
            // PART D: record tick when anger was set
            vars.angerTick[quad] = vars.tick;
        }
        updateBombVisual(quad);
    }

    // c. Update anger tracking vars
    vars.lastAngerTick = vars.tick;
    vars.angerPending = true;

    // PART D (Prompt 21): escalation sound (not exploding)
    SND_play(SND_getAssetId("digit_merge1.mp3"), 60);
}

// PART C: show/hide pass button
void showPassButton(bool visible) {
    if (visible) {
        int localQuad = 1; // quad 1 at OCT_PLANE_TOP
        float x = XSIGN[localQuad] * (120.0f + GAP);
        float y = YSIGN[localQuad] * (120.0f + GAP);
        vars.passLabel = OCT_add_label(1, false, OCT_PLANE_TOP, x, y, 0, FONT_2, ALIGN_CENTER);
        OCT_label_set(&gObjects[vars.passLabel], "PASS!");
        // Hide calm meter when pass button is shown
        if (vars.calmMeterLabel >= 0) {
            showLabel(&gObjects[vars.calmMeterLabel], false);
        }
        // PART D (Prompt 21): unlock/pass sound
        SND_play(SND_getAssetId("digit_merge1.mp3"), 60);
    } else {
        if (vars.passLabel >= 0) {
            showLabel(&gObjects[vars.passLabel], false);
            OCT_del(&gObjects[vars.passLabel]);
            vars.passLabel = -1;
        }
        // Show calm meter when pass button is hidden
        if (vars.calmMeterLabel >= 0) {
            showLabel(&gObjects[vars.calmMeterLabel], true);
        }
    }
}

// PART B (Prompt 19): Win screen
void showWinScreen(void) {
    int32_t idx1 = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 80.0f, 0, FONT_1, ALIGN_CENTER);
    vars.winLabel2 = idx1;
    OCT_label_set(&gObjects[vars.winLabel2], "DEFUSED!");
    int32_t idx2 = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 160.0f, 0, FONT_2, ALIGN_CENTER);
    vars.winLabel = idx2;
    OCT_label_set(&gObjects[vars.winLabel], "CUBE SAFE!");
    // Hide timer
    if (vars.timerLabel >= 0) showLabel(&gObjects[vars.timerLabel], false);
    // Hide calm meter
    if (vars.calmMeterLabel >= 0) showLabel(&gObjects[vars.calmMeterLabel], false);
    // PART D (Prompt 21): win jingle
    SND_play(SND_getAssetId("digit_merge0.mp3"), 90);
}

// PART B (Prompt 19): Lose screen
void showLoseScreen(void) {
    int32_t idx1 = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 80.0f, 0, FONT_1, ALIGN_CENTER);
    vars.loseLabel2 = idx1;
    OCT_label_set(&gObjects[vars.loseLabel2], "BOOM!");
    int32_t idx2 = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 160.0f, 0, FONT_2, ALIGN_CENTER);
    vars.loseLabel = idx2;
    OCT_label_set(&gObjects[vars.loseLabel], "TAP RETRY");
    // Hide timer
    if (vars.timerLabel >= 0) showLabel(&gObjects[vars.timerLabel], false);
    // Hide calm meter
    if (vars.calmMeterLabel >= 0) showLabel(&gObjects[vars.calmMeterLabel], false);
    // PART D (Prompt 21): lose jingle
    SND_play(SND_getAssetId("digit_merge2.mp3"), 90);
}

// PART B (Prompt 15): resetGame — restart from round 0
void resetGame(void) {
    vars.roundNumber = 0;
    vars.penaltyBombType = -1;
    vars.timerSecs = TIMER_START_SECS;
    vars.lastTickSec = vars.tick;
    initBoard();
    vars.state = STATE_PLAYING;
    // PART E (Prompt 19): reset win/lose shown flags
    vars.winShown = false;
    vars.loseShown = false;
    // Restore timer and calm meter visibility
    if (vars.timerLabel >= 0) showLabel(&gObjects[vars.timerLabel], true);
    if (vars.calmMeterLabel >= 0) showLabel(&gObjects[vars.calmMeterLabel], true);
    updateTimerDisplay();
}

// PART C (Prompt 16): startNewRound — advance round and apply penalty
void startNewRound(void) {
    vars.roundNumber++;
    vars.penaltyBombType = (vars.roundNumber - 1) % BOMB_TYPES;
    vars.timerSecs = TIMER_START_SECS;
    vars.lastTickSec = vars.tick;
    initBoard();

    // Apply penalty anger to bombs matching penaltyBombType
    for (int q = 2; q <= 23; q++) {
        if (vars.board[q] == vars.penaltyBombType) {
            appObject_t* obj = getBombAtQuad(q);
            if (vars.roundNumber >= 3) {
                vars.boardAnger[q] = ANGER_FURIOUS;
                if (obj != NULL) obj->anger = ANGER_FURIOUS;
            } else if (vars.roundNumber >= 2) {
                vars.boardAnger[q] = ANGER_ANGRY;
                if (obj != NULL) obj->anger = ANGER_ANGRY;
            }
            updateBombVisual(q);
        }
    }

    vars.state = STATE_PLAYING;
    vars.explosionStep = 0;
    vars.explosionStartTick = 0;
    // PART E (Prompt 19): reset win/lose shown flags
    vars.winShown = false;
    vars.loseShown = false;
    // Restore timer and calm meter visibility
    if (vars.timerLabel >= 0) showLabel(&gObjects[vars.timerLabel], true);
    if (vars.calmMeterLabel >= 0) showLabel(&gObjects[vars.calmMeterLabel], true);
    updateTimerDisplay();
}

// handlers
WASM_EXPORT void on_init() {
    OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t));
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
    OCT_background(0x0000);
    vars.state = STATE_TITLE;
    vars.tick = 0;
    vars.timerSecs = TIMER_START_SECS;
    vars.roundNumber = 0;
    vars.penaltyBombType = -1;
    vars.angerLevel = 0;
    vars.angerPending = false;
    vars.lastAngerTick = 0;
    vars.lastTickSec = 0;
    vars.titleLabel = -1;
    vars.startLabel = -1;
    vars.timerLabel = -1;
    vars.lastTwistMs = 0;
    vars.lastMergedQuad = -1;
    // PART A: init shake detection
    vars.prevGravMag = 1.0f;
    // PART B: init explosion
    vars.explosionStep = 0;
    vars.explosionStartTick = 0;
    // PART C: init pass labels
    vars.passLabel = -1;
    vars.passLabel2 = -1;
    for (int i = 0; i < 24; i++) {
        vars.board[i] = -1;
        vars.boardAnger[i] = ANGER_CALM;
        // PART D: init anger tick tracking
        vars.angerTick[i] = 0;
    }
    // PART E (Prompts 18-23): init new fields
    vars.calmMeterLabel = -1;
    vars.winLabel = -1;
    vars.winLabel2 = -1;
    vars.loseLabel = -1;
    vars.loseLabel2 = -1;
    vars.pauseLabel = -1;
    vars.winShown = false;
    vars.loseShown = false;
    initTitleScreen();
}

WASM_EXPORT void on_pretwisted(int32_t twid) {
    twid;
}

static const int TWIST_ROWS[12][8] = {
    { 0, 1, 2, 3,  4, 5, 6, 7},   // 0: TOP_CCW
    { 7, 6, 5, 4,  3, 2, 1, 0},   // 1: TOP_CW
    { 4, 5, 6, 7,  8, 9,10,11},   // 2: FRONT_CCW
    {11,10, 9, 8,  7, 6, 5, 4},   // 3: FRONT_CW
    { 8, 9,10,11, 12,13,14,15},   // 4: RIGHT_CCW
    {15,14,13,12, 11,10, 9, 8},   // 5: RIGHT_CW
    {12,13,14,15, 16,17,18,19},   // 6: BACK_CCW
    {19,18,17,16, 15,14,13,12},   // 7: BACK_CW
    {16,17,18,19, 20,21,22,23},   // 8: LEFT_CCW
    {23,22,21,20, 19,18,17,16},   // 9: LEFT_CW
    {20,21,22,23,  0, 1, 2, 3},   // 10: BOTTOM_CCW
    { 3, 2, 1, 0, 23,22,21,20}    // 11: BOTTOM_CW
};

void getRowForTwist(int twid, int row[8]) {
    int baseTwid = twid;
    if (baseTwid >= OCT_TWIST_HALF) baseTwid -= OCT_TWIST_HALF;
    for (int i = 0; i < 8; i++) {
        row[i] = TWIST_ROWS[baseTwid][i];
    }
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    // PART D: penalty twist and passing guard — replaces old single guard
    if (vars.state == STATE_PASS_PROMPT) {
        triggerExplosion(); // penalty: rotating during pass prompt = explosion
        return;
    }
    if (vars.state != STATE_PLAYING && vars.state != STATE_PASSING) return;
    if (vars.state == STATE_PASSING) return; // no rotations allowed while passing

    vars.lastTwistMs = disconnected_ms;
    int row[8];
    getRowForTwist(twid, row);
    OCT_trace(0, "twist row: %d %d %d %d %d %d %d %d\n", row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]);
    if (twid < OCT_TWIST_HALF) {
        slideBombs(row, 4);
        checkMergeInRow(row);
    } else {
        slideBombs(row, 2);
    }
    if (vars.lastTwistMs < TWIST_FAST_MS) {
        triggerAngerEvent();
    }
}


WASM_EXPORT void on_tap(int32_t tapid) {
    if (vars.state == STATE_TITLE) {
        startGame();
        return;
    }

    // PART E (Prompt 20): pause on BOTTOM tap during playing/pass_prompt — checked first
    if ((vars.state == STATE_PLAYING || vars.state == STATE_PASS_PROMPT) && tapid == OCT_PLANE_BOTTOM) {
        vars.state = STATE_PAUSE;
        vars.pauseLabel = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.0f, 120.0f, 0, FONT_2, ALIGN_CENTER);
        OCT_label_set(&gObjects[vars.pauseLabel], "PAUSED - TAP RESUME");
        return;
    }

    // PART C: handle tap in STATE_PASS_PROMPT — start passing on TOP tap
    if (vars.state == STATE_PASS_PROMPT) {
        if (tapid == OCT_PLANE_TOP) {
            showPassButton(false);
            vars.state = STATE_PASSING;
            vars.prevGravMag = 1.0f;
        }
        return;
    }

    // PART D: handle tap in STATE_PASSING — side tap confirms next player
    if (vars.state == STATE_PASSING) {
        if (tapid != OCT_PLANE_TOP && tapid != OCT_PLANE_BOTTOM) {
            vars.state = STATE_PLAYING;
        }
        return;
    }

    // PART B (Prompt 15): handle win state — tap to reset game
    if (vars.state == STATE_WIN) {
        resetGame();
        return;
    }

    // PART C (Prompt 16): handle lose state — tap to start new round (only after explosion finishes)
    if (vars.state == STATE_LOSE) {
        if (vars.explosionStep >= 21) {
            startNewRound();
        }
        return;
    }

    // PART E (Prompt 20): resume from pause on any tap
    if (vars.state == STATE_PAUSE) {
        if (vars.pauseLabel >= 0) {
            OCT_del(&gObjects[vars.pauseLabel]);
            vars.pauseLabel = -1;
        }
        vars.state = STATE_PLAYING;
        return;
    }
}


WASM_EXPORT void on_tick() {
    // PART A: accelerometer shake detection during pass
    if (vars.state == STATE_PASSING) {
        float gX = OCT_TM_gravity_x(OCT_PLANE_TOP);
        float gY = OCT_TM_gravity_y(OCT_PLANE_TOP);
        float gN = OCT_TM_gravity_n(OCT_PLANE_TOP);
        float mag = fabsf(gX) + fabsf(gY) + fabsf(gN);
        float delta = fabsf(mag - vars.prevGravMag);
        if (delta > 1.5f) {
            triggerAngerEvent();
        }
        vars.prevGravMag = mag;
    }

    // PART B: explosion animation during STATE_LOSE
    if (vars.state == STATE_LOSE) {
        int step = (int)((vars.tick - vars.explosionStartTick) / 2);
        if (step < 22 && step != vars.explosionStep) {
            vars.explosionStep = step;
            appObject_t* obj = getBombAtQuad(step + 2);
            if (obj != NULL) {
                OCT_sequence(obj, BMP_002, BMP_004, 2, OCT_SEQ_RESTART);
            }
        }
    }

    // PART E (Prompt 19): show win/lose screens once
    if (vars.state == STATE_WIN && !vars.winShown) {
        vars.winShown = true;
        showWinScreen();
    }
    if (vars.state == STATE_LOSE && vars.explosionStep >= 21 && !vars.loseShown) {
        vars.loseShown = true;
        showLoseScreen();
    }

    // PART A (Prompt 14): timer countdown during active game states
    if (vars.state == STATE_PLAYING || vars.state == STATE_PASSING || vars.state == STATE_PASS_PROMPT) {
        if (vars.tick - vars.lastTickSec >= (uint32_t)OCT_1SEC_TICKS) {
            vars.lastTickSec = vars.tick;
            vars.timerSecs--;
            updateTimerDisplay();
            // PART D (Prompt 21): tick sound when <= 10 seconds
            if (vars.timerSecs <= 10 && vars.timerSecs > 0) {
                SND_play(SND_getAssetId("digit_merge1.mp3"), 50);
            }
            if (vars.timerSecs <= 0) {
                triggerExplosion();
            }
        }
    }

    // PART D (Prompt 17): per-bomb calm-down over time
    if (vars.state == STATE_PLAYING) {
        for (int quad = 2; quad <= 23; quad++) {
            if (vars.board[quad] == -1) continue;
            if (vars.boardAnger[quad] == ANGER_CALM || vars.boardAnger[quad] == ANGER_LOVED) continue;
            if (vars.tick - vars.angerTick[quad] >= (uint32_t)CALM_TICKS) {
                vars.boardAnger[quad]--;
                vars.angerTick[quad] = vars.tick;
                appObject_t* obj = getBombAtQuad(quad);
                if (obj != NULL) {
                    obj->anger = (AngerLevel)vars.boardAnger[quad];
                }
                updateBombVisual(quad);
            }
        }
    }

    // PART E (Prompt 18): update calm meter every OCT_1SEC_TICKS/2 when playing
    if (vars.state == STATE_PLAYING) {
        if (vars.tick % (OCT_1SEC_TICKS / 2) == 0) {
            updateCalmMeter();
        }
    }

    // PART E (Prompt 23): tick increment at END of on_tick
    vars.tick++;
}
