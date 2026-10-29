#pragma once
// A robot player for the host tests and the demo capture (tests/logic_test.cpp, tests/capture.cpp):
// it plays the way a person would -- it tilts the cube to roll the paddle under the ball and pats. The
// tilt is the engine's gravity (Gf), the one input the rules read, so the rules run untouched.
//
// It aims where a ghost of the ball, flown through the walls and the bricks it would bounce off, will
// cross the paddle's line, and hits it off a random point of the paddle, so the rounds' angles vary.

#include <cmath>

#define BOT_TILT_MAX        0.75f       // the steepest tilt it uses, g
#define BOT_GAIN_POS        0.22f       // the speed it wants, per px of distance to the aim
#define BOT_LAUNCH_TICKS    12          // it pats the serve after this
#define BOT_FIRE_TICKS      8           // a laser shot every this many ticks
#define BOT_GHOST_STEPS     400         // ticks it flies the ghost before it gives up
#define BOT_AIM_SPREAD      0.7f        // of the paddle's half: where on it the ball is hit

typedef struct {
    uint32_t rng;
    float    aim;                       // -1..1 of the paddle's half
    uint32_t ticks;
    uint32_t livesLost;
    uint32_t capsules;
    uint8_t  lives;
    uint16_t hits;
    bool     drop;
} Bot_t;

static inline float botRand(Bot_t* b) {
    b->rng = b->rng * 1664525u + 1013904223u;
    return (float)(b->rng >> 8) / (float)(1u << 24);
}

static void botInit(Bot_t* b, uint32_t seed) {
    memset(b, 0, sizeof(*b));
    b->rng = seed ? seed : 1u;
    b->aim = (botRand(b) * 2.0f - 1.0f) * BOT_AIM_SPREAD;
}

static void botGravitySet(float x, float y, float z) {
    Gf[0] = x;
    Gf[1] = y;
    Gf[2] = z;
}

// The cube held level with `top` up.
static void botGravityLevel(int top) {
    botGravitySet(-OCT_N3D[top][0], -OCT_N3D[top][1], -OCT_N3D[top][2]);
}

// A tilt in the axes of `top` itself: gx along its +x, gy along its +y (the selector's frame).
static void botGravityTilt(int top, float gx, float gy) {
    const float c = sqrtf(fmaxf(0.0f, 1.0f - gx * gx - gy * gy));
    float v[3];
    for (int i = 0; i < 3; i++) v[i] = -OCT_N3D[top][i] * c + OCT_T3D[top][i] * gx + OCT_B3D[top][i] * gy;
    botGravitySet(v[0], v[1], v[2]);
}

// The +x of a field face in the cube's axes.
static void botFaceAxisX(const Field_t* f, int face, float v[3]) {
    const int p = f->plane[face];
    const float c = (float)cosDeg(f->angle[face]) / (float)TRIG_ONE, s = (float)sinDeg(f->angle[face]) / (float)TRIG_ONE;
    for (int i = 0; i < 3; i++) v[i] = c * OCT_T3D[p][i] + s * OCT_B3D[p][i];
}

// The cube tilted by `g` along the bottom line of a side face, the field's top up.
static void botGravityAlong(const Field_t* f, int face, float g) {
    float ax[3];
    botFaceAxisX(f, face, ax);
    const int top = f->plane[FIELD_TOP];
    const float c = sqrtf(fmaxf(0.0f, 1.0f - g * g));
    botGravitySet(-OCT_N3D[top][0] * c + ax[0] * g, -OCT_N3D[top][1] * c + ax[1] * g, -OCT_N3D[top][2] * c + ax[2] * g);
}

// A point of a field face in its plane's transform space, px.
static void botFieldToPlane(const Field_t* f, int face, int32_t x, int32_t y, float* px, float* py) {
    turnQuarters(&x, &y, f->angle[face] / DEG_QUARTER);
    *px = (float)x / (float)FX_ONE;
    *py = (float)y / (float)FX_ONE;
}

// The ghost meets the bricks as the ball would (play.h ballBricks), but breaks none.
static void botGhostBricks(const Level_t* lv, Ball_t* b, int32_t px, int32_t py) {
    const int32_t hx = PX(BRICK_W_PX / 2 + BALL_R_PX), hy = PX(BRICK_H_PX / 2 + BALL_R_PX);
    bool flipX = false, flipY = false;
    for (int r = 0; r < brickRows(b->face); r++) {
        const int32_t cy = brickRowY(r);
        if (iabs32(b->y - cy) >= hy) continue;
        for (int c = 0; c < BRICK_COLS; c++) {
            const int32_t cx = brickColX(c);
            if (iabs32(b->x - cx) >= hx || lv->bricks[b->face][r * BRICK_COLS + c].kind == BRICK_NONE) continue;
            const bool outX = iabs32(px - cx) >= hx, outY = iabs32(py - cy) >= hy;
            const bool sideX = (outX && !outY) || (outX && outY && (hx - iabs32(b->x - cx)) < (hy - iabs32(b->y - cy)));
            if (sideX) flipX |= ((px < cx) == (cosDeg(b->angle) > 0));
            else       flipY |= ((py < cy) == (sinDeg(b->angle) > 0));
        }
    }
    if (flipX) ballReflectX(b);
    if (flipY) ballReflectY(b);
    if (flipX || flipY) ballUnflatten(b);
}

