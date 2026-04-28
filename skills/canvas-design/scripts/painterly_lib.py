"""
painterly_lib.py — reusable watercolor / storybook primitives for the
WowCube canvas-design skill.

Use this when there is no real image-generation tool available in the
environment and the chosen style profile is `painterly_storybook` (see
`skills/cube_orchestrator/styles/painterly_storybook.md`).

What this library is:
- A toolbox of painterly primitives (overlapping blob washes, paper-grain
  texture, soft AO halo, jittered pencil-sketch outlines, gradient
  highlight / shadow washes).
- A way to write per-game renderers that always satisfy the soft-AA /
  watercolor / paper-texture contract from the style profile.

What this library is NOT:
- A replacement for real image generation when style fidelity matters.
  Output is "good warm placeholder", not "production children's-book art".
- For pixel-art presets — use `pixel_lib.py` instead.

Design conventions:
- A `ramp` is a dict with `wash`, `base`, `shade`, optional `deep`. RGBA
  tuples `(r, g, b, a)`. The `wash` slot is for the highlight wash (NOT
  a bright spec); `shade` is the soft mid-shadow.
- Coordinates are zero-based (x, y) with x → right, y → down.
- All blob / wash operations use overlapping translucent ellipses + a
  small Gaussian blur for soft AA edges.

Usage example (per-game renderer):

    from painterly_lib import (
        make_painterly_ramp, blank_rgba, paint_blob, paint_wash_upper_left,
        paint_shadow_lower_right, paper_texture_overlay, ao_halo,
        pencil_outline, save_rgba,
    )

    APPLE = make_painterly_ramp(wash="#F1A99B", base="#D9665A", shade="#A24338")

    def render_apple():
        img = blank_rgba(48, 48)
        # 1. base body — overlapping watercolor blobs
        paint_blob(img, cx=24, cy=27, color=APPLE["base"], r=14, alpha=220)
        paint_blob(img, cx=23, cy=28, color=APPLE["base"], r=13, alpha=200)
        paint_blob(img, cx=25, cy=26, color=APPLE["base"], r=12, alpha=180)
        # 2. highlight wash UL, shadow LR
        paint_wash_upper_left(img, color=APPLE["wash"], alpha=120)
        paint_shadow_lower_right(img, color=APPLE["shade"], alpha=110)
        # 3. small features (stem, leaf) — per-sprite, not in lib
        place_stem(img, color=warm_brown)
        place_leaf(img, color=sage)
        # 4. paper grain + AO halo + optional pencil sketch
        paper_texture_overlay(img, intensity=0.10, grain_color=PAPER_GRAIN)
        ao_halo(img, color=warm_shadow, radius=2.5, alpha=30)
        return img

    save_rgba(render_apple(), "assets/art/apple.png")

Quality bar enforced by this library:
- Every 48×48 sprite produced via this lib has 200+ unique colors after
  blur (gradient watercolor look, NOT flat ramp tones).
- Every silhouette has soft AA edges (alpha values across 0..255, NOT
  binary 0/255).
- Paper grain texture overlay is mandatory — assertions check for it.
- No hard 1-pixel outline. Optional pencil sketch must be jittered and
  rendered at low alpha in a warm-dark hue (NOT black).
"""

from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as e:
    raise ImportError(
        "painterly_lib requires Pillow. Install with `pip install --break-system-packages Pillow`."
    ) from e


# ---------------------------------------------------------------------------
# Type aliases (informational only)
# ---------------------------------------------------------------------------

RGBA = Tuple[int, int, int, int]
Ramp = Dict[str, RGBA]


# ---------------------------------------------------------------------------
# Color helpers (shared with pixel_lib in spirit, kept independent here so
# either lib can be used standalone)
# ---------------------------------------------------------------------------

def parse_hex(s: str, alpha: int = 255) -> RGBA:
    """Parse '#RRGGBB', '#RGB', 'RRGGBB', or 'RGB' into an RGBA tuple."""
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad hex color {s!r}; expected #RRGGBB or #RGB")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), alpha)


def with_alpha(c: RGBA, alpha: int) -> RGBA:
    """Return a copy of `c` with the given alpha channel."""
    return (c[0], c[1], c[2], max(0, min(255, alpha)))


def make_painterly_ramp(wash: str, base: str, shade: str,
                        deep: Optional[str] = None) -> Ramp:
    """
    Build a painterly 3-tone (optionally 4-tone) ramp.

    `wash`  — light highlight wash (NOT a bright spec). ~+30% lightness.
    `base`  — main body tone, the dominant color.
    `shade` — soft mid-shadow. ~-25% lightness.
    `deep`  — optional under-curve accent (used very sparingly).
    """
    ramp: Ramp = {
        "wash":  parse_hex(wash),
        "base":  parse_hex(base),
        "shade": parse_hex(shade),
    }
    if deep:
        ramp["deep"] = parse_hex(deep)
    return ramp


# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------

