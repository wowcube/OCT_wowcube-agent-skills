#pragma once
#include <stdint.h>

// The saved game, on the wire. A LEAF header: app_metadata.h includes it (uncomment the include there to give the app a
// save area), and the packer compiles that header on its own to read APP_SAVE_SIZE, so nothing here may depend on the
// engine or on the rest of the app. Rules (octavios app_template/src/app_save.h, docs/knowledge/game_saves.md):
//  - Every record starts with saveHeader_t and the game checks it FIRST: the magic says "one of my records" (a fresh
//    area reads as zeros, and OCT_save_read returns 0 with the buffer zeroed when it cannot vouch for the bytes), the
//    version is the layout number: a record an older build wrote is read through that layout, upgraded in memory and
//    written back in today's.
//  - Fixed-width fields only, the 4-byte ones first, then 2-byte, then bytes in groups of four, then arrays; one
//    static_assert of the wire size per version, so the size is identical on ARM GCC, MSVC and the host probe.
//  - Save what a player would be angry to lose (progress, best score, settings) and nothing else: pointers, sprite
//    indices and tween ids mean nothing after a relaunch.
//  - <= 512 KB (OCT_SAVE_SIZE_MAX); one OCT_save_sync call moves at most 64 KB.
#define SAVE_MAGIC   0x54504C31u     // "TPL1": pick four bytes that are yours (e.g. the game's initials), never 0
#define SAVE_VERSION 1               // bump whenever a field moves, grows or changes meaning

typedef struct {
    uint32_t magic;          // SAVE_MAGIC
    uint16_t version;        // SAVE_VERSION of the build that wrote the record
    uint16_t size;           // sizeof the whole record of that version
} saveHeader_t;

typedef struct {
    saveHeader_t header;
    uint32_t     bestScore;  // demo 18: best score so far
    uint32_t     runs;       // demo 18: how many times the save demo was opened
} saveRecord_t;

static_assert(sizeof(saveHeader_t) == 8,  "the record header is eight bytes on the wire");
static_assert(sizeof(saveRecord_t) == 16, "the record is sixteen bytes on the wire - update this when the record changes");

#define APP_SAVE_SIZE sizeof(saveRecord_t)
