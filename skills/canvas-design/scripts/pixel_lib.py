"""
pixel_lib.py — reusable pixel-art primitives for the WowCube canvas-design skill.

Use this when there is no real image-generation tool available in the
environment (no DALL-E / SD / Imagen) and you must produce pixel-art PNGs
that satisfy the `detailed_pixelart` style profile (see
`skills/cube_orchestrator/styles/detailed_pixelart.md`).

What this library is:
- A toolbox of pixel-art primitives (palette ramps, hard outlines, capsule
  highlights, dithering, light-direction shading, occlusion bands).
- A way to write per-game renderers that always satisfy the multi-tone /
  per-feature-highlight contract from the style profile.

What this library is NOT:
- A general-purpose image-generation tool. It cannot invent semantics.
  Every per-sprite rendering function still has to be hand-authored — the
  library only handles the common pixel-art chores.
- A replacement for real image generation when style fidelity matters.
  Output is "good placeholder", not "production art".

Naming convention used throughout:
- A `ramp` is a dict with the keys `hi`, `base`, `mid`, `deep` plus optional
  `accent`. Each value is an RGBA tuple `(r, g, b, a)` with a in [0..255].
- An `Image` is a PIL.Image in mode `RGBA`.
- Coordinates are zero-based (x, y) with x increasing right and y down.

Usage example (per-game renderer):

    from pixel_lib import (
        make_ramp, blank_rgba, place_capsule_highlight,
        trace_outline, add_occlusion_band, save_rgba,
    )

    STRAW = make_ramp(hi="#FFD8C0", base="#E23A2B", mid="#9C1B12", deep="#4A0A05")

    def render_strawberry():
        img = blank_rgba(48, 48)
        # 1) silhouette and base fill (per-sprite, not in lib)
        fill_heart_shape(img, 24, 26, 14, STRAW["base"])
        # 2) shading toward lower-right
        shade_lower_right(img, STRAW["base"], STRAW["mid"], strength=0.35)
        # 3) per-feature highlights (per-sprite)
        place_seed_pips(img, color=STRAW["hi"], count=7)
        # 4) capsule highlight upper-left
        place_capsule_highlight(img, cx=15, cy=14, length=5, ramp=STRAW)
        # 5) hard outline using deepest tone
        trace_outline(img, deep_color=STRAW["deep"])
        # 6) occlusion band lower-right
        add_occlusion_band(img, deep_color=STRAW["deep"], side="br")
        return img

    save_rgba(render_strawberry(), "assets/art/strawberry.png")

Quality bar enforced by this library:
- Every sprite produced via this lib uses at least 4 tones (ramp.hi/base/mid/deep).
- Every sprite has a 1-pixel hard outline using ramp.deep, NOT uniform black.
- Highlight placement defaults to upper-left to match the binding light
  direction (top-left ~35°) of `detailed_pixelart`.
- Per-feature pixel APIs (`place_feature_pixel`) make it cheap to add
  individual seed/grape/spike highlights, satisfying the detail-density
  rule of the style profile.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple

try:
    from PIL import Image, ImageDraw
except ImportError as e:
    raise ImportError(
        "pixel_lib requires Pillow. Install with `pip install --break-system-packages Pillow`."
    ) from e


# ---------------------------------------------------------------------------
# Type aliases (informational only)
# ---------------------------------------------------------------------------

RGBA = Tuple[int, int, int, int]
Ramp = Dict[str, RGBA]


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def parse_hex(s: str, alpha: int = 255) -> RGBA:
    """Parse '#RRGGBB', '#RGB', 'RRGGBB', or 'RGB' into an RGBA tuple."""
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad hex color {s!r}; expected #RRGGBB or #RGB")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return (r, g, b, alpha)


def make_ramp(hi: str, base: str, mid: str, deep: str,
              accent: Optional[str] = None) -> Ramp:
    """
    Build a 4-tone (optionally 5-tone) palette ramp for one sprite group.

    Order: highlight (lightest) → base → mid-shadow → deep-shadow / outline.
    The optional `accent` slot is for warm intrusions like a bomb spark or
    a leaf-green inside an otherwise-warm fruit ramp; it is NOT part of the
    main shading sequence and is only used at specific feature pixels.
    """
    ramp: Ramp = {
        "hi":   parse_hex(hi),
        "base": parse_hex(base),
        "mid":  parse_hex(mid),
        "deep": parse_hex(deep),
    }
    if accent:
        ramp["accent"] = parse_hex(accent)
    return ramp


def lighten(c: RGBA, t: float) -> RGBA:
    """Linear interpolation between c and white. t in [0..1]."""
    t = max(0.0, min(1.0, t))
    r, g, b, a = c
    return (
        int(r + (255 - r) * t),
        int(g + (255 - g) * t),
        int(b + (255 - b) * t),
        a,
    )


def darken(c: RGBA, t: float) -> RGBA:
    """Linear interpolation between c and black. t in [0..1]."""
    t = max(0.0, min(1.0, t))
    r, g, b, a = c
    return (int(r * (1 - t)), int(g * (1 - t)), int(b * (1 - t)), a)


# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------

def blank_rgba(w: int, h: int) -> Image.Image:
    """Fully-transparent RGBA canvas at the given size."""
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


def save_rgba(img: Image.Image, path: str) -> None:
    """Save the image to PNG, ensuring parent dir exists."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path, "PNG")


