# YOLO Mode (Autonomous Run — opt-in)

> Reference file for `cube_orchestrator`. **Read and follow this file only when YOLO
> is actually activated** (see the Hard Activation Rule below). The default run mode
> is checkpointed — `SKILL.md` describes it in full and stands on its own.

**Default OFF.** YOLO is an explicit, opt-in override of every human checkpoint and approval in `SKILL.md`. It removes the human checkpoints only — it does **not** remove the correctness gates that decide whether the final `.oct` actually runs on the cube.

## Hard Activation Rule — the only way YOLO turns on

Activate YOLO **if and only if the literal token `YOLO` (case-insensitive) appears in the body of the user's current prompt.** Nothing else activates it:

- No paraphrase, synonym, or translation activates YOLO — "автономный режим", "no checkpoints, just build it", "фигачь до финального билда / .oct", "go autonomous", etc. do **NOT** count. Only the literal string `YOLO`.
- Never infer it from intent, tone, or context.
- Never carry it across turns or unrelated requests — the token must be present in the current prompt body. A prior prompt's `YOLO` does not keep the mode on.
- If the user clearly wants autonomy but did not write `YOLO`, do **not** enter YOLO; proceed with normal checkpoints (you may note that they can write `YOLO` to enable it).

When activated this way, it applies to both Build and Mod mode.

## Mandatory pre-activation double-check (risk disclosure + explicit confirmation)

Even when the literal `YOLO` token is present, **the orchestrator does NOT go autonomous immediately.** It MUST first stop, explain the risks in plain language, and get one explicit confirmation. This is the single allowed prompt between seeing `YOLO` and going silent — never skip it, never assume the answer.

Present the risks clearly (adapt wording, but cover all of these):

- **Result is not guaranteed.** The pipeline runs unattended; the final game may not match what you pictured, and YOLO won't stop to course-correct.
- **No per-stage verification by you.** Design, prompts, assets, and gameplay are auto-accepted at each boundary — without your eyes on each stage, the cumulative result can drift far from your expectations, and a wrong early decision propagates through everything downstream.
- **It can take a long time.** A full design → prompts → assets → implement → device-build run is long-running with no interaction in between.
- **It can burn a lot of tokens / cost.** Autonomous generation, multi-agent verification, and up-to-5 fix cycles per prompt consume significantly more tokens than a checkpointed run.
- **Rework risk.** If the outcome is off, you may have to redo or heavily mod the game afterward — possibly costing more total than running with checkpoints.

Then ask for an explicit go/no-go, e.g. *"YOLO means I run the whole pipeline unattended to the final `.oct` — no result guarantee, no per-stage review from you, it can take a while and burn a lot of tokens. Confirm you want YOLO, or I'll proceed with normal checkpoints."*

- Proceed into YOLO **only on a clear affirmative** ("yes", "да", "go", "confirm").
- On anything ambiguous, silence, or "no" → **do NOT enter YOLO**; fall back to the normal checkpointed flow.

Only after this confirmation do the One-time intake and the autonomous run begin.

When YOLO turns on, the orchestrator runs the **entire pipeline in one session** and does not prompt the user again until it delivers the final device package `app_<game>/app_<game>.oct`.

## One-time intake (gather BEFORE going autonomous)

A truly autonomous run still needs the few inputs that cannot be invented. Collect these once, up front, then go silent:

1. **Game concept** (Build mode, if not already given) — ask for the brief now (genre, core mechanic, vibe, length). YOLO does not run the designer's interview turn-by-turn; it takes the brief once and lets `cube_game-designer` produce the GDD from it.
2. **Asset source + key** (Stage 3) — default to **Path A (AI generation)**, the autonomous path, and obtain `OPENROUTER_API_KEY` now. Path B (self-supplied art) is inherently non-autonomous (it waits on human-made files); use it in YOLO only if complete assets are already on disk.

Then announce YOLO once ("YOLO ON — running design → prompts → assets → implement → device build autonomously; next stop is the final .oct") and proceed without further prompts.

## What YOLO suspends

**General principle:** every "STOP", "wait for user approval", and "checkpoint with the user" instruction in `SKILL.md` is suspended. Concretely, per `SKILL.md` section:

