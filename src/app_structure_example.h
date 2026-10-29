#pragma once
#include "oct_api.h"
#include "oct_consts.h"

#include "app_ai_template_ids.h" // the Stage 4 copy command renames this to app_<game>_ids.h (orchestrator Stage 4, Step 1)

// Skeleton of a game header, src/app_<game>.h, for octavios dev >= 609d5ae.
// src/app.h includes src/app_metadata.h FIRST (version, APP_GUID1, title, categories, APP_HAS_* switches, the save
// area via app_save.h) and then this file. Engine facts, limits and pitfalls: templates/app_ai_template/API.md.
// Annotated examples of every call: templates/app_ai_template/src/app_ai_template.h.

#define OCT_PLANES_MAX 6 // max planes on cube
#define OCT_QUADS_AT_PLANE 4 // max quads at plane

// The app's own sprite pool. It lives in the 256 KB module image with the code: SPRITES_CAP * sizeof(appObject_t)
// must fit (80 B per sprite + your fields). Usable = SPRITES_CAP - 2; <= 512 sprites are drawn per screen.
#define SPRITES_CAP 400
#define GAP 18 // width of physical border between wowcube's display in pixels
// Screen-FILLING art (backgrounds, panorama pieces, edge-to-edge tiles) goes at OCT_add(..., XSIGN[q] * QUAD_FILL,
// YSIGN[q] * QUAD_FILL, ...), raw +-(QUAD_FILL + GAP): at +-120 a 2-px background line shows on the inner screen edges.
#define QUAD_FILL 119.5f
// Never define SIM_SINGLE_THREAD: the simulator must run all 8 copies of the game, as the cube does.

//// TEST HOOKS //// release and device builds keep these defaults; agent test builds flip them (-D / build.ps1 -Define).
// Rename the GAME_ prefix to the game's short upper-case prefix (e.g. TD_), the same in all three names.
#ifndef GAME_DEBUG_AUTOPLAY
#define GAME_DEBUG_AUTOPLAY 0      // 1 = the game plays itself (scripted inputs, no title tap, restarts rounds)
#endif
#ifndef GAME_MUTE
#define GAME_MUTE 0                // 1 = no sound at all: playSound()/playSoundAt() compile to nothing
#endif
#ifndef GAME_DEBUG_ROOM_PLANE
#define GAME_DEBUG_ROOM_PLANE (-1) // 0..5 = playfield pinned to this face (no tilt needed); -1 = normal
#endif


////////////////////////////////
//          OBJECTS           //
////////////////////////////////

// game specific data (sizeof must stay a multiple of 4)
typedef struct _appObject_t: octSprite_t{

} appObject_t;

// music bed: the engine cannot loop or stop a sound, the game re-issues the track
typedef struct {
    int32_t trackId; // sound asset id of the loop, -1 = no music
    uint32_t nextTick; // vars.tick of the next retrigger
} music_t;

// game specific vars (group related state into _t sub-structs)
typedef struct {
    uint32_t tick; // on_tick calls since on_init: the game clock, identical on all 8 modules
    music_t music;
} appvars_t;


////////////////////////////////
//         DEFINITION         //
////////////////////////////////

appObject_t* spriteAt(int32_t id);
bool isAlive(const appObject_t* obj);
int32_t playfieldPlane(void);
void playSound(int32_t id, int32_t volume);
void playSoundAt(int32_t id, int32_t volume, int32_t quad);
void updateMusic(void);


////////////////////////////////
//            MAPS            //
////////////////////////////////

//[NOTE]: Every MUTABLE global must be defined with the TL macro (the simulator runs the 8 modules as threads of
//one process); immutable `static const` tables may stay plain
TL static appObject_t gObjects[SPRITES_CAP];
TL static appvars_t vars;

static const int32_t MUSIC_VOLUME = 40;
static const uint32_t MUSIC_LOOP_TICKS = 300U; // ceil(track length in ms / OCT_FRAME_MS): 300 ticks = a 15 s loop


////////////////////////////////
//       IMPLEMENTATION       //
////////////////////////////////

// OCT_add / OCT_add_label return 0 when the pool is full; slot 0 is the pool's free-list head, never a sprite.
appObject_t* spriteAt(int32_t id) {
    return (id > 0 && id < (int32_t)SPRITES_CAP) ? &gObjects[id] : NULL;
}

// A slot is alive while gObjects[i].Idx == i (loop i from 1). Freed slots are reused by the next OCT_add (LIFO) and
// Autokill sprites vanish on their own: null a pointer when you delete its sprite, never keep Autokill pointers.
bool isAlive(const appObject_t* obj) {
    return obj != NULL && (int32_t)obj->Idx == (int32_t)(obj - gObjects);
}

// The face the playfield lives on: the face that is up, unless the GAME_DEBUG_ROOM_PLANE test hook pins it.
int32_t playfieldPlane(void) {
#if GAME_DEBUG_ROOM_PLANE >= 0
    return (int32_t)GAME_DEBUG_ROOM_PLANE;
#else
    return (int32_t)OCT_TM_top_side();
#endif
}

// Every sound goes through these two, so GAME_MUTE compiles all of them out. SND_play's result is per module (voice
// pool, simulator non-leaders): it is dropped on purpose, never branch on it.
void playSound(int32_t id, int32_t volume) {
#if GAME_MUTE
    (void)id; (void)volume;
#else
    if (id <= 0) return;
    SND_play(id, volume);
#endif
}

