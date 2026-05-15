"""
svg_to_png.py — rasterize a single SVG file to a single PNG via cairosvg.

Used by cube_svg-design as the final stage of every render. The CLI
accepts the SVG path, the target PNG path, and the explicit output
dimensions (which must match the manifest sprite size). The exit codes
are defined in config.ExitCode so callers can branch deterministically.

Usage:
    python svg_to_png.py --svg assets/svg/apple.svg \
                         --png assets/art/apple.png \
                         --width 48 --height 48
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from config import (
    DEFAULT_DPI,
    DEFAULT_PNG_BACKGROUND,
    REQUIRED_PY_DEPS,
    ExitCode,
)


logger = logging.getLogger("svg_to_png")


def _configure_logging(verbose: bool) -> None:
    """Route INFO+ to stdout, WARNING+ to stderr; idempotent across calls."""
    if logger.handlers:
        return
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    out = logging.StreamHandler(sys.stdout)
    out.setLevel(logging.DEBUG if verbose else logging.INFO)
    out.addFilter(lambda rec: rec.levelno < logging.WARNING)
    out.setFormatter(logging.Formatter("%(message)s"))
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    err.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(out)
    logger.addHandler(err)
    logger.propagate = False


def _check_deps() -> list[str]:
    """Return list of missing dependency descriptions. Empty == ok."""
    missing: list[str] = []
    for module_name, pip_name in REQUIRED_PY_DEPS:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(
                f"python module {module_name!r} - install with: "
                f"pip install --break-system-packages {pip_name}"
            )
    return missing


def convert(
    svg_path: Path,
    png_path: Path,
    *,
    width: int,
    height: int,
    dpi: int = DEFAULT_DPI,
    background: Optional[str] = DEFAULT_PNG_BACKGROUND,
) -> ExitCode:
    """Convert one SVG file to one PNG file.

    Returns one of the ExitCode values. Logs all warnings/errors via the
    module logger so the caller sees them on stderr.
    """
    if not svg_path.exists():
        logger.error("svg not found: %s", svg_path)
        return ExitCode.BAD_ARGS
    if width <= 0 or height <= 0:
        logger.error("width/height must be positive, got (%d, %d)", width, height)
        return ExitCode.BAD_ARGS

    try:
        import cairosvg  # type: ignore
    except ImportError:
        logger.error(
            "cairosvg is not installed. "
            "Run `pip install --break-system-packages cairosvg` and retry."
        )
        return ExitCode.MISSING_DEP

    png_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        kwargs: dict = {
            "url": str(svg_path),
            "write_to": str(png_path),
            "output_width": width,
            "output_height": height,
            "dpi": dpi,
        }
        if background is not None:
            # cairosvg fills any transparent pixels with this color when set.
            kwargs["background_color"] = background
        cairosvg.svg2png(**kwargs)
    except Exception as exc:  # cairosvg raises a variety of types on bad SVG
        logger.error("cairosvg failed to rasterize %s: %s", svg_path, exc)
        return ExitCode.SVG_INVALID

    if not png_path.exists() or png_path.stat().st_size == 0:
        logger.error("png not written or empty: %s", png_path)
        return ExitCode.PNG_WRITE_FAILED

    rc = _verify_dimensions(png_path, width, height)
    if rc is not ExitCode.OK:
        return rc

    logger.info("rasterized %s -> %s (%dx%d)", svg_path.name, png_path, width, height)
    return ExitCode.OK


def _verify_dimensions(png_path: Path, expected_w: int, expected_h: int) -> ExitCode:
    """Open the PNG via Pillow and confirm width/height match the contract."""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        logger.warning(
            "Pillow not installed; skipping output dimension verification."
        )
        return ExitCode.OK
    with Image.open(png_path) as img:
        actual_w, actual_h = img.size
    if (actual_w, actual_h) != (expected_w, expected_h):
        logger.error(
            "png dimension mismatch for %s: expected %dx%d, got %dx%d",
            png_path, expected_w, expected_h, actual_w, actual_h,
        )
        return ExitCode.SIZE_MISMATCH
    return ExitCode.OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="svg_to_png",
        description="Rasterize a single SVG to a single PNG via cairosvg.",
    )
    p.add_argument("--svg", required=True, type=Path,
                   help="Path to the source SVG file.")
    p.add_argument("--png", required=True, type=Path,
                   help="Path to the destination PNG file.")
    p.add_argument("--width", required=True, type=int,
                   help="Output PNG width in pixels (must match manifest).")
    p.add_argument("--height", required=True, type=int,
                   help="Output PNG height in pixels (must match manifest).")
    p.add_argument("--dpi", default=DEFAULT_DPI, type=int,
                   help=f"Rasterization DPI (default {DEFAULT_DPI}).")
    p.add_argument("--background", default=None,
                   help="Optional fill color for transparent pixels "
                        "(e.g. '#FFFFFF'). Default: keep transparent.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Enable DEBUG-level logging.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose)

    deps_missing = _check_deps()
    if deps_missing:
        logger.error("missing dependencies:")
        for d in deps_missing:
            logger.error("  - %s", d)
        return int(ExitCode.MISSING_DEP)

    rc = convert(
        svg_path=args.svg,
        png_path=args.png,
        width=args.width,
        height=args.height,
        dpi=args.dpi,
        background=args.background,
    )
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
