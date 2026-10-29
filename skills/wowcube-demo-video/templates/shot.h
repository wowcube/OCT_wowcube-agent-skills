#pragma once
// ============================================================================
//  shot.h -- the real engine renders all 24 screens (copy into the game's tests/).
//
//  The app's pack is loaded the way the simulator loads it (index.bin + art/packed + sound/assets:
//  pack the art first), every screen is rendered by OCT_RENDER_gather + OCT_render, and the faces are
//  laid out as an unfolded cube seen from outside (L F R B in a row, U above F, D below), written as
//  PNG. render_demo.py reads that layout (SHOT_* below) in its net mode.
//
//  Include after oct.h and app.h; needs stb_image_write.h (the engine's sim/src). Call shotInit() once,
//  then shotLoadPack(appDir); shotCube() writes a still and says so, shotNet() writes a video frame.
// ============================================================================

#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#define SHOT_GAP        18                              // bezel between two screens, px
#define SHOT_FACE       (2 * SIDE + SHOT_GAP)           // a face with its inner bezel
#define SHOT_MARGIN     12
#define SHOT_COLS       4                               // L F R B in a row, U above F, D below
#define SHOT_ROWS       3
#define SHOT_W          (SHOT_COLS * SHOT_FACE + (SHOT_COLS + 1) * SHOT_MARGIN)
#define SHOT_H          (SHOT_ROWS * SHOT_FACE + (SHOT_ROWS + 1) * SHOT_MARGIN)
#define SHOT_BEZEL      0x1A, 0x1A, 0x20
#define SHOT_PAPER      0x30, 0x30, 0x38
#define SHOT_PLANES     6
#define SHOT_QUADS      4
#define SHOT_SCREENS    (SHOT_PLANES * SHOT_QUADS)
#define SHOT_QUAD_RAW   120.0f                          // a quad centre on each axis of a plane

// A quad's centre signs, and how a screen's full-res row and column run along the plane's x / y
// (the engine turns quad k by -90 * k).
static const int8_t kShotQuadSign[SHOT_QUADS][2] = { { 1, 1}, {-1, 1}, {-1, -1}, { 1, -1} };
static const int8_t kShotRowRaw[SHOT_QUADS][2] = { { 1, 0}, { 0, 1}, {-1, 0}, { 0, -1} };
static const int8_t kShotColRaw[SHOT_QUADS][2] = { { 0, 1}, {-1, 0}, { 0, -1}, { 1, 0} };

static inline int shotQuadOf(float x, float y) { return (x >= 0.0f) ? ((y >= 0.0f) ? 0 : 3) : ((y >= 0.0f) ? 1 : 2); }

static std::vector<uint8_t> gShotPack;

// index.bin + art/packed + sound/assets -> one resident pack (sim.h SIM_build_pack, minus the code).
static bool shotLoadPack(const std::string& appDir)
{
    std::ifstream index(appDir + "/index.bin", std::ios::binary);
    if (!index) { std::fprintf(stderr, "no index.bin in %s: pack the art first\n", appDir.c_str()); return false; }
    int32_t count = 0;
    index.read((char*)&count, sizeof(count));
    if (count <= 0 || (uint32_t)count > OCT_ASSETS_CAP) return false;
    struct Entry { int32_t kind; char name[OCT_ASSET_NAME_MAXLEN]; std::vector<char> data; };
    std::vector<Entry> entries((size_t)count);
    size_t capacity = (sizeof(octPackHeader_t) + sizeof(octAssetDesc_t) * (size_t)count + 3) & ~(size_t)3;
    for (auto& e : entries) {
        index.read((char*)&e.kind, sizeof(e.kind));
        index.read(e.name, OCT_ASSET_NAME_MAXLEN);
        e.name[OCT_ASSET_NAME_MAXLEN - 1] = 0;
        std::string path = appDir + ((e.kind == OCT_ASSET_KIND_SOUND) ? "/sound/assets/" : "/art/packed/") + e.name
                         + ((e.kind == OCT_ASSET_KIND_SOUND) ? ".mp3" : (e.kind == OCT_ASSET_KIND_PAL) ? ".pal" : ".raw");
        std::ifstream f(path, std::ios::binary);
        if (!f) { std::fprintf(stderr, "missing %s\n", path.c_str()); return false; }
        e.data.assign(std::istreambuf_iterator<char>(f), std::istreambuf_iterator<char>());
        capacity = (capacity + e.data.size() + 3) & ~(size_t)3;
    }
    gShotPack.assign(capacity, 0);
    octPackHeader_t* header = (octPackHeader_t*)gShotPack.data();
    octAssetDesc_t* descs = (octAssetDesc_t*)(gShotPack.data() + sizeof(octPackHeader_t));
    memcpy(&header->Magic, OCT_PACK_MAGIC, 4);
    header->FormatVersion = OCT_PACK_FORMAT_SUPPORTED;
    header->EngineVersion = OCT_ENGINE_VERSION_CURRENT;
    header->AppVersion = APP_VERSION;
    header->Guid1 = APP_GUID1;
    header->Categories = APP_CATEGORIES;
#ifdef APP_SAVE_SIZE                                    // only an app with app_save.h declares one
    header->SaveSize = APP_SAVE_SIZE;                   // as sim.h stamps it: the save area's size
#endif
    uint32_t offset = (uint32_t)((sizeof(octPackHeader_t) + sizeof(octAssetDesc_t) * (size_t)count + 3) & ~(size_t)3);
    header->AssetDescs = header->SoundDescs = (uint32_t)sizeof(octPackHeader_t);
    for (int i = 0; i < count; i++) {
        const Entry& e = entries[(size_t)i];
        memcpy(gShotPack.data() + offset, e.data.data(), e.data.size());
        octAssetDesc_t* d = &descs[i];
        memset(d, 0, sizeof(*d));
        d->Offset = offset;
        d->Size = (uint32_t)e.data.size();
        d->Kind = (uint8_t)e.kind;
        OCT_strcpy(d->Name, OCT_ASSET_NAME_MAXLEN, e.name);
        if (e.kind == OCT_ASSET_KIND_SPRITE) memcpy(&d->Bmp, gShotPack.data() + offset, sizeof(octBmp_t));
        offset = (offset + (uint32_t)e.data.size() + 3) & ~3u;
    }
    header->AssetCount = (uint32_t)count;
    header->Size = offset;
    header->Crc = OCT_crc(gShotPack.data() + 8, header->Size - 8);
    return OCT_PACK_bind_resident(gShotPack.data());
}

