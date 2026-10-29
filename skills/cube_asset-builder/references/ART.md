# Art on a WowCube manifest

How the asset builder drives `skills/cube_art-director` (`scripts/art.py`) on
`plans/<game>_assets.json`, and the fallbacks when Codex is not available.
The art director's own rules (style bible, anchors, QA, review page) are in
its `SKILL.md`, `references/QA_RULES.md` and `references/CODEX.md`.

`ART` = `python <skills>/skills/cube_art-director/scripts/art.py`,
`M` = `plans/<game>_assets.json`; commands run from the project root.

## Provider chain

`scripts/image_providers.resolve_provider()` — first hit wins:

| # | Provider | Needs | How it draws |
|---|---|---|---|
| 0 | `codex` (default) | Codex CLI logged in with the user's ChatGPT account: newest `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` or `codex` on PATH; `codex login status` mentions ChatGPT | `build_pipeline.py generate` delegates the whole manifest to `ART gen` + `ART process` (style anchors, chroma-key backdrop, sets, colour lock); `genimg.py` one-offs go through a throw-away art.json |
| 1 | OpenRouter | `OPENROUTER_API_KEY` env var | paid; one `genimg` call per sprite |
| 2 | any key/URL | `IMAGE_API` env var (bare key/URL or JSON `{"provider","key","base_url","model"}`) | paid (or local SD) |
| 3 | any key/URL | `~/.wowcube/image_api.json` (written by `image_providers.save_provider()`) | same |
| – | none | — | agent-drawn placeholders (below) |

- **Paid keys are opt-in.** Steps 1-3 are used only with `WOWCUBE_ALLOW_PAID_IMAGES=1` (or `--allow-paid` on
  `build_pipeline.py generate`, `gen_sprites.py`, `genimg.py`); without it a key found in the environment is ignored and
  generation stops with exit 3 and the reason (an agent once paid through a key that happened to be set). Set the
  opt-in only when the user asked for a paid provider.
