# Skill: Implement Twist Topology

**Role:** You are an expert WowCube С/C++ Developer. Your task is to implement hardware twist logic so objects move correctly across the cube's faces when the user physically twists the device.

## Execution Steps:
1. **Locate Hook:** Find the `WASM_EXPORT void on_twisted(int32_t twid, uint32_t disconnected_ms)` function.
2. **Filter Twists (CRITICAL):** Add this exact guard clause at the top of the function to ignore non-functional half-twists:
   `if (twid >= OCT_TWIST_HALF) return;`
3. **Update Geometry:** Write a loop to apply `OCT_TM_twist` to all active objects.
   ```cpp
   for (int i = 1; i < OBJECTS_CAP; i++) {
       if (Objects[i].Idx == i) {
           OCT_TM_twist(&Objects[i].Tm, twid);
       }
   }