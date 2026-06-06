# WowCube Game Pipeline — User Flow

End-to-end flow driven by `cube_orchestrator`, from a user request to a
device-ready `.oct`. `⏸` marks a mandatory checkpoint where the orchestrator
stops and waits for explicit user approval — it never auto-advances.

```mermaid
flowchart TD
    U(["User: 'make a game' / 'continue'"]) --> ORCH["cube_orchestrator<br/>single entry point"]
    ORCH --> DET{"Stage detection:<br/>first missing artifact?"}

    %% Stage 1
    DET -->|no GDD| S1["Stage 1 — Design<br/>cube_game-designer<br/>discovery interview -> GDD"]
    S1 --> CP1{{"⏸ Checkpoint 1->2<br/>review GDD"}}
    CP1 -->|approved| S2

    %% Stage 2
    DET -->|"GDD ok, no prompts/manifest"| S2["Stage 2 — Prompts<br/>technical_prompter<br/>prompts.md + assets.json with gen_prompt"]
    S2 --> CP2{{"⏸ Checkpoint 2->3<br/>review prompts + manifest"}}
    CP2 -->|approved| S30

    %% Stage 3.0 choice
    DET -->|"prompts+manifest ok, no packed assets"| S30{"Stage 3.0 — Asset source?<br/>AskUserQuestion"}

    %% Path A: AI
    S30 -->|"Option 1: AI"| PA1["Gates: gen_prompt coverage<br/>+ OPENROUTER_API_KEY"]
    PA1 -->|"missing gen_prompt"| S2
    PA1 -->|"key ok"| PA2["Generate via OpenRouter<br/>gpt-5.4-image-2 -> assets/art"]
    PA2 --> PA3{"Consistency review agent"}
    PA3 -->|"fail, < 3 cycles"| PA3R["regen group"]
    PA3R --> PA2
    PA3 -->|pass| CP3U{{"⏸ User review<br/>ok / regen / swap / edit"}}
    CP3U -->|ok| PACK

    %% Path B: self-supplied
    S30 -->|"Option 2: self-supplied"| PB1["Hand user exact spec<br/>names, sizes, GDD style"]
    PB1 --> PB2{"Completeness check:<br/>all PNG/MP3 present?"}
    PB2 -->|missing| PB2M["List missing -> wait"]
    PB2M --> PB2
    PB2 -->|complete| PACK

    %% Pack (both paths)
    PACK["Stage 3.5 — pack<br/>assets.psd + exported/ + packed/ + _ids.h"]
    PACK --> CP3{{"⏸ Checkpoint 3->4"}}
    CP3 -->|approved| INFRA

    %% Infra gate (boilerplate #1)
    INFRA["Infra gate — wowcube-boilerplate #1<br/>scaffold + verify simulator builds/launches"]
    INFRA --> S4

    %% Stage 4 loop
    S4["Stage 4 — Implementation loop"] --> CODER["Coder agent -> src/app_game.h"]
    CODER --> VERIFY{"2 verifiers >= 90?"}
    VERIFY -->|"no, < 5 tries"| FIX["Fixer agent"]
    FIX --> VERIFY
    VERIFY -->|yes| SAVE["Save context"]
    SAVE --> CP4{{"⏸ Per-prompt checkpoint<br/>test in simulator"}}
    CP4 -->|"more prompts"| CODER
    CP4 -->|"all prompts done"| S5

    %% Stage 5 package (boilerplate #2)
    S5["Stage 5 — Package — wowcube-boilerplate #2<br/>build_device.ps1 -> ARM -> .oct + verify embedded"]
    S5 --> CP5{{"⏸ Checkpoint 5<br/>app_game.oct ready to flash"}}
    CP5 --> DONE(["Done: flash to physical cube"])
```

## Legend

- **Rounded nodes** — user-facing start/end.
- **Rectangles** — work done by a sub-skill or subagent.
- **Diamonds** — decisions (stage detection, asset-source choice, verification gates).
- **`{{ ⏸ … }}`** — mandatory checkpoints: the orchestrator stops and waits for explicit user approval. The per-prompt checkpoint (Stage 4) and every stage boundary are non-negotiable.

## Stage summary

| Stage | Owner | Produces |
|-------|-------|----------|
| 1. Design | `cube_game-designer` | `plans/<game>_gdd.md` |
| 2. Prompts | `technical_prompter` | `plans/<game>_prompts.md` + `plans/<game>_assets.json` (per-sprite `gen_prompt`) |
| 3. Assets | `cube_asset-builder` (+ consistency reviewer) | `assets/packed/*.png`, `pal.png`, `assets/mp3/*.mp3`, `src/app_<game>_ids.h` |
| Infra gate | `wowcube-boilerplate` (#1) | scaffolded `app_<game>/`, verified **simulator** build |
| 4. Implement | coder / verifier / fixer subagents | `src/app_<game>.h` (per prompt, sim-tested) |
| 5. Package | `wowcube-boilerplate` (#2) | `app_<game>/app_<game>.oct` (ARM embedded, verified) |

## Key points

- **Single entry point:** the user always talks to `cube_orchestrator`; it routes.
- **Two asset sources (Stage 3.0):** AI generation via an OpenRouter/GPT Image 2 key, or self-supplied assets validated for completeness before packing. Both converge on `pack`.
- **`wowcube-boilerplate` runs twice:** first to bring up the **simulator** before coding (so each prompt is testable), then at the end for the authoritative **device `.oct`** (built once because the simulator clobbers the `.oct` on every run).
- **Resume-safe:** on any re-entry, stage detection reads the filesystem/context and continues from the first incomplete stage.
