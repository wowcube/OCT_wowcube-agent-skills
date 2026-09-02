# OctaviOS API

Every call below goes through the app-facing interface: `oct_api.h` in the simulator, the `OCT_APP_IMPORTS` table (`oct_app_module.h`) in the ARM module, constants from `oct_shared.h` / `oct_consts.h`. Tap any face to cycle to the next demo.

## Summary

| Demo | API | What it does |
|---|---|---|
| all | `on_init` | Called once at startup to set up the scene. |
| all | `on_tick` | Called every tick for game logic, animation and physics. |
| all | `on_pretwisted` | Fires when a ring physically starts turning; the argument is the plane index, not a twist id. |
| all | `on_twisted` | Fires when a twist completes with the twist id and the disconnection time. |
| all | `on_tap` | Fires on a face tap with the plane index and the tap-series counter. |
| all | `on_shake` | Must exist for the ARM module to link; the engine currently runs the system go-home instead. |
| all | `on_proc_draw` | Draws a `PROCEDURAL_CUSTOM` sprite into a display back buffer; bound on the cube only under `APP_HAS_PROC_DRAW`. |
| 0 | `OCT_add` | Adds a sprite to the scene and returns its index in `gObjects`. |
| 0 | `OCT_del` | Deletes a sprite together with its child sprites and any tweens targeting it. |
| 0 | `OCT_random` | Random integer in a half-open range. |
| 0 | `SND_getAssetId` | Resolves a sound file name to its asset id. |
| 0 | `SND_play` | Plays a sound asset at a volume 0..100. |
| 0 | `OCT_TM_quad` | Returns the quad id (0..23) a transform sits on. |
| 0 | `OCT_TM_move` | Offsets a transform inside its plane without cross-plane handling. |
| 0 | `OCT_TM_change_plane` | Low-level move of a transform to another plane, adjusting coordinates and angle. |
| 0 | `XSIGN` / `YSIGN` | Engine tables with the coordinate signs of the four local quads. |
| 1 | `OCT_twist_sprites` | Applies a virtual twist to every twistable sprite. |
| 2 | `OCT_TM_walk` | Walks a transform along a direction angle, crossing plane edges automatically; the preferred way to move. |
| 2 | `OCT_TM_copy` | Copies a full transform. |
| 2 | `OCT_TM_lerp` | Interpolates between two transforms, handling cross-plane cases. |
| 3 | `OCT_sequence` | Sets a sprite frame sequence and its restart mode. |
| 4 | `OCT_add_label` | Adds a text label with a font and an alignment. |
| 4 | `OCT_label_set` | Sets the label text, rebuilding one child glyph sprite per character. |
| 5 | `OCT_BMP_info` | Fills `octBmpInfo_t` (name, size, pivot, bounding box) for any bitmap id. |
| 5 | `OCT_text` | Prints a debug line on screen when `OCT_DEV_TEXT` is on. |
| 5 | `OCT_F_INT` / `OCT_F_FRAC` | Template macros to print a float as `%d.%03d` since `%f` is unavailable on ARM. |
| 6 | `OCT_TM_set` | Teleports a transform to a position, angle and plane. |
| 8 | `OCT_TWISTS` | Table of the 12 full twists with their disk quads, ring quads, ring mask and impulses. |
| 8 | `OCT_TWIST_HALF` | Offset of half-twist ids; subtract it to index `OCT_TWISTS`. |
| 9 | `OCT_TM_sin` / `OCT_TM_cos` | Table-driven sine and cosine for integer degrees. |
| 10 | `OCT_ANIM_tm` | Starts an engine-driven tween of a transform between two points with an easing function. |
| 10 | `OCT_ANIM_tm_tw` | Same tween, but its endpoints are carried along by physical twists. |
| 10 | `OCT_ANIM_on_half` | Reports that a tween passed its half-way point. |
| 10 | `OCT_ANIM_on_end` | Reports that a tween finished on this tick. |
| 10 | `OCT_ANIM_get_progress` | Returns the tween tick counter. |
| 10 | `OCT_ANIM_del` | Cancels a tween by index. |
| 10 | `FUNC_LINEAR` .. `FUNC_SPAWN` | Easing functions; `FUNC_QUAD`, `FUNC_JELLY`, `FUNC_SPAWN` are effects that return to the start point. |
| 11 | `OCT_TM_face_up` | System "up" direction for a plane, latched on the top face the same way notifications orient themselves. |
| 11 | `OCT_TM_acc_x/y/n` | Linear acceleration without gravity projected on a plane. |
| 11 | `OCT_TM_mixed_acc_x/y/n` | Raw accelerometer including gravity projected on a plane. |
| 11 | `OCT_TM_tap_x/y/n` | Direction of the current tap series projected on a plane. |
| 11 | `OCT_TM_arctan` | Integer-degree arctangent of a vector. |
| 11 | `OCT_TM_normalize_angle` | Wraps an angle into 0..360. |
| 11 | `OCT_lerp` | Blends two floats with a reversed weight, `t = 1` returns `from`. |
| 11 | `OCT_acc_visual_x/y/z` | Latest raw IMU sample as integers, for debugging. |
| 12 | `OCT_TM_wrap` | Moves a transform that went past the plane edge onto the adjacent plane. |
| 12 | `OCT_TM_adapt_dir` | Re-expresses a velocity vector when moving to another plane so motion stays straight. |
| 12 | `OCT_TM_adapt_angle` | Angle delta that keeps a heading unchanged across a plane change. |
| 12 | `OCT_disconnected_axis` | Axis of the ring that is physically turning right now. |
| 12 | `OCT_TM_twist` | Applies a full twist to one transform by hand. |
| 12 | `OCT_TM_twist_impulse` | Direction a twist pushes a quad, or 360 when the quad is not affected. |
| 13 | `PROCEDURAL_CIRCLE` | Soft-edged filled circle sprite with radius in `Param3` and color in `Data0`. |
| 13 | `OCT_label_embed` | Switches a label to the OS built-in font without glyph sprites. |
| 13 | `PROCEDURAL_CUSTOM` | Sprite drawn by the app itself in `on_proc_draw`, culled by `Zw` / `Zh`. |
| 14 | `OCT_cache_assets` | Pre-loads assets from SD into the RAM cache. |
| 14 | `OCT_get_brightness` | Reads the saved backlight level. |
| 14 | `OCT_set_brightness` | Sets the backlight, transient or persisted into settings. |
| 14 | `OCT_get_volume` | Reads the saved volume. |
| 14 | `OCT_set_volume_transient` | Sets the volume temporarily without touching the saved setting. |
| 14 | `OCT_scratch` | 32 KB of fast scratch RAM for temporary work within a tick. |
| 14 | `OCT_trace` | Prints a line to the host console instead of the screen. |
| 14 | `OCT_calendar_time` | Cube local time as a UNIX epoch with the time zone applied. |
| 14 | `OCT_BAT_level` | Cube battery percent, the most discharged cublet. |
| 14 | `OCT_BAT_level_local` | Battery percent of this cublet. |
| 14 | `OCT_first_run` | True for the whole session in which the onboarding pack was autostarted. |
| 14 | `OCT_fw_up_to_date` | The phone verdict on whether the firmware is current. |
| 14 | `OCT_screen_quad` | Scene quad shown on a display of this cublet; cube-only. |
| 14 | `OCT_app_exit` | Returns the cube to its home screen. |
| 14 | `OCT_sleep_now` | Puts the whole cube to sleep at once. |
| 15 | `OCT_CATALOG_scan_entries` | Number of catalog entries held in RAM. |
| 15 | `OCT_CATALOG_count` | Number of catalog entries. |
| 15 | `OCT_CATALOG_entry` | Fills `octEntryInfo_t` (GUID, type, name) for an entry. |
| 15 | `OCT_CATALOG_version` | Installed pack version with the semver scheme tag in the high byte. |
| 15 | `OCT_launch` | Starts another installed app. |
| 15 | `OCT_launch_from` | Starts another installed app with the screen spot where the transition wave begins. |
| 16 | `OCT_modify_viewport` | Re-aims one display at another plane of the scene. |
| 16 | `OCT_viewports_layout` | Resets the camera layout to the default cube scheme. |
| setup | `OCT_restart` | Reinitializes the sprite pool, clearing every object. |
| setup | `OCT_background` | Fills the whole cube with a solid RGB565 color. |
| setup | `OCT_dev_mode` | Enables engine debug overlays by flags. |
| setup | `OCT_TM_gravity_x/y/n` | Filtered gravity vector projected on a plane. |
| setup | `OCT_TM_top_side` / `OCT_TM_bottom_side` | Planes currently facing up and down. |
| setup | `OCT_1SEC_TICKS` / `OCT_DT` | Ticks per second and tick length in seconds. |
| defines | `APP_VERSION` | App version packed by `OCT_APP_SEMVER(major, minor, patch)`. |
| defines | `APP_GUID1` | Unique 64-bit id of the app. |
| defines | `APP_CATEGORIES` | `APP_CATEGORY_GAME` or `APP_CATEGORY_LAUNCHER` for a home-screen app. |

