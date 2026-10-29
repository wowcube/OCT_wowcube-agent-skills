#pragma once
// ============================================================================
//  capture.h -- the demo video's capture harness (copy into the game's tests/).
//
//  The game runs headless on the host with its real rules and render; a scripted session (the
//  game's tests/capture.cpp) drives it, and every frame of the session is written as one line of
//  JSON to docs/demo/frames.jsonl. render_demo.py turns the lines into the video.
//
//  Two ways to record a frame:
//    sprites  (default)  every live sprite: plane, x, y, angle, layer, frames, tint, label text.
//                        The renderer draws them from the art dump (gen_art.py --dump). Fast, needs
//                        no packed art; the game's labels must pass through RENDER_LABEL_HOOK.
//    net      (CAPTURE_NET 1) the real engine renders all 24 screens from the packed art
//                        (shot.h) into docs/demo/net/NNNNN.png. For games that draw screens
//                        themselves (on_proc_draw) or need the engine's pixels exactly.
//
//  Include BEFORE app.h (its label hook must exist when render.h is compiled); in net mode include
//  shot.h AFTER app.h. capture.h calls nothing of the game: the game's capture.cpp ticks the game
//  (on_tick) and calls capFrame() after every tick.
// ============================================================================

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#ifndef CAPTURE_NET
#define CAPTURE_NET             0           // 1: frames rendered by the engine (shot.h), 0: sprite lists
#endif
#ifndef CAPTURE_DIR
#define CAPTURE_DIR             "docs/demo" // frames.jsonl (and net/ in net mode) go here
#endif
#define CAPTURE_LABELS_MAX      4096        // label sprite ids the hook remembers
#define CAPTURE_LEGEND_NONE     (-1)

// --- the label hook: the game's render passes every label's text here -------------------------
// In the game's render.h, next to the label call:   RENDER_LABEL_HOOK(id, text, font, color, align);
// with a default of ((void)0) under #ifndef, so the game's own builds are untouched.

struct CapLabel { std::string text; int font, color, align; };
static CapLabel gCapLabels[CAPTURE_LABELS_MAX];
#define RENDER_LABEL_HOOK(id, text, font, color, align) \
    do { if ((id) > 0 && (id) < CAPTURE_LABELS_MAX) gCapLabels[(id)] = CapLabel{ (text), (int)(font), (int)(color), (int)(align) }; } while (0)

// --- the shot: what the video says over the frames that follow ---------------------------------

typedef struct {
    const char* caption;                    // the bold line under the cube
    const char* sub;                        // the small line under it
    int         legend;                     // the legend row lit (demo.json "legend" index), -1 none
    float       yaw, pitch;                 // the 3D camera, degrees
    float       yawSpeed;                   // degrees a frame: a slow orbit
} CapShot_t;

typedef struct {
    FILE*                 out;
    uint32_t              frame;
    CapShot_t             shot;
    float                 yaw;
    int                   twist;            // the twist id that happened before the next frame, -1 none
    std::vector<int16_t>  bornFrom, bornTo;
    std::vector<uint32_t> born;
} Capture_t;

static Capture_t gCap;

#if CAPTURE_NET
static void shotNet(const char* path);      // shot.h, included after app.h
#endif

static void capJsonText(const char* s) {
    fputc('"', gCap.out);
    for (; *s; s++) {
        if (*s == '"' || *s == '\\') fputc('\\', gCap.out);
        if (*s == '\n') { fputs("\\n", gCap.out); continue; }
        fputc(*s, gCap.out);
    }
    fputc('"', gCap.out);
}

// Start writing; false when the file cannot be made (the folder must exist: capture_demo.sh makes it).
static bool capOpen(void) {
    gCap.out = fopen(CAPTURE_DIR "/frames.jsonl", "w");
    if (!gCap.out) { fprintf(stderr, "cannot write %s/frames.jsonl\n", CAPTURE_DIR); return false; }
    gCap.frame = 0;
    gCap.twist = -1;
    gCap.shot = CapShot_t{ "", "", CAPTURE_LEGEND_NONE, 30.0f, 24.0f, 0.0f };
    gCap.yaw = gCap.shot.yaw;
    return true;
}

