"""AI sprite generator for cube_asset-builder.

Two paths, picked by the resolved image provider
(`image_providers.resolve_provider()`):

- **codex** (default: Codex CLI on the user's ChatGPT subscription, no key):
  `generate_codex()` hands the whole manifest to cube_art-director's art.py
  (`gen` + `process`): STYLE.md Prompt block and style anchors on every
  prompt, the sprite's `background` (flat chroma-key backdrop, keyed, or an
  opaque full-canvas picture), shared scale + centroid alignment per
  animation, subject references and colour lock from
  `<workspace>/fixes.json`. Final PNGs land in `<workspace>/art/`.
- **paid API key** (OpenRouter, OpenAI, xAI, Gemini, local SD; the fallback):
  `generate()` runs one `genimg.generate_image()` call per sprite, removes a
  flat backdrop by flood fill and resizes to the manifest size.

AI output is NOT deterministic across runs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

from manifest_schema import Manifest, Sprite, load_manifest
import genimg
import image_providers

# Frame-sequence suffix: mirrors pack_beta._seq_frame_groups' _RE_SEQ_FRAME
# (2 or more digits) so a sprite derives the same group here as it chains
# into at pack time. A single digit ("_5") is not a sequence suffix to the
# packer either, so it is left attached to the base name here too.
_RE_FRAME_SUFFIX = re.compile(r"^(.+)_(\d{2,})$")

# words that make a magenta backdrop unsafe (the subject would be keyed out)
_PINKISH = ("pink", "magenta", "fuchsia", "purple", "violet")


def _derived_group(s: Sprite) -> str:
    """Explicit group wins; otherwise strip a trailing 2+ digit _NN.. suffix."""
    if s.group:
        return s.group
    m = _RE_FRAME_SUFFIX.match(s.name)
    return m.group(1) if m else s.name


def _write_zero_png(out_dir: Path) -> None:
    """The packer expects a 1x1 transparent `0.png` sentinel."""
    out_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(out_dir / "0.png", format="PNG")


def is_cutout(s: Sprite) -> bool:
    """True when the sprite is a cut-out (drawn on a flat backdrop that is
    keyed away), False for an opaque full-canvas picture. The manifest's
    explicit `background` ("key" | "opaque") wins; older manifests: backgrounds
    (`flags.bg`), fullsize art and full-colour art (no transparency) are
    pictures, everything else is a cut-out."""
    if s.background == "key":
        return True
    if s.background == "opaque":
        return False
    return not (s.flags.bg or s.flags.fullsize or s.color == "full")


def manifest_style(manifest_path) -> str | None:
    """The manifest's top-level `_style` string (the per-game style that also
    feeds assets_<game>/style/STYLE.md's Prompt block), or None."""
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    style = data.get("_style")
    return style.strip() if isinstance(style, str) and style.strip() else None


def api_prompt(s: Sprite, style: str | None = None) -> str:
    """The prompt sent to a paid-API provider for one sprite.

    On the Codex path art.py adds the style (STYLE.md Prompt block) and the
    backdrop sentence itself; the API path has neither, so the per-game
    `_style` goes in front (unless the gen_prompt already carries it) and a
    cut-out gets the flat chroma-key backdrop its flood-fill keyer relies on
    (green when the subject is pinkish, magenta otherwise)."""
    body = (s.gen_prompt or "").strip()
    parts = [style] if style and style not in body else []
    parts.append(body)
    low = body.lower()
    if is_cutout(s) and "#ff00ff" not in low and "#00ff00" not in low:
        key = "#00FF00 green" if any(w in low for w in _PINKISH) else "#FF00FF magenta"
        parts.append(f"Square canvas, one subject centred with a clear margin, on a flat uniform {key} "
                     "background (no gradient, no floor, no shadow); the subject never uses that colour.")
    return "\n\n".join(parts)


def generate(manifest: Manifest, out_dir: Path, *, group: str | None = None,
             style: str | None = None) -> list[Path]:
    """Paid-API path: one AI PNG per sprite in `manifest` to `out_dir`.

    Every sprite must carry a non-empty `gen_prompt`. If `group` is given,
    only sprites whose derived/explicit group matches are regenerated.
    `style` is the manifest `_style` string (see api_prompt). `0.png` is
    always (re)written.

    Raises ImageGenError (from genimg) on API/network failure, and ValueError
    if a selected sprite has no `gen_prompt`.
    """
    out_dir = Path(out_dir)
    _write_zero_png(out_dir)

    written: list[Path] = []
    for s in manifest.sprites:
        if group is not None and _derived_group(s) != group:
            continue
        if not (s.gen_prompt and s.gen_prompt.strip()):
            raise ValueError(
                f"sprite {s.name!r} has no gen_prompt — required for AI "
                f"generation. Add it to the manifest (technical_prompter "
                f"Step 4a) or regenerate the manifest."
            )
        target = out_dir / f"{s.name}.png"
        genimg.generate_image(api_prompt(s, style), target, size=s.size, cutout=is_cutout(s))
        written.append(target)
    return written