- `WOWCUBE_NO_CODEX=1` skips step 0 (use a key although Codex is logged in).
- Keys are recognised by pattern: `sk-or-` OpenRouter, `sk-` OpenAI, `xai-` xAI, `AIza` Gemini, `http(s)://` local Stable Diffusion (A1111).
- `image_providers.validate(cfg)` is the cheapest check per provider (Codex: `codex login status`).
- The paid path loses what only art.py has (anchors, subject references, shared scale, colour lock): it puts `_style` in front of each `gen_prompt`, asks for a flat backdrop, removes it by flood fill and resizes. Run the same QA (`ART qa M`) and review on its output.
- Never ask the user for a key while Codex works; never type credentials (`codex login` is the user's).

## No Codex: what still works with a paid provider

`ART candidates` and `ART gen` call the Codex CLI directly; without Codex they cannot draw. Every other art.py command works on images that already exist, so a configured paid provider still gives a style lock and the strict QA loop:

1. **Draw** with the provider: `python <skills>/scripts/build_pipeline.py generate --manifest M --workspace assets_<game>` (first `--group <g>` for the style frame's leaders, later the rest). Each sprite is drawn from `_style` + its `gen_prompt` on a flat backdrop, flood-filled and fitted to `size` straight into `assets_<game>/art/`; `fixes.json`, anchors and subject references are not used on this path.
2. **Hand the images to art.py**: copy them into `assets_<game>/raw/` under the same names (`Copy-Item assets_<game>\art\*.png assets_<game>\raw\` / `cp assets_<game>/art/*.png assets_<game>/raw/`). Then `ART process M` (re-key, shared scale per set, colour lock), the mock (below), the style lock from the approved leaders (`ART anchor M --only <leaders>`, `ART style M`), `ART qa M` and `ART review M` all work as on the Codex path.
3. **Fix loop**: record each fix in `fixes.json` as usual (a later Codex run replays it) and redraw one sprite with the provider: `python <skills>/scripts/genimg.py "<_style> <gen_prompt> <fix line>" -o assets_<game>/raw/<name>.png --cutout` for a `key` sprite (add the backdrop sentence the provider path writes: "Square canvas, one subject centred with a clear margin, on a flat uniform #FF00FF magenta background, no shadow", green `#00FF00` for a pink subject); no `--cutout` for an opaque picture; `-i assets_<game>/raw/<leader>.png` attaches a subject reference (Codex and OpenRouter only). Then `ART process M --only <name>` and `ART qa M --only <name>`. A fix that belongs in the subject prompt goes back to Stage 2.
4. The same QA rules apply (`cube_art-director/references/QA_RULES.md`); the style rules are measured against the anchors made in step 2. The final report says which provider drew the art.

## Placeholders (last resort)

Only when no provider resolves. The agent draws each sprite itself (ad-hoc Pillow code) into `assets_<game>/art/<name>.png` and writes `assets_<game>/art/0.png` (1×1 transparent): exact manifest `size`; cut-outs RGBA with alpha 0 around the silhouette, opaque pictures alpha 255 everywhere; shapes and colours distinct enough to playtest. They pack like any art, are **never accepted as final**, and the hand-off says the graphics are temporary. Sounds still get `gen_sounds.py` placeholders (`build_pipeline.py generate` is not usable without a provider; run `python <skills>/scripts/gen_sounds.py M`).

## fixes.json

`assets_<game>/fixes.json` is replayed on every regeneration. Every Codex run of `build_pipeline.py generate` merges in a subject reference from each later animation frame to its first frame (existing text kept; an entry that already names a `ref`, `null` included, is left alone); everything else is the reviewer's decision:

```json
{
  "*": "a line appended to every prompt (rare: prefer STYLE.md)",
  "hero_walk_01": {"text": "", "ref": "hero_walk_00"},
  "hero_shoot": {"text": "Keep her identical; only the recoil pose changes.", "ref": "hero_idle"},
  "zombie_hurt_00": {"text": "Same zombie, add wounds only.", "ref": "zombie_walk_00"},
  "muzzle_flash_00": "Only the flash burst itself: no person, no hands, no gun.",
  "@colour_lock": ["hero_", "zombie_"],
  "@colour_exempt": ["_hurt"],
  "@fill": {"table": 0.8, "floor": 1.0},
  "@style_exempt": ["logo", "banner_"],
  "@pose_exempt": ["_attack"],
  "@post": "post_process.py"
}
```

| Key | Meaning |
|---|---|
| `<name>`: text or `{"text", "ref"}` | prompt line for that sprite; `ref` = an **asset name** whose raw image is attached as the subject reference (same design, only the asked change). Write asset names, not paths. |
| `@colour_lock` | name prefixes: colour-matched to the first locked member of their set (same `group` and `size`) |
| `@colour_exempt` | name substrings: intended colour changes (wounded, broken), matched among themselves |
| `@fill` | name prefix → minimum share of the canvas the object must cover (cells, tiles) |
| `@style_exempt` | name prefixes: approved departures from the style palette (logo, UI, sky); add them under "Approved exceptions" in STYLE.md |
| `@pose_exempt` | name substrings: frames whose pose change is the point (scale rules only warn) |
| `@post` | a workspace script `ART process` runs after every run as `python <script> <final dir> <names>`: processing fixes no option expresses (stamp an outline, re-crop around a ring, clamp chroma). Without it a later `process` silently undoes hand edits to the finals; a failing script fails `process` |

An older workspace may hold `prompt_overrides.json` (keys `@colour_match`, `@colour_match_exclude`, `@fill_cell`); art.py reads it when `fixes.json` is absent.

## Keys and backdrops

Every sprite's manifest `background` decides: `"key"` = drawn on a flat backdrop and keyed (binary alpha), `"opaque"` = full-canvas picture. Without the field art.py infers it (full colour or `flags.bg` → opaque; a prompt naming `#FF00FF`/`#00FF00` → key; otherwise opaque) — ask Stage 2 to add it. The backdrop is magenta unless the prompt or the style palette is pink/magenta/purple (then green); the colour used is recorded in `raw/keys.json`, so adding anchors later never re-keys an old image. Holes that must stay solid (glass, gaps) are described as dark in the prompt.

## Mock

The style frame is judged at cube resolution. Regular sprites draw ×2 from their authored size, the screen is 240×240, a face is 2×2 screens with a bezel between them. A full-screen candidate (opaque scene) as the cube shows it:

```python
from PIL import Image
c = Image.open("assets_<game>/style/candidates/candidate_01.png").convert("RGB")
c.resize((120, 120), Image.BOX).resize((240, 240), Image.NEAREST).save("assets_<game>/style/mock.png")
```

A screen composed from drawn leaders (finals in `assets_<game>/art/`), every regular sprite scaled ×2 nearest (fullsize ×1):

```python
from PIL import Image
scr = Image.open("assets_<game>/art/floor.png").convert("RGBA").resize((240, 240), Image.NEAREST)
for name, (x, y) in {"hero_idle": (120, 140), "zombie_walk_00": (60, 60), "heart_full": (30, 220)}.items():
    s = Image.open(f"assets_<game>/art/{name}.png").convert("RGBA")
    s = s.resize((s.width * 2, s.height * 2), Image.NEAREST)
    scr.alpha_composite(s, (x - s.width // 2, y - s.height // 2))
scr.save("assets_<game>/style/mock.png")
```

Show the user the mock next to the candidate; extend the same composition in Step 4 to check every new family in context.

## Panoramas

Scenery that spans screens is ONE picture split per screen (never the same tile on every screen). The manifest lists the pieces as ordinary opaque sprites plus a `_panoramas` entry: `{"<pano>": {"size": [W, H], "grid": [cols, rows], "pieces": [row-major names], "gen_prompt": "..."}}`.

Default: one face = `[240, 240]`, grid `[2, 2]`, left and right edges tiling seamlessly, so the face picture repeated on the four side faces runs continuously around the cube. Unique objects (moon, sun) are separate sprites placed once. The code places each piece at `+-QUAD_FILL` (119.5), not `+-120`, or a 2-px line of the background splits the picture along the inner screen edges (template API.md "Coordinates").

1. Nothing to set up: `ART gen M` draws every `_panoramas` entry ONCE with Codex (opaque, the style anchors
   attached, the Prompt block in front, plus "one continuous picture cut into a cols x rows grid: no focal object on
   the cut lines; left and right edges join seamlessly") into `assets_<game>/raw/_pano_<pano>.png` and cuts it into
   the pieces' raw images (row-major, grid `[cols, rows]`). The pieces are never drawn one by one; their own
   `gen_prompt` is only a description. `fixes.json` entries keyed by the panorama name apply to the whole picture.
2. `ART process M --only <pieces>` and `ART qa M --only <pieces>`; look at `raw/_pano_<pano>.png` and at the pieces
   side by side (continuity across the cuts and around the cube).
   Which anchors: every style anchor is attached unless the `_panoramas` entry lists (`[]` = none)
   `"anchors": ["<asset>", ...]`: name the scenery anchors (ground, sky, props), never a character that would
   leak into the landscape. The Prompt block is written for the playfield; when the panorama is seen another way
   (a front view around a top-down playfield) its `gen_prompt` says so: "a flat front view, not an overhead view".
3. Redraw: `ART gen M --only <any piece> --force` redraws the whole panorama and re-cuts all its pieces.

## Launcher icon

160×160 RGBA, a **flat-top hexagon badge** (horizontal top and bottom edges, points left and right — the outline of `<skills>/templates/app_ai_template/art/icon.png`), transparent outside the hexagon, in the game's style.

1. The manifest carries it as the sprite `launcher_icon` (`icon` is reserved): `[160, 160]`, `color: "palette"` + `flags.fullsize` (so the PNG keeps its transparent corners through processing), `background: "key"`, `group: "icon"`. It is drawn with the set (`ART gen`/`process`), so the anchors and the Prompt block apply.
2. Check it like any asset, plus: the four corners transparent in the PNG, flat top and bottom edges, points left and right, readable at 80 px. If the badge outline breaks the style palette on purpose, add `"@style_exempt": ["launcher_icon"]` to `fixes.json` and note it under "Approved exceptions" in STYLE.md.
3. Copy `assets_<game>/art/launcher_icon.png` to `app_<game>/art/icon.png` (replacing the template icon) and pack with `--icon app_<game>/art/icon.png`; the pack builds the launcher's `ico` map from it.
4. **The packed tier decides whether the corners stay transparent.** The manifest's top-level `icon` object picks it: the default, full colour 160, is RAW565 with no transparency, so the corners render black on the dark launcher (a black square around the hexagon). Real transparent corners need `"icon": {"color": "palette", "side": 120}` (drawn ×2) or `240` (fullsize): the packer resizes the PNG to that side and keeps its alpha as palette index 0. Changing the `icon` object is a manifest change (Stage 2).
5. A manifest made before this rule has no `launcher_icon`: ask Stage 2 to add the entry (never hand-edit the manifest here).