## Handlers (mandatory in every app)

| Handler | What it does |
|---|---|
| `on_init` | Called once at startup - set up the scene, viewports, dev mode. |
| `on_tick` | Called every tick (20 per second, `OCT_1SEC_TICKS`) - game logic, animation, physics. |
| `on_pretwisted(twid)` | Fires when a ring physically starts turning; `twid` is the PLANE index (0..5), the direction is only known in `on_twisted`. |
| `on_twisted(twid, disconnected_ms)` | Fires when a twist completes; `twid` 0..11 is a full twist, 12..23 a half twist. |
| `on_tap(tapid, count)` | Fires on a face tap; `tapid` is the plane, `count` is the position in a quick tap series. |
| `on_shake(shakeid)` | Symbol must exist for the ARM module to link; the engine currently runs the system go-home instead of routing shakes here. |
| `on_proc_draw(back, idx, x, y, angle, vid, reserved)` | Draws a `PROCEDURAL_CUSTOM` sprite into a display's half-resolution back buffer; bound on the cube only under `APP_HAS_PROC_DRAW`. |

## Demo 0 - sprites, sounds, quads

| API | What it does |
|---|---|
| `OCT_add` | Adds a sprite to the scene on a plane at (x, y) with an angle, optional frame animation; returns its index in `gObjects`. |
| `OCT_del` | Deletes a sprite together with its child sprites and any tweens targeting it. |
| `OCT_random` | Random integer in `[dmin; dmax)`. |
| `SND_getAssetId` | Resolves a sound file name to its asset id. |
| `SND_play` | Plays a sound asset at a volume 0..100. |
| `OCT_TM_quad` | Returns the quad id (0..23) a transform sits on. |
| `OCT_TM_move` | Offsets a transform inside its plane, no cross-plane handling. |
| `OCT_TM_change_plane` | Low-level move of a transform to another plane, adjusting coordinates and angle. |
| `XSIGN` / `YSIGN` | Engine tables with the coordinate signs of the four local quads. |

