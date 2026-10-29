"""Find 1-2 px lines of one colour along screen edges in a sim_headless frame (the "cross" artifact).

A sprite that should fill a screen but is placed half a pixel off leaves a thin line of the background on two
inner edges of every face: 2 px for half-res (x2) art, 1 px for <FULLSIZE> art. Cause and fix: API.md,
"Coordinates" (place screen-filling art at +-119.5, not +-120).

    python seams.py <frame.png> [--face]      # --face: a one-face frame (run.ps1 -Face 0..5)

Prints every screen edge that starts with 1-2 lines of one exact colour (a background fill; art lines vary) followed
by a different line, grouped by colour. Exit 0 = no seams, 1 = seams found, 2 = unreadable input. An empty
(one-colour) screen never reports: its uniform band is wider than a seam.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import numpy as np
from PIL import Image

SIDE = 240                       # sim_headless_capture.h: HL_SIDE, HL_SCRGAP, HL_FACEGAP
SCRGAP = 4
FACEGAP = 12
FACE = 2 * SIDE + SCRGAP
# cross layout: (col, row) per plane TOP FRONT RIGHT BACK LEFT BOTTOM
CROSS = {"TOP": (1, 0), "FRONT": (1, 1), "RIGHT": (2, 1), "BACK": (3, 1), "LEFT": (0, 1), "BOTTOM": (1, 2)}
TOL = 12                         # summed RGB distance that still counts as the same colour
EXACT = 0.99                     # share of a line's pixels that must be exactly its colour
MAX_SEAM = 2


def screens(img: np.ndarray, one_face: bool):
    """Yield (label, 240x240x3 array) for every screen in the frame."""
    faces = {"FACE": (0, 0)} if one_face else {
        name: (c * (FACE + FACEGAP), r * (FACE + FACEGAP)) for name, (c, r) in CROSS.items()}
    for name, (fx, fy) in faces.items():
        for sy in (0, 1):
            for sx in (0, 1):
                x0, y0 = fx + sx * (SIDE + SCRGAP), fy + sy * (SIDE + SCRGAP)
                yield f"{name} r{sy}c{sx}", img[y0:y0 + SIDE, x0:x0 + SIDE]


def _line_colour(line: np.ndarray):
    """The line's colour when it is one flat colour (the background fill is exact; art lines vary), else None."""
    colours, counts = np.unique(line.reshape(-1, 3), axis=0, return_counts=True)
    top = counts.argmax()
    if counts[top] < EXACT * len(line):
        return None
    return colours[top]


def edge_seam(lines) -> tuple[int, tuple[int, int, int]] | None:
    """(width, colour) when the edge starts with 1..MAX_SEAM equal uniform lines and the next line differs."""
    ref = None
    width = 0
    for line in lines:
        col = _line_colour(line)
        if col is None or (ref is not None and np.abs(col - ref).sum() > TOL):
            break
        ref = col if ref is None else ref
        width += 1
        if width > MAX_SEAM:
            return None          # a wide uniform band is part of the picture (sky, frame), not a seam
    if width == 0:
        return None
    return width, tuple(int(v) for v in ref)


def find_seams(img: np.ndarray, one_face: bool = False):
    found = []
    for label, s in screens(img, one_face):
        if s.shape[:2] != (SIDE, SIDE):
            continue
        # no "empty screen" shortcut: a solid-colour picture with a 2-px seam is still ~98 % one colour, and a
        # truly empty screen never reports (its edge band is wider than MAX_SEAM)
        edges = {"top": (s[i] for i in range(MAX_SEAM + 1)),
                 "bottom": (s[SIDE - 1 - i] for i in range(MAX_SEAM + 1)),
                 "left": (s[:, i] for i in range(MAX_SEAM + 1)),
                 "right": (s[:, SIDE - 1 - i] for i in range(MAX_SEAM + 1))}
        for edge, lines in edges.items():
            hit = edge_seam(lines)
            if hit:
                found.append((label, edge, hit[0], hit[1]))
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("frame")
    ap.add_argument("--face", action="store_true", help="a one-face frame (run.ps1 -Face 0..5)")
    a = ap.parse_args(argv)
    try:
        img = np.asarray(Image.open(a.frame).convert("RGB")).astype(int)
    except OSError as e:
        print(f"seams: cannot read {a.frame}: {e}", file=sys.stderr)
        return 2
    seams = find_seams(img, a.face)
    if not seams:
        print("seams: none")
        return 0
    groups = defaultdict(list)
    for label, edge, width, colour in seams:
        groups[(width, colour)].append(f"{label} {edge}")
    print(f"seams: {len(seams)} screen edge(s) start with a thin line of one colour")
    for (width, colour), where in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        hexc = "#%02X%02X%02X" % colour
        print(f"  {width} px {hexc} x{len(where)}: {', '.join(where[:8])}{' ...' if len(where) > 8 else ''}")
    print("  a 2 px (x2 art) / 1 px (fullsize art) line of the background on inner screen edges = screen-filling art "
          "placed at +-120: place it at +-119.5 (API.md, Coordinates)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
