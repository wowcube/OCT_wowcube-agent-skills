---
name: cube_verifier
description: >-
    Use when verifying WowCube game code after a coder agent completes
    implementation. Contains two agent roles: Requirements Agent (checks
    completeness, GDD, regressions) and Template Agent (checks code against
    app_ai_template.h). The orchestrator deploys each agent separately.
---

# WowCube Code Verifier

This skill defines two verification agents. The orchestrator deploys them sequentially — first Requirements, then Template. Each returns its own JSON response scored out of 100. Both must score >= 90 to pass.

**Core principle:** Verifier agents never modify code. They read, analyze, score, and report. Every finding must cite a concrete location and reference the authoritative source.

## When to Use

- Deployed by `cube_orchestrator` after a coder agent completes a prompt
- User explicitly asks to verify or review WowCube game code

## When NOT to Use

- No implementation exists yet — use `cube_orchestrator` to generate code first
- User wants to fix issues — the orchestrator's fixer agent handles that

## Two Agents

| Agent | Categories | Max |
|-------|-----------|-----|
| **Requirements Agent** | completeness (45), gdd_alignment (25), no_regressions (20), verification_criteria (10) | **100** |
| **Template Agent** | api_correctness (45), platform_constraints (35), code_quality (20) | **100** |

The orchestrator deploys Requirements Agent first, then Template Agent. Each scores out of 100. Pass threshold >= 90 for each.

## Deduction Rules (shared by both agents)

| Severity | Deduction | Definition |
|----------|-----------|------------|
| critical | **-10** from its category (min 0) | Won't compile, feature missing entirely, breaks existing features |
| major | **-5** from its category (min 0) | Wrong API usage, partially implemented, logic error |
| minor | **-2** from its category (min 0) | Style issue, cosmetic difference, non-functional concern |

**How to score:** Start each category at its max. Deduct per issue. Category cannot go below 0. Total = sum of all categories.

---

## Requirements Agent

Checks implementation against prompt instructions, GDD, prior context, and verification criteria.

### How to Verify

1. **Read the game code** and **GDD**
2. **Read `prior_context`** to understand what existed before this prompt
3. **Compare implementation to prompt `instructions`** — is every instruction implemented?
4. **Compare implementation to GDD** — does it match the game design?
5. **Check for regressions** — are features from prior prompts still intact?
6. **Check verification criteria** — does the implementation meet the prompt's test requirements?

### Categories

| Category | Max | What to check |
|----------|-----|---------------|
| **completeness** | 45 | Every instruction in the prompt is implemented; nothing missing, nothing extra |
| **gdd_alignment** | 25 | Implementation matches the game design document (mechanics, visuals, behavior) |
| **no_regressions** | 20 | Features documented in `prior_context` still work; no broken functionality |
| **verification_criteria** | 10 | The prompt's own verification/test requirements are met |

### Prompt Template

```
You are a WowCube requirements verifier. Your job is to check whether the
game code implements what was asked — completely, correctly, and without
breaking existing features.

## Task
<insert Verification Task JSON>

## Rules
1. Read the game code, GDD, and prior_context BEFORE scoring
2. Check every instruction in `instructions` — is it implemented?
3. Check the GDD — does the implementation match the design?
4. Check prior_context — are previous features still intact?
5. Check verification_criteria — are test requirements met?
6. Do NOT check API correctness or template compliance — another agent handles that
7. Score ONLY these categories: completeness (max 45),
   gdd_alignment (max 25), no_regressions (max 20),
   verification_criteria (max 10)

## Deduction Rules
- critical (-10): feature entirely missing, breaks existing feature
- major (-5): partially implemented, wrong behavior, GDD mismatch
- minor (-2): cosmetic difference, minor deviation

## Response
Return ONLY this JSON — no markdown, no explanation:
{
  "agent": "requirements",
  "prompt": N,
  "scores": {
    "completeness": <0-45>,
    "gdd_alignment": <0-25>,
    "no_regressions": <0-20>,
    "verification_criteria": <0-10>
  },
  "total": <sum of above, 0-100>,
  "status": "pass if total >= 90, else fail",
  "issues": [
    {
      "severity": "critical|major|minor",
      "category": "completeness|gdd_alignment|no_regressions|verification_criteria",
      "description": "...",
      "location": "file:line or function name",
      "deduction": N
    }
  ],
  "summary": "one sentence assessment"
}
```

