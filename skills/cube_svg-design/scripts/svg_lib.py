"""
svg_lib.py — reusable SVG primitives for cube_svg-design.

Use this when the active style profile is one of:
- minimalist_flat
- cartoon_thick_outline
- realistic_render

For raster-native styles (detailed_pixelart, retro_8bit, painterly_storybook)
use canvas-design's pixel_lib / painterly_lib instead.

What this library is:
- A toolbox of SVG primitives (canvas, palettes, gradients, shadows,
  outlines, embedded brand-font text) plus per-style assertions.
- A way to write per-game renderers that always satisfy the SVG-friendly
  style profiles' contracts.

What this library is NOT:
- A general-purpose vector renderer. Each per-sprite renderer is still
  hand-authored — the lib only handles the common SVG chores.
- A replacement for `pixel_lib`/`painterly_lib`. Different output format,
  different quality model.

Naming convention:
- A `palette` is a dict with at minimum `base`, `highlight`, `outline`
  keys; richer styles add `mid`, `deep`, `accent`, `shadow`, `subsurface`.
- An RGB/RGBA color is an `(r, g, b)` or `(r, g, b, a)` tuple of int 0..255,
  OR a `#RRGGBB`/`#RRGGBBAA` string.
- All coordinates are in SVG user units (== pixels for this skill).

Authoring example (minimalist_flat):

    from svg_lib import (
        SvgCanvas, make_palette, hex_to_rgba, save_svg,
        assert_unique_colors, assert_safety_margin,
    )
    from config import SupportedStyle, OUTLINE_WEIGHT_BY_STYLE

    APPLE = make_palette(base="#E23A2B", highlight="#FFD8C0", outline="#3A0808")

    def render_apple():
        canvas = SvgCanvas(48, 48)
        # 1. Body
        canvas.add_circle(cx=24, cy=26, r=16, fill=APPLE["base"],
                          stroke=APPLE["outline"],
                          stroke_width=OUTLINE_WEIGHT_BY_STYLE[
                              SupportedStyle.MINIMALIST_FLAT].value)
        # 2. Highlight blob (upper-left)
        canvas.add_ellipse(cx=18, cy=20, rx=4, ry=6, fill=APPLE["highlight"])
        # 3. Stem
        canvas.add_path("M24,10 Q26,6 30,8", stroke=APPLE["outline"],
                        stroke_width=2, fill="none")
        return canvas

    save_svg(render_apple(), "assets/svg/apple.svg")
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple, Union

from config import (
    BRAND_FONT_FAMILY_NAME,
    BRAND_FONT_FORMAT,
    FILTER_ID_GAUSSIAN_BLUR,
    FILTER_ID_INNER_GLOW,
    FILTER_ID_SOFT_SHADOW,
    GRADIENT_ID_PREFIX,
    MAX_SPRITE_SIDE_PX,
    MIN_SPRITE_SIDE_PX,
    MIN_UNIQUE_COLORS_BY_STYLE,
    SAFETY_MARGIN_BY_STYLE,
    SVG_NAMESPACE,
    SVG_VERSION,
    SupportedStyle,
)


# ---------------------------------------------------------------------------
# Type aliases (informational only)
# ---------------------------------------------------------------------------
ColorLike = Union[str, Tuple[int, int, int], Tuple[int, int, int, int]]
GradientStop = Tuple[float, ColorLike, float]   # (offset 0..1, color, opacity 0..1)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def hex_to_rgba(value: str) -> Tuple[int, int, int, int]:
    """Parse '#RRGGBB' or '#RRGGBBAA' into (r,g,b,a) ints 0..255."""
    if not isinstance(value, str) or not value.startswith("#"):
        raise ValueError(f"hex color must start with '#', got {value!r}")
    raw = value[1:]
    if len(raw) == 6:
        r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
        return (r, g, b, 255)
    if len(raw) == 8:
        r = int(raw[0:2], 16); g = int(raw[2:4], 16)
        b = int(raw[4:6], 16); a = int(raw[6:8], 16)
        return (r, g, b, a)
    raise ValueError(f"hex color must be 6 or 8 digits, got {value!r}")


def rgba_to_hex(rgba: Tuple[int, int, int, int]) -> str:
    """Render an (r,g,b,a) tuple back to '#RRGGBBAA'."""
    r, g, b, a = rgba
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"


def color_to_svg(value: ColorLike) -> str:
    """Coerce any accepted color form to an SVG `fill`/`stroke` attribute string.

    Always returns a `#RRGGBB`-style string and an attribute is set
    separately for opacity, since SVG paints split color from alpha.
    """
    if isinstance(value, str):
        # Accept #RRGGBB and #RRGGBBAA; SVG paint takes only #RRGGBB so
        # we strip the alpha here and the caller passes alpha via opacity.
        if value.startswith("#") and len(value) == 9:
            return value[:7]
        return value
    if len(value) == 3:
        r, g, b = value
        return f"#{r:02X}{g:02X}{b:02X}"
    r, g, b, _a = value
    return f"#{r:02X}{g:02X}{b:02X}"


def color_alpha(value: ColorLike) -> float:
    """Return the alpha channel of any color form as a float 0..1."""
    if isinstance(value, str):
        if value.startswith("#") and len(value) == 9:
            return int(value[7:9], 16) / 255.0
        return 1.0
    if len(value) == 3:
        return 1.0
    return value[3] / 255.0


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
def make_palette(
    *,
    base: ColorLike,
    highlight: ColorLike,
    outline: ColorLike,
    mid: Optional[ColorLike] = None,
    deep: Optional[ColorLike] = None,
    accent: Optional[ColorLike] = None,
    shadow: Optional[ColorLike] = None,
    subsurface: Optional[ColorLike] = None,
) -> Mapping[str, ColorLike]:
    """Build a named palette dict. Keys map to roles in the style profiles.

    Required: base, highlight, outline (covers minimalist_flat).
    Optional: mid, deep, accent (cartoon_thick_outline / realistic_render).
    Optional: shadow, subsurface (realistic_render extras).
    """
    palette = {"base": base, "highlight": highlight, "outline": outline}
    if mid is not None:
        palette["mid"] = mid
    if deep is not None:
        palette["deep"] = deep
    if accent is not None:
        palette["accent"] = accent
    if shadow is not None:
        palette["shadow"] = shadow
    if subsurface is not None:
        palette["subsurface"] = subsurface
    return palette


# ---------------------------------------------------------------------------
# SvgCanvas — the central authoring object
# ---------------------------------------------------------------------------
class SvgCanvas:
    """A wrapper around an `<svg>` root that exposes high-level primitives.

    Internally builds an ElementTree and serializes on demand. Every
    primitive returns the freshly-created element so the caller can
    decorate it further (filters, opacity, transforms) without going
    through the wrapper.
    """

    def __init__(self, width: int, height: int):
        if not (MIN_SPRITE_SIDE_PX <= width <= MAX_SPRITE_SIDE_PX):
            raise ValueError(
                f"width {width} outside [{MIN_SPRITE_SIDE_PX}, {MAX_SPRITE_SIDE_PX}]"
            )
        if not (MIN_SPRITE_SIDE_PX <= height <= MAX_SPRITE_SIDE_PX):
            raise ValueError(
                f"height {height} outside [{MIN_SPRITE_SIDE_PX}, {MAX_SPRITE_SIDE_PX}]"
            )
        self.width = width
        self.height = height
        self.root = ET.Element("svg", {
            "xmlns": SVG_NAMESPACE,
            "version": SVG_VERSION,
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "shape-rendering": "geometricPrecision",
        })
        self.defs = ET.SubElement(self.root, "defs")
        self._gradient_serial = 0
        self._filter_serial = 0
        self._font_embedded = False

    # -- shape primitives ----------------------------------------------------
    def add_rect(
        self, x: float, y: float, w: float, h: float, *,
        fill: Optional[ColorLike] = None,
        stroke: Optional[ColorLike] = None,
        stroke_width: float = 0,
        rx: float = 0, ry: float = 0,
        opacity: float = 1.0,
        filter_id: Optional[str] = None,
    ) -> ET.Element:
        attrs = {
            "x": _fmt(x), "y": _fmt(y),
            "width": _fmt(w), "height": _fmt(h),
        }
        if rx:
            attrs["rx"] = _fmt(rx)
        if ry:
            attrs["ry"] = _fmt(ry)
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, filter_id)
        return ET.SubElement(self.root, "rect", attrs)

    def add_circle(
        self, cx: float, cy: float, r: float, *,
        fill: Optional[ColorLike] = None,
        stroke: Optional[ColorLike] = None,
        stroke_width: float = 0,
        opacity: float = 1.0,
        filter_id: Optional[str] = None,
    ) -> ET.Element:
        attrs = {"cx": _fmt(cx), "cy": _fmt(cy), "r": _fmt(r)}
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, filter_id)
        return ET.SubElement(self.root, "circle", attrs)

    def add_ellipse(
        self, cx: float, cy: float, rx: float, ry: float, *,
        fill: Optional[ColorLike] = None,
        stroke: Optional[ColorLike] = None,
        stroke_width: float = 0,
        opacity: float = 1.0,
        filter_id: Optional[str] = None,
    ) -> ET.Element:
        attrs = {"cx": _fmt(cx), "cy": _fmt(cy), "rx": _fmt(rx), "ry": _fmt(ry)}
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, filter_id)
        return ET.SubElement(self.root, "ellipse", attrs)

    def add_path(
        self, d: str, *,
        fill: Optional[ColorLike] = None,
        stroke: Optional[ColorLike] = None,
        stroke_width: float = 0,
        stroke_linecap: str = "round",
        stroke_linejoin: str = "round",
        opacity: float = 1.0,
        filter_id: Optional[str] = None,
    ) -> ET.Element:
        attrs = {"d": d}
        if stroke is not None:
            attrs["stroke-linecap"] = stroke_linecap
            attrs["stroke-linejoin"] = stroke_linejoin
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, filter_id)
        return ET.SubElement(self.root, "path", attrs)

    def add_polygon(
        self, points: Iterable[Tuple[float, float]], *,
        fill: Optional[ColorLike] = None,
        stroke: Optional[ColorLike] = None,
        stroke_width: float = 0,
        opacity: float = 1.0,
        filter_id: Optional[str] = None,
    ) -> ET.Element:
        pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)
        attrs = {"points": pts}
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, filter_id)
        return ET.SubElement(self.root, "polygon", attrs)

    def add_polyline(
        self, points: Iterable[Tuple[float, float]], *,
        stroke: ColorLike,
        stroke_width: float,
        stroke_linecap: str = "round",
        stroke_linejoin: str = "round",
        fill: ColorLike = "none",
        opacity: float = 1.0,
    ) -> ET.Element:
        pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points)
        attrs = {
            "points": pts,
            "stroke-linecap": stroke_linecap,
            "stroke-linejoin": stroke_linejoin,
        }
        _apply_paint(attrs, fill, stroke, stroke_width, opacity, None)
        return ET.SubElement(self.root, "polyline", attrs)

    # -- gradients -----------------------------------------------------------
    def add_radial_gradient(
        self,
        stops: Iterable[GradientStop],
        *,
        cx: float = 0.5,
        cy: float = 0.5,
        r: float = 0.5,
        fx: Optional[float] = None,
        fy: Optional[float] = None,
        spread_method: str = "pad",
    ) -> str:
        """Define a radial gradient inside <defs> and return its id."""
        gid = self._next_id(GRADIENT_ID_PREFIX)
        attrs = {
            "id": gid,
            "cx": _fmt(cx), "cy": _fmt(cy), "r": _fmt(r),
            "spreadMethod": spread_method,
        }
        if fx is not None:
            attrs["fx"] = _fmt(fx)
        if fy is not None:
            attrs["fy"] = _fmt(fy)
        gradient = ET.SubElement(self.defs, "radialGradient", attrs)
        _populate_stops(gradient, stops)
        return f"url(#{gid})"

    def add_linear_gradient(
        self,
        stops: Iterable[GradientStop],
        *,
        x1: float = 0.0, y1: float = 0.0,
        x2: float = 0.0, y2: float = 1.0,
        spread_method: str = "pad",
    ) -> str:
        """Define a linear gradient inside <defs> and return its id."""
        gid = self._next_id(GRADIENT_ID_PREFIX)
        gradient = ET.SubElement(self.defs, "linearGradient", {
            "id": gid,
            "x1": _fmt(x1), "y1": _fmt(y1),
            "x2": _fmt(x2), "y2": _fmt(y2),
            "spreadMethod": spread_method,
        })
        _populate_stops(gradient, stops)
        return f"url(#{gid})"

    # -- filters -------------------------------------------------------------
    def ensure_soft_shadow(
        self, *, dx: float = 1.0, dy: float = 2.0, std_deviation: float = 1.5,
        flood_color: ColorLike = "#000000", flood_opacity: float = 0.35,
    ) -> str:
        """Idempotently ensure a soft drop-shadow filter exists. Returns id ref."""
        if self._has_def(FILTER_ID_SOFT_SHADOW):
            return f"url(#{FILTER_ID_SOFT_SHADOW})"
        f = ET.SubElement(self.defs, "filter", {
            "id": FILTER_ID_SOFT_SHADOW,
            "x": "-50%", "y": "-50%", "width": "200%", "height": "200%",
        })
        ET.SubElement(f, "feGaussianBlur", {
            "in": "SourceAlpha", "stdDeviation": _fmt(std_deviation),
        })
        ET.SubElement(f, "feOffset", {
            "dx": _fmt(dx), "dy": _fmt(dy), "result": "offsetblur",
        })
        flood = ET.SubElement(f, "feFlood", {
            "flood-color": color_to_svg(flood_color),
            "flood-opacity": _fmt(flood_opacity),
        })
        flood.tail = ""
        ET.SubElement(f, "feComposite", {
            "in2": "offsetblur", "operator": "in",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode")
        ET.SubElement(merge, "feMergeNode", {"in": "SourceGraphic"})
        return f"url(#{FILTER_ID_SOFT_SHADOW})"

    def ensure_gaussian_blur(self, *, std_deviation: float = 1.0) -> str:
        """Idempotent Gaussian-blur filter. Returns id ref."""
        if self._has_def(FILTER_ID_GAUSSIAN_BLUR):
            return f"url(#{FILTER_ID_GAUSSIAN_BLUR})"
        f = ET.SubElement(self.defs, "filter", {"id": FILTER_ID_GAUSSIAN_BLUR})
        ET.SubElement(f, "feGaussianBlur", {
            "in": "SourceGraphic", "stdDeviation": _fmt(std_deviation),
        })
        return f"url(#{FILTER_ID_GAUSSIAN_BLUR})"

    def ensure_inner_glow(
        self, *, std_deviation: float = 1.0,
        glow_color: ColorLike = "#FFFFFF", glow_opacity: float = 0.6,
    ) -> str:
        """Subtle inner glow used for realistic_render highlights. Idempotent."""
        if self._has_def(FILTER_ID_INNER_GLOW):
            return f"url(#{FILTER_ID_INNER_GLOW})"
        f = ET.SubElement(self.defs, "filter", {"id": FILTER_ID_INNER_GLOW})
        ET.SubElement(f, "feGaussianBlur", {
            "in": "SourceAlpha", "stdDeviation": _fmt(std_deviation),
            "result": "blur",
        })
        ET.SubElement(f, "feFlood", {
            "flood-color": color_to_svg(glow_color),
            "flood-opacity": _fmt(glow_opacity),
            "result": "flood",
        })
        ET.SubElement(f, "feComposite", {
            "in": "flood", "in2": "blur", "operator": "in", "result": "glow",
        })
        merge = ET.SubElement(f, "feMerge")
        ET.SubElement(merge, "feMergeNode", {"in": "glow"})
        ET.SubElement(merge, "feMergeNode", {"in": "SourceGraphic"})
        return f"url(#{FILTER_ID_INNER_GLOW})"

    # -- text (brand typeface only) ------------------------------------------
    def add_text(
        self, x: float, y: float, text: str, *,
        font_size: float, fill: ColorLike,
        font_path: Path,
        anchor: str = "start",
        opacity: float = 1.0,
    ) -> ET.Element:
        """Draw a text node using the embedded brand typeface.

        The first call also embeds the TTF as a base64 data-URI in
        <defs><style>, so cairosvg never reaches out to the host's
        installed fonts. font_path must be an absolute resolvable path.
        """
        self._ensure_font_embedded(font_path)
        attrs = {
            "x": _fmt(x), "y": _fmt(y),
            "font-family": BRAND_FONT_FAMILY_NAME,
            "font-size": _fmt(font_size),
            "fill": color_to_svg(fill),
            "text-anchor": anchor,
        }
        alpha = color_alpha(fill) * opacity
        if alpha < 1.0:
            attrs["fill-opacity"] = _fmt(alpha)
        node = ET.SubElement(self.root, "text", attrs)
        node.text = text
        return node

    # -- serialization -------------------------------------------------------
    def to_string(self) -> str:
        """Serialize the canvas to a self-contained SVG string."""
        return ET.tostring(self.root, encoding="unicode")

    def save(self, path: Union[str, Path]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_string(), encoding="utf-8")
        return target

    # -- internals -----------------------------------------------------------
    def _next_id(self, prefix: str) -> str:
        if prefix == GRADIENT_ID_PREFIX:
            self._gradient_serial += 1
            return f"{prefix}-{self._gradient_serial:03d}"
        self._filter_serial += 1
        return f"{prefix}-{self._filter_serial:03d}"

    def _has_def(self, def_id: str) -> bool:
        return any(child.get("id") == def_id for child in self.defs)

    def _ensure_font_embedded(self, font_path: Path) -> None:
        if self._font_embedded:
            return
        if not font_path.exists():
            raise FileNotFoundError(
                f"brand font not found at {font_path}; "
                f"see config.BRAND_FONT_RELATIVE_PATH"
            )
        ttf = font_path.read_bytes()
        b64 = base64.b64encode(ttf).decode("ascii")
        style = ET.SubElement(self.defs, "style", {"type": "text/css"})
        style.text = (
            f"@font-face {{"
            f" font-family: '{BRAND_FONT_FAMILY_NAME}';"
            f" src: url(data:font/{BRAND_FONT_FORMAT};base64,{b64})"
            f" format('{BRAND_FONT_FORMAT}');"
            f" font-weight: bold; font-style: normal; }}"
        )
        self._font_embedded = True


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------
def save_svg(canvas: SvgCanvas, path: Union[str, Path]) -> Path:
    """Module-level wrapper so renderers can `from svg_lib import save_svg`."""
    return canvas.save(path)


# ---------------------------------------------------------------------------
# Quality gates (run on the rasterized PNG, not the SVG itself)
# ---------------------------------------------------------------------------
def assert_unique_colors(
    png_path: Union[str, Path],
    style: SupportedStyle,
    *,
    label: str = "",
    minimum: Optional[int] = None,
) -> None:
    """Assert the rasterized PNG has at least the style's minimum unique colors.

    Counts opaque (a > 0) pixels only. Fully transparent pixels do NOT
    count as a "color" for the gate — they are background, not material.
    """
    from PIL import Image  # imported lazily so SVG-only callers don't pay
    threshold = minimum if minimum is not None else MIN_UNIQUE_COLORS_BY_STYLE[style]
    img = Image.open(png_path).convert("RGBA")
    seen: set[Tuple[int, int, int, int]] = set()
    for px in img.getdata():
        if px[3] > 0:
            seen.add(px)
        if len(seen) >= threshold:
            return
    raise AssertionError(
        f"{label or png_path}: only {len(seen)} unique opaque colors, "
        f"style {style.value} requires >= {threshold}"
    )


def assert_safety_margin(
    png_path: Union[str, Path],
    style: SupportedStyle,
    *,
    label: str = "",
) -> None:
    """Assert no opaque pixel touches the canvas border within the safety margin."""
    from PIL import Image
    margin = SAFETY_MARGIN_BY_STYLE[style]
    img = Image.open(png_path).convert("RGBA")
    w, h = img.size
    px = img.load()
    for x in range(w):
        for y in range(margin):
            if px[x, y][3] > 0 or px[x, h - 1 - y][3] > 0:
                raise AssertionError(
                    f"{label or png_path}: opaque pixel inside top/bottom "
                    f"safety margin ({margin}px) — column {x}"
                )
    for y in range(h):
        for x in range(margin):
            if px[x, y][3] > 0 or px[w - 1 - x, y][3] > 0:
                raise AssertionError(
                    f"{label or png_path}: opaque pixel inside left/right "
                    f"safety margin ({margin}px) — row {y}"
                )


def assert_no_outline_stroke(
    png_path: Union[str, Path],
    *,
    label: str = "",
    max_dark_ring_fraction: float = 0.05,
) -> None:
    """For realistic_render: silhouette must be defined by value contrast,
    not by a uniform ink ring around the form.

    Heuristic: count opaque pixels whose luminance is below 32 AND that
    sit on the silhouette boundary (any neighbour is fully transparent).
    If they exceed `max_dark_ring_fraction` of the total boundary, the
    sprite has a stroke and fails the contract.
    """
    from PIL import Image
    img = Image.open(png_path).convert("RGBA")
    w, h = img.size
    px = img.load()
    boundary = 0
    dark = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            on_edge = False
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or px[nx, ny][3] == 0:
                    on_edge = True
                    break
            if on_edge:
                boundary += 1
                if (r * 299 + g * 587 + b * 114) // 1000 < 32:
                    dark += 1
    if boundary == 0:
        return
    ratio = dark / boundary
    if ratio > max_dark_ring_fraction:
        raise AssertionError(
            f"{label or png_path}: {ratio:.0%} of silhouette boundary is "
            f"near-black, suggesting an outline stroke. "
            f"realistic_render forbids outlines."
        )


# ---------------------------------------------------------------------------
# Internal formatting helpers
# ---------------------------------------------------------------------------
def _fmt(value: float) -> str:
    """Format a float without trailing zeros so SVG attributes stay tidy."""
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _apply_paint(
    attrs: dict,
    fill: Optional[ColorLike],
    stroke: Optional[ColorLike],
    stroke_width: float,
    opacity: float,
    filter_id: Optional[str],
) -> None:
    """Mutate `attrs` to carry fill/stroke/opacity/filter consistently.

    Centralized so every primitive treats colors and gradients the same
    way (string starting with 'url(' is a paint reference, not a color).
    """
    if fill is None:
        attrs["fill"] = "none"
    elif isinstance(fill, str) and fill.startswith("url("):
        attrs["fill"] = fill
    elif fill == "none":
        attrs["fill"] = "none"
    else:
        attrs["fill"] = color_to_svg(fill)
        a = color_alpha(fill)
        if a < 1.0:
            attrs["fill-opacity"] = _fmt(a)
    if stroke is not None and stroke != "none":
        if isinstance(stroke, str) and stroke.startswith("url("):
            attrs["stroke"] = stroke
        else:
            attrs["stroke"] = color_to_svg(stroke)
            a = color_alpha(stroke)
            if a < 1.0:
                attrs["stroke-opacity"] = _fmt(a)
        attrs["stroke-width"] = _fmt(stroke_width)
    if opacity < 1.0:
        attrs["opacity"] = _fmt(opacity)
    if filter_id:
        attrs["filter"] = filter_id


def _populate_stops(gradient_node: ET.Element, stops: Iterable[GradientStop]) -> None:
    """Append <stop> children to a <linearGradient>/<radialGradient> node."""
    for offset, color, opacity in stops:
        ET.SubElement(gradient_node, "stop", {
            "offset": f"{offset * 100:.2f}%",
            "stop-color": color_to_svg(color),
            "stop-opacity": _fmt(opacity),
        })