// Where a ball will cross the paddle's line, along it: a ghost flown through the walls and the bricks.
// False if it does not get there within BOT_GHOST_STEPS ticks.
static bool botGhost(const Level_t* lv, const Ball_t* real, int32_t* at, int32_t* ticks) {
    Ball_t b = *real;
    const Field_t* f = &lv->field;
    const int32_t lim = PX(WALL_LIMIT_PX - BALL_R_PX), line = PX(PADDLE_TOP_PX + BALL_R_PX);
    for (int t = 0; t < BOT_GHOST_STEPS; t++) {
        const int32_t px = b.x, py = b.y;
        b.x += ballDx(b.speed, b.angle);
        b.y += ballDy(b.speed, b.angle);
        const int dir = fieldEdgeOut(b.x, b.y);
        if (dir >= 0) {
            if (f->edge[b.face][dir].kind != EDGE_OPEN) return false;
            fieldCrossEdge(f, &b.face, dir, &b.x, &b.y, &b.angle);
            continue;
        }
        const Edge_t* e = f->edge[b.face];
        if (e[DIR_RIGHT].kind == EDGE_WALL && b.x > lim && cosDeg(b.angle) > 0) { b.x = 2 * lim - b.x; ballReflectX(&b); }
        if (e[DIR_LEFT].kind == EDGE_WALL && b.x < -lim && cosDeg(b.angle) < 0) { b.x = -2 * lim - b.x; ballReflectX(&b); }
        if (e[DIR_UP].kind == EDGE_WALL && b.y > lim && sinDeg(b.angle) > 0) { b.y = 2 * lim - b.y; ballReflectY(&b); }
        botGhostBricks(lv, &b, px, py);
        if (faceIsSide(b.face) && py >= line && b.y < line) {
            *at = fieldSegOf(f, b.face, b.x);
            *ticks = t;
            return true;
        }
    }
    return false;
}

// One tick of play: the tilt it holds, and a pat if it wants one.
static void botTick(Bot_t* bot, Game_t* g) {
    Level_t* lv = &g->level;
    bot->ticks++;
    if (g->run.lives < bot->lives) bot->livesLost += bot->lives - g->run.lives;
    bot->lives = g->run.lives;
    if (bot->drop && !lv->drop.live && lv->state == LEVEL_PLAY) bot->capsules++;
    bot->drop = lv->drop.live;
    if (g->scene != SCENE_LEVEL || !lv->field.built) return;
    if (lv->state == LEVEL_SERVE && lv->stateTicks >= BOT_LAUNCH_TICKS) vars.pat = true, vars.patPlane = lv->field.plane[FIELD_FRONT];
    if (lv->state != LEVEL_PLAY && lv->state != LEVEL_SERVE) { botGravityLevel(lv->field.plane[FIELD_TOP]); return; }

    // the ball to meet: the soonest at the line
    int32_t aim = lv->paddle.pos;
    int32_t soonest = INT32_MAX;
    bool stuck = false;
    for (int i = 0; i < BALLS_MAX; i++) {
        const Ball_t* b = &lv->balls[i];
        if (!b->live) continue;
        stuck |= b->stuck;
        int32_t at, t;
        if (!b->stuck && botGhost(lv, b, &at, &t) && t < soonest) { soonest = t; aim = at; }
    }
    const int32_t half = paddleHalf(&lv->paddle);
    if (soonest != INT32_MAX) {
        aim -= (int32_t)(bot->aim * (float)half);
    } else if (lv->drop.live && faceIsSide(lv->drop.face)) {
        aim = fieldSegOf(&lv->field, lv->drop.face, lv->drop.x);    // nothing coming: the capsule
    }
    if (lv->speedHits != bot->hits) {                                 // a hit: another point of the paddle next
        bot->hits = lv->speedHits;
        bot->aim = (botRand(bot) * 2.0f - 1.0f) * BOT_AIM_SPREAD;
    }

    // the tilt that brings the paddle's speed to the one it wants
    const float err = (float)fieldSegDelta(&lv->field, aim, lv->paddle.pos) / (float)FX_ONE;
    float want = err * BOT_GAIN_POS * (float)FX_ONE;
    if (want > (float)PADDLE_SPEED_MAX) want = (float)PADDLE_SPEED_MAX;
    if (want < -(float)PADDLE_SPEED_MAX) want = -(float)PADDLE_SPEED_MAX;
    const float keep = (float)lv->paddle.vel * (float)(PCT - PADDLE_FRICTION_PCT) / (float)PCT;
    float tilt = (want - keep) / (float)PADDLE_ACCEL;
    if (tilt > BOT_TILT_MAX) tilt = BOT_TILT_MAX;
    if (tilt < -BOT_TILT_MAX) tilt = -BOT_TILT_MAX;
    if (fabsf(tilt) * (float)GRAV_ONE < (float)PADDLE_DEADZONE && fabsf(err) > 2.0f)
        tilt = (tilt < 0 ? -1.0f : 1.0f) * (float)(PADDLE_DEADZONE + 1) / (float)GRAV_ONE;
    botGravityAlong(&lv->field, paddleFace(&lv->field, &lv->paddle), tilt);

    if (lv->state == LEVEL_PLAY && ((lv->effect == CAP_LASER && bot->ticks % BOT_FIRE_TICKS == 0) || stuck))
        vars.pat = true, vars.patPlane = lv->field.plane[FIELD_FRONT];
}