## Demo 1 - virtual twist

| API | What it does |
|---|---|
| `OCT_twist_sprites` | Applies a virtual twist (`TOP_CW`, `FRONT_CCW`, ...) to every twistable sprite. |

## Demo 2 - movement

| API | What it does |
|---|---|
| `OCT_TM_walk` | Preferred way to move: walks a transform along a direction angle, crossing plane edges automatically; returns the old plane. |
| `OCT_TM_copy` | Copies a full transform. |
| `OCT_TM_lerp` | Interpolates between two transforms by `t` in `[0; 1]`, handling cross-plane cases. |

## Demo 3 - frame animation

| API | What it does |
|---|---|
| `OCT_sequence` | Sets a sprite's frame sequence (from, to, ticks per frame) with a restart mode `OCT_SEQ_RESTART` / `OCT_SEQ_REVERSE` / `OCT_SEQ_REFRESH`. |
| `Paused` / `Loop` (sprite fields) | Sprite fields that pause or loop the frame animation. |

## Demo 4 - labels

| API | What it does |
|---|---|
| `OCT_add_label` | Adds a text label with a font (`FONT_1..3`) and alignment (`ALIGN_LEFT` / `ALIGN_CENTER` / `ALIGN_RIGHT`). |
| `OCT_label_set` | Sets the label text, rebuilding one child glyph sprite per character, `\n` starts a new line. |
| `Hidden` + `Parent` (sprite fields) | Hiding a label means hiding it and every child glyph (see `showLabel`). |

