# Changelog

## 2.2.0 — 2026-10-29

The pipeline brought up to **octavios dev (609d5ae, 2026-10-21)**, so agents work from the short references in this
repo instead of reading the SDK sources. Built from a real game (Shotgun Princess) and checked end to end on a second
one made only from these skills (Orb Catch). PR #31; includes the branches `part3-python-parity` (with
`part2-autonomous-orchestrator`), `updated-template` (with `separate-yolo`) and `mcp-server`, merged with their history.

### Added

- **`cube_art-director`** — a new skill for artists (also Stage 3's art engine): a style bible and approved anchors
  from the artist's references, generation with Codex on the ChatGPT subscription, a measured style lock (palette,
  light range, saturation, outline), set consistency (shared scale, colour lock), strict QA, an HTML review page with
  OK/Fix and feedback import, panoramas drawn once and cut per screen, an `@post` processing hook, a `qa/all.png` sheet.
- **`wowcube-html-prototype`** and **`wowcube-demo-video`** (author: Alex Poshivalov, from the Confluence AI Knowledge
  Base; local changes listed in each `SOURCE.md`) — a playable browser prototype of the mechanic as an optional
  designer Step 5, and demo videos in the team's 1920x1080 format.
- **`templates/app_ai_template/API.md`** — the engine reference agents read: limits with engine `file:line`, art
  tiers, minimum SDK, measured facts and pitfalls.
- **`scripts/sound_kit.py`** — CC0 sound recipes (layer, master, encode), a seamless music-loop finder, engine mp3,
  and a licence scan of the downloaded archives (exit 1 unless everything is CC0).
- **`tools/sim_headless`** — the dev Windows simulator patched to run hidden and silent: 24-screen frame dumps, the
  MCP control socket, a seam check (`seams.py`), a per-run log, `stop.ps1` (stops only its own process).
- **`tools/cube_upload`** — windowless Bluetooth upload of a `.oct` to the user's cube, on request.
- Orchestrator references: `RUN_MODES`, `STAGE3_ASSETS`, `AGENT_BRIEFS`, `VISUAL_GATE`, `DELIVERY`, `AGENT_SAFETY`
  (every incident of the build sessions is a rule), `SIM_MCP`; designer `GAME_FEEL`; asset-builder `ART`, `SOUND`, `PACK`.
- `build_pipeline.py validate` and `pack-status`; `pack_beta.py --verify-oct`.

### Changed

- **Template** rewritten for the dev app layout: `src/app_metadata.h` (`OCT_APP_SEMVER`, random `APP_GUID1`),
  `src/app_save.h`, demos for the 6-voice mixer and music loop, saves, tint and tap source. Builds for ARM with
  `-Wall -Werror` in every configuration.
- **Orchestrator** rewritten: autonomous by default with one creative stop (style frame + sound list), a mandatory
  visual gate on hidden 24-screen frames after every coder and fixer run, the Playtest Agent over MCP, re-check rounds
  after a fix, no open major at a pass, a budget per prompt. YOLO keeps a short risk confirmation.
- Designer, technical prompter, asset builder, boilerplate and verifier rewritten for the dev SDK.
- **Stage 5** builds with the official `octpack-build` (python builder as fallback, with SaveSize), verification is
  mandatory, octpacker's environment lives in `<ws>/.uv_octpack_venv`, never inside octavios.
- **Paid image APIs need an explicit user opt-in** in every mode (`WOWCUBE_ALLOW_PAID_IMAGES=1` / `--allow-paid`);
  without Codex the pipeline draws placeholders. Codex must be logged in with ChatGPT and never sees an API key from
  the environment. A local Stable Diffusion server needs no opt-in.
- The pack ships exactly the manifest's sounds; asset names up to 23 characters; no sound length cap.
- `check_env` is the one environment check (SDK incl. the 609d5ae import set, toolchain, Python 3.11+).

### Fixed

- **Screen-filling art at ±119.5, not ±120** (`QUAD_FILL`): at ±120 a 2-px background cross showed on every face.
- Palette FULLSIZE sprites and the palette icon get pivot 119.5; a FULLSIZE sprite without a `~pivot` marker gets
  the zoom-1 own-rect pivot (octpack's rule); RAW565 pivots.
- Rows over 255 bytes raise instead of corrupting the sprite; repack keeps rate and refreshes flags and pivots (also
  for a resized sprite); BOM manifests; case-insensitive PSD / `!pack.txt` lookup; `packbat` quoted `set` and
  `%~dp0`; `APP_TITLE` C escapes; hidden `~pivot` layers; `!rate` clamped; no stale ids header after a failed pack.
- Saves: a record of an unknown version is kept, never overwritten; the skeleton saves the real record.
- `appTapQuad` no longer reports screen 0 for every TOP tap on fw-0.100.0.
- `playfieldPlane()` uses `topWithHysteresis()`, which switches with the engine's `face_up` latch.
- Hidden-sim tools: a crash always fails a run; unsafe `-WorkDir` refused; non-ASCII paths; PowerShell 5.1; X11 on
  Wayland; `mcp.ps1` bare commands.
- Template font page names; the template's demo sounds no longer ship in games.

### Documented (measured on the hidden simulator)

- Fonts are packed x2 by both packers: text is twice the `.fnt` size, and `\n` steps only 1x the line height.
- `OCT_TM_top_side()` switches about 12° before the `face_up` latch; `UP_TOWARD` / `uprightAround()` orient the faces
  around the playfield.

### Removed

- `skills/cube_orchestrator/YOLO.md` (folded into `RUN_MODES.md`); old plans and specs moved to `docs/history`.

### Known

- octavios dev's stock Windows simulator does not compile with MSVC (`engine/oct_mp3.h`); our tools patch their
  own copy.
- Linux paths (hidden simulator under xvfb, upload via spptest) are documented but not verified.
- No adapter yet for PSD-authored art through octpacker.