def seed_fixes(manifest: Manifest, workspace: Path) -> list[str]:
    """Give every later animation frame a subject reference to the first frame
    of its animation in <workspace>/fixes.json (created when missing), so all
    frames keep one design (each frame is otherwise drawn from scratch and
    drifts). Merges, never overwrites: an entry's text is kept, and an entry
    that already names a "ref" — `null` meaning "deliberately none" — is left
    alone, so rerunning is a no-op. Skipped while only a legacy
    prompt_overrides.json exists (art.py reads it only as long as fixes.json
    is absent). Colour lock (`@colour_lock`, `@colour_exempt`), refs for state
    variants (hurt, attack, shoot) and "no characters" lines for effects stay
    the reviewer's decisions. Returns the sprite names that got a ref."""
    ws = Path(workspace)
    path = ws / "fixes.json"
    if not path.exists() and (ws / "prompt_overrides.json").exists():
        return []
    try:
        fixes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    first: dict[str, tuple[int, str]] = {}
    for s in manifest.sprites:
        if s.anim is not None and (s.anim not in first or s.frame < first[s.anim][0]):
            first[s.anim] = (s.frame, s.name)
    added: list[str] = []
    for s in manifest.sprites:
        if s.anim is None or first[s.anim][1] == s.name:
            continue
        cur = fixes.get(s.name)
        if isinstance(cur, dict) and "ref" in cur:
            continue
        entry = dict(cur) if isinstance(cur, dict) else {"text": cur if isinstance(cur, str) else ""}
        entry.setdefault("text", "")
        entry["ref"] = first[s.anim][1]
        fixes[s.name] = entry
        added.append(s.name)
    if added:
        ws.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixes, indent=1, ensure_ascii=False), encoding="utf-8")
    return added


def generate_codex(manifest_path, workspace, *, manifest: Manifest | None = None,
                   group: str | None = None, force: bool = False,
                   jobs: int | None = None) -> list[Path]:
    """Codex path: draw the manifest through cube_art-director's art.py.

    `group` limits the run to the sprites of one derived group (art.py
    `--only`); `force` redraws sprites that already have a raw image;
    `jobs` = parallel Codex runs. Returns the final PNGs in
    <workspace>/art/ for the selected sprites. Raises
    image_providers.ImageGenError when a step failed."""
    manifest = manifest or load_manifest(manifest_path)
    workspace = Path(workspace)
    only = None
    if group is not None:
        only = [s.name for s in manifest.sprites if _derived_group(s) == group]
        if not only:
            return []
    seeded = seed_fixes(manifest, workspace)
    if seeded:
        print(f"  {workspace / 'fixes.json'}: {len(seeded)} later animation frame(s) now reference "
              f"their first frame ({', '.join(seeded)})")
    image_providers.codex_generate(manifest_path, workspace, only=only, force=force, jobs=jobs)
    art = workspace / "art"
    names = only or [s.name for s in manifest.sprites]
    return [art / f"{n}.png" for n in names if (art / f"{n}.png").is_file()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate AI sprite PNGs from an asset manifest.")
    p.add_argument("manifest", help="Path to plans/<game>_assets.json")
    p.add_argument("--out", default=None,
                   help="Art dir = <workspace>/art (default: assets_<game>/art next to plans/)")
    p.add_argument("--group", default=None, help="Regenerate only this group")
    p.add_argument("--force", action="store_true", help="Codex: redraw sprites that already have a raw image")
    p.add_argument("--jobs", type=int, default=3, help="Codex: parallel runs (default 3)")
    p.add_argument("--allow-paid", action="store_true",
                   help="Opt in to a PAID image API when no Codex CLI is logged in (same as "
                        "WOWCUBE_ALLOW_PAID_IMAGES=1); only after the user agreed to pay per image")
    args = p.parse_args(argv)
    if args.allow_paid:
        import os
        os.environ[image_providers.ALLOW_PAID_ENV] = "1"      # this process only

    m = load_manifest(args.manifest)
    out = Path(args.out) if args.out else default_workspace(args.manifest, m.game) / "art"
    try:
        config = image_providers.resolve_provider()
        if config is not None and config.provider == image_providers.CODEX_PROVIDER:
            if out.name != "art":
                print("ERROR: with the codex provider --out must be <workspace>/art (art.py writes there)",
                      file=sys.stderr)
                return 2
            written = generate_codex(args.manifest, out.parent, manifest=m, group=args.group,
                                     force=args.force, jobs=args.jobs)
        else:
            written = generate(m, out, group=args.group, style=manifest_style(args.manifest))
    except (image_providers.ImageGenError, ValueError) as e:
        print(f"ERROR: sprite generation failed: {e}", file=sys.stderr)
        return 1
    print(f"gen_sprites: wrote {len(written)} PNG(s) to {out}")
    return 0


def default_workspace(manifest_path, game: str) -> Path:
    """assets_<game>/ at the project root (the folder that holds plans/) -
    the same folder cube_art-director's art.py uses for a WowCube manifest."""
    p = Path(manifest_path).resolve()
    root = p.parent.parent if p.parent.name == "plans" else p.parent
    return root / f"assets_{game}"


if __name__ == "__main__":
    sys.exit(main())
