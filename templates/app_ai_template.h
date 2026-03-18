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
// -----------------------------------------------------


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

// Game-specific data
typedef struct _appObject_t: octSprite_t {
    octTm_t animStart; // do not copy this
    octTm_t animEnd; // do not copy this
} appObject_t;

// Game-specific variables
typedef struct {
    appObject_t* demoObj;

    uint32_t demo2LerpStartTick;
    float demo2LerpDuration;

    uint32_t tick;
} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////

// utils
appObject_t* getQuadContent(size_t quad);
void showLabel(appObject_t* label, bool show);

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


////////////////////////////////
//            MAPS            //
////////////////////////////////

// [NOTE]: All global variables should be defined with the TL macro
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;


////////////////////////////////
//       IMPLEMENTATION       //
////////////////////////////////

// utils

// Util: copy this code to any project
appObject_t* getQuadContent(size_t quad) {
    // API info + util

    // A quad represents a physical display on a plane. Its size is 240x240.
    // Quads [0; 3] start from the top-right center (120 + GAP; 120 + GAP) and rotate CCW.
    // quadId = quad [0; 3] + plane_id * OCT_QUADS_AT_PLANE

    // gObjects[0] is an invalid object because the validation check is idx == obj.Idx.
    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];

        // Check for a valid object (Idx always equals the object ID).
        if (obj->Idx != i) continue; // Invalid object

        // Short: OCT_TM_quad returns the quad ID where the given transform (octTm_t) is located.
        // Declaration: int OCT_TM_quad(const octTm_t* tm);
        // Comment: Every sprite (octSprite_t) has a transform property (Tm) of type octTm_t.
        if((size_t)OCT_TM_quad(&obj->Tm) == quad) return obj;
        continue;

        // Second method: do not copy this!
        {
            // Short: Manual calculation of quad content based on coordinates.
            // Comment: XSIGN and YSIGN determine the sign of X and Y coordinates for each local quad [0; 3].
            // Warn: do not redeclare XSIGN and YSIGN! They are already declared in `oct_shared.h`.

            // XSIGN: {+1, -1, -1, +1}
            // YSIGN: {+1, +1, -1, -1}

            int16_t plane = (int16_t)quad / OCT_QUADS_AT_PLANE;
            int16_t lQuad = (int16_t)quad % OCT_QUADS_AT_PLANE;

            if (obj->Tm.Plane == plane && obj->Tm.X * XSIGN[lQuad] > 0 && obj->Tm.Y * YSIGN[lQuad] > 0) return obj;
        }
        
    }
    return NULL;
}

// Util: copy this code if need to modify label properties
void showLabel(appObject_t* label, bool show) {
    // API + util
    // Short: Toggles visibility of a label and all its child glyphs (letters).
    // Comment: A label created by OCT_add_label has child sprites (one per glyph) linked via Parent.
    // Comment: Setting Hidden on the label alone is not enough — each child glyph must also be toggled.
    label->Hidden = !show;

    for (size_t i = 1; i < SPRITES_CAP; i++) {
        appObject_t* obj = &gObjects[i];
        if (obj->Idx != i) continue;

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
                // OCT_add(0, false, plane, x, y, 0, false, BMP_000, BMP_000, 0);

                if (plane == OCT_PLANE_TOP) {
                    // Short: OCT_add adds a sprite to the scene; returns idx in gObjects.
                    // Declaration: int OCT_add(int layer, bool twistable, int plane, float x, float y, int a, bool loop, int bmpfrom, int bmpto, int framelen);
                    // Comment: twistable=false means the engine automatically resets the position after a twist.
                    // Comment: (loop, bmpfrom, bmpto, framelen) are used for animation; framelen is the number of global ticks per frame.
                    OCT_add(1, true, plane, x, y, 0, false, BMP_001, BMP_001, 0);
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
        if (gObjects[i].Idx != i) continue;

        gObjects[i].Tm.A = 0; // Reset angle (relative to Tm.Plane)
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
        if (obj->Idx != i || obj->Tm.Plane != plane) continue;

        // Short: OCT_random returns a random integer in the range [dmin; dmax).
        // Declaration: int OCT_random(int dmin, int dmax);
        size_t id = (size_t)OCT_random(0, sizeof(sounds) / sizeof(char*));

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
                OCT_add(0, false, plane, x, y, 0, false, BMP_000, BMP_000, 0);

                if (plane == OCT_PLANE_TOP)
                    OCT_add(1, true, plane, x, y, 0, false, BMP_001, BMP_001, 0);
            }
        }
    }

    // Directions: TOP_CCW, TOP_CW, FRONT_CCW, FRONT_CW, RIGHT_CCW, RIGHT_CW, BACK_CCW, BACK_CW, LEFT_CCW, LEFT_CW, BOTTOM_CCW, BOTTOM_CW

    // Short: OCT_twist_sprites performs a virtual twist of all twistable sprites on the cube.
    // Declaration: void OCT_twist_sprites(octTwistId_t twid);
    OCT_twist_sprites(FRONT_CW);
    OCT_twist_sprites(RIGHT_CCW);
}

// Demo: do not copy-paste this code
void initDemo2(void) {
    // demo
    int32_t id = OCT_add(0, true, OCT_PLANE_TOP, 120.f, 120.f, 0, false, BMP_001, BMP_001, 0);
    vars.demoObj = &gObjects[id];
}