static void capClose(void) {
    if (gCap.out) fclose(gCap.out);
    gCap.out = NULL;
    printf("    %u frames -> %s/frames.jsonl\n", gCap.frame, CAPTURE_DIR);
}

// The caption, the lit legend row and the camera from the next frame on.
static void capShot(const char* caption, const char* sub, int legend, float yaw, float pitch, float yawSpeed = 0.0f) {
    gCap.shot = CapShot_t{ caption, sub, legend, yaw, pitch, yawSpeed };
    gCap.yaw = yaw;
}

// A twist was just applied (on_pretwisted, OCT_twist_sprites, on_twisted): the renderer animates the
// turning half between the last frame and the next one.
static void capTwist(int twid) {
    gCap.twist = twid;
}

#if !CAPTURE_NET
// Every live sprite as the engine would gather it, in the pool's order.
static void capSprites(void) {
    if ((int)gCap.born.size() < OctCap) {
        gCap.bornFrom.assign((size_t)OctCap, -1);
        gCap.bornTo.assign((size_t)OctCap, -1);
        gCap.born.assign((size_t)OctCap, 0);
    }
    fputs(",\"s\":[", gCap.out);
    bool first = true;
    for (int i = 1; i < OctCap; i++) {
        octSprite_t* s = SPRITE_PTR(i);
        if (s->Idx != i) { gCap.bornFrom[i] = -1; continue; }
        if (s->Letter || s->Hidden || s->Tm.Plane < 0) continue;
        if (gCap.bornFrom[i] != s->FrameFrom || gCap.bornTo[i] != s->FrameTo) {   // an animation (re)started
            gCap.bornFrom[i] = s->FrameFrom;
            gCap.bornTo[i] = s->FrameTo;
            gCap.born[i] = gCap.frame;
        }
        if (!first) fputc(',', gCap.out);
        first = false;
        fprintf(gCap.out, "[%d,%d,%.1f,%.1f,%d,%d,%d,%d,%d,%d,%u,%d,%u", i, s->Tm.Plane, s->Tm.X, s->Tm.Y, (int)s->Tm.A,
                (int)s->Layer, (int)s->FrameFrom, (int)s->FrameTo, (int)s->FrameRate, (int)s->Loop, gCap.born[i],
                (int)s->Transp, (unsigned)s->Data0);
        if (s->Label) {
            const CapLabel& l = gCapLabels[i];
            fprintf(gCap.out, ",%d,%d,%d,", l.font, l.color, l.align);
            capJsonText(l.text.c_str());
        }
        fputc(']', gCap.out);
    }
    fputc(']', gCap.out);
}
#endif

// One frame of the video: call after every on_tick of the session.
static void capFrame(void) {
    if (!gCap.out) return;
    fprintf(gCap.out, "{\"t\":%u,\"cap\":", gCap.frame);
    capJsonText(gCap.shot.caption);
    fputs(",\"sub\":", gCap.out);
    capJsonText(gCap.shot.sub);
    fprintf(gCap.out, ",\"legend\":%d,\"yaw\":%.2f,\"pitch\":%.2f,\"g\":[%.3f,%.3f,%.3f],\"twist\":%d",
            gCap.shot.legend, gCap.yaw, gCap.shot.pitch, Gf[0], Gf[1], Gf[2], gCap.twist);
#if CAPTURE_NET
    char name[64];
    snprintf(name, sizeof(name), "net/%05u.png", gCap.frame);
    shotNet((std::string(CAPTURE_DIR "/") + name).c_str());
    fprintf(gCap.out, ",\"net\":\"%s\"", name);
#else
    capSprites();
#endif
    fputs("}\n", gCap.out);
    gCap.frame++;
    gCap.yaw += gCap.shot.yawSpeed;
    gCap.twist = -1;
}
