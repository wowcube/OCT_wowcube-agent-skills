#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_ai_template_ids.h"

//When defined, binds the per-pixel procedural callback (on_proc_draw) in both the simulator and the ARM module
///#define APP_HAS_PROC_DRAW

#define OCT_PLANES_MAX 6 // max planes on the cube
#define OCT_QUADS_AT_PLANE 4 // max quads per plane

#define SPRITES_CAP 400 // scene capacity - maximum possible object count
#define GAP 18 // width of the physical border between WowCube's displays in pixels
#define SIM_SINGLE_THREAD

// Print a float through OCT_text/OCT_trace without %f (double is poisoned on ARM).
// Split into integer and 3-digit fractional parts, format as "%d.%03d":
//   OCT_text(-1, "x=%d.%03d\n", OCT_F_INT(x), OCT_F_FRAC(x));
// Note: for values in (-1, 0) the sign lives in the fractional part only, so e.g. -0.5 prints as "0.500".
#define OCT_F_INT(x) ((int32_t)(x))
#define OCT_F_FRAC(x) ((int32_t)(((x) < 0.0f ? -(x) : (x)) * 1000.0f) % 1000)


// --- INSTRUCTIONS FOR AI AGENT -----------------------
// This file is a reference for OctaviOS API usage.
// * DO NOT copy code 1:1.
// * DO NOT copy internal comments from demos/apis.
// * Use this as a guide to implement specific logic.
// * ALWAYS use explicit type casts - never rely on implicit conversions between numeric types, pointers, or enums.
//   Every narrowing, widening, or cross-type assignment must have a visible cast.
// * Use only fixed-width types from <stdint.h> (int8_t, int16_t, int32_t, uint8_t, uint16_t, uint32_t, size_t, etc.).
//   Never use plain int, short, long.
// * ALWAYS copy the project header structure.
// * ALWAYS copy all handler functions (on_init, on_tick, on_tap, on_twisted, on_pretwisted, on_shake, on_proc_draw) into the output.
//   All seven are mandatory: on_shake must exist or the ARM module fails to link; on_proc_draw must exist as a stub even when unused (the simulator binds it unconditionally, so the SIM build fails without it - the ARM module only references it under APP_HAS_PROC_DRAW).
// * Write modular, readable code: extract game state into structs, split logic into small focused functions, use named constants instead of magic numbers.
// -----------------------------------------------------


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

// State machine
typedef enum {
    DEMO_0 = 0,
    DEMO_1,
    DEMO_2,
    DEMO_2_LERP,
    DEMO_3,
    DEMO_4,
    DEMO_5,
    DEMO_6,
    DEMO_7,
    DEMO_8,
    DEMO_9,
    DEMO_10,
    DEMO_11,
    DEMO_12,
    DEMO_13,
    DEMO_14,
    DEMO_15,
    DEMO_16,
    DEMO_COUNT
} demoId_t;

// Game-specific data
typedef struct _appObject_t: octSprite_t {
    octTm_t animStart; // do not copy this
    octTm_t animEnd; // do not copy this
} appObject_t;

// Demo 2: lerp animation state
typedef struct {
    appObject_t* obj;
    uint32_t lerpStartTick;
    float lerpDuration;
} demo2State_t;

// Demo 6: ring walk state
typedef struct {
    appObject_t* obj;
    int32_t ring; // current ring [0..OCT_PLANES_MAX)
    int32_t step; // current step [0..(OCT_PLANES_MAX-2)*OCT_QUADS_AT_PLANE/2)
} demo6State_t;

// Demo 10: engine tween state
typedef struct {
    appObject_t* obj; // sprite driven by OCT_ANIM_tm
    appObject_t* chaser; // sprite that follows obj through a referenced target
    int32_t anim; // active tween index for obj, 0 = none
    int32_t chaserAnim; // active tween index for chaser, 0 = none
    int32_t funcIdx; // index into DEMO10_FUNCS
    bool halfLogged; // OCT_ANIM_on_half stays set for the whole second half - log once
} demo10State_t;

// Demo 11: orientation state
typedef struct {
    appObject_t* label; // label that always faces "up" on the top plane
} demo11State_t;

// Demo 12: twist-aware transform state
typedef struct {
    appObject_t* obj; // non-twistable sprite moved by hand
    octTm_t velocity; // X/Y = pixels per tick in obj's plane space, do not copy this field name
} demo12State_t;

// Demo 13: procedural sprites state
typedef struct {
    appObject_t* circle;
    appObject_t* text;
    appObject_t* custom;
} demo13State_t;

// Demo 14: system info state
typedef struct {
    appObject_t* clock;
    uint8_t savedBrightness;
    bool dimmed;
} demo14State_t;

// Demo 15: catalog state
typedef struct {
    int32_t entries; // catalog entries seen at init
    uint64_t launchGuid1; // first foreign pack found, 0 = none
    uint64_t launchGuid2;
} demo15State_t;

// Game-specific variables (global)
typedef struct {
    demoId_t currentDemo;
    appObject_t* demoObj; // shared primary object for active demo
    demo2State_t demo2;
    demo6State_t demo6;
    demo10State_t demo10;
    demo11State_t demo11;
    demo12State_t demo12;
    demo13State_t demo13;
    demo14State_t demo14;
    demo15State_t demo15;
    uint32_t tick;
} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////

// utils
appObject_t* getQuadContent(size_t quad);
void showLabel(appObject_t* label, bool show);

// state machine
void switchDemo(demoId_t demo);

// demo
void initDemo0(void);
void twistDemo0(void);
void tapDemo0(size_t plane);
void processDemo0(void);
void processQuadsDemo0(size_t srcQuad, size_t destQuad);

void initDemo1(void);

void initDemo2(void);
void processDemo2(void);
void processDemo2Lerp(void);

void initDemo3(void);
void processDemo3(void);

void initDemo4(void);
void processDemo4(void);

void initDemo5(void);
void processDemo5(void);
void tapDemo5(size_t plane);

void initDemo6(void);
void processDemo6(void);

void initDemo7(void);
void processDemo7(void);

void initDemo8(void);
void twistDemo8(int32_t twid);

void initDemo9(void);
void processDemo9(void);

void initDemo10(void);
void startTweenDemo10(void);
void startChaserDemo10(void);
void processDemo10(void);

void initDemo11(void);
void processDemo11(void);

void initDemo12(void);
void processDemo12(void);
void pretwistDemo12(int8_t plane);
void twistDemo12(int32_t twid);

void initDemo13(void);
void processDemo13(void);
void drawCustomDemo13(uint16_t* back, int32_t idx, int32_t px, int32_t py);

void initDemo14(void);
void processDemo14(void);
void restoreBrightnessDemo14(void);
void tapDemo14(size_t plane, int32_t count);

void initDemo15(void);
void tapDemo15(size_t plane);

void initDemo16(void);


////////////////////////////////
//            MAPS            //
////////////////////////////////

// [NOTE]: All global variables should be defined with the TL macro
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;

// Demo6: 6 rings of the 2x2 WowCube, grouped by axis.
// Each ring is a closed belt of (OCT_PLANES_MAX-2)*OCT_QUADS_AT_PLANE/2 quads wrapping CW through 4 faces.
// Rings 0-1: axis TOP/BOTTOM, Rings 2-3: axis FRONT/BACK, Rings 4-5: axis LEFT/RIGHT.
static const int32_t RING_QUADS[OCT_PLANES_MAX][(OCT_PLANES_MAX - 2) * OCT_QUADS_AT_PLANE / 2] = {
    {0, 3, 4, 7, 20, 23, 14, 13}, // LEFT axis - upper belt CW (TOP -> FRONT -> BOTTOM -> BACK)
    {2, 1, 12, 15, 22, 21, 6, 5}, // LEFT axis - lower belt CW (TOP -> BACK -> BOTTOM -> FRONT)
    {5, 4, 9, 8, 13, 12, 17, 16}, // TOP axis - upper belt CW (FRONT -> RIGHT -> BACK -> LEFT)
    {6, 7, 10, 11, 14, 15, 18, 19}, // TOP axis - lower belt CW (FRONT -> RIGHT -> BACK -> LEFT)
    {3, 2, 16, 19, 21, 20, 10, 9}, // FRONT axis - upper belt CW (TOP -> LEFT -> BOTTOM -> RIGHT)
    {1, 0, 8, 11, 23, 22, 18, 17}, // FRONT axis - lower belt CW (TOP -> RIGHT -> BOTTOM -> LEFT)
};

static const int32_t RING_ANGLES[OCT_PLANES_MAX][(OCT_PLANES_MAX - 2) * OCT_QUADS_AT_PLANE / 2] = {
    {270, 270, 270, 270, 270, 270, 90, 90}, // LEFT axis - upper
    {90, 90, 270, 270, 90, 90, 90, 90}, // LEFT axis - lower
    {0, 0, 0, 0, 0, 0, 0, 0}, // TOP axis - upper
    {0, 0, 0, 0, 0, 0, 0, 0}, // TOP axis - lower
    {180, 180, 270, 270, 0, 0, 90, 90}, // FRONT axis - upper
    {0, 0, 270, 270, 180, 180, 90, 90}, // FRONT axis - lower
};

// Demo10: easing functions cycled by the tween demo (see oct_shared.h, enum ANIM_FUNC)
static const ANIM_FUNC DEMO10_FUNCS[] = {FUNC_LINEAR, FUNC_ACC, FUNC_DEC, FUNC_BOUNCEOUT, FUNC_FALL, FUNC_QUAD, FUNC_JELLY, FUNC_SPAWN};
static const int32_t DEMO10_FUNC_COUNT = (int32_t)(sizeof(DEMO10_FUNCS) / sizeof(DEMO10_FUNCS[0]));

