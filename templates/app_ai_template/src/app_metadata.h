#pragma once
// Everything the packer stamps into this app's pack header, in a LEAF header: octavios `octpack-build`
// (tools/build.ps1|.sh) compiles this file on its own with a host compiler, and the pipeline's python packer
// (scripts/pack_beta.py read_app_defines, scripts/repack_app.py) reads the same lines as text. So: include only
// oct_app_version.h, oct_app_categories.h and app_save.h here, and write every value as a literal or one of the
// macros below. Requires octavios dev >= 609d5ae (engine/oct_app_version.h must exist). Reference: ../API.md.
#include "oct_app_version.h"
#include "oct_app_categories.h"

// Version: bump on every release (scripts/repack_app.py bumps APP_VERSION_PATCH). The store and the cube's update
// check compare APP_VERSION exactly. OCT_APP_SEMVER puts scheme byte 1 on top, so readers show 0.1.0 instead of an
// opaque counter (a bare integer such as 100 is the legacy scheme-0 "build 100", not v1.00).
#define APP_VERSION_MAJOR 0
#define APP_VERSION_MINOR 1
#define APP_VERSION_PATCH 0
#define APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, APP_VERSION_MINOR, APP_VERSION_PATCH)

// !!! APP_GUID1 MUST BE A FRESH RANDOM 64-BIT VALUE FOR EVERY GAME. NEVER COPY IT FROM ANOTHER APP. !!!
// It is the app's permanent identity on the cube, in the store and on the phone (Guid2 is always 0). Installing a pack
// REPLACES any installed pack with the same GUID, and the save area is keyed by it: two games sharing a GUID overwrite
// each other on the cube and read each other's saves. The scaffolder (scripts/new_app.ps1|.sh) replaces the zero
// placeholder below with a random value; zeros here mean "no identity" and must not ship. Generate one by hand with
//   PowerShell: $b=[byte[]]::new(8); [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); '0x{0:X16}ULL' -f [BitConverter]::ToUInt64($b,0)
//   Linux/macOS: echo "0x$(od -An -tx8 -N8 /dev/urandom | tr -d ' ' | tr a-f A-F)ULL"
// Once set it never changes, across every version of the game.
#define APP_GUID1 0x0000000000000000ULL

// The name under the launcher icon, in the install toasts and on the phone, <= 79 characters. Left undefined, the
// cube shows the name the pack was installed under.
#define APP_TITLE "AI DEMO"

// What each bit makes the engine do: engine/oct_app_categories.h.
//   APP_CATEGORY_GAME         plain game: paused on the dock and after 60 s idle (battery save), cube sleeps 5 min later
//   APP_CATEGORY_SCREENSAVER  runs unattended: never paused on the dock or when idle, never dimmed, never slept by idling
//   APP_CATEGORY_TEST         test/diagnostic app: never paused (dock or battery save), only dimmed
//   APP_CATEGORY_LAUNCHER / _CHARGER / _SYSTEM / _GETSTARTED / _SLEEP are system packs, never for a game
#define APP_CATEGORIES (APP_CATEGORY_GAME)

// uint32 stored in the pack header (launcher colouring)
#define APP_COLORS 0x00000000

// The save area, if this app keeps one: the record lives in app_save.h (a skeleton is in this folder), which defines
// APP_SAVE_SIZE as sizeof that record (<= 512 KB). Without the include the app has no save area and every OCT_save_*
// call answers OCT_SAVE_NO_AREA. The pack header must carry the size: octpack-build and the simulators stamp it.
//   OCT_save_read(&rec, 0, sizeof(rec))    loads a range: byte count, 0 = nothing readable (rec zeroed), negative = refused
//   OCT_save_write(&rec, 0, sizeof(rec))   stores a range: the bytes are on the card before the call returns
//   OCT_save_erase()                       empties the whole area ("new game")
//   OCT_save_sync(offset, size)            makes the leader's bytes for that range the bytes on every module
// #include "app_save.h"

// The optional callbacks: each define exports the function of that name from the game header (and the game header
// must then define it). on_init, on_tick, on_pretwisted, on_twisted, on_tap and on_shake are always exported.
// #define APP_HAS_ON_SAVE          // on_save(): stores the record as the app closes, on every docking and before sleep
// #define APP_HAS_ON_SAVE_SYNCED   // on_save_synced(result): the answer to OCT_save_sync, where cube-wide data is read back
// #define APP_HAS_ON_DOCK          // on_dock(docked): only for an APP_CATEGORY_SYSTEM app holding OCT_shake_exit_block(true)
// #define APP_HAS_PROC_DRAW        // on_proc_draw(): draws the sprites that carry PROCEDURAL_CUSTOM itself

// Telemetry, if this app is instrumented (WLOG_* / WCOUNT records, gated in its sources on APP_TELEMETRY):
// octpack-build then builds it with the telemetry library, which has to be checked out next to octavios.
// #define APP_HAS_TELEMETRY
