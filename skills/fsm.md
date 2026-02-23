# Skill: Scaffold WowCube Game & FSM

**Role:** You are an expert WowCube C++ Developer. Your task is to initialize a new game header file using a Finite State Machine (FSM) architecture.

## Execution Steps:
1. **Read Core Rules:** Silently review `docs/reference_examples.md` to understand WowCube's header-only constraints, the `TL` macro, and the 1-based index object pool.
2. **Use Template:** Start with the structure from `templates/base_app.h`.
3. **Define States:** Create an FSM enum (e.g., `GameState_t` with `INIT`, `PLAY`, `WIN`, `LOSE`).
4. **Build Global Container:** - Create a `struct Game_t` containing the current state and core game variables.
   - Instantiate it globally using the `TL` macro: `TL Game_t gGame;`.
5. **Implement Logic Router:** Write a `static void gameProcess(Game_t* game, bool twisted)` function containing a `switch` statement for routing states.
6. **Wire Lifecycle:**
   - In `on_init()`: Call `OCT_restart`, set `OCT_viewports_layout`, and set the initial FSM state.
   - In `on_tick()`: Call `gameProcess(&gGame, false);`.

## Constraints & Anti-Patterns:
- **NO SPAGHETTI CODE:** Do not write game logic directly inside `on_tick()`. All logic must be handled inside state-specific functions called by `gameProcess`.
- **NO ZERO INDEX:** If you need to spawn or iterate objects, ALWAYS start from index 1. `Objects[0]` is reserved by the engine.
