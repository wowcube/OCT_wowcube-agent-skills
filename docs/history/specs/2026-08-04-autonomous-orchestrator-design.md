# Part 2: Autonomous-by-default orchestrator + tooling upgrades — design spec

**Status:** agreed with the owner 2026-08-04; supersedes the opt-in-YOLO model merged in PR #24.
**Base:** `main` after PR #24 (beta transition) and PR #25 (placeholder generator dropped).

## 1. Why

The pipeline's primary audience is business users. Observed behavior: they bypass permissions, paste one huge prompt ("сделай игру про X, вот фичи, не задавай вопросов") and expect a cube-loadable game with zero interaction. Some paste internet-hype prompts ("spin up a hundred agents and do research"). The current opt-in YOLO (literal token + a confirmation stop) does not match how they actually work — they never opt in; they just fight the checkpoints. The redesign makes their natural behavior land on the rails instead of derailing from them: the rails become invisible, not interactive.

## 2. Run modes (the default flips)

| Mode | How it activates | Behavior |
|---|---|---|
| **Autonomous (DEFAULT)** | Any orchestrator entry, no signal needed | Drives Build or Mod all the way to the verified device `.oct` with no approval stops. Prints ONE jargon-free start line and goes: "Делаю игру для кубика, вернусь с готовым файлом (~оценка). Хочешь контролировать шаги — напиши «по шагам»." It does NOT wait for a reply to that line. |
| **Stepwise (opt-in)** | Phrase in the prompt ("по шагам", "с чекпоинтами", "review mode") or "стоп" at any time mid-run | The pre-part-2 checkpointed flow, unchanged: stage-boundary and per-prompt checkpoints, asset review, mod-mode mini-plan approval. |
| **`YOLO` token (compat)** | Literal token in the prompt | Autonomous + skip even the allowed questions (§3): missing concept → designer invents one; missing image key → placeholders without asking. The old double-gate (risk speech + confirmation) is REMOVED. |

Mode is decided per entry from the current prompt; nothing carries across turns. The correctness invariants (verifier 90/90 + fixer per prompt, asset-set completeness before pack, device build with ARM-embed verification) hold in every mode and are never suspended.

## 3. The only two questions autonomous mode may ask

Both are asked once, at intake (before going silent), never mid-run:

1. **Game concept — only if the prompt carries none at all.** "Про что игра? Одним предложением — или скажи «на твой вкус»." Any concept fragment in the prompt (genre, theme, mechanic) means no question.
2. **Image API key — only if no key/endpoint is configured anywhere (§4).** The orchestrator asks for a key and **waits for the answer** (this is a real block, per the owner's decision). Two outcomes:
   - The user pastes something → provider adapter (§4) identifies and validates it, run proceeds with AI art.
   - The user answers "не знаю"/"нет ключа"/anything conveying no-key → the run proceeds with **agent-drawn placeholder art** (§5) and the final report says exactly one line about it: "Графика временная — добавь ключ (файл `<path>`) и скажи «перегенери графику»."

Everything else — GDD content, prompts, asset review, per-prompt results — is decided autonomously and only reported at the end.

## 4. Image provider adapter (multi-provider, auto-detected)

Today `genimg.py` is hardwired to OpenRouter. Business users will paste whatever key they have — OpenAI, Grok, Gemini, or a URL of their local Stable Diffusion. The pipeline must accept any of them.

**Resolution chain** (first hit wins):
1. `OPENROUTER_API_KEY` env var (backward compat — treated as an OpenRouter key).
2. `IMAGE_API` env var or config file `~\.wowcube\image_api.json`: `{"provider": "...", "key": "...", "base_url": "...", "model": "..."}` (any field optional; missing ones auto-detected/defaulted).
3. Nothing found → the intake question (§3.2). A pasted answer is written to the config file so the question never repeats.

**Provider detection** from the pasted value:
| Pattern | Provider | API |
|---|---|---|
| `sk-or-...` | OpenRouter | current implementation |
| `sk-...` (non-`or`) | OpenAI | Images API (`gpt-image-*`) |
| `xai-...` | xAI / Grok | xAI images endpoint |
| `AIza...` | Google Gemini ("nano banana") | Gemini image generation |
| `http(s)://...` | Local/self-hosted Stable Diffusion | Automatic1111-compatible `/sdapi/v1/txt2img` (covers A1111 and compatible shims) |
| anything else | unknown | one retry question naming the supported forms, then placeholder fallback |

**Design:** one interface `generate_image(prompt, out_path, size, *, cutout, ...)` with per-provider implementations behind it; provider chosen once per run and validated with a cheap ping/one tiny test call before the pipeline commits to AI art. A failed validation degrades exactly like "no key": placeholders + one report line (never a mid-run stall). Retries/timeouts follow the current genimg behavior (non-streaming, `(15, 180)` timeouts).

## 5. Placeholder art is authored by the agent (no script)

`gen_placeholders.py` is deleted (PR #25) — its procedural output was weak. When a run has no working image provider, the **asset-builder agent draws each sprite itself** from the manifest `description`/`gen_prompt`: readable silhouettes, flat shapes, correct sizes and alpha per the manifest, written as PNGs into the same layout AI art would use (agent chooses its own means — e.g. ad-hoc Pillow code; nothing is canned). Requirements the skill text pins:
- every manifest sprite gets a file, exact `size`, correct alpha (palette tiers) / opacity (full-color);
- placeholder art must be visually distinct enough per sprite that gameplay is testable;
- the pack and every later stage treat placeholder PNGs identically to AI PNGs (repack path is the same).

## 6. Failure policy: degrade, never abort

After 5 failed fixer attempts on a prompt, the feature is cut or simplified and the run continues. The floor is the simplest playable loop that passes the verifier. Every cut is listed in the final report. (Old YOLO aborted on foundational-prompt failure; autonomous mode instead re-plans around the failure — a foundational failure triggers one re-scope pass of the remaining prompts so later prompts don't build on the missing piece.) The run always ends with a verified `.oct`.

## 7. Telemetry

- One-way progress lines at stage transitions ("дизайн готов → генерю графику (~5 мин)…"), never questions.
- Final report in plain user language: `.oct` path, how to load it, what was cut (§6), placeholder-art note if any (§3.2), playtime hints. No pipeline jargon.

## 8. Hype-prompt normalization

Instructions about methodology inside user prompts ("подними 100500 агентов", "сделай глубокий рисёрч", "ultra-approach") are silently mapped onto the pipeline's own stages; the orchestrator never alters its mechanics because a prompt asked it to. From such prompts only the game payload is extracted: concept, features, style, constraints. The rails are non-negotiable — and never advertised.

## 9. Versioning: automatic patch bump

`APP_VERSION` encodes `v<major>.<minor><patch>` as an int (100 = v1.00). Rule: **every rebuild/repack that produces a new device `.oct` bumps the patch (+1)** — automatically, in the repack command (§10), the mod-mode flow, and Stage 5 rebuilds of an already-shipped app. Minor/major are NEVER changed without an explicit user instruction. Rationale: the cube's catalog compares versions on install; an un-bumped rebuild may not apply over an installed app.

## 10. `repack` command

One command for the "я заменил ассеты — пересобери" cycle (today: four manual steps). Skill-level flow (orchestrator Mod mode T2/T3 uses it; also directly invokable):
1. refresh/replace source PNGs (whatever the user changed),
2. repack the beta container (same canonical invocation the app was built with),
3. auto patch-bump `APP_VERSION` (§9),
4. rebuild device package with ARM-embed verification,
5. hand back the `.oct` path.
Implementation: a `scripts/repack_app.(ps1|sh|py)` wrapper plus orchestrator/boilerplate doc text. It must detect the app's canonical pack invocation from what exists on disk (manifest present → manifest path; icon present → `--icon`), not require the user to remember flags.

## 11. Pure-python `.oct` builder

`pack_beta.py` gains `build_oct(app_dir, code_bin, out_path, *, title, guid, version, ...)`: assembles the full pack (232-byte header, 84-byte descriptor table with embedded octBmp_t copies, 4-byte-aligned payloads, ARM code tail, CRC32) exactly as the simulator does — all primitives already exist and are golden-tested. `build_device.(ps1|sh)` switches to it: ARM build → python `.oct` → tail verification. Consequences:
- the simulator is no longer needed for packaging (MSVC becomes optional, needed only for play-testing);
- the sim's in-memory assembly path and its size characteristics stop mattering for delivery;
- the "sim overwrites your .oct" footgun disappears from the delivery path (docs updated accordingly — the sim-written `.oct` remains a sim artifact only).
Verification: byte-compare a python-built `.oct` against a sim-built one for the same app (header fields that legitimately differ: BuildDateTime — pin it to 0 or copy; document).

## 12. Manifest animation numbering

The manifest's declarative animation grouping accepts BOTH zero-based (`_00, _01…`) and one-based (`_001…`) contiguous frame groups (2- or 3-digit suffixes). The packer already chains both (since `460a054`); the validator and `_derived_group` are updated to match, so manifests can declare any real-world asset set.

## 13. Animation guidelines (docs, from the owner)

Added to designer/prompter/orchestrator/verifier texts:
- **Hardware cap: 20 fps.** Never design/request faster.
- **Keep clips ≤ 5 s** as the default guideline (attention + pack size), though longer is technically possible — only app size limits it.
- **Prefer tier-1 animations** (palette 120×120, ×2 upscale) — the cheapest render path.
- **Fullsize animations: short and careful** — they load the cube; if frametime rises above **70 ms**, that's a bad sign — cut frames, size, or tier.
- **Full-color (tier-3) animations only on an explicit user request**, with a warning in the design that they must be treated VERY carefully.
- **At most ONE animated picture per physical module** (the photoframe rule): the four screens of a face belong to four different modules; adjacent faces share two. The designer/verifier check placement so no module carries two animated screens.

## 14. Out of scope

- Streaming read-ahead tuning (quadrant interleaving for very long clips) — document as a note, no tooling.
- Central key-management proxy (per-user quotas/revocation) — YAGNI until the team asks.
- Any change to stepwise mode's flow.

## 15. Implementation shape

Single branch `part2-autonomous-orchestrator`, one PR, two workstreams that can proceed in parallel after the tooling lands:
- **W1 tooling (code + tests):** provider adapter (§4), python `.oct` builder (§11), repack command (§10), auto-bump (§9), numbering (§12).
- **W2 orchestration (docs):** orchestrator SKILL.md rewrite (modes §2, questions §3, normalization §8, failure §6, telemetry §7), asset-builder placeholder-authoring section (§5), animation guidelines sweep (§13), boilerplate/verifier touches.
W2's text references W1's commands, so W1 merges into the branch first. E2E gate before PR: one autonomous run from a single fat prompt with no key configured (placeholder path) and one with a key, both ending in a verified `.oct`.
