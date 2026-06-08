"""Deterministic PNG placeholder generator for cube_asset-builder.

Seeds all randomness from hashlib.md5 — identical manifest input produces
byte-identical PNG output, regardless of process/platform.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from manifest_schema import Manifest, Sprite, load_manifest

SHAPES = ("circle", "rounded_rect", "diamond", "hex", "triangle")

COLOR_KEYWORDS = {
    "red": 0.0, "orange": 0.08, "yellow": 0.16, "green": 0.33,
    "cyan": 0.5, "blue": 0.66, "purple": 0.77, "magenta": 0.9,
}
SHAPE_KEYWORDS = {
    "round": "circle", "circle": "circle",
    "square": "rounded_rect", "rect": "rounded_rect",
    "diamond": "diamond",
    "hex": "hex", "hexagon": "hex",
    "spiky": "triangle", "triangle": "triangle",
}


def _derived_group(s: Sprite) -> str:
    """Explicit group wins; otherwise strip a trailing _NN suffix."""
    if s.group:
        return s.group
    n = s.name
    if len(n) >= 3 and n[-3] == "_" and n[-2:].isdigit():
        return n[:-3]
    return n


def _md5_seed(label: str) -> int:
    """Stable integer seed from an MD5 digest of `label`."""
    return int(hashlib.md5(label.encode("utf-8")).hexdigest()[:8], 16)


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


class GroupStyle:
    """Visual style shared by all sprites in a group."""

    def __init__(self, group_name: str, desc_keywords: set[str]):
        seed = _md5_seed(group_name)
        hue = ((seed >> 0) & 0xFF) / 255.0
        for kw, h in COLOR_KEYWORDS.items():
            if kw in desc_keywords:
                hue = h
                break
        self.primary = _hsl_to_rgb(hue, 0.7, 0.55)
        self.secondary = _hsl_to_rgb((hue + 0.5) % 1.0, 0.5, 0.35)
        self.outline = _hsl_to_rgb(hue, 0.8, 0.20)
        shape = SHAPES[seed % len(SHAPES)]
        for kw, s_override in SHAPE_KEYWORDS.items():
            if kw in desc_keywords:
                shape = s_override
                break
        self.shape = shape


def _draw_shape(draw: ImageDraw.ImageDraw, shape: str, rect, fill, outline):
    x0, y0, x1, y1 = rect
    if shape == "circle":
        draw.ellipse(rect, fill=fill, outline=outline, width=2)
    elif shape == "rounded_rect":
        draw.rounded_rectangle(rect, radius=max(2, (x1 - x0) // 6),
                               fill=fill, outline=outline, width=2)
    elif shape == "diamond":
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        draw.polygon([(cx, y0), (x1, cy), (cx, y1), (x0, cy)],
                     fill=fill, outline=outline)
    elif shape == "hex":
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        r = min(x1 - x0, y1 - y0) / 2.0
        pts = [
            (cx + r * math.cos(math.radians(60 * i)),
             cy + r * math.sin(math.radians(60 * i)))
            for i in range(6)
        ]
        draw.polygon(pts, fill=fill, outline=outline)
    elif shape == "triangle":
        cx = (x0 + x1) // 2
        draw.polygon([(cx, y0), (x1, y1), (x0, y1)],
                     fill=fill, outline=outline)


def _render_sprite(sp: Sprite, style: GroupStyle) -> Image.Image:
    w, h = sp.size
    if sp.flags.bg and sp.flags.fullsize:
        img = Image.new("RGBA", (w, h), style.primary + (255,))
        draw = ImageDraw.Draw(img)
        stripe = style.secondary + (160,)
        for d in range(-h, w, 8):
            draw.line([(d, 0), (d + h, h)], fill=stripe, width=3)
        return img

    if sp.flags.bg:
        img = Image.new("RGBA", (w, h), style.primary + (255,))
        return img

    bg = style.secondary + (255,) if not sp.flags.alpha else (0, 0, 0, 0)
    img = Image.new("RGBA", (w, h), bg)
    draw = ImageDraw.Draw(img)

    if sp.flags.fullsize:
        img.paste(style.primary + (255,), (0, 0, w, h))
        stripe = style.secondary + (160,)
        for d in range(-h, w, 8):
            draw.line([(d, 0), (d + h, h)], fill=stripe, width=3)
        return img

    frame_offset = 0
    if sp.anim is not None and sp.frame is not None:
        frame_offset = sp.frame * 2

    pad = max(2, min(w, h) // 10)
    rect = (pad, pad + frame_offset, w - pad, h - pad + frame_offset)
    _draw_shape(draw, style.shape, rect,
                fill=style.primary + (255,),
                outline=style.outline + (255,))

    label = sp.name[:6]
    txt_color = style.outline + (255,)
    try:
        draw.text((pad + 1, pad + 1 + frame_offset), label, fill=txt_color)
    except Exception:
        pass

    return img


def _desc_keywords(desc: str) -> set[str]:
    return {w.strip(".,:;!?").lower() for w in desc.split()}


def _write_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=False, compress_level=6)


def _write_zero_png(out_dir: Path) -> None:
    z = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    _write_png(z, out_dir / "0.png")


def generate(manifest: Manifest, out_dir: Path, *, group: str | None = None) -> list[Path]:
    """Generate PNGs for every sprite in `manifest` to `out_dir`.

    If `group` is given, only sprites whose derived/explicit group matches
    are regenerated. `0.png` is always (re)written.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_zero_png(out_dir)

    group_map: dict[str, list[Sprite]] = {}
    for s in manifest.sprites:
        group_map.setdefault(_derived_group(s), []).append(s)

    written: list[Path] = []
    for grp, members in group_map.items():
        if group is not None and grp != group:
            continue
        desc_words: set[str] = set()
        for s in members:
            desc_words |= _desc_keywords(s.description)
        style = GroupStyle(grp, desc_words)
        for s in members:
            img = _render_sprite(s, style)
            target = out_dir / f"{s.name}.png"
            _write_png(img, target)
            written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate placeholder PNGs from an asset manifest.")
    p.add_argument("manifest", help="Path to <game>_assets.json")
    p.add_argument("--out", default="assets/art", help="Output directory (default: assets/art)")
    p.add_argument("--group", default=None, help="Regenerate only this group")
    args = p.parse_args(argv)

    m = load_manifest(args.manifest)
    written = generate(m, Path(args.out), group=args.group)
    print(f"gen_placeholders: wrote {len(written)} PNG(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