def put(img: Image.Image, x: int, y: int, color: RGBA) -> None:
    """Set a single pixel with bounds check (silently ignores out-of-bounds)."""
    w, h = img.size
    if 0 <= x < w and 0 <= y < h:
        img.putpixel((x, y), color)


def is_opaque(img: Image.Image, x: int, y: int) -> bool:
    """True if the pixel at (x, y) has alpha > 0 (i.e., is part of the sprite)."""
    w, h = img.size
    if not (0 <= x < w and 0 <= y < h):
        return False
    return img.getpixel((x, y))[3] > 0


# ---------------------------------------------------------------------------
# Light-direction shading (top-left ~35°)
# ---------------------------------------------------------------------------

def shade_lower_right(img: Image.Image, base_color: RGBA, mid_color: RGBA,
                      strength: float = 0.35) -> None:
    """
    Replace ~strength of base-color pixels with mid-color in the lower-right
    region, simulating shadow under top-left light. Pixels that aren't base_color
    are skipped (so existing details survive).
    """
    w, h = img.size
    for y in range(h):
        for x in range(w):
            px = img.getpixel((x, y))
            if px != base_color:
                continue
            nx = x / max(1, w - 1)
            ny = y / max(1, h - 1)
            # distance from upper-left, normalized to [0..1]
            d = (nx + ny) * 0.5
            if d > 1.0 - strength:
                img.putpixel((x, y), mid_color)


def apply_4tone_distribution(img: Image.Image, ramp: Ramp,
                             hi_radius: int = 4) -> None:
    """
    Walk every base-color pixel and reclassify into hi/base/mid by distance
    from the upper-left light pole. Useful when you fill the silhouette with
    `ramp.base` and want auto multi-tone shading without per-feature work.

    Order of operations:
      1. Pixels within `hi_radius` of the silhouette's UL extremum → hi.
      2. Pixels in the LR third → mid.
      3. Everything else stays base.
    """
    w, h = img.size
    base = ramp["base"]
    hi = ramp["hi"]
    mid = ramp["mid"]

    # find the UL extremum of the opaque region
    ul_x, ul_y = w, h
    lr_x, lr_y = 0, 0
    for y in range(h):
        for x in range(w):
            if is_opaque(img, x, y):
                if x + y < ul_x + ul_y:
                    ul_x, ul_y = x, y
                if x + y > lr_x + lr_y:
                    lr_x, lr_y = x, y
    if (ul_x, ul_y) == (w, h):
        return  # empty image

    span = max(1, (lr_x + lr_y) - (ul_x + ul_y))

    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y)) != base:
                continue
            d = (x + y) - (ul_x + ul_y)
            t = d / span  # 0 at UL extremum, 1 at LR extremum
            if abs(x - ul_x) + abs(y - ul_y) <= hi_radius:
                img.putpixel((x, y), hi)
            elif t > 0.65:
                img.putpixel((x, y), mid)


# ---------------------------------------------------------------------------
# Capsule highlight (the signature pixel-art shine)
# ---------------------------------------------------------------------------