// Demo15: octEntryInfo_t.Type of an installed app pack (the engine's OCT_ENTRY_PACK enum is not visible to a module build)
static const uint32_t APP_ENTRY_PACK = 1;

// Demo13: RGB565 colors used by the procedural sprites
static const uint16_t DEMO13_COLOR_GREEN = 0x07E0;
static const uint16_t DEMO13_COLOR_YELLOW = 0xFFE0;
static const uint16_t DEMO13_COLOR_CYAN = 0x07FF;
static const int16_t DEMO13_CUSTOM_HALF = 30; // half-extent of the custom-drawn square in display pixels


////////////////////////////////
//       IMPLEMENTATION       //
////////////////////////////////

// utils

// Util: copy this code if needed
appObject_t* getQuadContent(size_t quad) {
    // API info + util

    // A quad represents a physical display on a plane. Its size is 240x240.
    // Quads [0; 3] start from the top-right center (120 + GAP; 120 + GAP) and rotate CCW.
    // quadId = quad [0; 3] + plane_id * OCT_QUADS_AT_PLANE

    // gObjects[0] is an invalid object because the validation check is idx == obj.Idx.
    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];

        // Check for a valid object (Idx always equals the object ID).
        if ((size_t)obj->Idx != i) continue; // Invalid object

        // Short: OCT_TM_quad returns the quad ID where the given transform (octTm_t) is located.
        // Declaration: int OCT_TM_quad(const octTm_t* tm);
        // Comment: Every sprite (octSprite_t) has a transform property (Tm) of type octTm_t.
        if((size_t)OCT_TM_quad(&obj->Tm) == quad) return obj;

        // Second method: do not copy this!
        {
            // Short: Manual calculation of quad content based on coordinates.
            // Comment: XSIGN and YSIGN determine the sign of X and Y coordinates for each local quad [0; 3].
            // Warn: do not redeclare XSIGN and YSIGN! They are already declared in `oct_shared.h`.

            // XSIGN: {+1, -1, -1, +1}
            // YSIGN: {+1, +1, -1, -1}

            int16_t plane = (int16_t)(quad / OCT_QUADS_AT_PLANE);
            int16_t lQuad = (int16_t)(quad % OCT_QUADS_AT_PLANE);

            if ((int16_t)obj->Tm.Plane == plane && obj->Tm.X * (float)XSIGN[lQuad] > 0 && obj->Tm.Y * (float)YSIGN[lQuad] > 0) return obj;
        }

    }
    return NULL;
}

// Util: copy this code if need to modify label properties
void showLabel(appObject_t* label, bool show) {
    // API + util
    // Short: Toggles visibility of a label and all its child glyphs (letters).
    // Comment: A label created by OCT_add_label has child sprites (one per glyph) linked via Parent.
    // Comment: Setting Hidden on the label alone is not enough - each child glyph must also be toggled.
    label->Hidden = !show;

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if ((size_t)obj->Idx != i) continue;

        // check if object is child of label
        if (obj->Parent == label->Idx) {
            obj->Hidden = !show;
        }
    }
}

// demo

// Demo: do not copy-paste this code
void initDemo0(void) {
    // API info + demo
    // Demo 0: how to add sprites

    for (size_t plane = OCT_PLANE_TOP; plane < OCT_PLANES_MAX; plane++) {
        for (int16_t y = -120; y <= 120; y += 240) {
            for (int16_t x = -120; x <= 120; x+= 240) {
                // OCT_add(0, false, (int32_t)plane, (float)x, (float)y, 0, false, BMP_000, BMP_000, 0);

                if (plane == OCT_PLANE_TOP) {
                    // Short: OCT_add adds a sprite to the scene; returns idx in gObjects.
                    // Declaration: int OCT_add(int layer, bool twistable, int plane, float x, float y, int a, bool loop, int bmpfrom, int bmpto, int framelen);
                    // Comment: twistable=false means the engine automatically resets the position after a twist.
                    // Comment: parameter 'a' is the sprite angle in degrees (int16_t, not float); only right angles are supported (0, 90, 180, 270). Positive values rotate counter-clockwise (CCW), 0 degrees points right (+X).
                    // Comment: (loop, bmpfrom, bmpto, framelen) are used for animation; framelen is the number of global ticks per frame.
                    // Critical Comment: NO NEED to account for GAP in the x/y coordinates - the engine handles GAP offsets automatically!
                    OCT_add(1, true, (int32_t)plane, (float)x, (float)y, 0, false, BMP_001, BMP_001, 0);
                }
            }
        }
    }

    OCT_add(1, true, OCT_PLANE_FRONT, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
}

// Demo: do not copy-paste this code
void twistDemo0(void) {
    // API info + demo
    // Demo 0: how to reset angles
    // Comment: Use only if required by game logic or specified by the user; default behavior is NOT to reset angles.

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        if ((size_t)gObjects[i].Idx != i) continue;

        gObjects[i].Tm.A = 0; // Reset angle (relative to Tm.Plane)
        // Comment: Tm.A is the sprite angle in degrees (int16_t, not float); only right angles are supported (0, 90, 180, 270). Positive values rotate counter-clockwise (CCW), 0 degrees points right (+X).
    }
}

// Demo: do not copy-paste this code
void tapDemo0(size_t plane) {
    // API info + demo
    // Demo 0: how to delete objects + play sounds + use random

    const char* sounds[] = {
        "digit_merge0.mp3",
        "digit_merge1.mp3",
        "digit_merge2.mp3"
    };

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if ((size_t)obj->Idx != i || (size_t)obj->Tm.Plane != plane) continue;

        // Short: OCT_random returns a random integer in the range [dmin; dmax).
        // Declaration: int OCT_random(int dmin, int dmax);
        // Comment: Upper bound dmax is exclusive.
        size_t id = (size_t)OCT_random(0, (int32_t)(sizeof(sounds) / sizeof(char*)));

        // Short: SND_getAssetId returns the asset ID for a given sound file name.
        // Declaration: int SND_getAssetId(const char* name);
        int32_t soundId = SND_getAssetId(sounds[id]);

        // Short: SND_play plays a sound by its asset ID with a specified volume.
        // Declaration: int SND_play(int id, int volume);
        // Comment: volume is in the range [0; 100].
        SND_play(soundId, 100);

        // Short: OCT_del delete a sprite from the scene.
        // Declaration: void OCT_del(octSprite_t* s).
        // Comment: Also deletes child sprites (label glyphs) and cancels every engine tween (OCT_ANIM_tm) targeting the sprite.
        OCT_del(obj);
    }
}

// Demo: do not copy-paste this code
void processDemo0(void) {
    if (vars.tick == OCT_1SEC_TICKS)
        processQuadsDemo0(4, 5);
}

// Demo: do not copy-paste this code
void initDemo1(void) {
    // API info + demo
    // Demo 1: how to make virtual twist

    for (size_t plane = OCT_PLANE_TOP; plane < OCT_PLANES_MAX; plane++) {
        for (int16_t y = -120; y <= 120; y += 240) {
            for (int16_t x = -120; x <= 120; x+= 240) {
                OCT_add(0, false, (int32_t)plane, (float)x, (float)y, 0, false, BMP_000, BMP_000, 0);

                if (plane == OCT_PLANE_TOP)
                    OCT_add(1, true, (int32_t)plane, (float)x, (float)y, 0, false, BMP_001, BMP_001, 0);
            }
        }
    }

    // Directions: TOP_CCW, TOP_CW, FRONT_CCW, FRONT_CW, RIGHT_CCW, RIGHT_CW, BACK_CCW, BACK_CW, LEFT_CCW, LEFT_CW, BOTTOM_CCW, BOTTOM_CW
    // Warning: CW and CCW are defined looking from outside of the cube at the given face (right-hand rule), NOT from the perspective of a neighboring face.

    // Short: OCT_twist_sprites performs a virtual twist of all twistable sprites on the cube.
    // Declaration: void OCT_twist_sprites(octTwistId_t twid);
    OCT_twist_sprites(FRONT_CW);
    OCT_twist_sprites(RIGHT_CCW);
}

