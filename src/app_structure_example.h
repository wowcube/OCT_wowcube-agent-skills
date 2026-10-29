#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_ai_template_ids.h" // renamed to app_<game>_ids.h by the scaffolder token pass

//When defined, binds the per-pixel procedural callback (on_proc_draw) in both the simulator and the ARM module
///#define APP_HAS_PROC_DRAW

#define OCT_PLANES_MAX 6 // max planes on cube
#define OCT_QUADS_AT_PLANE 4 // max quads at plane

#define SPRITES_CAP 400 // scene capacity - maximum objects count possible
#define GAP 18 // width of physical border between wowcube's display in pixels
#define SIM_SINGLE_THREAD


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

// game specific data
typedef struct _appObject_t: octSprite_t{

} appObject_t;

// game specific vars
typedef struct {

} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////



////////////////////////////////
//            MAPS            //
////////////////////////////////

//[NOTE]: All global variables should be defined with TL macro
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;


////////////////////////////////
//       IMPLEMENTATION       //
////////////////////////////////


// handlers
OCT_CALLBACK void on_init() {

}

OCT_CALLBACK void on_pretwisted(int32_t twid) {
    // twid is the PLANE (0..5) whose ring started turning, not a twist id - the direction is only known in on_twisted.
    (void)twid;
}

OCT_CALLBACK void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    (void)twid; (void)disconnected_ms;
}


OCT_CALLBACK void on_tap(int32_t tapid, int32_t count) {
    (void)tapid; (void)count;
}


OCT_CALLBACK void on_tick() {

}


OCT_CALLBACK void on_shake(int32_t shakeid) {
    // on_shake fires when the cube is shaken.
    // NOTE: in the current beta the engine always runs the system default (animated go-home) and does NOT route shakes here - but the symbol MUST exist or the ARM module fails to link (octavios/apps/src/app_module.cpp references it).
    (void)shakeid;
}


//Enable the APP_HAS_PROC_DRAW define (top of this file) to use procedural sprites
OCT_CALLBACK void on_proc_draw(uint16_t* back, int idx, float x, float y, int angle, int vid, int reserved) {
    // Per-pixel procedural drawing callback.
    // Only bound when APP_HAS_PROC_DRAW is defined, keep the stub otherwise.
    (void)back; (void)idx; (void)x; (void)y; (void)angle; (void)vid; (void)reserved;
}