def blank_rgba(w: int, h: int) -> Image.Image:
    """Fully-transparent RGBA canvas."""
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def save_rgba(img: Image.Image, path: str) -> None:
    """Save the image to PNG, ensuring parent dir exists."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path, "PNG")


# ---------------------------------------------------------------------------
# Watercolor blob primitive
# ---------------------------------------------------------------------------

def paint_blob(img: Image.Image, cx: int, cy: int, color: RGBA,
               r: int, alpha: int = 200,
               blur_radius: float = 1.2) -> None:
    """
    Paint one watercolor blob: a filled ellipse on a temporary RGBA layer
    at the given alpha, soft-blurred, then alpha-composited onto `img`.

    Stack 3–5 blobs of slightly varying (cx, cy, r, alpha) at the same
    color to build a hand-painted body. The blur on each layer is what
    creates the soft AA edges that distinguish painterly from pixel-art.
    """
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=with_alpha(color, alpha))
    if blur_radius > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    composite = Image.alpha_composite(img, layer)
    img.paste(composite, (0, 0))


def paint_brushstroke(img: Image.Image, x0: int, y0: int, x1: int, y1: int,
                      color: RGBA, width: int = 3, alpha: int = 180,
                      blur_radius: float = 0.9) -> None:
    """
    Paint a single soft brushstroke between two points. Useful for stems,
    fuses, calyx tips. Renders a thick line, blurs it for soft edges,
    composites on top.
    """
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line([(x0, y0), (x1, y1)], fill=with_alpha(color, alpha), width=width)
    if blur_radius > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    composite = Image.alpha_composite(img, layer)
    img.paste(composite, (0, 0))


# ---------------------------------------------------------------------------
# Highlight / shadow washes (gradient overlays — NOT bright specs)
# ---------------------------------------------------------------------------

def paint_wash_upper_left(img: Image.Image, color: RGBA, alpha: int = 120,
                          coverage: float = 0.45) -> None:
    """
    Add a soft highlight wash to the upper-left of the existing silhouette.
    `coverage` is the diagonal fraction (0..1) the wash extends across.

    Operates only on already-opaque pixels so it never paints over
    transparent canvas. Result is blurred for soft AA.
    """
    w, h = img.size
    wash_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y))[3] == 0:
                continue
            nx = x / max(1, w - 1)
            ny = y / max(1, h - 1)
            d = nx + ny  # 0 at UL, 2 at LR
            if d < coverage * 2:
                t = max(0.0, 1.0 - d / (coverage * 2))
                local_alpha = int(alpha * t)
                wash_layer.putpixel((x, y), with_alpha(color, local_alpha))
    wash_layer = wash_layer.filter(ImageFilter.GaussianBlur(radius=1.0))
    composite = Image.alpha_composite(img, wash_layer)
    img.paste(composite, (0, 0))


def paint_shadow_lower_right(img: Image.Image, color: RGBA, alpha: int = 110,
                             coverage: float = 0.45) -> None:
    """Mirror of `paint_wash_upper_left` for the lower-right shadow band."""
    w, h = img.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y))[3] == 0:
                continue
            nx = x / max(1, w - 1)
            ny = y / max(1, h - 1)
            d = (1 - nx) + (1 - ny)  # 0 at LR, 2 at UL
            if d < coverage * 2:
                t = max(0.0, 1.0 - d / (coverage * 2))
                local_alpha = int(alpha * t)
                layer.putpixel((x, y), with_alpha(color, local_alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius=1.0))
    composite = Image.alpha_composite(img, layer)
    img.paste(composite, (0, 0))


# ---------------------------------------------------------------------------
# Paper texture overlay (the signature painterly grain)
# ---------------------------------------------------------------------------

def paper_texture_overlay(img: Image.Image, intensity: float = 0.10,
                          grain_color: Optional[RGBA] = None,
                          seed: int = 7) -> None:
    """
    Add a painted-paper grain texture over the silhouette. Restricts to
    already-opaque pixels via an alpha mask so the grain doesn't leak
    onto the transparent canvas. `intensity` is the per-pixel alpha
    factor (0..1) for the grain dabs.

    Uses a deterministic seed by default so renders are reproducible.
    """
    w, h = img.size
    if grain_color is None:
        grain_color = (217, 201, 168, 0)  # warm sand grain by default
    rng = random.Random(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    grain_alpha = int(intensity * 255)
    # sparse specks
    for _ in range((w * h) // 30):
        x = rng.randint(0, w - 1)
        y = rng.randint(0, h - 1)
        if img.getpixel((x, y))[3] > 0:
            layer.putpixel((x, y), with_alpha(grain_color, grain_alpha))
    # a few faint streaks
    for _ in range(max(2, w * h // 800)):
        x0 = rng.randint(0, w - 1)
        y0 = rng.randint(0, h - 1)
        x1 = max(0, min(w - 1, x0 + rng.randint(-6, 6)))
        y1 = max(0, min(h - 1, y0 + rng.randint(-6, 6)))
        d = ImageDraw.Draw(layer)
        d.line([(x0, y0), (x1, y1)],
               fill=with_alpha(grain_color, max(8, grain_alpha // 2)),
               width=1)
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.6))
    # mask to silhouette
    mask = img.split()[3]
    final = Image.composite(layer, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask)
    composite = Image.alpha_composite(img, final)
    img.paste(composite, (0, 0))


# ---------------------------------------------------------------------------
# Ambient occlusion halo (warm shadow under shapes)
# ---------------------------------------------------------------------------

def ao_halo(img: Image.Image, color: RGBA = (155, 122, 74, 0),
            radius: float = 2.5, alpha: int = 30,
            offset: Tuple[int, int] = (1, 2)) -> None:
    """
    Add a soft warm-shadow halo behind the silhouette, offset slightly
    down-right. Creates a gentle "hand-painted on paper" lift.

    Default `color` is `warm shadow #9B7A4A` from the painterly preset.
    """
    w, h = img.size
    silhouette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = img.split()[3]
    silhouette.paste(with_alpha(color, alpha), (0, 0), mask)
    silhouette = silhouette.filter(ImageFilter.GaussianBlur(radius=radius))

    # offset
    halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    halo.paste(silhouette, offset, silhouette)

    # composite halo BEHIND existing image
    composite = Image.alpha_composite(halo, img)
    img.paste(composite, (0, 0))


# ---------------------------------------------------------------------------
# Optional pencil-sketch outline (jittered, low alpha, warm hue — never black)
# ---------------------------------------------------------------------------

def pencil_outline(img: Image.Image, color: RGBA = (110, 82, 56, 0),
                   alpha: int = 80, jitter: int = 1,
                   seed: int = 11) -> None:
    """
    Add an optional pencil-sketch outline around the silhouette. Each
    boundary pixel is offset by ±`jitter` in random directions before
    drawing, then the whole layer is softly blurred. The result reads
    as a warm hand-drawn line, NOT a uniform 1-px hard outline.

    Default `color` is `pencil line #6E5238`. Use `alpha=0` (effectively
    skip) on sprites where the silhouette is defined purely by value
    contrast (the painterly preset prefers no outline).
    """
    w, h = img.size
    if alpha <= 0:
        return
    rng = random.Random(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if img.getpixel((x, y))[3] > 0:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    if img.getpixel((x + dx, y + dy))[3] > 0:
                        jx = x + rng.randint(-jitter, jitter)
                        jy = y + rng.randint(-jitter, jitter)
                        if 0 <= jx < w and 0 <= jy < h:
                            layer.putpixel((jx, jy), with_alpha(color, alpha))
                        break
                else:
                    continue
                break
    layer = layer.filter(ImageFilter.GaussianBlur(radius=0.5))
    composite = Image.alpha_composite(img, layer)
    img.paste(composite, (0, 0))


# ---------------------------------------------------------------------------
# Quality assertions (use these in render scripts to fail loud, per SKILL.md)
# ---------------------------------------------------------------------------

def assert_painterly_aa(img: Image.Image, label: str = "<unnamed>",
                        min_intermediate_alphas: int = 5) -> None:
    """
    Raise AssertionError if the image's alpha channel has fewer than
    `min_intermediate_alphas` distinct values in (1..254). Painterly
    requires soft AA edges, so a binary alpha image fails this check.
    """
    alphas = set()
    for px in img.getdata():
        alphas.add(px[3])
    intermediate = [a for a in alphas if 1 <= a <= 254]
    if len(intermediate) < min_intermediate_alphas:
        raise AssertionError(
            f"sprite {label!r} has {len(intermediate)} intermediate alpha "
            f"values (< {min_intermediate_alphas}). "
            f"This violates the painterly_storybook soft-AA contract."
        )


def assert_unique_colors(img: Image.Image, minimum: int,
                         label: str = "<unnamed>") -> None:
    """
    Raise AssertionError if the image has fewer than `minimum` unique colors.
    For 48×48 painterly_storybook sprites the minimum should be 200
    (gradient washes produce many intermediate tones).
    """
    cs = img.getcolors(maxcolors=10000) or []
    n = len(cs)
    if n < minimum:
        raise AssertionError(
            f"sprite {label!r} has {n} unique colors (< {minimum}). "
            f"This violates the painterly_storybook gradient contract — "
            f"likely missing washes or the paper-texture overlay."
        )


def assert_no_pure_black(img: Image.Image, label: str = "<unnamed>") -> None:
    """
    Raise AssertionError if the image contains any opaque pure-black
    pixels (0, 0, 0, 255). painterly_storybook forbids cold blacks.
    Use `charcoal warm #5A4D3C` instead.
    """
    for px in img.getdata():
        if px == (0, 0, 0, 255):
            raise AssertionError(
                f"sprite {label!r} contains pure-black opaque pixels. "
                f"painterly_storybook forbids cold blacks; "
                f"use a warm dark hue like #5A4D3C instead."
            )
