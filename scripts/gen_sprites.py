"""AI sprite generator for cube_asset-builder.

Turns each sprite's `gen_prompt` (written by `technical_prompter`) into a PNG
via the OpenRouter image model in `genimg.py`.

AI output is NOT deterministic across runs.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image

from manifest_schema import Manifest, Sprite, load_manifest
import genimg

# Frame-sequence suffix: mirrors pack_beta._seq_frame_groups' _RE_SEQ_FRAME
# (2 or more digits) so a sprite derives the same group here as it chains
# into at pack time. A single digit ("_5") is not a sequence suffix to the
# packer either, so it is left attached to the base name here too.
_RE_FRAME_SUFFIX = re.compile(r"^(.+)_(\d{2,})$")


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


def generate(manifest: Manifest, out_dir: Path, *, group: str | None = None) -> list[Path]:
    """Generate one AI PNG per sprite in `manifest` to `out_dir`.

    Every sprite must carry a non-empty `gen_prompt` (AI mode). If `group` is
    given, only sprites whose derived/explicit group matches are regenerated.
    `0.png` is always (re)written.

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
        # Object sprites get their backdrop cut out for a clean transparent
        # background; frame-filling tiles (fullsize) and backgrounds (bg) keep
        # their solid fill.
        cutout = not (s.flags.bg or s.flags.fullsize)
        genimg.generate_image(s.gen_prompt, target, size=s.size, cutout=cutout)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate AI sprite PNGs from an asset manifest.")
    p.add_argument("manifest", help="Path to <game>_assets.json")
    p.add_argument("--out", default="assets/art", help="Output directory (default: assets/art)")
    p.add_argument("--group", default=None, help="Regenerate only this group")
    args = p.parse_args(argv)

    m = load_manifest(args.manifest)
    written = generate(m, Path(args.out), group=args.group)
    print(f"gen_sprites: wrote {len(written)} AI PNG(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
