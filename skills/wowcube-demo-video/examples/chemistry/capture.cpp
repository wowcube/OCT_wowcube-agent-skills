// Chemistry's demo capture -- an EXAMPLE of a game's tests/capture.cpp on the skill's capture.h, net
// mode: the real engine renders all 24 screens from the packed art on every frame, and every twist is
// marked for render_demo.py, which turns the half of the cube in 3D between the frames around it.
//
//   CAPTURE_NET=1 capture_demo.sh [path-to-engine]   -> docs/demo/frames.jsonl + docs/demo/net/*.png
//
// What is the game's own here: startGame / startLevel / unscramble (the game's levels and scrambles),
// the captions. What every net capture has: shotInit + shotLoadPack, tick() = on_tick -> capFrame,
// twist() = on_pretwisted -> OCT_twist_sprites -> on_twisted -> capTwist.

#include "oct_test_shim.h"

#define MINIMP3_IMPLEMENTATION
#include "oct.h"

#include "capture.h"                    // before app.h (its label hook is not used in net mode)

#define ATTR_RODATA_IN_TCM
#include "app.h"

#include "shot.h"                       // after app.h: the engine's render of every screen

#define DEMO_LEVEL_H2       0           // scripts/molecules.py, 0-based
#define DEMO_LEVEL_WATER    2
#define DEMO_LEVEL_METHANE  14
#define DEMO_TWIST_GAP      14          // frames between two twists of the robot: the turn reads
#define DEMO_HOLD           40          // frames a finished scene is held

void TestBegin()
{
    Debug = new simDebug();
    Debug->Init("log_capture.txt");
    SET.TimeZero = SIM_now_ms() - 100000u;
    OCT_SHIM_init();
}

static void setGravity(float x, float y, float z) { Gf[0] = x; Gf[1] = y; Gf[2] = -z; }   // cube space -> engine

static void ticks(int n)
{
    for (int i = 0; i < n; i++) {
        on_tick();
        capFrame();
    }
}

// A twist as the engine delivers it, marked for the renderer's turn.
static void twist(int t)
{
    on_pretwisted(t);
    OCT_twist_sprites((octTwistId_t)t);
    on_twisted(t, 0);
    capTwist(t);
}

// The title screen, the cube standing on its bottom face.
static void startGame(void)
{
    shotQuietEngine();
    setGravity(0.0f, -1.0f, 0.0f);
    on_init();
    for (int i = 0; i < SETTLE_TICKS + 1; i++) on_tick();       // not filmed: gravity settling
}

static void startLevel(int level)
{
    twist(TOP_CW);
    gameStartLevel(&gGame, level);
    ticks(DEMO_HOLD);
}

// The scramble undone twist by twist, the last scramble twist first.
static void unscramble(int count)
{
    const LevelDef_t* lv = &kLevels[gGame.level];
    for (int i = 0; i < count; i++) {
        twist(lv->scramble[lv->scrambleLen - 1 - i] ^ TWIST_INVERSE_BIT);
        ticks(DEMO_TWIST_GAP);
    }
}

int main(int argc, char** argv)
{
    const std::string app = (argc > 1) ? argv[1] : "..";
    TestBegin();
    shotInit();
    if (!shotLoadPack(app) || !capOpen()) return 1;

    capShot("CHEMISTRY", "Twist the atoms into a molecule", CAPTURE_LEGEND_NONE, 30.0f, 24.0f, 0.15f);
    startGame();
    ticks(DEMO_HOLD);

    capShot("Level 1: H2", "One twist brings the two hydrogens together", 0, 30.0f, 24.0f);
    startLevel(DEMO_LEVEL_H2);
    unscramble(kLevels[DEMO_LEVEL_H2].scrambleLen);
    ticks(FORMED_TICKS + DEMO_HOLD);

    capShot("Level 3: water", "Bonds reach over the cube's edges", 1, 36.0f, 26.0f);
    startLevel(DEMO_LEVEL_WATER);
    unscramble(kLevels[DEMO_LEVEL_WATER].scrambleLen);
    ticks(FORMED_TICKS + DEMO_HOLD);

    capShot("Later: methane", "Carbon forms 4 bonds: all four neighbours of its screen", 2, 24.0f, 30.0f, 0.2f);
    startLevel(DEMO_LEVEL_METHANE);
    unscramble(kLevels[DEMO_LEVEL_METHANE].scrambleLen);
    ticks(FORMED_TICKS + DEMO_HOLD);

    capClose();
    return 0;
}
