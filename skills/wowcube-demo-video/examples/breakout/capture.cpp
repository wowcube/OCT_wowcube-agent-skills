// Breakout's demo capture -- an EXAMPLE of a game's tests/capture.cpp on the skill's capture.h, sprite
// mode. The real rules and render.h run headless, the robot (bot.h) at the controls; a script plays the
// title, the first round with its hints, a round of each stage, a clear, the selector and a game over.
//
//   capture_demo.sh [path-to-engine]    -> docs/demo/frames.jsonl
//
// What is the game's own here: the robot, the session (levelEnter, dropCapsule...), the captions.
// What every capture has: the includes, TestBegin, tick() = input -> on_tick -> capFrame.

#include "oct_test_shim.h"

#define MINIMP3_IMPLEMENTATION
#include "oct.h"

#include "oct_test.h"

#include "capture.h"                    // before app.h: its RENDER_LABEL_HOOK reaches render.h

#define ATTR_RODATA_IN_TCM
#include "app.h"

#include "bot.h"

void TestBegin()
{
    Debug = new simDebug();
    Debug->Init("log_capture.txt");
    SET.TimeZero = SIM_now_ms();
    OCT_SHIM_init();
}

static Bot_t gBot;

// A tick of the game as the engine runs it, the robot at the controls when `play`.
static void tick(bool play = true)
{
    if (play) botTick(&gBot, &gGame);
    on_tick();                                                          // the engine's tick: the game, the render
    capFrame();
}

static void ticks(int n, bool play = true)
{
    for (int i = 0; i < n; i++) tick(play);
}

// A pat on `plane`, as the engine reports it.
static void pat(int plane, bool twice = false)
{
    vars.pat = true;
    vars.patDouble = twice;
    vars.patPlane = plane;
}

// Breakout's twist is a command (start, pause), not a turn of the field: nothing to animate.
static void twist(void)
{
    vars.twisted = true;
    vars.twistSettle = TWIST_SETTLE_TICKS;
}

// A round from the selector: READY, the front patted, the serve launched.
static void playRound(int level, int readyTicks, int serveTicks)
{
    runReset(&gGame.run);
    gGame.run.score = (uint32_t)level * 7350u;
    levelEnter(&gGame, level, SOURCE_SELECT);
    ticks(readyTicks, false);
    pat(OCT_PLANE_FRONT);
    ticks(serveTicks, false);
    pat(OCT_PLANE_FRONT);
    tick();
}

static void dropCapsule(Capsule_t kind)
{
    Level_t* lv = &gGame.level;
    int8_t face;
    int32_t x;
    fieldSegToFace(&lv->field, lv->paddle.pos, &face, &x);
    lv->drop = Drop_t{ true, (uint8_t)kind, face, x, PX(60) };
}

static void capture(void)
{
    EXPECT(capOpen(), "cannot write the capture");
    if (!gCap.out) return;

    botGravityLevel(OCT_PLANE_TOP);
    OctMem = (int*)gSprites, OctCap = SPRITES_CAP, OctStride = (int)sizeof(octSprite_t) / 4, OCT_clear();
    OCT_ANIM_restart();
    OCT_viewports_layout(SCHEME_CUBE, GAP, GAP);
    memset(&vars, 0, sizeof(vars));
    vars.front = PLANE_NONE;
    memset(&gGame, 0, sizeof(gGame));
    runReset(&gGame.run);
    renderInit();
    botInit(&gBot, 20261027u);
    gGame.highScore = 48210;
    for (int i = 0; i < 6; i++) gGame.levelBest[i] = 2400u + 610u * (uint32_t)i;
    gGame.flags = SAVE_FLAG_PLAYED;
    gGame.lastLevel = 0;
    startShow(&gGame);

    capShot("BREAKOUT", "The field grows round by round: front, the ring, the roof", 2, 30.0f, 24.0f, 0.15f);
    ticks(50, false);

    // a fresh run at round 1: READY, the front patted, the hints, the launch
    gGame.levelBest[0] = 0;
    capShot("Twist to start", "Round 1 is set up around the face you pat", 2, 37.5f, 24.0f);
    twist();
    ticks(40, false);
    capShot("Pat the face in front of you", "It becomes the front: the paddle rolls along its bottom line", 1, 37.5f, 24.0f);
    pat(OCT_PLANE_FRONT);
    ticks(36, false);
    capShot("Tilt to roll the paddle", "It rolls downhill: tilt left, tilt right", 0, 37.5f, 24.0f);
    pat(OCT_PLANE_FRONT);
    ticks(120);
    capShot("Capsules", "L laser: pat to fire. E expand, D three balls, C catch, S slow, B break, P life", 4, 37.5f, 24.0f);
    dropCapsule(CAP_LASER);
    ticks(130);

    capShot("Stage 2: around the corner", "Rounds 5-8 play on the front and the right face", 0, 45.0f, 22.0f);
    playRound(4, 18, 10);
    ticks(200);

    capShot("Stage 4: the whole ring", "One paddle rolls round all four side faces", 4, 30.0f, 22.0f, 0.9f);
    playRound(12, 14, 8);
    dropCapsule(CAP_DISRUPT);
    ticks(260);

    capShot("Stage 5: the roof", "The top face joins in: over it and down another face", 0, 20.0f, 38.0f, 0.7f);
    playRound(16, 14, 8);
    dropCapsule(CAP_EXPAND);
    ticks(260);

    capShot("Round clear", "Twist: the next round. Double pat: the selector", 2, 30.0f, 24.0f);
    levelWon(&gGame, false);
    ticks(56, false);

    capShot("Select a round", "Tilt to float the frame, double pat to play. A face per stage", 3, 30.0f, 30.0f, 0.4f);
    pat(OCT_PLANE_TOP, true);
    ticks(30, false);
    botGravityTilt(OCT_PLANE_TOP, -0.45f, 0.0f);
    ticks(40, false);
    botGravityTilt(OCT_PLANE_TOP, 0.0f, 0.5f);
    ticks(30, false);
    botGravityLevel(OCT_PLANE_TOP);
    ticks(20, false);

    capShot("Game over", "Twist: try the round again. Saves keep the best of every round", 2, 30.0f, 24.0f);
    playRound(8, 6, 4);
    gGame.run.lives = 1;
    memset(gGame.level.balls, 0, sizeof(gGame.level.balls));
    ticks(60, false);

    capClose();
}

TEST_MAIN(
    RUN(capture);
)
