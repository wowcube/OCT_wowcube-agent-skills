#pragma once
#include "oct_api.h"
#include "oct_consts.h"
#include "app_change_me_ids.h" // Replace with actual generated IDs

#define OBJECTS_CAP 400
#define GAP 18

// 1. Enums for Logic Control
enum class GAME_STATE : uint8_t { NONE, PLAYING, WIN, LOSE };
enum class OBJ_TYPE : uint8_t { NONE, PLAYER, ENEMY, ITEM };

// 2. Data Structures
struct appObject_t : octSprite_t {
    OBJ_TYPE type;
    float spdX, spdY;
};

struct appVars_t {
    GAME_STATE gameState;
    uint32_t score;
};

// 3. Thread-Local Memory
TL appObject_t Objects[OBJECTS_CAP];
TL appVars_t vars;

// 4. Lifecycle Hooks
WASM_EXPORT void on_init() {
    OCT_restart((int*)Objects, OBJECTS_CAP, sizeof(appObject_t));
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
}

WASM_EXPORT void on_tick() {
    // Main loop logic here
}

WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    if (twid >= OCT_TWIST_HALF) return;
    // Twist-related coordinate updates
}

WASM_EXPORT void on_tap(int32_t tapid) { /* Handle plane taps */ }
WASM_EXPORT void on_pretwisted(int32_t twid) {}