| Checkpoint in `SKILL.md` | YOLO behavior |
|---|---|
| Stage-Boundary Checkpoint (between every stage) | **Suspended** — after a stage's artifact is produced, re-run Stage Detection and auto-advance without stopping. |
| Per-prompt checkpoint (Stage 4, Step 5) | **Suspended** — do not summarize, do not stop, do not ask. Save context (Step 4) and go straight to the next prompt cycle. |
| Stage 3 Step 3.0 — "ask which asset path" | **Suspended** — default to **Path A** and use the `OPENROUTER_API_KEY` from the intake. Use Path B only if a complete asset set is already on disk (the 3.B2 completeness check still applies). If Path A is required but the key is missing, that is the one input YOLO must request before continuing. |
| Stage 3 Step 3.4 — user asset review | **Suspended** — auto-accept any set the consistency reviewer (3.A3) passed; the review→regen loop (max 3) already enforced cohesion. Proceed directly to Step 3.5. |
| Stage 3 Step 3.5 — Stage 3→4 boundary checkpoint | **Suspended** — pack, then auto-advance into Stage 4. |
| Stage 4 Step 1, item 6 — execution-plan approval | **Suspended** — do not wait for approval of the plan. Also build the prompt dependency graph now (foundational vs. cosmetic/isolated) so parallel batches can be planned. |
| 5-attempt verification failure → ask user | **Auto-decide** per the Failure policy below. |
| Mod mode M3 — mini-plan approval | **Suspended** — the mini-plan is still composed but auto-approved. Gather any required resource (e.g. the OpenRouter key) during the intake; if it is genuinely missing, that single input may be requested, otherwise proceed. |
| Mod mode M5 — per-change checkpoint | **Suspended** — independent mods are processed back-to-back and reported once at the end alongside the repackaged `.oct`. |
| Mod mode M6 — final `.oct` checkpoint | **Suspended** — the device build + ARM-embed verification still run; the final path is reported automatically. |
| Stage 5 final report | Delivered **automatically without waiting** — it is the single end-of-run report. |

## What YOLO NEVER drops (hard invariants — these decide whether the .oct runs)

Dropping any of these yields a package that won't load or won't run on the cube, defeating the whole point of an autonomous run.

- **Both verifier agents** (Requirements + Template) run every prompt, threshold **90/90**, max **5** fix attempts. In Mod mode the same 90/90 verifier + fixer gate runs on every change.
- The orchestrator still **never writes code, design, prompts, or assets itself**.
- **`_ids.h` is never hand-edited; assets stay valid; the asset-set completeness check (3.B2) still blocks a partial set** — a missing sprite/sound is an uncompilable build, so it stops the run even in YOLO.
- **Stage 5 device build + ARM-embed verification still runs and must exit 0** — a sim-only `.oct` is never delivered.
- All mandatory platform reminders in every coding task, explicit casts, fixed-width types, the half-resolution/x2-upscale coordinate rule, and all seven handlers (`on_init`, `on_tick`, `on_tap(tapid, count)`, `on_twisted`, `on_pretwisted`, `on_shake`, `on_proc_draw` stub) — still enforced.

## Safe parallelism (Stage 4)

All game code is one file (`app_<game>/src/app_<game>.h`), so **coding stays sequential** — only one coder writes the file at a time. YOLO extracts parallelism from everything else:

1. Build a prompt dependency graph up front (foundational vs. cosmetic/isolated, per the Pipeline Model table in `SKILL.md`). That table's decision criteria do not change in YOLO — its "Pipeline" / "Safe to pipeline" rows become parallel verifier+fixer batches, while "Wait" / "Always wait" rows stay strictly sequential.
2. **Verifiers (Requirements + Template) and fixers fan out** in parallel; verification of prompt N overlaps task-JSON prep for N+1. This fan-out is the norm in YOLO, not the exception.
3. **Independent cosmetic/isolated prompts** (audio, visual polish, UI text — touching disjoint code regions, no mutual dependency) batch their verify+fix in parallel.
4. Coders for independent prompts are still serialized on the file but dispatched back-to-back, as soon as the file is free, with no waiting between them.
5. **Foundational prompts** (scaffold, data structures, core init) stay strictly sequential and fully verified before anything downstream is dispatched.
6. Never dispatch two coders that could both edit the file concurrently. When in doubt, serialize the coding and parallelize only the checking.

## Failure policy in YOLO (no user to ask)

When a prompt fails verification after the 5-attempt limit:

- **Foundational prompt** (scaffold, data structures, core init) → **abort the run**, save context, surface immediately. This is the one time YOLO breaks silence before the `.oct` — downstream prompts can't be trusted.
- **Non-foundational prompt** → keep the best-scoring version, record it as a known issue for the final report, and **continue** to the next prompt.

A **Stage 5 ARM build failure** (missing toolchain, asset-only pack) is always a hard stop — surface it; never ship a sim-only `.oct`.

## YOLO completion

After the device build verifies, present a single end-of-run report: stages run, per-prompt verification scores, total fix cycles, any prompts that finished below threshold (with best scores), the consistency-review outcome, and the absolute path to the verified `app_<game>/app_<game>.oct`.

## Configuration (YOLO-specific)

| Setting | Default | Description |
|---------|---------|-------------|
| YOLO foundational-failure | abort | On 5-attempt failure of a foundational prompt, abort the run; non-foundational failures keep best effort and continue. |
| YOLO asset path | A (AI gen) | Defaults to AI generation (Path A) and gathers the OpenRouter key up front; Path B only if a complete set is already on disk. |
