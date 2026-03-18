#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_test_ids.h"

// #define LINUX

#ifdef LINUX
    #define APP_PNG "assets/packed"
    #define APP_SND "assets/mp3"
#else
    #define APP_PNG "..\\..\\app_ai_template\\art\\packed"
    #define APP_SND "..\\..\\app_ai_template\\art\\mp3"
#endif

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
WASM_EXPORT void on_init() {

}

WASM_EXPORT void on_pretwisted(int32_t twid) {
    twid;
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
   
}


WASM_EXPORT void on_tap(int32_t tapid) {

}


WASM_EXPORT void on_tick() {

}
