"""
Centralized configuration for the cube_svg-design skill.

All tunable constants, identifiers, and exit codes live here so the rest
of the skill never hard-codes magic numbers. If a number appears in
svg_lib.py or svg_to_png.py, it should also be defined here, imported
by name, and documented in this file.
"""
from __future__ import annotations

import enum
from typing import Mapping


# =============================================================================
# Workspace paths
# =============================================================================
# Layout produced by this skill (relative to the user's workspace root):
#   assets/svg/<name>.svg   <- vector source (editable)
#   assets/art/<name>.png   <- rasterized PNG (consumed by cube_asset-builder)
ASSETS_ROOT_DEFAULT = "assets"
SVG_SUBDIR = "svg"
PNG_SUBDIR = "art"


# =============================================================================
# SVG document constants
# =============================================================================
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
SVG_VERSION = "1.1"
SVG_ENCODING = "utf-8"
# Tag prefixes used to keep IDs predictable inside <defs>.
GRADIENT_ID_PREFIX = "grad"
FILTER_ID_PREFIX = "filt"
PATTERN_ID_PREFIX = "pat"
CLIP_ID_PREFIX = "clip"
# Stable IDs for the most common shared filters.
FILTER_ID_SOFT_SHADOW = "soft-shadow"
FILTER_ID_GAUSSIAN_BLUR = "gaussian-blur"
FILTER_ID_INNER_GLOW = "inner-glow"


# =============================================================================
# Rasterization (cairosvg)
# =============================================================================
DEFAULT_DPI = 96
# Background color for the rasterized PNG. None = fully transparent (default).
DEFAULT_PNG_BACKGROUND = None
# When the SVG carries no explicit width/height, fall back to viewBox.
USE_VIEWBOX_AS_FALLBACK_SIZE = True


# =============================================================================
# Supported styles
# =============================================================================
class SupportedStyle(str, enum.Enum):
    """Style profiles that this skill knows how to render in SVG.

    Membership is checked at startup; an unsupported style is routed to
    canvas-design instead of being approximated here.
    """
    MINIMALIST_FLAT = "minimalist_flat"
    CARTOON_THICK_OUTLINE = "cartoon_thick_outline"
    REALISTIC_RENDER = "realistic_render"


# Styles intentionally NOT handled by this skill. Routed to canvas-design.
UNSUPPORTED_STYLES = frozenset({
    "detailed_pixelart",
    "retro_8bit",
    "painterly_storybook",
})


# =============================================================================
# Light direction
# =============================================================================
# Top-left light at ~35°. Highlights cluster on the upper-left of every
# primary form; shadows fall to the lower-right. This is consistent
# across the entire asset set; never flip light per sprite.
LIGHT_AZIMUTH_DEG = -135
LIGHT_ELEVATION_DEG = 35
HIGHLIGHT_OFFSET_FRACTION = 0.30  # highlight cluster origin (UL corner side)
SHADOW_OFFSET_FRACTION = 0.25     # shadow cluster origin (LR corner side)


# =============================================================================
# Outline / stroke widths
# =============================================================================
class OutlineWeight(enum.IntEnum):
    """Stroke width in pixels for ink outlines.

    NONE means the silhouette is defined by value contrast (realistic
    render). All other styles use one of THIN/MEDIUM/THICK.
    """
    NONE = 0
    THIN = 1
    MEDIUM = 2
    THICK = 3


OUTLINE_WEIGHT_BY_STYLE: Mapping[SupportedStyle, OutlineWeight] = {
    SupportedStyle.MINIMALIST_FLAT: OutlineWeight.MEDIUM,
    SupportedStyle.CARTOON_THICK_OUTLINE: OutlineWeight.THICK,
    SupportedStyle.REALISTIC_RENDER: OutlineWeight.NONE,
}


# =============================================================================
# Quality gates
# =============================================================================
# Minimum number of unique opaque colors a rasterized sprite must contain
# to satisfy the style's "richness" contract. Values are intentionally
# strict: if a renderer cannot meet them, the renderer is too sparse,
# not the gate too strict.
MIN_UNIQUE_COLORS_BY_STYLE: Mapping[SupportedStyle, int] = {
    SupportedStyle.MINIMALIST_FLAT: 3,        # base + highlight + outline
    SupportedStyle.CARTOON_THICK_OUTLINE: 4,  # base + 1 cel-shade + outline + accent
    SupportedStyle.REALISTIC_RENDER: 12,      # gradient richness, no outline
}

# Safety margin in pixels: number of fully-transparent pixels required
# on every side of the canvas. Realistic render needs more breathing room
# because contact shadows extend beyond the main silhouette.
SAFETY_MARGIN_PX_DEFAULT = 1
SAFETY_MARGIN_PX_REALISTIC = 2

# Per-style safety margin lookup.
SAFETY_MARGIN_BY_STYLE: Mapping[SupportedStyle, int] = {
    SupportedStyle.MINIMALIST_FLAT: SAFETY_MARGIN_PX_DEFAULT,
    SupportedStyle.CARTOON_THICK_OUTLINE: SAFETY_MARGIN_PX_DEFAULT,
    SupportedStyle.REALISTIC_RENDER: SAFETY_MARGIN_PX_REALISTIC,
}


# =============================================================================
# Sprite size bounds (mirrors cube_asset-builder's manifest validator)
# =============================================================================
MIN_SPRITE_SIDE_PX = 1
MAX_SPRITE_SIDE_PX = 240


# =============================================================================
# Brand typeface
# =============================================================================
# Path is relative to the workspace root (the agent resolves it to the
# OCT_wowcube-agent-skills mount). The skill embeds the font as a base64
# data-URI inside the SVG so cairosvg never has to look it up on disk.
BRAND_FONT_RELATIVE_PATH = "OCT_wowcube-agent-skills/skills/canvas-design/canvas-fonts/Rubik-Bold.ttf"
BRAND_FONT_FAMILY_NAME = "WowCubeBrand"
BRAND_FONT_FORMAT = "truetype"


# =============================================================================
# Exit codes
# =============================================================================
class ExitCode(enum.IntEnum):
    """Exit codes returned by svg_to_png.py and tooling helpers."""
    OK = 0
    BAD_ARGS = 2
    MISSING_DEP = 3
    SVG_INVALID = 4
    PNG_WRITE_FAILED = 5
    SIZE_MISMATCH = 6
    QUALITY_GATE_FAILED = 7


# =============================================================================
# Required Python dependencies
# =============================================================================
# (module_name_used_in_import, pip_install_name)
REQUIRED_PY_DEPS: tuple[tuple[str, str], ...] = (
    ("cairosvg", "cairosvg"),
    ("PIL", "Pillow"),
)