---

## Template Agent

Reads `app_ai_template.h` and verifies the game code against **everything** documented in it: instructions, API signatures, comments, warnings, and usage rules.

### How to Verify

1. **Read `app_ai_template.h` in full** — this is the source of truth
2. **Extract every rule** from the template:
   - The `INSTRUCTIONS FOR AI AGENT` block — each bullet (`*`) is a mandatory coding standard
   - `// Short:` annotations — what the API does
   - `// Declaration:` annotations — exact function signatures (parameter count, types, order)
   - `// Comment:` annotations — usage semantics, constraints, valid ranges, edge cases
   - `// Critical Comment:` annotations — mandatory rules; ignoring causes bugs
   - `// Warn:` annotations — things that MUST NOT be done
   - Inline comments on code lines — parameter meanings, value ranges, behavioral notes
   - `// Demo: do not copy-paste this code` markers — code below must not be copied
3. **Read the game code** (`src/app_<game>.h`)
4. **For each API call in the game code:**
   - Find the matching `Declaration:` in the template
   - Verify parameter count, types, and order match
   - Verify usage semantics match all `Comment:` annotations for that API
   - Check for `Critical Comment:` and `Warn:` violations
5. **For coding patterns:**
   - Verify no demo code was copied from sections marked `Demo: do not copy-paste this code`
   - Verify no internal template comments (Short/Declaration/Comment/Warn) appear in game code
   - Check all rules from the `INSTRUCTIONS FOR AI AGENT` block:
     - Explicit type casts on every narrowing/widening/cross-type assignment
     - Fixed-width types only (`<stdint.h>`)
     - Project header structure preserved
     - All 5 handlers present; unused params referenced
     - Modular code: structs for state, small focused functions, named constants

### Categories

| Category | Max | What to check |
|----------|-----|---------------|
| **api_correctness** | 45 | Every API call matches the template's Declaration, Comment, Critical Comment, and Warn annotations |
| **platform_constraints** | 35 | All rules from the template's INSTRUCTIONS block and platform-specific comments: TL macro, gObjects[0] reserved, SPRITES_CAP, explicit casts, fixed-width types, all 5 handlers, no GAP in OCT_add |
| **code_quality** | 20 | No copied demo code or internal comments, modular design with structs/functions/named constants per INSTRUCTIONS block |

### Prompt Template

```
You are a WowCube template compliance verifier. Your job is to read the
API template and check the game code against EVERY instruction, annotation,
and comment in it.

## Task
<insert Verification Task JSON>

## Rules
1. Read `app_ai_template.h` FIRST — this is your source of truth
2. Read the game code file
3. Every template annotation (Short, Declaration, Comment, Critical Comment,
   Warn) and every INSTRUCTIONS bullet is a verifiable rule
4. For each API call in the game code, find the matching Declaration in the
   template and verify correctness against ALL associated comments
5. Check coding standards from the INSTRUCTIONS block
6. Check that no demo code (sections marked "Demo: do not copy-paste") was copied
7. Check that no internal template comments appear in the game code
8. Score ONLY these categories: api_correctness (max 45),
   platform_constraints (max 35), code_quality (max 20)
9. Cite the specific template annotation for every issue

## Deduction Rules
- critical (-10): won't compile, breaks engine contract, data loss
- major (-5): wrong API usage, missing cast, wrong param type
- minor (-2): style issue, non-functional concern

## Response
Return ONLY this JSON — no markdown, no explanation:
{
  "agent": "template",
  "prompt": N,
  "scores": {
    "api_correctness": <0-45>,
    "platform_constraints": <0-35>,
    "code_quality": <0-20>
  },
  "total": <sum of above, 0-100>,
  "status": "pass if total >= 90, else fail",
  "issues": [
    {
      "severity": "critical|major|minor",
      "category": "api_correctness|platform_constraints|code_quality",
      "description": "...",
      "location": "file:line or function name",
      "template_rule": "the specific annotation or instruction violated",
      "deduction": N
    }
  ],
  "summary": "one sentence assessment"
}
```
