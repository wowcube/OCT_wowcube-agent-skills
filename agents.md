# WowCube Universal Agent Instructions

This document defines the core standards for AI agents developing games on the WowCube platform.

## 1. Architectural Mandates
- **Header-Only:** All C++ implementation must reside in `.h` files. Never create `.c` or `.cpp` files.
- **State Isolation:** All global variables MUST use the `TL` (Thread Local) macro to ensure they are correctly handled by the system.
- **Memory Management:** Use the pre-allocated `Objects[OBJECTS_CAP]` pool. Start iterating from index 1 (Index 0 is reserved).

## 2. Required WASM Exports
Every game must implement these exact functions to interface with the WowCube OS:
- `on_init()`: Initialize the object pool with `OCT_restart` and layout with `OCT_viewports_layout`.
- `on_tick()`: Primary game loop for logic, physics, and frame updates.
- `on_twisted(int32_t twid, ...)`: Vital for gameplay. Must handle topology changes. Always ignore half-twists (`twid >= OCT_TWIST_HALF`).
- `on_tap(int32_t tapid)`: Handle touch events on specific cube planes.
- `on_pretwisted(int32_t twid)`: Standard stub required by the compiler.

## 3. Object & Physics Patterns
- **Transforms:** Manipulate objects via the `Tm` (Transform) field using `OCT_TM_walk`, `OCT_TM_lerp`, or `OCT_TM_twist`.
- **Validation:** Always verify object existence in loops using `if (Objects[i].Idx == i)`.
- **Collision:** Implement manual bounding box (RectVsRect) or distance-based checks as seen in reference games.