# Source

Author: Alex Poshivalov. Taken (with the local changes listed below) from the attachment `wowcube-demo-video.skill` of the Confluence page
"AI Knowledge Base: OctaviOS Game Development" (wowcube.atlassian.net, games space, page 1052606466) on
2026-10-29. Changes to this skill belong in the author's copy first; keep this folder in sync with it.

## Local changes

Made in this repository after the import (2026-10-29); offer them to the author's copy:

- `templates/shot.h`: `header->SaveSize = APP_SAVE_SIZE` under `#ifdef APP_SAVE_SIZE`, as sim.h does, so a
  game without `app_save.h` compiles.
- `templates/capture.h`: a label sprite id at or above `CAPTURE_LABELS_MAX` (4096) no longer reads past the
  label table; it is written with an empty text.
- `examples/chemistry/capture.cpp` and SKILL.md: `on_pretwisted` gets the plane being turned
  (`(t % OCT_TWIST_HALF) / 2`, the engine's `OCT_TWIST_PRE + plane`), not the twist id.
- `examples/breakout/demo.json`: `ids` points at `src/app_breakout_ids.h` instead of the `<game>` placeholder.
- `scripts/render_demo.py`: a sprite-mode capture stops with a message when `ids` is not a file / has no
  `BMP_` lines or the sprite dump is empty, instead of rendering a blank video.
- `scripts/record_html.mjs` removed: the one copy is `wowcube-html-prototype/scripts/record_html.mjs`
  (identical); SKILL.md points there.
- SKILL.md description: every video request (including a video of a prototype) is this skill; building the
  prototype page is `wowcube-html-prototype`. Method A names the prototype's folder (`plans/` or `docs/`).