// A sound that belongs to a place: only the module showing scene quad 0..23 plays it (e.g. OCT_TM_quad(&obj->Tm)).
// Needs cube firmware >= fw-0.98.19 (the module macro has no NULL guard).
void playSoundAt(int32_t id, int32_t volume, int32_t quad) {
#if GAME_MUTE
    (void)id; (void)volume; (void)quad;
#else
    if (id <= 0 || quad < 0 || quad >= OCT_PLANES_MAX * OCT_QUADS_AT_PLANE) return;
    SND_play_quad(id, volume, quad);
#endif
}

// Called from on_tick: re-issues the music loop every MUSIC_LOOP_TICKS (counts ticks, identical on all 8 modules).
void updateMusic(void) {
    if (vars.music.trackId <= 0 || vars.tick < vars.music.nextTick) return;
    playSound(vars.music.trackId, MUSIC_VOLUME);
    vars.music.nextTick = vars.tick + MUSIC_LOOP_TICKS;
}


// handlers
OCT_CALLBACK void on_init() {
    // 1. FIRST: bind the sprite pool. It switches the engine to RUNNING (without it on_tick never runs) and resets
    //    sprites, tweens, label slots, external maps and the OCT_random seed.
    OCT_restart((int*)gObjects, SPRITES_CAP, (int32_t)sizeof(appObject_t));

    // 2. Global render state survives from the previous app: set it on every launch.
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
    OCT_background(0x0000);

    // Debug overlay: OR flags into the mask, never replace it (it holds OCT_DEV_DIRTY_SKIP).
    // OCT_dev_mode(OCT_dev_mode(-1) | OCT_DEV_TEXT);

    memset(&vars, 0, sizeof(vars));
    vars.music.trackId = -1; // e.g. (int32_t)SND_music_loop from app_<game>_ids.h, or SND_getAssetId("music_loop.mp3")

    // Random content: roll it in the first on_tick (OCT_random draws made here after OCT_restart repeat every launch).
    // Saves: load here (OCT_save_read, or OCT_save_sync + on_save_synced when saved data drives game logic).
}

OCT_CALLBACK void on_tick() {
    // 20 times a second while the game is not held (dock, battery save, save sync): the app is not told about holds.
    updateMusic();

#if GAME_DEBUG_AUTOPLAY
    // the bot: feed scripted input here
#endif

    vars.tick++;
}

OCT_CALLBACK void on_pretwisted(int32_t side) {
    // A layer started turning on SIDE 0..5 (not a twist id). A command (same tick on all 8 modules), but the twist may
    // be abandoned: on_twisted is not guaranteed to follow.
    (void)side;
}

OCT_CALLBACK void on_twisted(int32_t twid, uint32_t disconnected_ms) {
    // twid 0..11 full twist (twistable sprites already moved), 12..23 half twist (moved nothing). A 180-degree twist
    // arrives as two calls with the same twid. disconnected_ms is a timestamp (leader clock), not a duration.
    if (twid >= OCT_TWIST_HALF) return;
    (void)disconnected_ms;
}

OCT_CALLBACK void on_tap(int32_t tapid, int32_t count) {
    // tapid = plane 0..5; count = place in a quick series (1, 2, ... max 7), delivered tap by tap.
    // The exact screen (scene quad 0..23): OCT_tap_source, see appTapQuad in app_ai_template.h (keep a per-face fallback).
    (void)tapid; (void)count;
}

OCT_CALLBACK void on_shake(int32_t shakeid) {
    // Must exist (the export table references it) but is never called: a shake always exits a plain game.
    (void)shakeid;
}


// Optional callbacks: define each one only together with its APP_HAS_* switch in app_metadata.h.

#ifdef APP_HAS_ON_SAVE
OCT_CALLBACK void on_save() {
    // On every exit, on docking and before sleep: OCT_save_write the state the game trusts and return. No animation,
    // no sound. Never overwrite a good save with a record that was never loaded.
#ifdef APP_SAVE_SIZE
    saveRecord_t rec; // a local is fine: the engine reads it before the call returns
    memset(&rec, 0, sizeof(rec));
    rec.header.magic = SAVE_MAGIC;
    rec.header.version = (uint16_t)SAVE_VERSION;
    rec.header.size = (uint16_t)sizeof(rec);
    // ... fill the record from the game state ...
    OCT_save_write(&rec, 0U, (uint32_t)sizeof(rec));
#endif
}
#endif

#ifdef APP_HAS_ON_SAVE_SYNCED
OCT_CALLBACK void on_save_synced(int32_t result) {
    // The verdict of OCT_save_sync, same tick on all 8 modules: OCT_SAVE_OK or a negative OCT_SAVE_* code. Read back here.
    (void)result;
}
#endif

#ifdef APP_HAS_ON_DOCK
OCT_CALLBACK void on_dock(int32_t docked) {
    // Only for an APP_CATEGORY_SYSTEM app holding OCT_shake_exit_block(true); a game is simply paused on the dock.
    (void)docked;
}
#endif

#ifdef APP_HAS_PROC_DRAW
OCT_CALLBACK void on_proc_draw(uint16_t* back, int idx, float x, float y, int angle, int vid, int reserved) {
    // Draws one PROCEDURAL_CUSTOM sprite into back (120x120 RGB565, back[row * HALFSIDE + col]; never write outside).
    // x = Tm.Y, y = Tm.X in full-res screen pixels (>> 1 for back), angle = 90 - Tm.A. Render path: no game state,
    // no OCT_random. Set Keyed = 1 and bump DrawKey when the picture changes, or the face redraws every frame.
    (void)back; (void)idx; (void)x; (void)y; (void)angle; (void)vid; (void)reserved;
}
#endif