// The engine state a running app sees, with every overlay quiet.
static void shotQuietEngine(void)
{
    OctState = OCT_STATE_RUNNING; OctPoweringOff = 0; OctLowBatNotify = OCT_LOWBAT_NOTIFY_OFF;
    OctToastKind = OCT_NOTIFY_NONE; OctDevMode = 0; OctClearEnabled = 1; OctClearColor = COLOR_BLACK;
    OctTransState = OCT_TRANS_IDLE; OctDebugFlags = 0;
    VisibleDebugStatus = VisibleDebugText = VisibleNetStats = -1;
    OctFullScreenVisible = 0; OctSyncedTick = 1000;
}

// Net cell of each plane (column, row): L F R B in the middle row, U over F, D under it.
static const int kShotNet[SHOT_PLANES][2] = { {1, 0}, {1, 1}, {2, 1}, {3, 1}, {0, 1}, {1, 2} };

static void shotPut(std::vector<uint8_t>& img, int x, int y, uint16_t px)
{
    uint8_t* p = &img[((size_t)y * SHOT_W + x) * 3];
    p[0] = (uint8_t)(((px >> 11) & 31) * 255 / 31);
    p[1] = (uint8_t)(((px >> 5) & 63) * 255 / 63);
    p[2] = (uint8_t)((px & 31) * 255 / 31);
}

// Every screen rendered, each face laid out as seen from outside (raw x right, raw y up).
static void shotNet(const char* path)
{
    static uint16_t screens[SHOT_SCREENS][SIDE * SIDE];
    for (int vid = 0; vid < VIEWPORTS_COUNT && vid < SHOT_SCREENS; vid++) {
        OCT_RENDER_gather(vid);
        OCT_render(0, vid, screens[vid], 0);
    }
    std::vector<uint8_t> img((size_t)SHOT_W * SHOT_H * 3);
    const uint8_t paper[3] = { SHOT_PAPER }, bezel[3] = { SHOT_BEZEL };
    for (size_t i = 0; i < img.size(); i += 3) memcpy(&img[i], paper, 3);
    for (int p = 0; p < SHOT_PLANES; p++) {
        const int ox = SHOT_MARGIN + kShotNet[p][0] * (SHOT_FACE + SHOT_MARGIN);
        const int oy = SHOT_MARGIN + kShotNet[p][1] * (SHOT_FACE + SHOT_MARGIN);
        for (int y = 0; y < SHOT_FACE; y++)
            for (int x = 0; x < SHOT_FACE; x++) {
                const bool gx = (x >= SIDE && x < SIDE + SHOT_GAP), gy = (y >= SIDE && y < SIDE + SHOT_GAP);
                if (gx || gy) { memcpy(&img[((size_t)(oy + y) * SHOT_W + ox + x) * 3], bezel, 3); continue; }
                const float fx = (x < SIDE) ? (float)(x - SIDE) + 0.5f : (float)(x - SIDE - SHOT_GAP) + 0.5f;
                const float fy = (y < SIDE) ? (float)(SIDE - y) - 0.5f : (float)(SIDE + SHOT_GAP - y) - 0.5f;
                const int q = shotQuadOf(fx, fy);
                const float cx = kShotQuadSign[q][0] * SHOT_QUAD_RAW, cy = kShotQuadSign[q][1] * SHOT_QUAD_RAW;
                const int row = (int)(SHOT_QUAD_RAW + kShotRowRaw[q][0] * (fx - cx) + kShotRowRaw[q][1] * (fy - cy));
                const int col = (int)(SHOT_QUAD_RAW + kShotColRaw[q][0] * (fx - cx) + kShotColRaw[q][1] * (fy - cy));
                if ((unsigned)row >= (unsigned)SIDE || (unsigned)col >= (unsigned)SIDE) continue;
                shotPut(img, ox + x, oy + y, screens[p * SHOT_QUADS + q][row * SIDE + col]);
            }
    }
    stbi_write_png(path, SHOT_W, SHOT_H, 3, img.data(), SHOT_W * 3);
}

// A still: the same picture, and its path on stdout.
static void shotCube(const char* path)
{
    shotNet(path);
    std::printf("%s\n", path);
}

// The headless displays the renderer draws into: once, before the first shot.
static void shotInit(void)
{
    OCT_SHIM_displays_up(0);
    for (int i = 0; i < OCT_CUBE_COUNT * OCT_DISPLAY_COUNT; i++) Backs[i] = new uint16_t[HALFSIDE * HALFSIDE];
}