## Demo 5 - bitmap info

| API | What it does |
|---|---|
| `OCT_BMP_info` | Fills `octBmpInfo_t` (name, size, pivot, bounding box) for any bitmap id. |
| `OCT_text` | Prints a debug line on screen when `OCT_DEV_TEXT` is on; slot index or `-1` for log mode. |
| `OCT_F_INT` / `OCT_F_FRAC` | Template macros to print a float as `%d.%03d` since `%f` is not available on ARM. |

## Demo 6 - rings

| API | What it does |
|---|---|
| `OCT_TM_set` | Teleports a transform to a position, angle and plane in one call. |

## Demo 7 - transparency

| API | What it does |
|---|---|
| `Transp` (sprite field) | Sprite transparency 0 (opaque) .. `OCT_TRANSP_MAX` (invisible). |

## Demo 8 - twist table

| API | What it does |
|---|---|
| `OCT_TWISTS` | Constant table of the 12 full twists: disk quads, the two ring quad lists, ring mask and per-plane impulse. |
| `OCT_TWIST_HALF` | Offset of half-twist ids (12); subtract it to index `OCT_TWISTS`. |

## Demo 9 - parent and child

| API | What it does |
|---|---|
| `Parent` (sprite field) | Setting a sprite's `Parent` makes its transform local to the parent, composed by the engine at render time. |
| `OCT_TM_sin` / `OCT_TM_cos` | Table-driven sine and cosine for integer degrees. |

## Demo 10 - engine tweens

| API | What it does |
|---|---|
| `OCT_ANIM_tm` | Starts an engine-driven tween of a transform between two points with an easing function; the engine writes `Tm` every tick. |
| `OCT_ANIM_tm_tw` | Same, but the tween endpoints are carried along by physical twists. |
| `OCT_ANIM_on_half` / `OCT_ANIM_on_end` | Report that a tween passed its half-way point or finished on this tick. |
| `OCT_ANIM_get_progress` / `OCT_ANIM_del` | Read a tween's tick counter and cancel a tween by index. |
| `FUNC_LINEAR` .. `FUNC_SPAWN` | Easing functions; `FUNC_QUAD`, `FUNC_JELLY`, `FUNC_SPAWN` are effects that return to the start point. |

## Demo 11 - orientation and IMU

| API | What it does |
|---|---|
| `OCT_TM_face_up` | System "up" direction for a plane in degrees, latched on the top face the same way system notifications orient themselves. |
| `OCT_TM_acc_x/y/n` | Linear acceleration without gravity projected on a plane, for bumps and shakes. |
| `OCT_TM_mixed_acc_x/y/n` | Raw accelerometer including gravity projected on a plane. |
| `OCT_TM_tap_x/y/n` | Direction of the current tap series projected on a plane. |
| `OCT_TM_arctan` / `OCT_TM_normalize_angle` | Integer arctangent of a vector and wrapping of an angle into 0..360. |
| `OCT_lerp` | Blends two floats; note the reversed weight, `t = 1` returns `from`. |
| `OCT_acc_visual_x/y/z` | Latest raw IMU sample as integers, for debugging. |

## Demo 12 - twist-aware transforms

| API | What it does |
|---|---|
| `OCT_TM_wrap` | Moves a transform that went past the plane edge onto the adjacent plane. |
| `OCT_TM_adapt_dir` / `OCT_TM_adapt_angle` | Re-express a velocity vector or a heading when moving to another plane so motion stays straight. |
| `OCT_disconnected_axis` | Axis of the ring that is physically turning right now (`AXIS_X/Y/Z`, `AXIS_NONE`). |
| `OCT_TM_twist` | Applies a full twist to one transform by hand, for non-twistable sprites that should follow selectively. |
| `OCT_TM_twist_impulse` | Direction a twist pushes a quad's content, or 360 when the quad is not affected. |

