---
name: cube_orchestrator
description: >-
  This skill should be used when executing WowCube game implementation prompts
  produced by the technical_prompter skill. Orchestrates multi-step code
  generation with live context injection, user build checkpoints, and regression
  tracking to prevent context degradation across 30-40 sequential prompts.
---

# WowCube Cube Orchestrator

Execute a sequence of WowCube implementation prompts with live context injection, build checkpoints, and regression tracking.

**Core principle:** Never let a code-mode agent operate on stale context. Before every subtask, read the actual source, extract structural context, and inject it alongside the prompt instructions. After every prompt, stop and let the user verify the build.

## When to Use

- A prompts file exists in `plans/` (produced by `technical_prompter`) and implementation needs to be orchestrated
- User says "run the prompts," "execute the implementation," or "build the game from prompts"
- User has a GDD and prompts file and wants automated, context-aware execution
- Resuming a partially-completed implementation

## When NOT to Use

- No prompts file exists — use `technical_prompter` first to generate one
- No GDD exists — use `cube_game-designer` first
- User wants to modify a single specific feature — dispatch directly to code mode
- User wants to design a game — use `cube_game-designer`

## Prerequisites

Before starting orchestration, verify these files exist:

| File | Source | Required |
|------|--------|----------|
| `plans/<game>_prompts.md` | `technical_prompter` skill | Yes |
| `plans/<game>_gdd.md` | `cube_game-designer` skill | Yes |
| `templates/app_ai_template.h` | Project template | Yes |

**If a prerequisite file is missing**, do not proceed. Instead, delegate to the appropriate skill:
- Missing GDD → invoke `cube_game-designer` to create it
- Missing prompts → invoke `technical_prompter` to create them
- Missing template → halt and inform the user (this is a project setup issue)

Resume orchestration only after all prerequisites are satisfied.

## Workflow

### Step 1: Initialize

1. Verify all prerequisites exist. If any are missing, delegate to the appropriate skill (see Prerequisites above)
2. Read `plans/<game>_prompts.md` to get the full prompt list
3. Read `plans/<game>_gdd.md` for high-level game understanding
4. Read `templates/app_ai_template.h` for platform patterns
5. Parse the prompts file to extract individual prompts (each delimited by `## Prompt N:` headers)
6. Count total prompts and present the execution plan to the user

### Step 2: Validate Prompts

Each prompt produced by `technical_prompter` must represent a testable build — meaning after executing the prompt, the user can build and observe a specific, verifiable result.

Before executing any prompt, validate that it meets this criterion:
- The prompt has a clear **Verification** section describing what the user should see/hear
- The prompt does not depend on a subsequent prompt to produce a testable state
- The prompt's instructions are self-contained enough to produce a compilable result

**If a prompt fails validation** (e.g., it is a partial step that requires the next prompt to be testable), do NOT execute it. Instead:
1. Document which prompt(s) failed validation and why
2. Return the issue to `technical_prompter` for rework
3. Resume orchestration only after receiving corrected prompts

### Step 3: Execute Prompts

For each prompt in sequence:

#### 3a. Read Current Source

Read the actual source files:
- `src/app_<game>.h`
- `src/app_<game>_ids.h`

If this is prompt 1 and no source exists yet, note that the agent starts from scratch using the template structure.

#### 3b. Extract Structural Context

From the source files, extract all structural context needed for a fresh agent to understand the codebase: struct definitions and their fields, enum types and values, function signatures, global variable declarations, and any other architectural elements. The goal is to give the code-mode agent a complete structural map of the current source so it can make changes without introducing inconsistencies.

#### 3c. Build the Enriched Subtask

Construct the code-mode subtask message using this template:

```
## MANDATORY: Read Before Changing

Before making ANY changes, read these files completely:
1. `src/app_<game>.h` — current implementation (SOURCE OF TRUTH)
2. `templates/app_ai_template.h` — reference patterns only, do NOT copy demo code

The actual source code is the source of truth, not the summaries below.

## Structural Context (extracted from actual source)

<full structural context extracted in Step 3b: structs, enums, functions, globals, etc.>

## Architecture Decisions
<key decisions from GDD and previous prompts>

## API Reminders
<selectively included based on prompt content — see 3d>

## Task Instructions
<original prompt content from prompts file>

## Verification
<original verification section from prompt>

## Regression Check
<list of previously-confirmed working features — include after prompt 10>
```

