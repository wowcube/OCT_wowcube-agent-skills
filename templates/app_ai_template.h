#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_ai_template_ids.h"

#ifdef _WIN32
    #define APP_PNG "..\\..\\app_ai_template\\art\\packed"
    #define APP_SND "..\\..\\app_ai_template\\art\\mp3"
#else
    #define APP_PNG "assets/packed"
    #define APP_SND "assets/mp3"
#endif

#define OCT_PLANES_MAX 6 // max planes on the cube
#define OCT_QUADS_AT_PLANE 4 // max quads per plane

#define SPRITES_CAP 400 // scene capacity - maximum possible object count
#define GAP 18 // width of the physical border between WowCube's displays in pixels
#define SIM_SINGLE_THREAD


// --- INSTRUCTIONS FOR AI AGENT -----------------------
// This file is a reference for OctaviOS API usage.
// * DO NOT copy code 1:1.
// * DO NOT copy internal comments from demos/apis.
// * Use this as a guide to implement specific logic.
// * ALWAYS use explicit type casts \u2014 never rely on
//   implicit conversions between numeric types, pointers,
//   or enums. Every narrowing, widening, or cross-type
//   assignment must have a visible cast.
// * Use only fixed-width types from <stdint.h>
//   (int8_t, int16_t, int32_t, uint8_t, uint16_t,
//   uint32_t, size_t, etc.). Never use plain int, short, long.
// * ALWAYS copy the project header structure.
// * ALWAYS copy all handler functions (on_init, on_tick,
//   on_tap, on_twisted, on_pretwisted) into the output.
// * If a handler body has no game logic, you MUST still
//   reference every parameter as a statement to suppress
//   unused-variable warnings. Example:
//     WASM_EXPORT void on_tap(int32_t tapid) { tapid; }
//     WASM_EXPORT void on_pretwisted(int32_t twid) { twid; }
//     WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) { twid; disconnected_ms; }
// * Write modular, readable code: extract game state into
//   structs, split logic into small focused functions,
//   use named constants instead of magic numbers.
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

// Game-specific variables (global)
typedef struct {
    demoId_t currentDemo;
    appObject_t* demoObj; // shared primary object for active demo
    demo2State_t demo2;
    demo6State_t demo6;
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
    // Comment: Setting Hidden on the label alone is not enough \u2014 each child glyph must also be toggled.
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
                    // Comment: parameter 'a' is the sprite angle in degrees; positive values rotate counter-clockwise (CCW), 0 degrees points right (+X).
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
        // Comment: Tm.A is the sprite angle in degrees; positive values rotate counter-clockwise (CCW), 0 degrees points right (+X).
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
    // Comment: octBmpInfo_t fields: Name[24], W, H (screen pixels), PivotX, PivotY, Bx, By, Bw, Bh (bounding geometry), NumPixels, Tags, Number, Group, Type.
    // Comment: Can be called at any time with any valid BMP index; does not require a sprite to exist.
    octBmpInfo_t info;
    OCT_BMP_info((uint32_t)BMP_001, &info);

    OCT_trace(0, "Demo5 init BMP_001: name=%s W=%d H=%d pivotX=%f pivotY=%f numPixels=%d\n",
        info.Name, (int32_t)info.W, (int32_t)info.H, info.PivotX, info.PivotY, info.NumPixels);
}

