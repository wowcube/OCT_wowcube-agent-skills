
WowCube SDK Reference Guide
This document provides verified code patterns and API usage examples for AI agents. All examples are derived from production-ready source files.

1. Architecture and Global State
Applications must follow a header-only architecture with thread-local state isolation.

Header-Only: Only .h files are used; .c files are strictly prohibited.

Thread-Local Storage: Global variables must use the TL macro.

C++
#pragma once
#include "oct_api.h"
#include "oct_consts.h"
#include "app_game_ids.h" // Asset IDs

// Global variables encapsulated in a struct
struct appVars_t {
    uint32_t score;
    uint8_t gameState;
};

TL appVars_t vars; // Use TL for all globals

2. Object Pool Management
WowCube uses a fixed-size object pool. Objects are accessed via an index.

Pool Size: Typically defined as OBJECTS_CAP 400.

Iteration: Always start loops from index 1. Index 0 is reserved.

Validation: Check Objects[i].Idx == i to ensure the object is active.

C++
for (int i = 1; i < OBJECTS_CAP; ++i) {
    if (Objects[i].Idx == i) { // Check if slot is occupied
        appObject_t* obj = &Objects[i];
        // Process object logic
    }
}
3. Lifecycle (WASM Exports)
Every application must implement the following lifecycle hooks.

C++
WASM_EXPORT void on_init() {
    OCT_restart((int*)Objects, OBJECTS_CAP, sizeof(appObject_t)); // Initialize pool
    OCT_viewports_layout(SCHEME_CUBE, 18, 18); // Set cube topology
}

WASM_EXPORT void on_tick() {
    // Main logic loop called every frame
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    if (twid >= OCT_TWIST_HALF) return; // Ignore non-functional twists
    // Update object positions based on twist
}

WASM_EXPORT void on_tap(int32_t tapid) {
    // Handle taps on specific planes (0-5)
}
4. Movement and Physics
The SDK provides tools for both discrete (grid) and continuous movement.

Continuous Movement: Use OCT_TM_walk for directional velocity.

Interpolation: Use OCT_TM_lerp for smooth transitions between two points.

Coordinate Wrapping: Use OCT_TM_wrap to automatically move objects across cube edges.

Gravity Sensors: Access tilt data using OCT_TM_gravity_x and OCT_TM_gravity_y.

C++
// Move object using internal velocity
OCT_TM_walk(&obj->Tm, obj->Tm.A, obj->spdX, obj->spdY, true);

// Wrap position around the cube surface
OCT_TM_wrap(&obj->Tm);

// Parallax effect based on tilt
obj->Tm.X = obj->baseX + (5.0f * OCT_TM_gravity_x(obj->Tm.Plane));
5. UI and Rendering
UI elements are handled as sprites or text labels on specific planes.

Sprites: Use OCT_add to create visual entities.

Labels: Use OCT_add_label for dynamic text.

Animations: Sequences are controlled by OCT_sequence. Check obj->OnEnd for completion.

C++
// Spawn a tile sprite
int spawnedI = OCT_add(30, true, plane, x, y, 0, false, BMP_start, BMP_end, 0);

// Update text label
int labelI = OCT_add_label(35, false, plane, 120.0f, 120.0f, 0, FONT_1, ALIGN_CENTER);
OCT_label_set(&Objects[labelI], "SCORE: 100");