#### 3d. Select API Reminders

Include only the API reminders relevant to the current prompt:

| If prompt mentions... | Include reminder |
|----------------------|-----------------|
| new global, TL, static | All globals must use `TL` macro: `TL static type name;` |
| iterate, loop, gObjects, for | gObjects[0] is reserved — start iteration from index 1, validate with `obj->Idx == i` |
| label, text, OCT_label, glyph | Label child visibility: to show/hide a label, must also iterate and toggle all child glyphs where `obj->Parent == label->Idx` |
| OCT_add, sprite, layer | SPRITES_CAP = 400 max. Verify total count stays under limit. |
| walk, move, cross, plane, wrap | Cross-display distance = `240.0f + 2.0f * GAP`. Use `OCT_TM_walk` with `wrap=true` for cross-plane. |
| sound, SND, audio, mp3 | Pattern: `int id = SND_getAssetId(name); SND_play(id, volume);` |
| animation, sequence, frame | `OCT_sequence` restart modes: `OCT_SEQ_RESTART`, `OCT_SEQ_REVERSE`, `OCT_SEQ_REFRESH` |
| twist, twid, on_twisted | Full twists: twid 0-11. Half twists: twid 12-23 (offset by `OCT_TWIST_HALF`). |

#### 3e. Dispatch and Monitor

Dispatch the enriched subtask to a code-mode agent via `new_task`. After completion:
1. Read the modified source files to verify changes were applied
2. Record the prompt as completed
3. Add any new features to the regression checklist

### Step 4: Checkpoint with User

After **every prompt**, stop and checkpoint with the user. Each prompt is a testable build — the user verifies it before proceeding.

**Checkpoint protocol:**

1. **Summarize** what was implemented:
   - Prompt number and title
   - Features added or changed
   - Files modified

2. **Provide test instructions:**
   - What to look for on the cube
   - Expected behaviors to verify
   - Specific interactions to test (twist, tap, etc.)

3. **Collect feedback** using `ask_followup_question`:
   - "Everything works as expected — continue to next prompt"
   - "Found bugs — here is what I see: ..."
   - "Want to change the design — here is what I want: ..."
   - "Need to stop here — will resume later"

4. **Handle feedback:**
   - **Continue**: Proceed to next prompt
   - **Bugs**: Create fix subtasks with full structural context plus the error description, execute them, re-checkpoint
   - **Design change**: Note the change, adjust remaining prompts if needed, proceed
   - **Stop**: Note the last completed prompt number for later resumption

### Step 5: Handle Errors

#### Build Failures
1. Read the error details from user
2. Create a fix subtask with full structural context plus the error message
3. Dispatch to code mode
4. Re-checkpoint after fix

#### Context Drift
If the actual source diverges significantly from expectations:
1. Perform a full re-extraction from source (Step 3b)
2. Review next prompt for compatibility
3. Adapt prompt instructions if needed, documenting changes

#### Prompt Incompatibility
If a prompt assumes code that does not exist or has different structure:
1. Identify the specific conflict
2. Adapt the prompt to work with actual source state
3. Proceed with adapted prompt

### Step 6: Complete

After all prompts are executed and the final checkpoint passes:
1. Summarize the full implementation:
   - Total prompts executed
   - Total fix subtasks needed
   - Features implemented
   - Known issues remaining
2. Suggest next steps (testing, polish, feature additions)

## Validation Checklist

Before dispatching each subtask, verify:

1. [ ] Source files have been read (not relying on stale context)
2. [ ] Structural context matches actual source (structs, enums, functions)
3. [ ] API reminders are relevant to this specific prompt
4. [ ] Regression checklist is included (after prompt 10)
5. [ ] Checkpoint schedule is being followed (every prompt)

Before each checkpoint, verify:

1. [ ] The prompt completed successfully
2. [ ] Test instructions are specific and actionable
3. [ ] Feedback options cover all likely scenarios

## Output

Primary outputs:
- Enriched code-mode subtasks dispatched via `new_task`
- User checkpoint summaries with test instructions

The orchestrator does not directly modify source files. All code changes are made by code-mode agents through dispatched subtasks.

## Configuration

At the start of orchestration, confirm these settings with the user:

| Setting | Default | Description |
|---------|---------|-------------|
| Regression start | 10 | Include regression checklist after this prompt number |
| Start from | 1 | First prompt to execute (for resumption) |
