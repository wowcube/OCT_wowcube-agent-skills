# Source

Author: Alex Poshivalov. Taken (with the local changes listed below) from the attachment `wowcube-html-prototype.skill` of the Confluence page
"AI Knowledge Base: OctaviOS Game Development" (wowcube.atlassian.net, games space, page 1052606466) on
2026-10-29. Changes to this skill belong in the author's copy first; keep this folder in sync with it.

## Local changes

Made in this repository after the import (2026-10-29); offer them to the author's copy:

- `references/example-maze_box.html`: links `common/cube.css` and `common/cube.js`, the layout SKILL.md
  prescribes, instead of `../assets/`.
- SKILL.md "Where to put it": pipeline games use `plans/<game>_prototype.html` + `plans/common/` (as
  `cube_game-designer` Step 5), an existing game repository keeps `docs/`; autonomous runs build one only when
  the brief asks.
- SKILL.md description: this skill builds the page; recording or rendering any video (also of a prototype) is
  `wowcube-demo-video`, which uses this skill's `scripts/record_html.mjs` (now the only copy).
- `scripts/record_html.mjs`: the default query adds `video`, so a recording never plays sound (the skill silences
  sound only under `?video`).
