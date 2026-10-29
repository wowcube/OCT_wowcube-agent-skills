# Run modes (cube_orchestrator reference)

Read this before the intake of every new run. The run mode is decided per entry
from the current prompt; nothing carries across turns, except a mid-run "stop"
that switches the rest of that run to stepwise. User phrases quoted in this file are English examples: recognize the same intent in any language, and write every message to the user in the user's language.

| Mode | How it activates | Behaviour |
|---|---|---|
| **Autonomous (default)** | Any entry; no signal needed, never asked to confirm, no risk speech | Intake (at most two questions), one start line, then the whole pipeline to the verified device `.oct`. Stops only at the **style lock** (the one creative checkpoint) and for real blockers (below). |
| **Stepwise (opt-in)** | "stepwise", "step by step", "with checkpoints", "review mode" in the prompt, or "stop" at any time mid-run | Every checkpoint in the skill is in force: stage boundaries, the designer interview, the asset batch review, each prompt, each mod change. Nothing advances without an explicit "ok / next". |
| **`YOLO` token (compat alias)** | The literal token `YOLO` (case-insensitive) in the body of the current prompt, then one short risk confirmation (below) | Autonomous, plus: no intake questions (no concept → the designer invents one; no Codex → temporary placeholder art) and the style lock is waived (an independent reviewer approves the style frame instead of the user). |