def place_capsule_highlight(img: Image.Image, cx: int, cy: int,
                            ramp: Ramp, length: int = 4) -> None:
    """
    Place a capsule-shaped highlight (a few pixels arranged as a short
    diagonal rounded rectangle) using ramp.hi. Convention: capsule is
    drawn upper-left of (cx, cy) to match the binding top-left light.

    `length` is the long axis in pixels. The capsule is `length` wide,
    `max(2, length // 2)` tall, oriented at ~135° (UL-to-LR-of-the-spot).
    """
    hi = ramp["hi"]
    width = max(2, length // 2)
    # core: two-pixel-thick line, upper-left of center
    for i in range(length):
        x = cx - i
        y = cy - i
        for w in range(width):
            put(img, x - w, y, hi)
    # round one end with a single-pixel cap
    put(img, cx + 1, cy + 1, hi)


def place_secondary_spec(img: Image.Image, cx: int, cy: int,
                         ramp: Ramp) -> None:
    """One bright pixel `ramp.hi` at (cx, cy) — the small secondary specular
    that glossy fruits get in addition to the main capsule highlight."""
    put(img, cx, cy, ramp["hi"])


def place_feature_pixel(img: Image.Image, x: int, y: int,
                        color: RGBA, with_highlight: bool = False,
                        highlight_color: Optional[RGBA] = None) -> None:
    """
    Stamp a single feature pixel (seed, spike, dot). If `with_highlight`
    is True, also place a 1-pixel highlight at (x-1, y-1) using the
    given highlight_color (defaults to white).
    """
    put(img, x, y, color)
    if with_highlight:
        hc = highlight_color if highlight_color else (255, 255, 255, 255)
        put(img, x - 1, y - 1, hc)


# ---------------------------------------------------------------------------
# Dithering
# ---------------------------------------------------------------------------

def dither_2x2(img: Image.Image, region: Iterable[Tuple[int, int]],
               base_color: RGBA, alt_color: RGBA) -> None:
    """
    Apply 2×2 checkerboard dithering across `region`. Pixels where
    (x + y) % 2 == 0 stay `base_color`, the rest become `alt_color`.

    `region` is an iterable of (x, y) pairs (or a generator). The caller
    owns the choice of which pixels to dither — typically the band where
    base→mid would otherwise have a hard tone-step.
    """
    for (x, y) in region:
        if (x + y) % 2 == 0:
            put(img, x, y, base_color)
        else:
            put(img, x, y, alt_color)


def base_to_mid_band(img: Image.Image, base_color: RGBA, mid_color: RGBA,
                    band_width: int = 2) -> None:
    """
    Find every pixel that is `base_color` AND has at least one
    `mid_color` neighbor within `band_width`, then dither it 50/50.
    Smooths the otherwise-hard step between two ramp tones.
    """
    w, h = img.size
    band: list[Tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if img.getpixel((x, y)) != base_color:
                continue
            for dy in range(-band_width, band_width + 1):
                for dx in range(-band_width, band_width + 1):
                    if dy == 0 and dx == 0:
                        continue
                    if (0 <= x + dx < w) and (0 <= y + dy < h):
                        if img.getpixel((x + dx, y + dy)) == mid_color:
                            band.append((x, y))
                            break
                else:
                    continue
                break
    dither_2x2(img, band, base_color, mid_color)


# ---------------------------------------------------------------------------
# Outline (1-pixel hard, sprite-internal — uses ramp.deep, NOT pure black)
# ---------------------------------------------------------------------------

def trace_outline(img: Image.Image, deep_color: RGBA) -> None:
    """
    Add a 1-pixel hard outline around every opaque region of the sprite,
    using `deep_color`. Mutates the image in place. Skips edges of the
    canvas (respects the 1-pixel safety margin).

    Algorithm: for every transparent pixel that has at least one opaque
    8-neighbor, set it to `deep_color`. This grows the silhouette by one
    pixel; do it AFTER all interior shading is finalized.
    """
    w, h = img.size
    work = img.copy()  # read from a snapshot to avoid recursive growth
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if work.getpixel((x, y))[3] > 0:
                continue
            # transparent pixel — check 8 neighbors
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    if work.getpixel((x + dx, y + dy))[3] > 0:
                        img.putpixel((x, y), deep_color)
                        break
                else:
                    continue
                break


def add_occlusion_band(img: Image.Image, deep_color: RGBA,
                      side: str = "br", width: int = 1) -> None:
    """
    Add a 1–2 pixel occlusion band on one side of the sprite's silhouette.
    `side` ∈ {"br" (bottom-right, default), "b" (bottom), "r" (right)}.

    Sets the inner-most layer of the silhouette on that side to `deep_color`,
    creating a subtle ambient-occlusion read.
    """
    w, h = img.size
    work = img.copy()
    for y in range(h):
        for x in range(w):
            if work.getpixel((x, y))[3] == 0:
                continue
            # check if this pixel is on the named side of the silhouette
            on_right = work.getpixel((min(x + 1, w - 1), y))[3] == 0
            on_bottom = work.getpixel((x, min(y + 1, h - 1)))[3] == 0
            if side == "br" and (on_right or on_bottom):
                img.putpixel((x, y), deep_color)
            elif side == "b" and on_bottom:
                img.putpixel((x, y), deep_color)
            elif side == "r" and on_right:
                img.putpixel((x, y), deep_color)


# ---------------------------------------------------------------------------
# Bulk fills (helpers for per-game silhouette work)
# ---------------------------------------------------------------------------

def fill_circle(img: Image.Image, cx: int, cy: int, r: int, color: RGBA) -> None:
    """Filled circle (pixel-art, no AA). Uses Bresenham-style scanline fill."""
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                put(img, x, y, color)


def fill_ellipse(img: Image.Image, cx: int, cy: int, rx: int, ry: int,
                 color: RGBA) -> None:
    """Filled ellipse (pixel-art, no AA)."""
    if rx <= 0 or ry <= 0:
        return
    for y in range(cy - ry, cy + ry + 1):
        for x in range(cx - rx, cx + rx + 1):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                put(img, x, y, color)


def fill_polygon(img: Image.Image, points: Iterable[Tuple[int, int]],
                 color: RGBA) -> None:
    """Filled polygon via PIL ImageDraw — careful: this DOES introduce AA
    on diagonal edges. Only use for chunky shapes or call `harden_silhouette`
    afterward."""
    d = ImageDraw.Draw(img)
    d.polygon(list(points), fill=color)


def harden_silhouette(img: Image.Image, threshold: int = 200) -> None:
    """
    Force any pixel with alpha < `threshold` to fully transparent and any
    pixel with alpha >= `threshold` to fully opaque. Use after PIL's
    polygon/ellipse helpers if you don't want AA on the silhouette.
    """
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = img.getpixel((x, y))
            if a < threshold:
                img.putpixel((x, y), (0, 0, 0, 0))
            else:
                img.putpixel((x, y), (r, g, b, 255))


# ---------------------------------------------------------------------------
# Quality assertions (use these in render scripts to fail loud, per SKILL.md)
# ---------------------------------------------------------------------------

def assert_unique_colors(img: Image.Image, minimum: int,
                         label: str = "<unnamed>") -> None:
    """
    Raise AssertionError if the image has fewer than `minimum` unique colors.
    For 48×48 detailed_pixelart sprites the minimum should be 6.
    """
    cs = img.getcolors(maxcolors=4096) or []
    n = len(cs)
    if n < minimum:
        raise AssertionError(
            f"sprite {label!r} has {n} unique colors (< {minimum}). "
            f"This violates the detailed_pixelart multi-tone contract."
        )


def assert_safety_margin(img: Image.Image, label: str = "<unnamed>") -> None:
    """
    Raise AssertionError if any pixel on the canvas border (x=0, x=w-1,
    y=0, y=h-1) is opaque. Style profile requires a 1-pixel transparent
    margin on every side.
    """
    w, h = img.size
    for x in range(w):
        if img.getpixel((x, 0))[3] > 0 or img.getpixel((x, h - 1))[3] > 0:
            raise AssertionError(
                f"sprite {label!r} touches the top/bottom edge at x={x}; "
                f"detailed_pixelart requires a 1-pixel transparent margin."
            )
    for y in range(h):
        if img.getpixel((0, y))[3] > 0 or img.getpixel((w - 1, y))[3] > 0:
            raise AssertionError(
                f"sprite {label!r} touches the left/right edge at y={y}; "
                f"detailed_pixelart requires a 1-pixel transparent margin."
            )
