# Part 2 Implementation Plan — Autonomous orchestrator + tooling

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement `docs/superpowers/specs/2026-08-04-autonomous-orchestrator-design.md` — autonomous-by-default orchestrator, multi-provider image adapter, agent-authored placeholders, python `.oct` builder, repack command, auto patch-bump, animation guidelines.

**Branch:** `part2-autonomous-orchestrator` (off merged main). PR at the end; NO merge without owner review.

**Architecture:** W1 tooling first (code+tests), W2 docs second (they reference W1 commands), E2E gate before the PR. The spec is the authority — every task below implements a numbered spec section; when in doubt read the spec file in this repo.

**Testing:** `$env:PYTHONPATH='scripts'; python -m pytest tests/ -q` from repo root (baseline on this branch: 117 passed). TDD per task. No AI attribution in commits.

**Reference workspace:** `..\` holds `octavios\` (engine), `app_photoframe\`, `app_gbhotel\`, `app_paltest\`, `app_bdemo\` (real built apps for E2E), golden fixtures in `tests/golden/`.

---

### Task 1 (W1): Image provider adapter — spec §4

**Files:** rework `scripts/genimg.py` (keep the public `generate_image(prompt, out_path, size=..., cutout=...)` signature and `ImageGenError`); Create `scripts/image_providers.py`; Test `tests/test_image_providers.py`.

- [ ] Resolution chain exactly as spec §4: `OPENROUTER_API_KEY` env → `IMAGE_API` env (JSON or bare key/URL) → `~\.wowcube\image_api.json` → None (caller decides: intake question / placeholders). A helper `resolve_provider() -> ProviderConfig | None` plus `save_provider(value) -> ProviderConfig` (persists a pasted key/URL to the config file; used by the orchestrator flow).
- [ ] Detection by pattern (spec table): `sk-or-` → openrouter; `sk-` → openai; `xai-` → xai; `AIza` → gemini; `http(s)://` → sd_a1111; else raise `UnknownProviderError` with the supported-forms message.
- [ ] Per-provider `txt2img` implementations behind one interface; openrouter = current code moved; openai/xai/gemini/sd_a1111 per their public APIs (non-streaming, timeouts `(15, 180)`, retry pattern copied from current genimg). `validate(config)` = cheapest possible authenticated call per provider; failures raise `ProviderValidationError`.
- [ ] Tests: detection table (all six patterns incl. unknown); resolution chain precedence with tmp config files + monkeypatched env; each provider's request assembly + response parsing against canned JSON (mock `requests`); save/load roundtrip; NO live network in tests.
- [ ] Commit: `feat(genimg): multi-provider image adapter - openrouter/openai/xai/gemini/local-sd, auto-detect + config chain`

### Task 2 (W1): Pure-python `.oct` builder — spec §11

**Files:** `scripts/pack_beta.py` (append), `tests/test_build_oct.py`.