// Demo: do not copy-paste this code
void initDemo2(void) {
    // demo
    int32_t id = OCT_add(0, true, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demo2.obj = &gObjects[id];
    vars.demo2.lerpStartTick = 0;
    vars.demo2.lerpDuration = 0;
}

// Demo: do not copy-paste this code
void processDemo2(void) {
    // API info + demo
    // Demo 2: PREFERRED way to move sprites - OCT_TM_walk handles cross-plane transitions automatically

    if (vars.tick % OCT_1SEC_TICKS != 0) return;

    // Short: [PREFERRED] OCT_TM_walk moves a transform forward (and optionally sideways) along a given direction angle; returns old plane.
    // Declaration: int OCT_TM_walk(octTm_t* tm, int forward_direction_angle, float forward_distance, float left_distance, bool wrap);
    // Comment: forward_direction_angle is the movement direction in degrees; forward_distance is the distance in pixels along that direction; left_distance is the perpendicular (left) offset.
    // Comment: wrap is needed to correct coords after reaching side limits (240x240) to automatically change plane; in most cases wrap should be true.
    OCT_TM_walk(&vars.demo2.obj->Tm, (int32_t)vars.demo2.obj->Tm.A, 240.f + 2.f * GAP, 0.0f, true); // 240.f (size of quad) + 2 * GAP ensures the sprite moves to the next display
}

// Demo: do not copy-paste this code
void processDemo2Lerp(void) {
    // API info + demo
    // Demo 2: sprite movement animation - uses OCT_TM_walk to compute the target, then lerps to animate
    // Comment: For fire-and-forget movement prefer the engine tweens of Demo 10 (OCT_ANIM_tm) - no per-tick bookkeeping in the app.

    // start
    if (vars.demo2.lerpStartTick == 0) {
        vars.demo2.lerpStartTick = vars.tick;
        vars.demo2.lerpDuration = (float)OCT_1SEC_TICKS; // 1 second

        // Short: OCT_TM_copy copies the full transform (octTm_t) from src to dst.
        // Declaration: void OCT_TM_copy(octTm_t* dst, const octTm_t* src);
        OCT_TM_copy(&vars.demo2.obj->animStart, &vars.demo2.obj->Tm);

        // set animation end
        OCT_TM_copy(&vars.demo2.obj->animEnd, &vars.demo2.obj->Tm);
        OCT_TM_walk(&vars.demo2.obj->animEnd, (int32_t)vars.demo2.obj->Tm.A, 240.f + 2.f * GAP, 0.0f, true);
    }

    float progress = (float)(vars.tick - vars.demo2.lerpStartTick) / vars.demo2.lerpDuration;

    // Short: OCT_TM_lerp linearly interpolates between two transforms a and b by factor t [0; 1], handling cross-plane transitions.
    // Declaration: void OCT_TM_lerp(octTm_t* tm, octTm_t* a, octTm_t* b, float t);
    // Comment: t is clamped to [0; 1]; the result is written to tm; transform a is converted to b's plane space before interpolation.
    OCT_TM_lerp(&vars.demo2.obj->Tm, &vars.demo2.obj->animStart, &vars.demo2.obj->animEnd, progress);
}

// Demo: do not copy-paste this code
void initDemo3(void) {
    // demo
    int32_t id = OCT_add(0, true, OCT_PLANE_TOP, 120.f, 120.f, 0, true, BMP_001, BMP_003, 1);
    vars.demoObj = &gObjects[id];
    vars.demoObj->Paused = true; // pause animation to start it explicitly in process; otherwise will start on next tick; default Paused=false.
}

// Demo: do not copy-paste this code
void processDemo3(void) {
    // API + demo
    // Demo3: how to change sprite animation

    if (vars.tick == 0) vars.demoObj->Paused = false;

    if (vars.tick == OCT_1SEC_TICKS) {
        // Short: OCT_sequence sets up a frame animation sequence for a sprite; zeroes keep current values.
        // Declaration: void OCT_sequence(octSprite_t* spr, int from, int to, int framelen, octSeqRestart_t restart);
        // Comment: restart mode: OCT_SEQ_RESTART (play from start), OCT_SEQ_REVERSE (play from end), OCT_SEQ_REFRESH (keep current position).
        OCT_sequence(vars.demoObj, BMP_004, BMP_009, 1, OCT_SEQ_RESTART);
        vars.demoObj->Loop = true; // loop animation
    }
}

// Demo: do not copy-paste this code
void initDemo4(void) {
    // API + demo
    // Demo4: how to create labels

    // Short: OCT_add_label adds a text label to the scene; returns idx in gObjects.
    // Declaration: int OCT_add_label(int layer, bool twistable, int side, float x, float y, int a, int font_idx, int align);
    // Comment: parameter 'a' is int16_t (not float); only right angles are supported (0, 90, 180, 270).
    // Comment: font_idx selects the font [1..3] (FONT_1, FONT_2, FONT_3); align sets text alignment (ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT).
    // Comment: Each glyph is a separate child sprite with Parent set to the label's Idx.
    // Comment: Use OCT_label_set to assign text after creation; use showLabel to toggle visibility of the label and its glyphs.
    int32_t id = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.f, 120.f, 0, FONT_1, ALIGN_CENTER);
    vars.demoObj = &gObjects[id];
}

// Demo: do not copy-paste this code
void processDemo4(void) {
    // API + demo
    // Demo4: how to modify and delete labels

    if (vars.tick % OCT_1SEC_TICKS == 0) {
        showLabel(vars.demoObj, true);

        char buf[12];
        snprintf(buf, 12, "%lu", vars.tick / OCT_1SEC_TICKS);

        // Short: OCT_label_set updates the text of a label; recreates child glyph sprites; returns text length.
        // Declaration: int OCT_label_set(octSprite_t* label, const char* text);
        // Comment: Deletes old glyph sprites and creates new ones based on the text string; supports '\n' for multi-line labels.
        // Comment: Skips update if the text has not changed since the last call.
        OCT_label_set(vars.demoObj, buf);
    }

    if (vars.tick % (2 * OCT_1SEC_TICKS) == 0)
        showLabel(vars.demoObj, false);

    if (vars.tick == 10 * OCT_1SEC_TICKS) {
        // no need to delete childs explicity
        OCT_del(vars.demoObj);
    }
}


// Demo: do not copy-paste this code
void processQuadsDemo0(size_t srcQuad, size_t destQuad) {
    // API + demo
    // Demo 0: LOW-LEVEL way to move objects between quads. Prefer OCT_TM_move and OCT_TM_walk for general movement.

    appObject_t* src = getQuadContent(srcQuad);
    if (!src) return;

    appObject_t* dest = getQuadContent(destQuad);
    if (dest) return; // quad is occupied

    float destX = (120.f + GAP) * (float)XSIGN[destQuad % OCT_QUADS_AT_PLANE];
    float destY = (120.f + GAP) * (float)YSIGN[destQuad % OCT_QUADS_AT_PLANE];

    // Short: OCT_TM_move offsets a transform by (dx, dy) within the current plane; does not handle cross-plane transitions.
    // Declaration: void OCT_TM_move(octTm_t* tm, float dx, float dy);
    // Comment: Use OCT_TM_move for simple in-plane displacement. For cross-plane movement, prefer OCT_TM_walk.
    OCT_TM_move(&src->Tm, destX - src->Tm.X, destY - src->Tm.Y);

    // Short: [LOW-LEVEL] OCT_TM_change_plane moves a transform to a different plane, adjusting coordinates and angle accordingly.
    // Declaration: void OCT_TM_change_plane(octTm_t* tm, int to);
    OCT_TM_change_plane(&src->Tm, (int32_t)(destQuad / OCT_QUADS_AT_PLANE));

    // [LOW-LEVEL] Alternative: direct coordinate assignment (shown for reference only).
    src->Tm.X = destX;
    src->Tm.Y = destY;
}


// Demo: do not copy-paste this code
void initDemo5(void) {
    // API info + demo
    // Demo 5: how to get bitmap info (size, pivots, bounding box)

    int32_t id = OCT_add(0, true, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demoObj = &gObjects[id];

    // Short: OCT_BMP_info fills an octBmpInfo_t structure with bitmap metadata (size, pivot, bounding box, etc.).
    // Declaration: void OCT_BMP_info(uint32_t bmp_idx, octBmpInfo_t* info);
    // Comment: octBmpInfo_t fields: Name[24], W, H (screen pixels), PivotX, PivotY, Bx, By, Bw, Bh (bounding geometry), Tags, Number, Group, Type.
    // Comment: Can be called at any time with any valid BMP index; does not require a sprite to exist.
    octBmpInfo_t info;
    OCT_BMP_info((uint32_t)BMP_001, &info);

    // Short: OCT_text prints a printf-style debug line shown on screen when OCT_dev_mode(OCT_DEV_TEXT) is on.
    // Declaration: void OCT_text(int string_index, const char* format, ...);
    // Comment: string_index is a slot in a fixed array of DEBUG_STRINGS (10) lines. An in-range index [0; 10) overwrites that slot directly (use for a stable line refreshed each tick); any out-of-range index (e.g. -1) appends in log mode, scrolling older lines toward higher slots.
    // Comment: lines whose text starts with '.' are pinned and do not scroll. Same no-%f rule as OCT_trace (variadic, double poisoned on ARM) - print floats via OCT_F_INT/OCT_F_FRAC.
    OCT_text(-1, "Demo5 init BMP_001: name=%s W=%d H=%d pivotX=%d.%03d pivotY=%d.%03d\n",
        info.Name, (int32_t)info.W, (int32_t)info.H, OCT_F_INT(info.PivotX), OCT_F_FRAC(info.PivotX), OCT_F_INT(info.PivotY), OCT_F_FRAC(info.PivotY));
}

// Demo: do not copy-paste this code
void processDemo5(void) {
    // API info + demo
    // Demo 5: how to query bitmap info dynamically

    if (vars.tick == 0) {
        octBmpInfo_t info;
        OCT_BMP_info((uint32_t)BMP_000, &info);

        OCT_text(-1, "Demo5 tick0 BMP_000: name=%s W=%d H=%d pivotX=%d.%03d pivotY=%d.%03d\n",
            info.Name, (int32_t)info.W, (int32_t)info.H, OCT_F_INT(info.PivotX), OCT_F_FRAC(info.PivotX), OCT_F_INT(info.PivotY), OCT_F_FRAC(info.PivotY));
    }
}

// Demo: do not copy-paste this code
void tapDemo5(size_t plane) {
    // API info + demo
    // Demo 5: how to get bounding box info for sprites on a tapped plane

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if ((size_t)obj->Idx != i || (size_t)obj->Tm.Plane != plane) continue;

        octBmpInfo_t info;
        OCT_BMP_info((uint32_t)obj->Frame, &info);

        OCT_text(-1, "Demo5 tap sprite[%lu]: name=%s W=%d H=%d Bx=%d.%03d By=%d.%03d Bw=%d.%03d Bh=%d.%03d\n",
            i, info.Name, (int32_t)info.W, (int32_t)info.H, OCT_F_INT(info.Bx), OCT_F_FRAC(info.Bx), OCT_F_INT(info.By), OCT_F_FRAC(info.By), OCT_F_INT(info.Bw), OCT_F_FRAC(info.Bw), OCT_F_INT(info.Bh), OCT_F_FRAC(info.Bh));
    }
}


