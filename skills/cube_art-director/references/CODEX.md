# Driving the Codex CLI for images

Images come from the Codex CLI's built-in image generation tool, billed to
the user's ChatGPT subscription. No API key, no OpenRouter, nothing paid per
call. `scripts/art_codex.py` wraps everything below; this page is for
debugging and for running Codex by hand.

## Setup check

- Binary: newest `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` on Windows (often not on PATH), else `codex` on PATH.
- `codex login status` must say it is logged in with ChatGPT. If not, the user runs `codex login` themselves (never type credentials for them).
- Model: the strongest visible model at its maximum reasoning effort. `art_codex.pick_model()` reads `~/.codex/models_cache.json` (lowest `priority` among `visibility: "list"` models) and picks its highest effort below `ultra` (ultra = max + auto-delegation, not deeper). The `model` pinned in `~/.codex/config.toml` may be rejected under ChatGPT auth, so always pass `-m`. Override with `ART_CODEX_MODEL` / `ART_CODEX_EFFORT`.

## One call

```
codex exec -m <model> -c model_reasoning_effort="<effort>" --skip-git-repo-check \
  -C <short temp dir> -s workspace-write --ephemeral -i <anchor.png> [-i <subject.png>] -
```
The prompt goes on stdin: "Use your built-in image generation tool exactly
once ... save the PNG as <name>.png in the current directory". The output is
1024x1024 when asked for a square canvas.

## Gotchas (each one broke a batch once)

| Symptom | Cause | Fix (already in art_codex.py) |
|---|---|---|
| Two assets come back as the same picture | parallel runs share `~/.codex/generated_images`; Codex's own "copy the newest PNG" grabs a sibling's image | take the PNG from `generated_images/<this run's session id>/` |
| CLI fails before drawing on Windows | long working-directory path | short temp dir `%TEMP%\artgen\<name>` |
| "model is at capacity" / 429 | transient | retry with back-off |
| The reference itself is returned or edited | reference in the work dir | refs attached with `-i` from outside the work dir; prompt forbids returning them |
| A person appears inside an effect sprite | the style anchor's content leaks | prompt says "copy ONLY the style"; add an explicit "no characters" fix for effect assets |
| Pink character keyed out in holes | magenta backdrop vs pink subject | green key (`key: green`, or automatic when the prompt/palette is pink) |
| Glass / gaps become transparent | key colour visible through holes | describe them as dark/solid in the prompt |
| Frames of one character drift in colour | separate generations | `colour_lock` (matched to the set's first frame) |
| Cost of a long batch | one image per call, minutes each | `--jobs 3` in parallel; regenerate only failures (`--only`) |

## Consulting Codex as a second opinion

Codex can also review instead of draw: run `codex exec` with `-s read-only`
and a prompt like "Compare these two images against the style bible below;
list every difference in palette, outline, shading, viewpoint" with the
anchor and the candidate attached. Useful when Claude and the artist
disagree, or as the independent consistency pass before a review round.
