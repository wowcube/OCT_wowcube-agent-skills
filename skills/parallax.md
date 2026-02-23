# Skill: Sensor-Driven Physics (Gravity & Parallax)

**Role:** You are an expert WowCube С/C++ Developer. Your task is to implement game mechanics or visual effects driven by the built-in accelerometer.

## Execution Steps:
1. **Plane Awareness:** Always retrieve gravity vectors based on the *current* plane of the object. Use `obj->Tm.Plane` as the argument.
2. **Read Sensors:** Use `OCT_TM_gravity_x(plane)` and `OCT_TM_gravity_y(plane)` to get normalized tilt values (-1.0 to 1.0).
3. **Apply Physics:** - For **Gravity Movement**: Update `Tm.X` and `Tm.Y` by adding `gravity * sensitivity`.
   - For **Parallax**: Calculate offset from a base "idle" position: `obj->Tm.X = obj->baseX + (maxShift * gx)`.
4. **Boundary Control:** Always call `OCT_TM_wrap(&obj->Tm)` after sensor-based movement to ensure objects don't get stuck at screen edges.

## Code Reference Pattern:
```cpp
//
void ApplyGravity(appObject_t* obj, float power) {
    float gx = OCT_TM_gravity_x(obj->Tm.Plane);
    float gy = OCT_TM_gravity_y(obj->Tm.Plane);
    
    obj->Tm.X += gx * power;
    obj->Tm.Y += gy * power;
    
    OCT_TM_wrap(&obj->Tm); // Essential for cross-plane movement
}