// Demo: do not copy-paste this code
void processDemo5(void) {
    // API info + demo
    // Demo 5: how to query bitmap info dynamically

    if (vars.tick == 0) {
        octBmpInfo_t info;
        OCT_BMP_info((uint32_t)BMP_000, &info);

        OCT_trace(0, "Demo5 tick0 BMP_000: name=%s W=%d H=%d pivotX=%f pivotY=%f\n",
            info.Name, (int32_t)info.W, (int32_t)info.H, info.PivotX, info.PivotY);
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

        OCT_trace(0, "Demo5 tap sprite[%lu]: name=%s W=%d H=%d Bx=%f By=%f Bw=%f Bh=%f\n",
            i, info.Name, (int32_t)info.W, (int32_t)info.H, info.Bx, info.By, info.Bw, info.Bh);
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

    OCT_trace(0, "Demo8 twist %d: disk=[%d,%d,%d,%d] ring1=[%d,%d,%d,%d] ring2=[%d,%d,%d,%d]\n",
        twid,
        tw->QuadsDisk[0], tw->QuadsDisk[1], tw->QuadsDisk[2], tw->QuadsDisk[3],
        tw->QuadsRing1[0], tw->QuadsRing1[1], tw->QuadsRing1[2], tw->QuadsRing1[3],
        tw->QuadsRing2[0], tw->QuadsRing2[1], tw->QuadsRing2[2], tw->QuadsRing2[3]);

    OCT_trace(0, "Demo8 impulse=[%d,%d,%d,%d,%d,%d] ringsMask=0x%08lx\n",
        tw->Impulse[0], tw->Impulse[1], tw->Impulse[2],
        tw->Impulse[3], tw->Impulse[4], tw->Impulse[5],
        (uint32_t)tw->RingsMask);
}


// State machine

void switchDemo(demoId_t demo) {
    // Short: OCT_restart reinitializes the sprite engine, clearing all objects.
    // Declaration: void OCT_restart(int* objects, int capacity, int objectSize);
    OCT_restart((int32_t*)gObjects, SPRITES_CAP, (int32_t)sizeof(appObject_t));

    // Short: OCT_background sets the background color for the entire cube (all planes and quads).
    // Declaration: void OCT_background(int color);
    // Comment: color is in RGB565 format. Can be used to fill the entire cube with a solid background color.
    OCT_background(0x0000);

    vars.currentDemo = demo;
    vars.tick = 0;

    switch (demo) {
        case DEMO_0:      initDemo0(); break;
        case DEMO_1:      initDemo1(); break;
        case DEMO_2:      initDemo2(); break;
        case DEMO_2_LERP: initDemo2(); break;
        case DEMO_3:      initDemo3(); break;
        case DEMO_4:      initDemo4(); break;
        case DEMO_5:      initDemo5(); break;
        case DEMO_6:      initDemo6(); break;
        case DEMO_7:      initDemo7(); break;
        case DEMO_8:      initDemo8(); break;
        default: break;
    }
}


// Handlers
WASM_EXPORT void on_init() {
    // API info
    // on_init is called once when the application starts.
    // Use it to initialize the engine, set up the scene, and load resources.

    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP); // Set default viewport layout with gap between quads = GAP
    OCT_dev_mode(OCT_DEV_TEXT);

    switchDemo(DEMO_8);
}

WASM_EXPORT void on_pretwisted(int32_t twid) {
    // API info
    // on_pretwisted is called when a twist action begins.
    // Use it to prepare the game state for the twist, e.g., pause animations.
    twid;
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
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
        OCT_trace(0, "twist: %s; %lu ms.\n", twid >= OCT_TWIST_HALF ? HALF[twid - OCT_TWIST_HALF] : TWISTS[twid], disconnected_ms);
    }

    switch (vars.currentDemo) {
        case DEMO_0: twistDemo0(); break;
        case DEMO_8: twistDemo8(twid); break;
        default: break;
    }
}


WASM_EXPORT void on_tap(int32_t tapid) {
    // API info
    // on_tap is called when the user taps on a plane.
    // Use it to handle user interactions, e.g., select objects or trigger actions.

    // API info
    {
        // tapid = plane
        const char* TAPS[OCT_PLANES_MAX] = {"TOP", "FRONT", "RIGHT", "BACK", "LEFT", "BOTTOM"};

        // Logging
        OCT_trace(0, "tap: %s\n", TAPS[tapid]);
    }
    // State machine: tap switches to next demo
    demoId_t next = (demoId_t)((int32_t)vars.currentDemo + 1);
    if (next >= DEMO_COUNT) next = (demoId_t)0;
    switchDemo(next);

    // Per-demo tap handlers (uncomment to use instead of switching):
    // switch (vars.currentDemo) {
    //     case DEMO_0: tapDemo0((size_t)tapid); break;
    //     case DEMO_5: tapDemo5((size_t)tapid); break;
    //     default: break;
    // }
}


WASM_EXPORT void on_tick() {
    // API info
    // on_tick is called every frame (tick) of the game loop.
    // Use it to update game logic, animations, and physics.

    // OCT_1SEC_TICKS is the number of ticks in one second (standard is 20 ticks, 50ms per tick).

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

        // Short: OCT_TM_top_plane/bottom_plane returns the current top/bottom plane ID based on the accelerometer.
        // Declaration: int OCT_TM_top_plane();
        // Declaration: int OCT_TM_bottom_plane();
        size_t topPlane = (size_t)OCT_TM_top_plane();
        size_t bottomPlane = (size_t)OCT_TM_bottom_plane();

        // Logging
        OCT_trace(0, "gX: %f; gY: %f; gN: %f; top: %s; bottom: %s\n", gX, gY, gN, planes[topPlane], planes[bottomPlane]);
    }

    switch (vars.currentDemo) {
        case DEMO_0:      processDemo0(); break;
        case DEMO_2:      processDemo2(); break;
        case DEMO_2_LERP: processDemo2Lerp(); break;
        case DEMO_3:      processDemo3(); break;
        case DEMO_4:      processDemo4(); break;
        case DEMO_5:      processDemo5(); break;
        case DEMO_6:      processDemo6(); break;
        case DEMO_7:      processDemo7(); break;
        default: break;
    }

    vars.tick++;
}