// Demo: do not copy-paste this code
void initDemo6(void) {
    // Demo 6: Ring Demo - one sprite walks around 6 rings of the cube.
    // Rings grouped by axis: 2 TOP, 2 FRONT, 2 LEFT. Each ring is a CW loop through 4 faces.

    int32_t id = OCT_add(0, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demo6.obj = &gObjects[id];
    vars.demo6.ring = 0;
    vars.demo6.step = 0;
}

// Demo: do not copy-paste this code
void processDemo6(void) {
    // Demo 6: walk the sprite one quad every second along the current ring.
    // Each ring is a closed CW loop - after 8 walks the sprite returns to its start.
    // Then OCT_TM_set teleports it to the first quad of the next ring.

    if (vars.demo6.ring >= OCT_PLANES_MAX) return;
    if (vars.tick % OCT_1SEC_TICKS != 0) return;

    OCT_TM_walk(&vars.demo6.obj->Tm, RING_ANGLES[vars.demo6.ring][vars.demo6.step], 240.f + 2 * GAP, 0.0f, true);

    vars.demo6.step++;
    if (vars.demo6.step >= (OCT_PLANES_MAX - 2) * OCT_QUADS_AT_PLANE / 2) {
        vars.demo6.ring++;
        vars.demo6.step = 0;
        if (vars.demo6.ring < OCT_PLANES_MAX) {
            int32_t q = RING_QUADS[vars.demo6.ring][0];
            float x = (120.f + GAP) * XSIGN[q % OCT_QUADS_AT_PLANE];
            float y = (120.f + GAP) * YSIGN[q % OCT_QUADS_AT_PLANE];
            // Short: OCT_TM_set sets a transform's position, angle, and plane directly (teleport).
            // Declaration: void OCT_TM_set(octTm_t* tm, float x, float y, int a, int plane);
            // Comment: Unlike OCT_TM_walk, this does not animate or handle transitions - it overwrites all fields at once.
            // Comment: parameter 'a' is int16_t (not float); only right angles are supported (0, 90, 180, 270).
            OCT_TM_set(&vars.demo6.obj->Tm, x, y, 0, q / OCT_QUADS_AT_PLANE);
        }
    }
}

// Demo: do not copy-paste this code
void initDemo7(void) {
    // Demo 7: transparency fade-in-out.
    int32_t id = OCT_add(0, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demoObj = &gObjects[id];
    vars.demoObj->Transp = 0;
}

// Demo: do not copy-paste this code
void processDemo7(void) {
    // Demo 7: full fade cycle in 2 seconds: 0 -> OCT_TRANSP_MAX -> 0.
    // Comment: transparency mapping is 0 = fully opaque, OCT_TRANSP_MAX = fully transparent.
    uint32_t period = (uint32_t)(2U * OCT_1SEC_TICKS);
    uint32_t phase = vars.tick % period;
    uint32_t half = period / 2U;
    uint32_t transp;

    if (phase < half) {
        transp = (phase * (uint32_t)OCT_TRANSP_MAX) / half;
    } else {
        transp = ((period - phase) * (uint32_t)OCT_TRANSP_MAX) / half;
    }

    vars.demoObj->Transp = (uint8_t)transp;
}

// Demo: do not copy-paste this code
void initDemo8(void) {
    // API info + demo
    // Demo 8: how to query OCT_TWISTS to find affected quads after a twist.

    OCT_add(0, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
}

// Demo: do not copy-paste this code
void twistDemo8(int32_t twid) {
    // API info + demo
    // Demo 8: log quads affected by a twist using the OCT_TWISTS table.

    if (twid >= OCT_TWIST_HALF) return; // half-twists share the same quad layout as standard twists

    // Short: OCT_TWISTS is a constant table of 12 octTwist_t entries (one per standard twist).
    // Declaration: const octTwist_t OCT_TWISTS[12];
    // Comment: octTwist_t fields: QuadsDisk[4] (rotating face), QuadsRing1[4] and QuadsRing2[4] (two adjacent rings), RingsMask (bitmask of ring quads 0..23), Impulse[6] (direction per plane; 360 = unaffected).
    // Comment: Index OCT_TWISTS with twid [0..11]. For half-twists (twid >= 12), subtract OCT_TWIST_HALF to get the base index.
    const octTwist_t* tw = &OCT_TWISTS[twid];

    OCT_text(-1, "Demo8 twist %d: disk=[%d,%d,%d,%d] ring1=[%d,%d,%d,%d] ring2=[%d,%d,%d,%d]\n",
        twid,
        tw->QuadsDisk[0], tw->QuadsDisk[1], tw->QuadsDisk[2], tw->QuadsDisk[3],
        tw->QuadsRing1[0], tw->QuadsRing1[1], tw->QuadsRing1[2], tw->QuadsRing1[3],
        tw->QuadsRing2[0], tw->QuadsRing2[1], tw->QuadsRing2[2], tw->QuadsRing2[3]);

    OCT_text(-1, "Demo8 impulse=[%d,%d,%d,%d,%d,%d] ringsMask=0x%08lx\n",
        tw->Impulse[0], tw->Impulse[1], tw->Impulse[2],
        tw->Impulse[3], tw->Impulse[4], tw->Impulse[5],
        (uint32_t)tw->RingsMask);
}

// Demo: do not copy-paste this code
void initDemo9(void) {
    // API info + demo
    // Demo 9: parent-child sprite relationship.
    // Child sprite uses local coordinates relative to its parent.
    // When parent moves or rotates, the child follows automatically (the engine composes transforms via OCT_TM_combine at render time).

    // create parent sprite at center of TOP plane, quad 0
    int32_t parentId = OCT_add(0, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demoObj = &gObjects[parentId];

    // create child sprite - world coords first, then convert to local
    int32_t childId = OCT_add(0, false, OCT_PLANE_TOP, 120.f + 60.f, 120.f, 0, false, BMP_002, BMP_002, 0);
    appObject_t* child = &gObjects[childId];

    // Short: Setting Parent to the parent's Idx makes the child's Tm local (relative to parent).
    // Comment: The engine applies OCT_TM_combine at render time: rotates child's local (X,Y) by parent's angle, adds parent's position, and inherits parent's plane.
    // Comment: After setting Parent, child coordinates MUST be converted to parent-local space by subtracting the parent's world position.
    child->Parent = vars.demoObj->Idx;
    child->Tm.X = child->Tm.X - vars.demoObj->Tm.X; // convert to local X (= 60)
    child->Tm.Y = child->Tm.Y - vars.demoObj->Tm.Y; // convert to local Y (= 0)
}

// Demo: do not copy-paste this code
void processDemo9(void) {
    // API info + demo
    // Demo 9: parent orbits around the quad center; child follows automatically.

    // Short: OCT_TM_sin/cos return sin/cos for an integer angle in degrees; backed by a 360-entry lookup table.
    // Declaration: float OCT_TM_sin(int deg);
    // Declaration: float OCT_TM_cos(int deg);

    float radius = 120.f;
    int32_t angle = (int32_t)(vars.tick * 6) % 360; // 6 deg/tick -> full circle in 3 seconds
    float cx = 0.f; // plane center X
    float cy = 0.f; // plane center Y

    float x = cx + radius * OCT_TM_cos(angle);
    float y = cy + radius * OCT_TM_sin(angle);
    OCT_TM_set(&vars.demoObj->Tm, x, y, 0, (int32_t)vars.demoObj->Tm.Plane);
}


// Demo: do not copy-paste this code
void initDemo10(void) {
    // API info + demo
    // Demo 10: engine tweens - the engine moves a transform for you over N ticks with an easing function.
    // The main sprite hops between the two right-hand quads of the TOP plane cycling through every easing.
    // A second "chaser" sprite is tweened towards a REFERENCED target, so it follows the main sprite while it moves.

    int32_t id = OCT_add(1, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demo10.obj = &gObjects[id];

    int32_t chaserId = OCT_add(0, false, OCT_PLANE_TOP, -120.f, -120.f, 0, false, BMP_002, BMP_002, 0);
    vars.demo10.chaser = &gObjects[chaserId];

    vars.demo10.anim = 0;
    vars.demo10.chaserAnim = 0;
    vars.demo10.funcIdx = 0;
    vars.demo10.halfLogged = false;

    startTweenDemo10();
    startChaserDemo10();
}

// Demo: do not copy-paste this code
void startTweenDemo10(void) {
    // API info + demo
    // Demo 10: start a tween from the sprite's current transform to the mirrored quad on the same plane.

    appObject_t* obj = vars.demo10.obj;

    octTm_t from;
    octTm_t to;
    OCT_TM_copy(&from, &obj->Tm);
    OCT_TM_copy(&to, &obj->Tm);
    to.X = -from.X; // mirrored quad, same plane (positions already include the engine's GAP offset)

    ANIM_FUNC func = DEMO10_FUNCS[vars.demo10.funcIdx];
    float arc = (func == FUNC_LINEAR) ? 0.f : 60.f;

    // Short: OCT_ANIM_tm starts an engine-driven tween that writes X, Y and Plane into *target every tick; returns the tween index (0 = no free slot).
    // Declaration: int OCT_ANIM_tm(float arc, int delay_ticks, int duration_ticks, void* context, int func, octTm_t* from, octTm_t* to, bool reffrom, bool refto, octTm_t* target);
    // Comment: arc is an extra Y offset at mid-flight (0 = straight line, > 0 = ballistic hop); 'to' may be on another plane, the tween crosses the edge.
    // Comment: func is an easing from enum ANIM_FUNC (never FUNC_NONE): FUNC_LINEAR, FUNC_ACC, FUNC_DEC, FUNC_BOUNCEOUT, FUNC_FALL move to 'to'; FUNC_QUAD, FUNC_JELLY, FUNC_SPAWN are effects that RETURN to 'from'.
    // Comment: reffrom/refto = true stores the POINTER and re-reads it every tick (a moving target that must outlive the tween); false copies the transform now.
    vars.demo10.anim = OCT_ANIM_tm(arc, 0, OCT_1SEC_TICKS, NULL, (int32_t)func, &from, &to, false, false, &obj->Tm);
    vars.demo10.halfLogged = false;

    OCT_text(-1, "Demo10 tween func=%d arc=%d anim=%d\n", (int32_t)func, (int32_t)arc, vars.demo10.anim);
}

// Demo: do not copy-paste this code
void startChaserDemo10(void) {
    // API info + demo
    // Demo 10: tween the chaser towards the main sprite's LIVE transform (refto = true).

    appObject_t* chaser = vars.demo10.chaser;

    octTm_t from;
    OCT_TM_copy(&from, &chaser->Tm);

    // Short: OCT_ANIM_tm_tw is OCT_ANIM_tm for twistable content: the tween's endpoints are carried along by physical twists.
    // Declaration: int OCT_ANIM_tm_tw(float arc, int delay_ticks, int duration_ticks, void* context, int func, octTm_t* from, octTm_t* to, bool reffrom, bool refto, octTm_t* target);
    // Comment: Here 'to' is a pointer to the main sprite's Tm (refto = true), so the chaser re-aims every tick while its target moves.
    vars.demo10.chaserAnim = OCT_ANIM_tm(0.f, 0, 2 * OCT_1SEC_TICKS, NULL, FUNC_DEC, &from, &vars.demo10.obj->Tm, false, true, &chaser->Tm);
}

// Demo: do not copy-paste this code
void processDemo10(void) {
    // API info + demo
    // Demo 10: poll tween events and chain the next tween.

    if (vars.demo10.anim != 0) {
        // Short: OCT_ANIM_on_half returns 1 while a tween is past its half-way point (a level, not a one-tick pulse).
        // Declaration: int OCT_ANIM_on_half(int aidx);
        if (!vars.demo10.halfLogged && OCT_ANIM_on_half(vars.demo10.anim) != 0) {
            vars.demo10.halfLogged = true;

            // Short: OCT_ANIM_get_progress returns the tween's tick counter: negative while delayed, then 0..duration_ticks.
            // Declaration: int OCT_ANIM_get_progress(int aidx);
            OCT_text(-1, "Demo10 half-way at progress=%d\n", OCT_ANIM_get_progress(vars.demo10.anim));
        }

        // Short: OCT_ANIM_on_end returns 1 during the single tick a tween reaches its end; the tween auto-deletes on the next tick and its index may be reused.
        // Declaration: int OCT_ANIM_on_end(int aidx);
        if (OCT_ANIM_on_end(vars.demo10.anim) != 0) {
            vars.demo10.anim = 0;
            vars.demo10.funcIdx = (vars.demo10.funcIdx + 1) % DEMO10_FUNC_COUNT;
            startTweenDemo10();
        }
    }

    if (vars.demo10.chaserAnim != 0 && OCT_ANIM_on_end(vars.demo10.chaserAnim) != 0) {
        vars.demo10.chaserAnim = 0;
        startChaserDemo10();
    }

    // Short: OCT_ANIM_del cancels a running tween by index (a stale or zero index is ignored).
    // Declaration: void OCT_ANIM_del(int aidx);
    if (vars.tick == 30 * OCT_1SEC_TICKS && vars.demo10.chaserAnim != 0) {
        OCT_ANIM_del(vars.demo10.chaserAnim);
        vars.demo10.chaserAnim = 0;
        OCT_text(-1, "Demo10 chaser stopped\n");
    }
}


// Demo: do not copy-paste this code
void initDemo11(void) {
    // API info + demo
    // Demo 11: orientation - keep content "up" on the top face the same way system toasts do, and read the IMU.

    int32_t id = OCT_add_label(1, false, OCT_TM_top_side(), 120.f, 120.f, 0, FONT_2, ALIGN_CENTER);
    vars.demo11.label = &gObjects[id];
    OCT_label_set(vars.demo11.label, "UP");
}

// Demo: do not copy-paste this code
void processDemo11(void) {
    // API info + demo
    // Demo 11: re-aim the label every tick; log the sensors twice a second.

    int8_t top = (int8_t)OCT_TM_top_side();

    // Short: OCT_TM_face_up returns the system "up" direction for a plane in degrees (0 = the plane's +Y).
    // Declaration: int OCT_TM_face_up(int side);
    // Comment: On a side plane it is gravity-up; for the top plane and its opposite it is LATCHED when that plane became top, so content does not spin while the cube is tilted - the same orientation system notifications use.
    // Comment: Snap it to the nearest right angle before assigning to Tm.A.
    int32_t up = OCT_TM_face_up(top);
    int32_t snapped = ((up + 45) / 90) * 90;
    // Short: OCT_TM_normalize_angle wraps any integer angle into [0; 360).
    // Declaration: int OCT_TM_normalize_angle(int deg);
    snapped = OCT_TM_normalize_angle(snapped);

    OCT_TM_set(&vars.demo11.label->Tm, vars.demo11.label->Tm.X, vars.demo11.label->Tm.Y, snapped, top);

    if (vars.tick % (OCT_1SEC_TICKS / 2) != 0) return;

    // Short: OCT_TM_acc_x/y/n return the LINEAR acceleration projected on a plane (gravity removed) - bumps, knocks, shakes.
    // Declaration: float OCT_TM_acc_x(int side); float OCT_TM_acc_y(int side); float OCT_TM_acc_n(int side);
    // Comment: OCT_TM_mixed_acc_x/y/n is the same projection of the RAW accelerometer (gravity included).
    float ax = OCT_TM_acc_x(top);
    float ay = OCT_TM_acc_y(top);
    float an = OCT_TM_acc_n(top);

    // Short: OCT_TM_tap_x/y/n project the direction of the current tap series onto a plane - which way the cube was knocked.
    // Declaration: float OCT_TM_tap_x(int side); float OCT_TM_tap_y(int side); float OCT_TM_tap_n(int side);
    float tx = OCT_TM_tap_x(top);
    float ty = OCT_TM_tap_y(top);

    // Short: OCT_TM_arctan returns the angle of vector (x, y) in integer degrees; fast approximation (max error 0.25 degree).
    // Declaration: int OCT_TM_arctan(int y, int x);
    float gx = OCT_TM_gravity_x(OCT_PLANE_FRONT);
    float gy = OCT_TM_gravity_y(OCT_PLANE_FRONT);
    int32_t downhill = OCT_TM_normalize_angle(OCT_TM_arctan((int32_t)(gy * 1000.f), (int32_t)(gx * 1000.f)));

    // Short: OCT_lerp blends two floats; NOTE the reversed weight: t = 1 returns 'from', t = 0 returns 'to'.
    // Declaration: float OCT_lerp(float from, float to, float t);
    float smoothed = OCT_lerp(ax, 0.f, 0.5f);


    // Short: OCT_acc_visual_x/y/z return the latest raw IMU sample as integers (debug/telemetry only).
    // Declaration: int OCT_acc_visual_x(); int OCT_acc_visual_y(); int OCT_acc_visual_z();
    OCT_text(-1, "Demo11 top=%d up=%d acc=%d.%03d,%d.%03d,%d.%03d half=%d.%03d tap=%d.%03d,%d.%03d down=%d raw=%d,%d,%d\n",
        (int32_t)top, up,
        OCT_F_INT(ax), OCT_F_FRAC(ax), OCT_F_INT(ay), OCT_F_FRAC(ay), OCT_F_INT(an), OCT_F_FRAC(an),
        OCT_F_INT(smoothed), OCT_F_FRAC(smoothed),
        OCT_F_INT(tx), OCT_F_FRAC(tx), OCT_F_INT(ty), OCT_F_FRAC(ty),
        downhill, OCT_acc_visual_x(), OCT_acc_visual_y(), OCT_acc_visual_z());
}


// Demo: do not copy-paste this code
void initDemo12(void) {
    // API info + demo
    // Demo 12: twist-aware transforms - a NON-twistable sprite that the app moves by hand and carries through twists itself.
    // Comment: twistable=true sprites are carried by the engine; twistable=false ones stay in scene space. Use OCT_TM_twist when only SOME sprites should follow a twist.

    int32_t id = OCT_add(1, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_002, BMP_002, 0);
    vars.demo12.obj = &gObjects[id];

    // 4 px per tick along +Y in obj's plane space
    OCT_TM_set(&vars.demo12.velocity, 0.f, 4.f, 0, OCT_PLANE_TOP);
}

// Demo: do not copy-paste this code
void processDemo12(void) {
    // API info + demo
    // Demo 12: integrate velocity by hand, wrap across plane edges and keep the velocity vector consistent.

    appObject_t* obj = vars.demo12.obj;
    int8_t oldPlane = obj->Tm.Plane;

    obj->Tm.X += vars.demo12.velocity.X;
    obj->Tm.Y += vars.demo12.velocity.Y;

    // Short: OCT_TM_wrap moves a transform whose X/Y went past the plane edge onto the adjacent plane (repeats until inside).
    // Declaration: void OCT_TM_wrap(octTm_t* tm);
    OCT_TM_wrap(&obj->Tm);

    int8_t newPlane = obj->Tm.Plane;
    if (newPlane != oldPlane) {
        // Short: OCT_TM_adapt_dir rotates a direction vector (X, Y and A of a transform) from oldside's space into newside's space.
        // Declaration: void OCT_TM_adapt_dir(octTm_t* tm, int oldside, int newside);
        // Comment: Never call it with opposite planes, they are not adjacent.
        OCT_TM_adapt_dir(&vars.demo12.velocity, oldPlane, newPlane);
        vars.demo12.velocity.Plane = newPlane;

        // Short: OCT_TM_adapt_angle returns the angle delta (degrees) that keeps a heading unchanged when moving from oldside to newside.
        // Declaration: int OCT_TM_adapt_angle(int oldside, int newside);
        OCT_text(-1, "Demo12 plane %d -> %d angleDelta=%d\n", (int32_t)oldPlane, (int32_t)newPlane, OCT_TM_adapt_angle(oldPlane, newPlane));
    }
}

// Demo: do not copy-paste this code
void pretwistDemo12(int8_t plane) {
    // API info + demo
    // Demo 12: a twist has started - which ring is physically disconnected?

    // Short: OCT_disconnected_axis returns the axis whose ring is currently turning: AXIS_Y (TOP/BOTTOM), AXIS_Z (FRONT/BACK), AXIS_X (LEFT/RIGHT) or AXIS_NONE.
    // Declaration: int OCT_disconnected_axis();
    OCT_text(-1, "Demo12 pretwist plane=%d axis=%d\n", (int32_t)plane, OCT_disconnected_axis());
}

// Demo: do not copy-paste this code
void twistDemo12(int32_t twid) {
    // API info + demo
    // Demo 12: carry the non-twistable sprite through the twist by hand and read the twist impulse.

    if (twid >= OCT_TWIST_HALF) return; // full twists only

    appObject_t* obj = vars.demo12.obj;
    int32_t quad = OCT_TM_quad(&obj->Tm);

    // Short: OCT_TM_twist_impulse returns the direction (degrees, in the quad's plane space) content on a quad is pushed by a twist; 360 = quad not affected.
    // Declaration: int OCT_TM_twist_impulse(int quad, octTwistId_t twid);
    int32_t impulse = OCT_TM_twist_impulse(quad, twid);

    // Short: OCT_TM_twist applies a full twist (twid 0..11) to one transform: ring quads move along the ring, disk quads rotate in place.
    // Declaration: void OCT_TM_twist(octTm_t* tm, octTwistId_t twid);
    // Comment: Call it on selected non-twistable sprites to keep them in sync with the physical cube.
    OCT_TM_twist(&obj->Tm, twid);

    if (impulse != 360) {
        vars.demo12.velocity.X = 4.f * OCT_TM_cos(impulse);
        vars.demo12.velocity.Y = 4.f * OCT_TM_sin(impulse);
    }
    vars.demo12.velocity.Plane = obj->Tm.Plane;

    OCT_text(-1, "Demo12 twist=%d quad=%d impulse=%d\n", twid, quad, impulse);
}


// Demo: do not copy-paste this code
void initDemo13(void) {
    // API info + demo
    // Demo 13: procedural sprites - drawn by code instead of a bitmap. Three kinds: circle, OS-font text, app-drawn.
    // Comment: A procedural sprite is a normal OCT_add with bmpfrom = bmpto = 0 plus the Procedural field; it keeps Tm, Layer, Transp, Parent, Twistable...

    // filled circle
    int32_t circleId = OCT_add(1, false, OCT_PLANE_TOP, 120.f, 120.f, 0, false, 0, 0, 0);
    vars.demo13.circle = &gObjects[circleId];
    // Short: PROCEDURAL_CIRCLE draws a soft-edged filled circle: Param3 = radius in pixels (int8_t, max 127), Data0 = RGB565 color, Transp = 0..OCT_TRANSP_MAX.
    vars.demo13.circle->Procedural = PROCEDURAL_CIRCLE;
    vars.demo13.circle->Param3 = (int8_t)40;
    vars.demo13.circle->Data0 = DEMO13_COLOR_GREEN;
    vars.demo13.circle->Transp = 0;

    // text in the OS built-in font, no font bitmaps needed
    int32_t textId = OCT_add_label(1, false, OCT_PLANE_FRONT, 120.f, 120.f, 0, FONT_1, ALIGN_CENTER);
    vars.demo13.text = &gObjects[textId];
    // Short: OCT_label_embed sets a label's text and switches it to the OS built-in font (PROCEDURAL_TEXT); returns 1, or 0 for a non-label sprite.
    // Declaration: int OCT_label_embed(octSprite_t* label, const char* text);
    // Comment: Data0 = RGB565 color (0 = white), alignment comes from OCT_add_label; do not mix with OCT_label_set on the same label.
    OCT_label_embed(vars.demo13.text, "OS FONT");
    vars.demo13.text->Data0 = DEMO13_COLOR_YELLOW;

    // app-drawn sprite, see on_proc_draw
    int32_t customId = OCT_add(1, false, OCT_PLANE_RIGHT, 120.f, 120.f, 0, false, 0, 0, 0);
    vars.demo13.custom = &gObjects[customId];
    // Short: PROCEDURAL_CUSTOM hands the sprite to on_proc_draw every frame it is visible; Zw/Zh = half-extents in pixels used for culling (0 = drawn only while the center is on a display).
    // Comment: Requires APP_HAS_PROC_DRAW on the cube; a display showing such a sprite is redrawn every frame, keep the count low.
    vars.demo13.custom->Procedural = PROCEDURAL_CUSTOM;
    vars.demo13.custom->Zw = DEMO13_CUSTOM_HALF;
    vars.demo13.custom->Zh = DEMO13_CUSTOM_HALF;
    vars.demo13.custom->Data0 = DEMO13_COLOR_CYAN; // free field, on_proc_draw reads the color from here
}

// Demo: do not copy-paste this code
void processDemo13(void) {
    // Demo 13: pulse the circle radius between 10 and 100 pixels over 2 seconds.
    uint32_t period = (uint32_t)(2U * OCT_1SEC_TICKS);
    uint32_t phase = vars.tick % period;
    uint32_t half = period / 2U;
    uint32_t radius = (phase < half) ? (10U + phase * 90U / half) : (100U - (phase - half) * 90U / half);
    vars.demo13.circle->Param3 = (int8_t)radius;
}

// Demo: do not copy-paste this code
void drawCustomDemo13(uint16_t* back, int32_t idx, int32_t px, int32_t py) {
    // API info + demo
    // Demo 13: draw a checkered square centered at (px, py) into the half-resolution back buffer.
    // Comment: back is HALFSIDE x HALFSIDE RGB565 pixels, back[row * HALFSIDE + col]; always clip, the sprite may be partially off this display.

    uint16_t color = gObjects[idx].Data0;
    int32_t halfExtent = (int32_t)DEMO13_CUSTOM_HALF >> 1; // half-res

    for (int32_t dy = -halfExtent; dy < halfExtent; dy++) {
        int32_t row = py + dy;
        if (row < 0 || row >= HALFSIDE) continue;

        for (int32_t dx = -halfExtent; dx < halfExtent; dx++) {
            int32_t col = px + dx;
            if (col < 0 || col >= HALFSIDE) continue;

            bool checker = (((dx + halfExtent) >> 2) + ((dy + halfExtent) >> 2)) % 2 == 0;
            if (checker) back[row * HALFSIDE + col] = color;
        }
    }
}


// Demo: do not copy-paste this code
void initDemo14(void) {
    // API info + demo
    // Demo 14: host services - clock, battery, brightness, volume, link, asset cache, scratch memory, tracing.

    int32_t id = OCT_add_label(1, false, OCT_PLANE_TOP, 120.f, 120.f, 0, FONT_2, ALIGN_CENTER);
    vars.demo14.clock = &gObjects[id];

    // Short: OCT_cache_assets forces the listed assets resident in the RAM cache right now; returns how many are resident.
    // Declaration: int OCT_cache_assets(int* ids, int num);
    // Comment: Assets stream from the SD card on first use - pre-warm the ones a level needs to avoid first-frame hitches.
    int32_t ids[] = {(int32_t)BMP_001, (int32_t)BMP_002, (int32_t)BMP_003};
    int32_t resident = OCT_cache_assets((int*)ids, (int32_t)(sizeof(ids) / sizeof(ids[0])));

    // Short: OCT_get_brightness returns the user's saved backlight level 0..100.
    // Declaration: int OCT_get_brightness(void);
    vars.demo14.savedBrightness = (uint8_t)OCT_get_brightness();

    // Short: OCT_set_brightness drives the backlight; OCT_BRIGHTNESS_TRANSIENT is reverted on app exit, OCT_BRIGHTNESS_PERSIST writes the user setting to flash.
    // Declaration: OCT_set_brightness(level, persist) - macro, level is float for TRANSIENT and int for PERSIST.
    // Warning: Games must ONLY use OCT_BRIGHTNESS_TRANSIENT. PERSIST is for the settings app.
    OCT_set_brightness(30.f, OCT_BRIGHTNESS_TRANSIENT);
    vars.demo14.dimmed = true;

    // Short: OCT_scratch returns 32 KB (OCT_SCRATCH_BYTES) of fast scratch RAM for temporary work, not preserved between ticks.
    // Declaration: void* OCT_scratch();
    uint16_t* scratch = (uint16_t*)OCT_scratch();
    scratch[0] = (uint16_t)resident;

    // Short: OCT_trace writes a printf-style line to the host console (simulator output / UART), not to the screen.
    // Declaration: void OCT_trace(int cubeid, const char* format, ...);
    // Comment: cubeid >= 0 prints only from that cublet, -1 from any; compiled out on the cube.
    OCT_trace(-1, "Demo14 cached=%d brightness=%d\n", (int32_t)scratch[0], (int32_t)vars.demo14.savedBrightness);

    // Short: OCT_get_volume returns the user's saved volume 0..100.
    // Declaration: OCT_get_volume() - macro.
    // Comment: OCT_set_volume_transient(level) is reverted on app exit; OCT_set_volume(level) persists - settings app only.
    OCT_text(-1, "Demo14 volume=%d cached=%d\n", OCT_get_volume(), resident);
}

// Demo: do not copy-paste this code
void restoreBrightnessDemo14(void) {
    if (!vars.demo14.dimmed) return;
    OCT_set_brightness((float)vars.demo14.savedBrightness, OCT_BRIGHTNESS_TRANSIENT);
    vars.demo14.dimmed = false;
}

// Demo: do not copy-paste this code
void processDemo14(void) {
    // API info + demo
    // Demo 14: refresh the clock label once a second, log the host state, undim after 2 seconds.

    if (vars.tick == 2 * OCT_1SEC_TICKS) restoreBrightnessDemo14();
    if (vars.tick % OCT_1SEC_TICKS != 0) return;

    // Short: OCT_calendar_time returns the cube's LOCAL wall-clock time as a UNIX epoch in seconds (zone offset already applied).
    // Declaration: uint32_t OCT_calendar_time(void);
    // Comment: Returns 1 while the RTC is unset; the simulator reports UTC.
    uint32_t now = OCT_calendar_time();
    uint32_t secondsInDay = now % 86400U;
    uint32_t hour = secondsInDay / 3600U;
    uint32_t minute = (secondsInDay / 60U) % 60U;

    char buf[8];
    snprintf(buf, sizeof(buf), "%02lu:%02lu", hour, minute);
    OCT_label_set(vars.demo14.clock, buf);

    // Short: OCT_BAT_level returns the cube battery percent 0..100 (the most discharged cublet, settled); -1 = not measured yet.
    // Declaration: int8_t OCT_BAT_level(void);
    // Comment: OCT_BAT_level_local is this cublet's own reading - use OCT_BAT_level for anything the user sees.
    int8_t battery = OCT_BAT_level();
    int8_t batteryLocal = OCT_BAT_level_local();

    // Short: OCT_first_run is true for the whole session in which the onboarding pack was autostarted; OCT_fw_up_to_date is the phone's verdict on the firmware.
    // Declaration: OCT_first_run() / OCT_fw_up_to_date() - macros returning bool.
    bool firstRun = OCT_first_run();

    OCT_text(-1, "Demo14 %s bat=%d local=%d first=%d\n", buf, (int32_t)battery, (int32_t)batteryLocal, (int32_t)firstRun);

#ifndef OCTSIM
    // Short: OCT_screen_quad returns the scene quad (0..23) shown on this cublet's display 0..2, or -1 if unbound; cube-only, the simulator has no such call.
    // Declaration: OCT_screen_quad(display) - macro.
    OCT_text(-1, "Demo14 displays -> quads %d,%d,%d\n", OCT_screen_quad(0), OCT_screen_quad(1), OCT_screen_quad(2));
#endif
}

// Demo: do not copy-paste this code
void tapDemo14(size_t plane, int32_t count) {
    // API info + demo
    // Demo 14: leave the app on a double tap.
    (void)plane;
    if (count != 2) return;

    restoreBrightnessDemo14();

    // Short: OCT_app_exit returns the cube to its home screen (installed launcher or the built-in shell) - an in-app "Exit" item.
    // Declaration: void OCT_app_exit(void);
    // Comment: OCT_sleep_now() instead puts the whole cube to sleep at once.
    OCT_app_exit();
}


// Demo: do not copy-paste this code
void initDemo15(void) {
    // API info + demo
    // Demo 15: the app catalog - enumerate installed packs and launch one. This is the API a launcher-category app (APP_CATEGORY_LAUNCHER) is built on.

    vars.demo15.entries = 0;
    vars.demo15.launchGuid1 = 0;
    vars.demo15.launchGuid2 = 0;

    // Short: OCT_CATALOG_scan_entries returns the number of catalog entries the engine holds in RAM (no SD re-scan); < 0 on failure.
    // Declaration: int OCT_CATALOG_scan_entries();
    if (OCT_CATALOG_scan_entries() < 0) {
        OCT_text(-1, "Demo15 catalog unavailable\n");
        return;
    }

    // Short: OCT_CATALOG_count returns the number of entries; OCT_CATALOG_entry fills octEntryInfo_t for index i and returns 0 on success.
    // Declaration: int OCT_CATALOG_count(); int OCT_CATALOG_entry(int index, octEntryInfo_t* out);
    // Comment: octEntryInfo_t fields: Guid1, Guid2 (the app id), Type (APP_ENTRY_PACK = an app, other values = non-app entries such as logs), Name[OCT_SOFTWARE_NAME_MAXLEN].
    int32_t count = OCT_CATALOG_count();
    for (int32_t i = 0; i < count; i++) {
        octEntryInfo_t info;
        if (OCT_CATALOG_entry(i, &info) != 0 || info.Type != APP_ENTRY_PACK) continue;

        // Short: OCT_CATALOG_version returns the installed pack's AppVersion (0 on an invalid index or non-pack entry).
        // Declaration: uint32_t OCT_CATALOG_version(int index);
        // Comment: Byte 3 is the scheme: 1 = semver (bytes 2..0 = major.minor.patch, as produced by OCT_APP_SEMVER in app.h), 0 = legacy opaque counter.
        uint32_t version = OCT_CATALOG_version(i);
        uint32_t scheme = (version >> 24) & 0xFFU;
        uint32_t major = (version >> 16) & 0xFFU;
        uint32_t minor = (version >> 8) & 0xFFU;
        uint32_t patch = version & 0xFFU;

        OCT_text(-1, "Demo15 [%d] %s v%lu.%lu.%lu (scheme %lu)\n", i, (const char*)info.Name, major, minor, patch, scheme);
        vars.demo15.entries++;

        // remember the first pack that is not this app
        if (vars.demo15.launchGuid1 == 0 && info.Guid1 != (uint64_t)APP_GUID1) {
            vars.demo15.launchGuid1 = info.Guid1;
            vars.demo15.launchGuid2 = info.Guid2;
        }
    }

    OCT_text(-1, "Demo15 packs=%d\n", vars.demo15.entries);
}

// Demo: do not copy-paste this code
void tapDemo15(size_t plane) {
    // API info + demo
    // Demo 15: launch the remembered pack from the tapped face.

    if (vars.demo15.launchGuid1 == 0) return;

    // Short: OCT_launch_from starts another installed app; the app-switch transition wave starts at (plane, x, y) - pass the tapped icon's Tm.
    // Declaration: void OCT_launch_from(uint64_t guid1, uint64_t guid2, int action, int plane, float x, float y);
    // Comment: OCT_launch(guid1, guid2, action) is the same without an origin; both are leader-only under the hood, just call them on every cublet.
    OCT_launch_from(vars.demo15.launchGuid1, vars.demo15.launchGuid2, CMD_APP_ACTION_DEFAULT, (int8_t)plane, 120.f, 120.f);
}


// Demo: do not copy-paste this code
void initDemo16(void) {
    // API info + demo
    // Demo 16: viewports - each of the 24 displays is a camera looking at a quad of the scene; re-aim them for mirrors and split views.

    for (int16_t y = -120; y <= 120; y += 240) {
        for (int16_t x = -120; x <= 120; x += 240) {
            OCT_add(1, false, OCT_PLANE_TOP, (float)x, (float)y, 0, false, BMP_001, BMP_001, 0);
        }
    }

    // Short: OCT_modify_viewport re-aims display vid (0..23 = plane * 4 + sector) at a plane of the scene with the given camera transform.
    // Declaration: void OCT_modify_viewport(int vid, int plane, int angle, float x, float y, int xflip, int yflip, int mode);
    // Comment: The camera transform is INVERTED: the default layout for sector s of plane p is (plane = p, angle = -90 * s, x = y = -GAP, xflip = yflip = 1, mode = 0). Start from these values and change one thing.
    // Comment: mode < 0 keeps the current mode; OCT_viewports_layout(SCHEME_CUBE, GAP, GAP) restores everything.
    for (int32_t sector = 0; sector < OCT_QUADS_AT_PLANE; sector++) {
        int32_t vid = OCT_PLANE_BOTTOM * OCT_QUADS_AT_PLANE + sector;
        OCT_modify_viewport(vid, OCT_PLANE_TOP, -90 * sector, -(float)GAP, -(float)GAP, 1, 1, 0);
    }
}


// State machine

void switchDemo(demoId_t demo) {
    // leave no host side effects behind when switching
    restoreBrightnessDemo14();

    // Short: OCT_restart reinitializes the sprite engine, clearing all objects.
    // Declaration: void OCT_restart(int* objects, int capacity, int objectSize);
    OCT_restart((int*)gObjects, SPRITES_CAP, (int32_t)sizeof(appObject_t));

    // Short: OCT_viewports_layout sets the camera layout (SCHEME_CUBE maps the 6 planes to the 6 faces) with the inner and outer bezel widths in pixels; calling it again undoes OCT_modify_viewport.
    // Declaration: void OCT_viewports_layout(int scheme, int inside_border_width, int outside_border_width);
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);

    // Short: OCT_background sets the background color for the entire cube (all planes and quads).
    // Declaration: void OCT_background(int color);
    // Comment: color is in RGB565 format. Can be used to fill the entire cube with a solid background color.
    OCT_background(0x0000);

    vars.currentDemo = demo;
    vars.tick = 0;

    switch (demo) {
        case DEMO_0: initDemo0(); break;
        case DEMO_1: initDemo1(); break;
        case DEMO_2: initDemo2(); break;
        case DEMO_2_LERP: initDemo2(); break;
        case DEMO_3: initDemo3(); break;
        case DEMO_4: initDemo4(); break;
        case DEMO_5: initDemo5(); break;
        case DEMO_6: initDemo6(); break;
        case DEMO_7: initDemo7(); break;
        case DEMO_8: initDemo8(); break;
        case DEMO_9: initDemo9(); break;
        case DEMO_10: initDemo10(); break;
        case DEMO_11: initDemo11(); break;
        case DEMO_12: initDemo12(); break;
        case DEMO_13: initDemo13(); break;
        case DEMO_14: initDemo14(); break;
        case DEMO_15: initDemo15(); break;
        case DEMO_16: initDemo16(); break;
        default: break;
    }
}


// Handlers
OCT_CALLBACK void on_init() {
    // API info
    // on_init is called once when the application starts.
    // Use it to initialize the engine, set up the scene, and load resources.

    // Short: OCT_dev_mode enables engine debug overlays (flags combine with |); returns the previous mode.
    // Declaration: int OCT_dev_mode(int mode);
    // Comment: OCT_DEV_TEXT shows OCT_text lines, OCT_DEV_STAT / OCT_DEV_FPS engine statistics, OCT_DEV_QUAD_IDS quad ids on every display, OCT_DEV_COLLIDERS sprite outlines; ship with OCT_dev_mode(0).
    OCT_dev_mode(OCT_DEV_TEXT);

    switchDemo(DEMO_0);
}

OCT_CALLBACK void on_pretwisted(int32_t twid) {
    // API info
    // on_pretwisted is called when a twist has physically STARTED (a ring disconnected).
    // twid here is the PLANE index (0..5) whose ring is turning - NOT a twist id, the direction is unknown until on_twisted, which is authoritative.
    // Use it to pause logic on the affected ring or to freeze animations, never move sprites here.
    switch (vars.currentDemo) {
        case DEMO_12: pretwistDemo12(twid); break;
        default: break;
    }
}

OCT_CALLBACK void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    // API info
    // on_twisted is called when a twist action is completed.
    // Use it to update the game state after the twist, e.g., check for matches or update positions.
    // twistDemo0();

    // API info
    {
        // disconnected_ms - time elapsed since the last connection during a twist

        // twid in [0; 11] - standard twists
        // twid in [12; 23] - half twists
        // Warning: CW and CCW are defined looking from outside of the cube at the given face (right-hand rule), NOT from the perspective of a neighboring face.

        const char* TWISTS[OCT_PLANES_MAX * 2] = {
            "TOP_CCW", "TOP_CW",
            "FRONT_CCW", "FRONT_CW",
            "RIGHT_CCW", "RIGHT_CW",
            "BACK_CCW", "BACK_CW",
            "LEFT_CCW", "LEFT_CW",
            "BOTTOM_CCW", "BOTTOM_CW"
        };

        const char* HALF[OCT_PLANES_MAX * 2] = {
            "TOP_HALF_CCW", "TOP_HALF_CW",
            "FRONT_HALF_CCW", "FRONT_HALF_CW",
            "RIGHT_HALF_CCW", "RIGHT_HALF_CW",
            "BACK_HALF_CCW", "BACK_HALF_CW",
            "LEFT_HALF_CCW", "LEFT_HALF_CW",
            "BOTTOM_HALF_CCW", "BOTTOM_HALF_CW"
        };

        // Logging
        OCT_text(-1, "twist: %s; %lu ms.\n", twid >= OCT_TWIST_HALF ? HALF[twid - OCT_TWIST_HALF] : TWISTS[twid], disconnected_ms);
    }

    switch (vars.currentDemo) {
        case DEMO_0: twistDemo0(); break;
        case DEMO_8: twistDemo8(twid); break;
        case DEMO_12: twistDemo12(twid); break;
        default: break;
    }
}


OCT_CALLBACK void on_tap(int32_t tapid, int32_t count) {
    // API info
    // on_tap is called when the user taps on a plane.
    // Use it to handle user interactions, e.g., select objects or trigger actions.
    // tapid - the plane index (0..5) that was tapped
    // count - tap-series counter: 1 for a single tap, 2 for the second tap in a quick series (within 500 ms), and so on
    (void)count;

    // API info
    {
        // tapid = plane
        const char* TAPS[OCT_PLANES_MAX] = {"TOP", "FRONT", "RIGHT", "BACK", "LEFT", "BOTTOM"};

        // Logging
        OCT_text(-1, "tap: %s\n", TAPS[tapid]);
    }
    // State machine: tap switches to next demo
    demoId_t next = (demoId_t)((int32_t)vars.currentDemo + 1);
    if (next >= DEMO_COUNT) next = (demoId_t)0;
    switchDemo(next);

    // Per-demo tap handlers (uncomment to use instead of switching):
    // switch (vars.currentDemo) {
    //     case DEMO_0: tapDemo0((size_t)tapid); break;
    //     case DEMO_5: tapDemo5((size_t)tapid); break;
    //     case DEMO_14: tapDemo14((size_t)tapid, count); break; // double tap exits the app
    //     case DEMO_15: tapDemo15((size_t)tapid); break; // launches another installed app
    //     default: break;
    // }
}


OCT_CALLBACK void on_tick() {
    // API info
    // on_tick is called every frame (tick) of the game loop.
    // Use it to update game logic, animations, and physics.

    // OCT_1SEC_TICKS is the number of ticks in one second (standard is 20 ticks, 50ms per tick).
    // OCT_DT is the tick length in seconds (0.05f) for velocity integration.

    // API info
    if (vars.tick % OCT_1SEC_TICKS / 2 == 0) {
        const char* planes[OCT_PLANES_MAX] = {"TOP", "FRONT", "RIGHT", "BACK", "LEFT", "BOTTOM"};

        // Short: OCT_TM_gravity_x/y/n returns the gravity vector components for a given plane.
        // Declaration: float OCT_TM_gravity_x(int plane);
        // Declaration: float OCT_TM_gravity_y(int plane);
        // Declaration: float OCT_TM_gravity_n(int plane);
        // Comment: 'n' stands for the normal vector component (Z-axis relative to the plane).
        float gX = OCT_TM_gravity_x(OCT_PLANE_TOP);
        float gY = OCT_TM_gravity_y(OCT_PLANE_TOP);
        float gN = OCT_TM_gravity_n(OCT_PLANE_TOP);

        // Short: OCT_TM_top_side/bottom_plane returns the current top/bottom plane ID based on the accelerometer.
        // Declaration: int OCT_TM_top_side();
        // Declaration: int OCT_TM_bottom_side();
        size_t topPlane = (size_t)OCT_TM_top_side();
        size_t bottomPlane = (size_t)OCT_TM_bottom_side();

        // Logging
        OCT_text(-1, "gX: %d.%03d; gY: %d.%03d; gN: %d.%03d; top: %s; bottom: %s\n", OCT_F_INT(gX), OCT_F_FRAC(gX), OCT_F_INT(gY), OCT_F_FRAC(gY), OCT_F_INT(gN), OCT_F_FRAC(gN), planes[topPlane], planes[bottomPlane]);
    }

    if (vars.tick % OCT_1SEC_TICKS == 0)
        OCT_text(-1, "demo:%d tick:%lu\n", (int32_t)vars.currentDemo, vars.tick);

    switch (vars.currentDemo) {
        case DEMO_0: processDemo0(); break;
        case DEMO_2: processDemo2(); break;
        case DEMO_2_LERP: processDemo2Lerp(); break;
        case DEMO_3: processDemo3(); break;
        case DEMO_4: processDemo4(); break;
        case DEMO_5: processDemo5(); break;
        case DEMO_6: processDemo6(); break;
        case DEMO_7: processDemo7(); break;
        case DEMO_9: processDemo9(); break;
        case DEMO_10: processDemo10(); break;
        case DEMO_11: processDemo11(); break;
        case DEMO_12: processDemo12(); break;
        case DEMO_13: processDemo13(); break;
        case DEMO_14: processDemo14(); break;
        default: break;
    }

    vars.tick++;
}


OCT_CALLBACK void on_shake(int32_t shakeid) {
    // on_shake fires when the cube is shaken.
    // NOTE: in the current beta the engine always runs the system default (animated go-home) and does NOT route shakes here - but the symbol MUST exist or the ARM module fails to link (octavios/apps/src/app_module.cpp references it).
    (void)shakeid;
}


//Enable the APP_HAS_PROC_DRAW define (top of this file) to use procedural sprites
OCT_CALLBACK void on_proc_draw(uint16_t* back, int idx, float x, float y, int angle, int vid, int reserved) {
    // API info
    // on_proc_draw is called by the renderer for every visible PROCEDURAL_CUSTOM sprite, once per display it appears on.
    // back - this display's half-resolution back buffer, HALFSIDE x HALFSIDE RGB565, back[row * HALFSIDE + col]
    // idx - index of the sprite in gObjects
    // x, y - sprite center in display pixels (0..239), x = column, y = row; shift right by 1 for the half-res buffer
    // angle - sprite rotation in display space (degrees)
    // vid - display (quad) id 0..23 being rendered
    // Comment: Runs on the render path - only write into back, never touch the scene or app state here.
    (void)angle;
    (void)vid;
    (void)reserved;

    if (gObjects[idx].Idx != idx) return;

    int32_t px = (int32_t)x >> 1;
    int32_t py = (int32_t)y >> 1;

    switch (vars.currentDemo) {
        case DEMO_13: drawCustomDemo13(back, idx, px, py); break;
        default: break;
    }
}