`YOLO` activation is literal: no paraphrase or translation counts ("autonomous
mode", "go autonomous", "just run it to the end", in any language, do not), it is never inferred from tone,
and a previous prompt's token does not carry over. It removes stops, never checks.

**YOLO risk confirmation** (the one message before a `YOLO` run; in the user's
language; wait for an explicit "yes", anything else → the default autonomous
mode):

> YOLO: I'll run to the finished file without stopping. I'll invent the game if the request has none, and I won't show you the art style for approval (an independent reviewer checks it instead). Risk: the result may not be what you wanted and may need rework. YOLO does NOT approve paid APIs or downloads: without Codex the art is temporary and the sounds are synthesized. Start? (yes / no)

**Paid image APIs need the user's own explicit opt-in, in every mode.** Neither the
default autonomous mode nor `YOLO` (nor its confirmation) implies consent to pay: a
paid provider (`OPENROUTER_API_KEY`, `IMAGE_API`, `~/.wowcube/image_api.json`) is
used only when the user, in this run, explicitly asked for it and agreed to pay per
image; only then set `WOWCUBE_ALLOW_PAID_IMAGES=1` / `--allow-paid`. A key that is
merely configured is not consent. A local Stable Diffusion server on this machine
(`http://localhost` / `127.0.0.1`) costs nothing and needs no opt-in.

On "stop" mid-run: finish the atomic step in flight (a coder run, a generation
batch), save context, then continue in stepwise mode.

## Hard invariants (every mode)

These decide whether the result runs on the cube; no mode suspends them.

- Every prompt: Requirements ≥ 90 and Template ≥ 90 (`cube_verifier`), no unresolved
  **critical** finding from any check whatever the score, no open **major** unless it is
  accepted with a reason in the context (`accepted_majors`), the **visual gate** (hidden
  simulator, all 24 screens, the agent looks at the frames), the Playtest Agent (≥ 90,
  no critical) whenever the hidden instance's control socket answers; fixer at most 5
  rounds per prompt.
- **A prompt is never marked complete while a gate fails.** A prompt that keeps failing
  is rescoped (failure policy below) and the rescoped version must pass every gate.
- The orchestrator never writes code, design, prompts or assets itself.
- `_ids.h` is never hand-edited; a partial asset set is never packed:
  `build_pipeline.py pack` refuses it before writing anything (a missing sprite breaks
  the compile, a missing sound would only go silent, so both are checked).
- Art is packed only when every rule in `cube_art-director/references/QA_RULES.md`
  passes; placeholder art is never presented as final.
- Downloads only after the user approved the list (the `YOLO` waiver is not an
  approval of downloads).
- Paid image APIs only after the user's explicit opt-in (`--allow-paid`); autonomous
  mode and `YOLO` never imply it.
- The deliverable is the Stage 5 device `.oct` with verified ARM code, in `dist/`;
  never a simulator-written `.oct`.
- `references/AGENT_SAFETY.md`, for you and in every subagent brief.

## Intake (once, before going quiet)

Ask only what cannot be decided; ask nothing mid-run. Questions are short, with
options (AskUserQuestion), never a wall of text.

1. **Game concept** — only if the prompt has none at all: "What is the game about? One
   sentence, or say 'your choice'." Any genre, theme or mechanic in the prompt
   means no question.
2. **Art access** — only if Codex cannot draw: `python <skills>/skills/cube_art-director/scripts/art.py doctor`
   fails on the Codex CLI or the ChatGPT login. Ask the user to install Codex or run
   `codex login` themselves (never type credentials, never ask for a paid key while the
   subscription path can work). Answers: logged in → Codex; "can't" / "no" →
   temporary placeholder art, one line about it in the final report. A paid image
   provider only when the user says explicitly that they want one and agree to pay per
   image (then `--allow-paid`; `scripts/image_providers.py`, driven by
   `cube_asset-builder`; what still works without Codex:
   `cube_asset-builder/references/ART.md` "No Codex"); never offer it while
   `codex login` can still work.

Not a question but a blocker, reported at intake when the entry checks find it: the
SDK is older than octavios dev 2026-10-21 (`609d5ae`), `telemetry/` is missing, or
the toolchain is incomplete. Send the exact update commands once (SKILL.md, entry
check 3); design, prompts, art and sound continue; the run waits before the infra gate
until the user says it is done.

`YOLO`: after the risk confirmation, skip questions 1 and 2 (invent the concept; no
Codex → placeholders, never a paid provider unless the prompt itself explicitly asks
for one and agrees to pay). The environment blocker still applies.

**Start line** (autonomous; in the user's language), printed once, then continue
without waiting for a reply:

> Making a game for the cube. I'll stop once to show you the art style and the list of sounds for approval, then go on my own to the finished file (~estimate). Want to approve each step? Say "stepwise".

Fill `~estimate` with an honest rough estimate (Codex art takes minutes per picture).

## What each mode does at each checkpoint

| Checkpoint | Stepwise | Autonomous |
|---|---|---|
| Stage boundary | Summarize, STOP, wait | One progress line, re-run stage detection, continue |
| Designer discovery interview | Short questionnaire | GDD from the concept, no interview |
| Asset source (AI / own art / PSDs) | Ask | Codex, unless a complete own set is already on disk |
| **Style lock: style frame + mock** | STOP, iterate until approved | **STOP, iterate until approved** (waived only by an explicit user statement or `YOLO`) |
| **Sound list (downloads)** | Approve with the style lock | **Approve with the style lock**; not approved → synthesis |
| Art batch review (`review.html`) | The user marks OK / Fix | Fresh-agent review instead; page linked in the final report |
| Execution plan before Stage 4 | Present, wait | Dependency graph, continue |
| Per-prompt checkpoint | Summary + the agent's frames, STOP | Save context, next prompt |
| 5 failed fix rounds | Ask: rescope / retry / stop | Rescope, then the gates again (below) |
| Mod mini-plan, per-change check | Present, STOP | Auto-approved, mods back-to-back |
| Upload to the cube | When asked | When the prompt asked; otherwise offered in the report |

**Real blockers** that stop autonomous mode: the environment (SDK, telemetry,
toolchain; at Stage 5 the ARM toolchain), the Codex login when the user wants Codex
art, an upload the user asked for without naming the cube (its Bluetooth name /
MAC), and a game whose simplest playable loop still fails the gates (below).

## Safe parallelism (Stage 4)

All game code is one file (`app_<game>/src/app_<game>.h`), so coding is sequential.

1. Build the prompt dependency graph first: foundational (scaffold, data structures,
   core init) vs cosmetic/isolated (audio, polish, UI text).
2. The code verifiers run in parallel with each other and with the visual gate's
   build; prepare prompt N+1's brief while N is being checked.
3. Never dispatch the next coder before prompt N has passed every gate (the visual gate
   builds from that file); never run two coders that could touch the file.
4. Foundational prompts are strictly sequential and fully verified before anything
   downstream.
5. **One hidden simulator at a time**: visual-gate runs and playtests never run in
   parallel (one binary, one port).
6. Art: `art.py gen --jobs 3` parallelizes Codex calls; the review loop decides what to
   redraw.

## Failure policy: degrade, never abort (autonomous)

Degrading means **rescoping**, never accepting a failure: a prompt counts as complete
only when every gate passes on what was finally asked. After 5 fix rounds a prompt
still fails:

- **Any prompt** → rescope it: cut or simplify the failing feature in this prompt's
  instructions and record the cut (you change scope only; coders still write all
  code). The fixer gets the rescoped prompt, then every gate runs again on it:
  Requirements and Template ≥ 90 with no critical issue (judged against the rescoped
  instructions), the visual gate, the Playtest Agent when deployed. A new 5-round
  budget; rescope again while it still fails.
- **Foundational prompt**, or a build that does not compile or renders nothing → also
  run ONE re-scope pass over the remaining prompts (simplify or drop what builds on
  the missing piece).
- **Visual or playtest findings** → the rescope cuts or simplifies the feature that
  shows them (an effect, an extra animated layer, a tilt mode) until the frames and
  the playtest pass; the findings and their frames go into the cut's record.
- **Art rule that genuinely cannot be met** (after real changes to prompt, references
  and processing) → simplify the asset within its manifest entry (same name and size)
  until QA passes, record it.
- **Visual gate unavailable** (the hidden tool itself broke, not the game) → try to fix
  the tool; if that fails, continue code-only, record the prompt in
  `not_checked_visually` (never as passed) and retry the gate on the next prompt.
  Delivery needs a passing visual gate on the final source, so the tool must work
  again before Stage 5.
- The floor is the simplest playable loop that passes every gate; every cut is in the
  final report. Nothing is dropped silently. If even the floor cannot pass, that is a
  real blocker: report it with the evidence; never deliver a build whose gates fail.

Stepwise mode asks instead: "The check still fails after 5 attempts (best score:
X). Simplify the feature / try again / stop?" (rescope / retry / stop; a rescoped prompt
goes through every gate again).