// Demo: do not copy-paste this code
void processDemo2(void) {
    // API info + demo
    // Demo 2: how to walk sprite in the direction with correction between sides

    if (vars.tick % OCT_1SEC_TICKS != 0) return;

    // Short: OCT_TM_walk moves a transform forward (and optionally sideways) along a given direction angle; returns old plane.
    // Declaration: int OCT_TM_walk(octTm_t* tm, int forward_direction_angle, float forward_distance, float left_distance, bool wrap);
    // Comment: forward_direction_angle is the movement direction in degrees; forward_distance is the distance in pixels along that direction; left_distance is the perpendicular (left) offset.
    // Comment: wrap is needed to correct coords after reaching side limits (240x240) to automatically change plane; in most cases wrap should be true.
    OCT_TM_walk(&vars.demoObj->Tm, vars.demoObj->Tm.A, 240.f + 2.f * GAP, 0.0, true); // 240.f (size of quad) + 2 * GAP ensures the sprite moves to the next display
}

// Demo: do not copy-paste this code
void processDemo2Lerp(void) {
    // API info + demo
    // Demo 2: sprite movement animation and copy tranformation

    // start
    if (vars.demo2LerpStartTick == 0) {
        vars.demo2LerpStartTick = vars.tick;
        vars.demo2LerpDuration = (float)OCT_1SEC_TICKS; // 1 second

        // Short: OCT_TM_copy copies the full transform (octTm_t) from src to dst.
        // Declaration: void OCT_TM_copy(octTm_t* dst, const octTm_t* src);
        OCT_TM_copy(&vars.demoObj->animStart, &vars.demoObj->Tm);

        // set animation end
        OCT_TM_copy(&vars.demoObj->animEnd, &vars.demoObj->Tm);
        OCT_TM_walk(&vars.demoObj->animEnd, vars.demoObj->Tm.A, 240.f + 2.f * GAP, 0.0, true);
    }

    float progress = (vars.tick - vars.demo2LerpStartTick) / vars.demo2LerpDuration;

    // Short: OCT_TM_lerp linearly interpolates between two transforms a and b by factor t [0; 1], handling cross-plane transitions.
    // Declaration: void OCT_TM_lerp(octTm_t* tm, octTm_t* a, octTm_t* b, float t);
    // Comment: t is clamped to [0; 1]; the result is written to tm; transform a is converted to b's plane space before interpolation.
    OCT_TM_lerp(&vars.demoObj->Tm, &vars.demoObj->animStart, &vars.demoObj->animEnd, progress);
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
    // Demo 0: how to move objects with check if quad is occupied.

    appObject_t* src = getQuadContent(srcQuad);
    if (!src) return;

    appObject_t* dest = getQuadContent(destQuad);
    if (dest) return; // quad is occupied

    // Short: OCT_TM_change_plane moves a transform to a different plane, adjusting coordinates and angle accordingly.
    // Declaration: void OCT_TM_change_plane(octTm_t* tm, int to);
    OCT_TM_change_plane(&src->Tm, destQuad / OCT_QUADS_AT_PLANE);

    src->Tm.X = (120.f + GAP) * XSIGN[destQuad % OCT_QUADS_AT_PLANE];
    src->Tm.Y = (120.f + GAP) * YSIGN[destQuad % OCT_QUADS_AT_PLANE];
}


// Handlers
WASM_EXPORT void on_init() {
    // API info
    // on_init is called once when the application starts.
    // Use it to initialize the engine, set up the scene, and load resources.
    {
        // Initialize engine
        OCT_restart((int32_t*)gObjects, SPRITES_CAP, sizeof(appObject_t)); // Clear scene
        OCT_viewports_layout(SCHEME_CUBE, GAP, GAP); // Set default viewport layout with gap between quads = GAP
        OCT_background(0x0000); // Set background to BLACK (RGB565)
    }

    // Settings
    vars.tick = 0;

    // Game
    initDemo0();
    // initDemo1();
    // initDemo2();
    // initDemo3();
    // initDemo4();
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
    twistDemo0();

    // API info
    {
        // disconnected_ms - time elapsed since the last connection during a twist
    
        // twid in [0; 11] - standard twists
        // twid in [12; 23] - half twists
    
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
    tapDemo0(tapid);
}


WASM_EXPORT void on_tick() {
    // API info
    // on_tick is called every frame (tick) of the game loop.
    // Use it to update game logic, animations, and physics.
    
    // OCT_1SEC_TICKS is the number of ticks in one second (standard is 20 ticks, 50ms per tick).

    // API info
    if (vars.tick % OCT_1SEC_TICKS / 2 == 0) {
        const char* PLANES[OCT_PLANES_MAX] = {"TOP", "FRONT", "RIGHT", "BACK", "LEFT", "BOTTOM"};

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
        OCT_trace(0, "gX: %f; gY: %f; gN: %f; top: %s; bottom: %s\n", gX, gY, gN, PLANES[topPlane], PLANES[bottomPlane]);
    }
    
    // demo
    processDemo0();
    // processDemo2();
    // processDemo2Lerp();
    // processDemo3();
    // processDemo4();

    vars.tick++;
}