- [ ] `build_oct(app_dir, code_bin, out_path, *, title, guid1, app_version, categories=0, colors=0) -> Path`: read `index.bin` + payload files (`art/packed/*.raw|*.pal`, `sound/assets/*.mp3`), assemble: 232-B header (magic CC 00 00 BB, FormatVersion=4, EngineVersion=2, Guid1, AppVersion, Categories, Title[80], Colors, BuildDateTime=0 for determinism), 84-B descriptor table (embed first 48 B of sprite payloads into desc.Bmp; Offset/Size per payload; ExtId=1? — mirror what the sim writes: verify against a sim-built .oct), payloads 4-byte aligned, ARM code tail, CodeOffset/CodeSize, AssetDescs/AssetCount, SoundDescs=AssetDescs & SoundCount=0, CRC32 over bytes 8..Size stored at offset 4. Read defines (`APP_TITLE`, `APP_GUID1`, `APP_VERSION`, `APP_CATEGORIES`, `APP_COLORS`) from `src/app.h` when kwargs omitted (regex like videopack's `read_app_guid`).
- [ ] Ground truth: `..\app_hulk\app_hulk\art\videopack.py` `build_pack()` (offsets/order) and a real sim-built `.oct` — byte-compare `build_oct` output against the sim-built `..\app_bdemo\app_bdemo.oct` (or rebuild one via build_device first): identical except BuildDateTime (sim stamps time; ours = 0) — assert equality after zeroing that field in both, or full equality if the sim copy has 0.
- [ ] Unit tests: synthesize a tiny app dir with pack_beta primitives (reuse test_beta_emit fixtures), build, parse back header fields + CRC + code tail; error paths (missing index.bin, missing payload file, missing code bin → ValueError).
- [ ] E2E check (manual step in report, not a pytest): `build_oct` over `..\app_paltest` equals sim-built modulo BuildDateTime.
- [ ] Commit: `feat(pack): pure-python .oct builder - sim no longer needed for packaging`

### Task 3 (W1): build_device switches to the python builder — spec §11

**Files:** `scripts/build_device.ps1`, `scripts/build_device.sh`.

- [ ] Replace the "launch sim 5 s to write .oct" step with `python -c` / a small CLI entry (`python scripts/pack_beta.py --build-oct --app-dir ... --code out/<app>.bin --out <app>.oct` — add that argparse entry to pack_beta or a thin `scripts/build_oct.py`). Keep the tail byte-verification exactly as is. MSVC/sim is no longer required by this script — remove that prerequisite check if present; keep ARM toolchain checks.
- [ ] Update the script's .oct-overwrite warning: the sim still overwrites `<app>.oct` on launch, so the note stays but reworded (delivery no longer depends on the sim; re-run this script after sim sessions).
- [ ] Validate: run against `..\app_gbhotel` (has out/*.bin already) → byte-identical result to Task 2's builder; syntax checks (PS parser, bash -n).
- [ ] Commit: `feat(boilerplate): device packaging via python build_oct, simulator now optional`

### Task 4 (W1): auto patch-bump + repack command — spec §9, §10

**Files:** Create `scripts/repack_app.py` (single cross-platform entry; ps1/sh not needed — document `python scripts/repack_app.py`); modify `scripts/build_device.ps1/.sh` only if trivial; Test `tests/test_repack_app.py`.

- [ ] `bump_patch(app_h_path) -> int`: parse `#define APP_VERSION <int>`, +1, rewrite preserving the line's comment tail; returns new version. Never touches minor/major (they're just higher digits of the same int — document that +1 semantics only).
- [ ] `repack_app.py --app-dir <dir> [--manifest auto] [--icon auto] [--skip-device]`: (1) detect the canonical pack invocation from disk — manifest at `plans/*_assets.json` (single match) → include `--manifest`; `art/icon.png` exists → `--icon`; exported PNGs present → keep `--build-palette` only when palette sprites exist in the manifest (or unconditionally — harmless with the loud-failure fix); (2) run pack.py with `--beta-app-dir`; (3) `bump_patch` on `src/app.h`; (4) unless `--skip-device`: ARM cmake build (reuse build_device logic or invoke the script) + python `build_oct` + tail verify; (5) print the `.oct` path + new version. Exit non-zero on any stage failure.
- [ ] Tests: bump_patch parsing/rewrite (with comment, without, missing define → error); invocation detection matrix with tmp app dirs (mock the subprocess calls, assert assembled command); `--skip-device` path end-to-end on a tiny fixture app (real pack, no ARM).
- [ ] Manual validation in report: `python scripts/repack_app.py --app-dir ..\app_gbhotel` runs the full cycle (version 102→103, verified .oct).
- [ ] Commit: `feat(tools): repack_app one-command cycle with automatic patch bump`

### Task 5 (W1): manifest animation numbering both schemes — spec §12

**Files:** `scripts/manifest_schema.py`, `scripts/gen_sprites.py` (`_derived_group`), `tests/test_manifest_schema.py`.

- [ ] `_derived_group` (and any manifest-side `_NN` logic) accepts 2- AND 3-digit suffixes; wherever the validator enforces zero-based frame groups, accept any contiguous run starting at 0 or 1 (mirror pack_beta's `_seq_frame_groups` semantics — read it first). Note: `gen_placeholders.py` was dropped in PR #25 — if that PR isn't merged yet, cherry-pick `c5ace1c` from branch `drop-gen-placeholders` into this branch FIRST (check `git log origin/main` before deciding).
- [ ] Tests: `hero_00/01`, `boom_001..003` both group and validate; gap (`_01,_03`) rejected; `_05`-only stays standalone.
- [ ] Commit: `feat(manifest): accept zero- and one-based animation frame groups`

### Task 6 (W2): orchestrator autonomy rewrite — spec §2, §3, §6, §7, §8

**Files:** `skills/cube_orchestrator/SKILL.md` (major rewrite of Mode Detection / checkpoints / YOLO section).

- [ ] Replace the "Run mode" paragraph + `## YOLO Mode` section with `## Run Modes` implementing spec §2 exactly: autonomous DEFAULT (start line verbatim from the spec, in Russian, no waiting), stepwise opt-in (triggers list), `YOLO` token compat (skips the two questions; the old activation-hard-rule + risk-confirmation blocks are deleted).
- [ ] Rewrite every checkpoint clause: stage-boundary checkpoint and per-prompt checkpoint texts get "stepwise mode only" framing; autonomous mode = re-run stage detection and continue + emit a one-way progress line (spec §7). Mod-mode mini-plan: auto-approved in autonomous.
- [ ] Intake section (spec §3): the two allowed questions with exact behavior (concept question wording; key question → WAIT; "не знаю" → placeholder path + final-report line; pasted key → `save_provider`, validated, §4 flow). Reference `scripts/image_providers.py` resolution order.
- [ ] Failure policy (spec §6): degrade-never-abort, foundational failure → one re-scope pass; floor = simplest playable loop; cuts listed in the final report.
- [ ] Hype normalization (spec §8) as a short hard rule near Mode Detection.
- [ ] Final report template (spec §7): .oct path, load instruction, cuts, placeholder note.
- [ ] Grep the file afterwards: no leftover "HARD ACTIVATION RULE", no confirmation-gate text, no contradiction with the new default (e.g. "MANDATORY between every stage" headers must be qualified).
- [ ] Commit: `docs(orchestrator): autonomous-by-default run modes, two-question intake, degrade-never-abort`

### Task 7 (W2): asset-builder — placeholders + provider docs — spec §4, §5

**Files:** `skills/cube_asset-builder/SKILL.md`.

- [ ] Replace OPENROUTER-only prerequisite with the provider chain (env → `IMAGE_API` → `~\.wowcube\image_api.json` → ask once → placeholders); supported providers table incl. local SD URL; key persisted via `save_provider`.
- [ ] New "Placeholder art (no image provider)" section per spec §5: the agent authors each sprite itself (own judgment, e.g. ad-hoc Pillow code), pinned requirements (every manifest sprite, exact size, correct alpha, distinct silhouettes, same downstream path). Remove any leftover references to the deleted `gen_placeholders.py` (check `Path A/Path B` texts and error tables).
- [ ] Commit: `docs(asset-builder): provider chain + agent-authored placeholder art`

### Task 8 (W2): animation guidelines sweep — spec §13

**Files:** `skills/cube_game-designer/SKILL.md`, `skills/technical_prompter/SKILL.md`, `skills/cube_orchestrator/SKILL.md`, `skills/cube_verifier/SKILL.md`.

- [ ] Add the owner's animation rules where each skill talks about animation/sprites: 20 fps hardware cap; ≤5 s default clip guideline (longer technically fine — only app size); prefer tier-1 animations; fullsize = short & careful, frametime >70 ms = bad sign; tier-3 (full-color) animations ONLY on explicit user request + "handle VERY carefully" warning; ONE animated picture per physical module (explain the module geometry briefly: a face's four screens live on four different modules; adjacent faces share two). Designer validates placement; verifier checks it (new checklist row).
- [ ] Commit: `docs: animation guidelines - 20fps cap, 5s default, tier preferences, one-anim-per-module`

### Task 9 (W2): boilerplate/docs alignment — spec §9, §10, §11

**Files:** `skills/wowcube-boilerplate/SKILL.md`, `README.md`, `docs/pipeline-flow.md`.

- [ ] Boilerplate: device packaging now python-built (sim optional, MSVC needed only for play-testing); repack command documented (`python scripts/repack_app.py --app-dir ...`); auto patch-bump rule (§9) stated where Stage 5 and Mod repack are described; the .oct-overwrite gotcha reworded (delivery path immune now).
- [ ] README/pipeline-flow: autonomous default mentioned in the overview; provider chain one-liner; repack command in the tool list.
- [ ] Commit: `docs(boilerplate+readme): python packaging, repack command, auto version bump`

### Task 10: E2E gate + PR — spec §15

- [ ] E2E-1 (no key): in a scratch dir under `..\`, simulate the business flow with tooling only: manifest with a few palette + one full-color sprite, NO image config visible (isolate env), agent-drawn placeholder PNGs (author them ad hoc), pack, `repack_app.py --skip-device`… then full device build via new build_device → verified `.oct` built by python. Confirm version bumped, report lines sane.
- [ ] E2E-2 (with key): if `OPENROUTER_API_KEY` is present in the environment, run one real single-sprite generation through the new adapter (openrouter path) to prove the refactor didn't break live generation; otherwise mark SKIPPED with reason.
- [ ] Full suite green; `git log` clean of attribution; push branch; open PR to main via GitHub API (title `Part 2: autonomous-by-default orchestrator + tooling`, body summarizing spec sections and testing; NO attribution footer). Do NOT merge.
- [ ] Report PR URL.

---

## Review discipline

Same as part 1: per-task spec review (verify against this plan + the spec file), quality review for W1 code tasks (W2 doc tasks: spec review only, quality folded in), fix loops until green. Final whole-branch review before the PR.