## Progress lines and the final report

During an autonomous run: one-way progress lines at stage transitions, in the user's
language, no pipeline jargon (no "verifier", "manifest", "Stage 4"):
"design done → drawing the art (~20 min)…", "art done → writing the code…".

The final report (autonomous; also the end of a stepwise run), plain language:

1. **The game file**: absolute path to `dist/app_<game>.oct` and its version; uploaded
   or not; how to put it on the cube (say "upload it to the cube", or the manual way in
   `references/DELIVERY.md`), and that the cube needs a restart after an upload.
2. **What the agent saw**: the path of the last frames sheet, the gameplay video if
   made, the art review page (`assets_<game>/review.html`), and what no check could
   judge (how it sounds, how it feels, balance, the real cube).
3. **What was cut or simplified** — every item, one line each; prompts nobody could
   check visually.
4. **Temporary parts**, one line each when they apply: "The art is temporary: log in to
   Codex (`codex login`) and say 'redraw the art'."; "The sounds are synthesized: say
   'find real sounds'."; "You did not approve the style: say so if you want another one."
5. **Sound credits**: `app_<game>/sound/CREDITS.md`.
6. **How to play**: the controls (taps, twists, tilt), what to try first.
7. **Next**: the on-device checklist (short) and an offer of a balance pass.

Per-prompt scores, fix rounds and gate verdicts stay in
`context/<game>_context.json`; give them when the user asks.

## Stepwise specifics

- Every stop presents what was produced (paths, counts, frames) and waits for an
  explicit answer; silence is not approval.
- The per-prompt checkpoint arrives with the agent's own evidence (frames sheet,
  playtest findings) and leads with what the agent could not judge, so the user's
  time goes to feel, difficulty, sound and pacing.
- Offer to open the visible simulator for the user (it plays sound, it is theirs);
  start it only when they ask.
- Long builds: suggest one stage, or one batch of prompts, per session. Everything
  resumes from the files (`plans/`, `assets_<game>/`, `context/`).
