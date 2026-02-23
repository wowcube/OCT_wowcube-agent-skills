WowCube SDK API Reference Guide
This document defines the production standards for WowCube development. AI agents must strictly follow these architectural patterns and API usage examples.

1. Core Architecture & Global State
WowCube uses a header-only architecture. Logic must be isolated via a State Machine (FSM).

🔑 Key Rules
Header-Only: Only .h files are permitted. No .c or .cpp.

TL Macro: Every global variable or struct instance must use the TL macro for Thread-Local storage.

FSM Pattern: Use a state router (gameProcess) to separate logic from frame counting.

C++
#pragma once
#include "oct_api.h"
#include "oct_consts.h"

// State definition
typedef enum { GAME_STATE_INIT, GAME_STATE_PLAY, GAME_STATE_WIN } GameState_t;

// Global container wrapped in TL
struct appVars_t {
    GameState_t state;
    uint32_t score;
};
TL appVars_t vars; 
2. Object Pool Management
WowCube handles memory via a fixed object pool.

🔑 Key Rules
Index 0 is Reserved: Always start loops from i = 1. Index 0 acts as a null-check.

Validation: Always check if (Objects[i].Idx == i) to verify a slot is active.

C++
// Correct iteration pattern
for (int i = 1; i < OBJECTS_CAP; ++i) {
    if (Objects[i].Idx == i) { 
        appObject_t* obj = &Objects[i];
        // Execute logic here
    }
}
3. WASM Lifecycle Exports
Mandatory hooks for interacting with the WowCube OS.

C++
WASM_EXPORT void on_init() {
    // Standard startup sequence
    OCT_restart((int*)Objects, OBJECTS_CAP, sizeof(appObject_t));
    OCT_viewports_layout(SCHEME_CUBE, 18, 18); // 18px is the standard physical gap
}

WASM_EXPORT void on_tick() {
    // Primary logic entry point
    gameProcess(&vars.state, false); 
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    if (twid >= OCT_TWIST_HALF) return; // Ignore non-functional twists
    
    // Update all object coordinates to match physical rotation
    for (int i = 1; i < OBJECTS_CAP; i++) {
        if (Objects[i].Idx == i) OCT_TM_twist(&Objects[i].Tm, twid);
    }
}
4. Physics, Movement & Sensors
Patterns for moving objects across the non-Euclidean surface of the cube.

🔑 Key Rules
Wrapping: Use OCT_TM_wrap to ensure objects don't disappear when crossing cube edges.

Gravity: Hardware tilt is accessed via gravity_x/y for the specific plane the object is on.

C++
// Continuous movement with edge wrapping
OCT_TM_walk(&obj->Tm, obj->Tm.A, obj->spdX, obj->spdY, true);
OCT_TM_wrap(&obj->Tm); 

// Parallax/Tilt effect (cite: app_example_gravity.h)
float gx = OCT_TM_gravity_x(obj->Tm.Plane);
float gy = OCT_TM_gravity_y(obj->Tm.Plane);
obj->Tm.X += gx * 2.0f; 
5. UI, Labels & Lookups
Efficient HUD management to avoid per-frame pool scanning.

🔑 Key Rules
Lookup Helper: Use GetByName to find specific objects defined in map assets.

Caching: Find UI objects once during INIT and store pointers in vars.

C++
// Helper: Find object by its 'Name' attribute (cite: app_example_labels.h)
appObject_t* GetByName(int name) {
    for (int i = 1; i < OBJECTS_CAP; i++) {
        if (Objects[i].Idx == i && Objects[i].Name == name) return &Objects[i];
    }
    return NULL;
}

// Updating a label (cached pointer)
if (vars.scoreLabel) {
    char buf[16];
    sprintf(buf, "%d", vars.score);
    OCT_label_set(vars.scoreLabel, buf);
}
6. Advanced Animation Structures
Clean interpolation based on the global application tick.

C++
// (cite: app_crystal_crush.h)
typedef struct {
    uint32_t startTime;
    octTm_t startPos;
    octTm_t endPos;
} Anim_t;

void updateAnim(Anim_t* a, octTm_t* target, uint32_t currentTick) {
    uint32_t duration = 20; // 1 second @ 20fps
    if (currentTick < a->startTime + duration) {
        float p = (float)(currentTick - a->startTime) / duration;
        OCT_TM_lerp(target, &a->startPos, &a->endPos, p);
    }
}