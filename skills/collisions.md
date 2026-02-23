# Skill: Implement Collision & Interaction Logic

**Role:** You are an expert WowCube С/C++ Developer. Your task is to implement interaction logic between game entities (e.g., bullets hitting enemies or fish eating food).

## Execution Steps:
1. **Define Hitboxes:** Add hitbox data to `appObject_t` (e.g., `float radius` or `struct { float w, h; } rect`).
2. **Implement Checkers:**
   - For circular collision: Use the distance-squared pattern from `app_aquarium.h`.
   - For rectangular collision: Use the `RectVsRect` AABB pattern from `app_space_Invaders_cubed_old.h`.
3. **Optimized Scan:** Inside `on_tick`, implement a nested loop to check collisions. 
   - **Important:** Start both loops from index 1.
   - **Optimization:** Skip dead objects or objects on different planes if the game logic allows.
4. **Handle Interaction:** Define a callback or state change (e.g., `obj->state = STATE_EXPLODING`) when a collision is detected.

## Code Reference Pattern:
```cpp
// AABB Collision
bool CheckCollision(appObject_t* a, appObject_t* b) {
    return (a->Tm.X < b->Tm.X + b->w && a->Tm.X + a->w > b->Tm.X &&
            a->Tm.Y < b->Tm.Y + b->h && a->Tm.Y + a->h > b->Tm.Y);
}