## Demo 13 - procedural sprites

| API | What it does |
|---|---|
| `PROCEDURAL_CIRCLE` | Soft-edged filled circle sprite; radius in `Param3`, RGB565 color in `Data0`. |
| `OCT_label_embed` | Switches a label to the OS built-in font, no glyph sprites; color in `Data0`. |
| `PROCEDURAL_CUSTOM` + `on_proc_draw` | Sprite drawn by the app itself into the display's half-resolution back buffer; `Zw` / `Zh` are half-extents for culling. |

## Demo 14 - host services

| API | What it does |
|---|---|
| `OCT_cache_assets` | Pre-loads assets from SD into the RAM cache to avoid first-use hitches. |
| `OCT_get_brightness` / `OCT_set_brightness` | Read and set the backlight, `OCT_BRIGHTNESS_TRANSIENT` (reverted on exit) or `OCT_BRIGHTNESS_PERSIST` (settings app only). |
| `OCT_get_volume` / `OCT_set_volume_transient` | Read the volume and set it temporarily without touching the saved setting. |
| `OCT_scratch` | 32 KB of fast scratch RAM for temporary work within a tick. |
| `OCT_trace` | Prints a line to the host console instead of the screen. |
| `OCT_calendar_time` | Cube local time as a UNIX epoch with the time zone already applied. |
| `OCT_BAT_level` / `OCT_BAT_level_local` | Cube battery percent (most discharged cublet) and this cublet's own reading. |
| `OCT_first_run` / `OCT_fw_up_to_date` | First-boot session flag and the phone's verdict on the firmware. |
| `OCT_screen_quad` | Which scene quad this cublet's display shows; cube-only, absent in the simulator. |
| `OCT_app_exit` / `OCT_sleep_now` | Return to the home screen or put the whole cube to sleep at once. |

## Demo 15 - app catalog

| API | What it does |
|---|---|
| `OCT_CATALOG_scan_entries` / `OCT_CATALOG_count` / `OCT_CATALOG_entry` | Enumerate installed packs from the RAM catalog with GUID, type and name. |
| `OCT_CATALOG_version` | Installed pack version, semver in the low bytes with the scheme tag in the high byte. |
| `OCT_launch` / `OCT_launch_from` | Start another installed app, optionally from a screen spot where the transition wave begins. |

## Demo 16 - viewports

| API | What it does |
|---|---|
| `OCT_modify_viewport` | Re-aims one display at another plane of the scene, for mirrors and split views. |
| `OCT_viewports_layout` | Resets the camera layout to the default cube scheme with the given bezel widths. |

## Scene setup (`switchDemo`, `on_init`, `on_tick`)

| API | What it does |
|---|---|
| `OCT_restart` | Reinitializes the sprite pool, clearing every object. |
| `OCT_background` | Fills the whole cube with a solid RGB565 color. |
| `OCT_dev_mode` | Enables engine debug overlays by flags (`OCT_DEV_TEXT`, `OCT_DEV_STAT`, `OCT_DEV_FPS`, `OCT_DEV_QUAD_IDS`, `OCT_DEV_COLLIDERS`). |
| `OCT_TM_gravity_x/y/n` | Filtered gravity vector projected on a plane. |
| `OCT_TM_top_side` / `OCT_TM_bottom_side` | Plane currently facing up or down according to the accelerometer. |
| `OCT_1SEC_TICKS` / `OCT_DT` | Ticks per second and tick length in seconds. |

## App defines

| Define | What it does |
|---|---|
| `APP_VERSION` | App version packed by the engine macro `OCT_APP_SEMVER(major, minor, patch)`; the phone reads it as semver thanks to the scheme tag. |
| `APP_GUID1` | Unique 64-bit id of the app; generate it, never copy from another app. |
| `APP_CATEGORIES` | `APP_CATEGORY_GAME` for a plain app, `APP_CATEGORY_LAUNCHER` for an app that autoruns as the home screen. |
