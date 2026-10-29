#pragma once
// The entry header every build includes: the ARM module (octavios/apps/src/app_module.cpp) and both simulators
// (SIM_APP_HEADER="app.h"). Layout of octavios dev (>= 609d5ae), see ../API.md.
//
// app_metadata.h comes FIRST: the game header may use APP_GUID1, APP_VERSION, APP_SAVE_SIZE and the APP_HAS_* switches.
// The pack-header defines live in app_metadata.h and never here: #define APP_VERSION, #define APP_GUID1,
// #define APP_TITLE, #define APP_CATEGORIES, #define APP_COLORS (and APP_SAVE_SIZE through app_save.h).
#include "app_metadata.h"
#include "app_ai_template.h"

// Where the Windows simulator packs this app from, relative to the folder it runs in (bin/). The Linux and macOS
// simulator takes the app folder from CMake (-DAPP_DIR=...) instead.
#define APP_DIR "../../app_ai_template"
