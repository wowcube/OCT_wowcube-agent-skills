#!/usr/bin/env python3
"""The demo video of a WowCube game: the cube in 3D on the left, the same 24 screens unfolded on the
right with the title and the controls legend, a caption under the cube. 1920 x 1080, a frame per
captured frame (the engine's 20 ticks a second by default).

Input -- docs/demo/frames.jsonl written by the capture harness (capture.h), one JSON line a frame:
    {"t", "cap", "sub", "legend", "yaw", "pitch", "g": [x, y, z], "twist": id | -1,
     "s": [[sprite], ...]          sprite mode: every live sprite, drawn here from the art dump
     | "net": "net/00012.png"}     net mode: the engine's render of the 24 screens (shot.h layout)

Sprite mode draws every sprite from the art itself (gen_art.py --dump: each sprite whole, its pivot in
its centre) where the capture says it is, turned, tinted and faded as the engine would; a sprite that
hangs over an edge is drawn on the next face too, by the engine's own unfolding (oct_tm.h OCT_CONV).
Labels are set in the game's font.

A frame with "twist" >= 0 follows a twist: the half that turned is animated between the frame before
and that one (--twist-frames extra frames). Which half and which way is found by matching the screens
before and after, so the engine's twist ids need no table here. A twist no turn explains clearly better
than the other turns (a twist that is a command and redraws the screens) is cut, not animated.

The page -- title, tagline, legend, font -- comes from a JSON config (demo.json, see the skill's
templates). Paths in it are relative to the current folder: run from the game's root.

Usage:
    uv run --with numpy==2.5.4 --with pillow==12.3.0 render_demo.py docs/demo/demo.json
        [--every N] [--still FRAME] [--out PATH] [--jobs N]
"""

import argparse
import json
import math
import multiprocessing as mp
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --- the cube ------------------------------------------------------------------------------------

W, H = 1920, 1080
LIM = 276                               # a face's edge in transform space (GAP 18)
FACE = 2 * LIM                          # a face image, bezels included
HALF = FACE // 2                        # a quadrant: one screen with its share of the bezels
SCREEN = 240
SCREEN_IN, SCREEN_OUT = 18, 258         # a screen spans these distances from the face centre

# shot.h net layout: faces of SHOT_FACE px (two screens and one 18 px gap), SHOT_MARGIN apart
SHOT_GAP = 18
SHOT_FACE = 2 * SCREEN + SHOT_GAP
SHOT_MARGIN = 12

# oct_tm.h OCT_CONV: from column side to row side -- dx, dy, dangle, cos, sin
CONV = [
    0, 0, 0, 1, 0, 0, -1, 0, 1, 0, 1, 0, 90, 0, 1, 0, 1, 180, -1, 0, -1, 0, -90, 0, -1, 0, 0, 0, 1, 0,
    0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 1, 0, 0, -1, 0, 1, 0,
    0, 1, -90, 0, -1, -1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 90, 0, 1,
    0, 1, -180, -1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, -1, 180, -1, 0,
    0, 1, 90, 0, 1, 1, 0, 0, 1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, -90, 0, -1,
    0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, -90, 0, -1, 0, -1, -180, -1, 0, -1, 0, 90, 0, 1, 0, 0, 0, 1, 0,
]
OPP = [5, 3, 4, 1, 2, 0]
# plane axes in cube space (OCT_N3D / T3D / B3D): normal, image right, image up
N3D = [(0, 1, 0), (0, 0, -1), (1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, -1, 0)]
T3D = [(1, 0, 0), (1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1), (1, 0, 0)]
B3D = [(0, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, -1)]
NET = {0: (1, 0), 4: (0, 1), 1: (1, 1), 2: (2, 1), 3: (3, 1), 5: (1, 2)}   # plane -> net cell (U, L F R B, D)
NET_NAME = {0: "U", 1: "F", 2: "R", 3: "B", 4: "L", 5: "D"}
QUADS = ((-1, 1), (1, 1), (1, -1), (-1, -1))   # quadrants of a face by (right, up) sign: TL TR BR BL

CAM = 5.0                               # the camera's distance from the cube's centre (cube half-size 1)
SCALE = 1040                            # projection scale, px
VIEW_SIZE = (1060, 860)
VIEW_TILT = 0.25                        # the cube in 3D leans this share of the captured tilt
LEVEL_KEEP = 0.5                        # the face held up stays the level one until it leans past 60 degrees
SEAM = (0x0A, 0x0C, 0x14, 255)          # lines between the modules, the inside of a turning cube
TWIST_FRAMES = 8                        # frames added for a twist's turn
TWIST_MATCH_PX = 24                     # screens compared at this size to find the twist
TWIST_MATCH_CLEAR = 0.85                # the best turn must beat the next best this much: a command twist does not
TWIST_MATCH_NONE = 1.1                  # ...and explain the change about as well as no turn, or better

# --- the page ------------------------------------------------------------------------------------

COLORS = {
    "page": "#0B0D18", "panel": "#121524", "panel_edge": "#262B44", "space": "#060818", "bezel": "#181A22",
    "text": "#F2F5FF", "dim": "#8A93B4", "accent": "#FFB830", "caption": "#0B1026", "caption_edge": "#3A6CF6",
    "row": "#16192A", "row_edge": "#2A2F48", "row_on": "#1C2240", "net_edge": "#3A4060",
}
DEFAULTS = {
    "head3d": "3D · TILT · PAT · TWIST",
    "headNet": "NET (2D) · SAME SCREENS, UNFOLDED",
    "fps": 20,
    "frames": "docs/demo/frames.jsonl",
    "sprites": "docs/demo/sprites",
    "labelFonts": {"1": [18, "SemiBold"], "2": [24, "SemiBold"], "3": [44, "Bold"]},
    "crf": 20,
}


def hex_rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def rgb565(v):
    return ((v >> 11) & 0x1F) * 255 // 31, ((v >> 5) & 0x3F) * 255 // 63, (v & 0x1F) * 255 // 31


def font(path, px, weight="SemiBold"):
    """The font at `px`; a variable font is set to the named instance, a static one is used as is."""
    if not path:
        return ImageFont.load_default(px)
    f = ImageFont.truetype(str(path), px)
    try:
        f.set_variation_by_name(weight.encode() if isinstance(weight, str) else weight)
    except (OSError, ValueError, KeyError):
        pass
    return f


# --- the faces of a frame ------------------------------------------------------------------------

class Art:
    """Sprite images by BMP id (sprite mode) and the fonts of the labels."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.folder = Path(cfg["sprites"])
        self.ids = {}
        if cfg.get("ids") and Path(cfg["ids"]).is_file():
            for m in re.finditer(r"^\s*BMP_(\w+)\s*=\s*(\d+),", Path(cfg["ids"]).read_text(), re.M):
                self.ids.setdefault(int(m.group(2)), []).append(m.group(1))
        self.cache = {}
        self.fonts = {int(k): font(cfg.get("font"), px, w) for k, (px, w) in cfg["labelFonts"].items()}

    def image(self, bmp):
        if bmp not in self.cache:
            paths = [self.folder / f"{n}.png" for n in self.ids.get(bmp, [])]
            path = next((p for p in paths if p.is_file()), None)
            self.cache[bmp] = Image.open(path).convert("RGBA") if path else None
        return self.cache[bmp]

    def label(self, text, fnt, color, align):
        """The label as the engine sets it: its anchor (x, baseline) at the image's centre."""
        f = self.fonts.get(fnt) or next(iter(self.fonts.values()))
        lines = text.split("\n")
        ascent, descent = f.getmetrics()
        line_h = ascent + descent
        w = max(int(f.getlength(t)) for t in lines) + 8
        size = 2 * (w + 8)
        hh = 2 * (line_h * len(lines) + 16)
        im = Image.new("RGBA", (size, hh), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        anchor = {0: "ms", 1: "ls", 2: "rs"}.get(align, "ms")
        for i, t in enumerate(lines):
            d.text((size // 2, hh // 2 + i * line_h), t, font=f, fill=(*rgb565(color), 255), anchor=anchor)
        return im


def frame_of(s, t):
    _, _, _, _, _, _, frm, to, rate, loop, born = s[:11]
    if frm == to or rate <= 0:
        return frm
    n = to - frm + 1
    k = (t - born) // rate
    return frm + (k % n if loop else min(k, n - 1))


def placements(plane, x, y, a):
    """The sprite on its own plane and on the neighbours it may reach over an edge."""
    out = [(plane, x, y, a)]
    for to in range(6):
        if to == plane or to == OPP[plane]:
            continue
        k = to * 30 + plane * 5
        dx, dy, da, c, s = CONV[k:k + 5]
        out.append((to, x * c - y * s + 2 * LIM * dx, x * s + y * c + 2 * LIM * dy, a + da))
    return out


def paste_clipped(dst, im, u, v):
    x0, y0 = max(0, u), max(0, v)
    x1, y1 = min(dst.width, u + im.width), min(dst.height, v + im.height)
    if x1 > x0 and y1 > y0:
        dst.alpha_composite(im.crop((x0 - u, y0 - v, x1 - u, y1 - v)), (x0, y0))


def draw_bezels(f, color):
    d = ImageDraw.Draw(f)
    d.rectangle((0, 0, FACE - 1, LIM - SCREEN_OUT - 1), fill=color)
    d.rectangle((0, LIM + SCREEN_OUT, FACE - 1, FACE - 1), fill=color)
    d.rectangle((0, 0, LIM - SCREEN_OUT - 1, FACE - 1), fill=color)
    d.rectangle((LIM + SCREEN_OUT, 0, FACE - 1, FACE - 1), fill=color)
    d.rectangle((LIM - SCREEN_IN, 0, LIM + SCREEN_IN - 1, FACE - 1), fill=color)
    d.rectangle((0, LIM - SCREEN_IN, FACE - 1, LIM + SCREEN_IN - 1), fill=color)


def faces_from_sprites(art, frame, space, bezel):
    faces = [Image.new("RGBA", (FACE, FACE), (*space, 255)) for _ in range(6)]
    t = frame["t"]
    for s in sorted(frame["s"], key=lambda s: (s[5], s[0])):
        _, plane, x, y, a = s[:5]
        transp, tint = s[11], s[12]
        if len(s) > 13:
            im = art.label(s[16], s[13], s[14], s[15])
        else:
            im = art.image(frame_of(s, t))
            if im is None:
                continue
            if tint != 0xFFFF:
                arr = np.array(im).astype(np.float32)
                for c, k in enumerate(rgb565(tint)):
                    arr[:, :, c] *= k / 255
                im = Image.fromarray(arr.astype(np.uint8), "RGBA")
        if transp:
            arr = np.array(im)
            arr[:, :, 3] = (arr[:, :, 3].astype(np.float32) * (31 - transp) / 31).astype(np.uint8)
            im = Image.fromarray(arr, "RGBA")
        half = max(im.width, im.height) / 2
        for p, px, py, pa in placements(plane, x, y, a):
            if p != plane and (abs(px) - half > LIM or abs(py) - half > LIM):
                continue
            r = im.rotate(pa % 360, expand=True) if pa % 360 else im
            paste_clipped(faces[p], r, int(round(LIM + px - r.width / 2)), int(round(LIM - py - r.height / 2)))
    for f in faces:
        draw_bezels(f, bezel)
    return faces


def faces_from_net(path, bezel):
    """shot.h's unfolded cube -> six face images with the bezels of the sprite mode."""
    net = Image.open(path).convert("RGBA")
    faces = []
    for p in range(6):
        i, j = NET[p]
        ox, oy = SHOT_MARGIN + i * (SHOT_FACE + SHOT_MARGIN), SHOT_MARGIN + j * (SHOT_FACE + SHOT_MARGIN)
        f = Image.new("RGBA", (FACE, FACE), (*bezel, 255))
        for qx in (0, 1):
            for qy in (0, 1):
                box = (ox + qx * (SCREEN + SHOT_GAP), oy + qy * (SCREEN + SHOT_GAP))
                screen = net.crop((box[0], box[1], box[0] + SCREEN, box[1] + SCREEN))
                f.paste(screen, (LIM - SCREEN_OUT + qx * (SCREEN + 2 * SCREEN_IN), LIM - SCREEN_OUT + qy * (SCREEN + 2 * SCREEN_IN)))
        faces.append(f)
    return faces


# --- 3D ------------------------------------------------------------------------------------------

def v3(t):
    return np.array(t, dtype=np.float64)


def rot_axis(axis, ang):
    """Rotation by `ang` radians about the unit `axis` (right-handed)."""
    x, y, z = axis
    c, s, k = math.cos(ang), math.sin(ang), 1 - math.cos(ang)
    return np.array([[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
                     [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
                     [z * x * k - y * s, z * y * k + x * s, c + z * z * k]])


def rot_between(a, b):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-6:
        return np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def persp_coeffs(src, dst):
    """PIL PERSPECTIVE coefficients mapping output points `dst` to input points `src`."""
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(m, dtype=np.float64), np.array([p for uv in src for p in uv], dtype=np.float64)).tolist()


def frame_up(frame):
    g = v3(frame.get("g", (0, -1, 0)))
    up = -g if np.linalg.norm(g) > 0.1 else v3((0, 1, 0))
    return up / np.linalg.norm(up)


def mark_level(frames):
    """Each frame's level face: the face up stays it while the cube leans less than 60 degrees off it,
    so a robot's steep tilt does not flip the view to a side face."""
    level = None
    for f in frames:
        up = frame_up(f)
        if level is None or up @ v3(N3D[level]) < LEVEL_KEEP:
            level = int(np.argmax([up @ v3(n) for n in N3D]))
        f["level"] = level


def view_matrix(frame):
    """The cube tilted the way the player holds it (a quarter as steep), then the camera's yaw and pitch."""
    up = frame_up(frame)
    level = v3(N3D[frame["level"]])
    up = level + VIEW_TILT * (up - level)
    tilt = rot_between(up, level) @ rot_between(level, v3((0, 1, 0)))
    pitch, yaw = math.radians(-frame["pitch"]), math.radians(frame["yaw"])
    rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    return rx @ ry @ tilt


def project(pt):
    cx, cy = VIEW_SIZE[0] / 2, VIEW_SIZE[1] / 2 - 10
    z = pt[2] + CAM
    return (cx + SCALE * pt[0] / z, cy - SCALE * pt[1] / z)


def visible(normal, centre):
    return (v3((0, 0, -CAM)) - centre) @ normal > 0


def shade(img, normal):
    k = 0.82 + 0.18 * max(0.0, float(normal @ v3((0.3, 0.8, -0.5))))
    if k >= 1.0:
        return img
    arr = np.array(img).astype(np.float32)
    arr[:, :, :3] *= k
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def warp(out, img, corners, normal, outline=4):
    """`img` onto the quad `corners` (its TL TR BR BL) of `out`, shaded by `normal`."""
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    x0, y0 = int(math.floor(min(xs))), int(math.floor(min(ys)))
    x1, y1 = int(math.ceil(max(xs))) + 1, int(math.ceil(max(ys))) + 1
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    local = [(x - x0, y - y0) for x, y in corners]
    src = [(0, 0), (img.width, 0), (img.width, img.height), (0, img.height)]
    w = img.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, persp_coeffs(src, local), Image.BILINEAR)
    mask = Image.new("L", w.size, 0)
    ImageDraw.Draw(mask).polygon(local, fill=255)
    w.putalpha(mask)
    out.alpha_composite(shade(w, normal), (x0, y0))
    if outline:
        ImageDraw.Draw(out).line(corners + [corners[0]], fill=SEAM, width=outline)


def cube_view(faces, frame):
    r = view_matrix(frame)
    out = Image.new("RGBA", VIEW_SIZE, (0, 0, 0, 0))
    order = []
    for p in range(6):
        n = r @ v3(N3D[p])
        if visible(n, n):
            order.append((n[2], p))
    for _, p in sorted(order, reverse=True):
        n, t, b = (r @ v3(v) for v in (N3D[p], T3D[p], B3D[p]))
        corners = [project(n + t * su + b * sv) for su, sv in QUADS]
        warp(out, faces[p], corners, n, outline=6)
    return out


# --- twists --------------------------------------------------------------------------------------

def stickers():
    """The 24 screens as stickers: (plane, quadrant index, 3D centre, corners TL TR BR BL, crop box)."""
    out = []
    for p in range(6):
        n, t, b = v3(N3D[p]), v3(T3D[p]), v3(B3D[p])
        for q, (su, sv) in enumerate(QUADS):
            u0, u1 = (-1, 0) if su < 0 else (0, 1)
            vb, vt = (0, 1) if sv > 0 else (-1, 0)
            corners = [n + t * u0 + b * vt, n + t * u1 + b * vt, n + t * u1 + b * vb, n + t * u0 + b * vb]
            box = (0 if su < 0 else HALF, 0 if sv > 0 else HALF)
            out.append((p, q, n + t * su * 0.5 + b * sv * 0.5, corners, (box[0], box[1], box[0] + HALF, box[1] + HALF)))
    return out


STICKERS = stickers()


def where(centre, right, rot):
    """Plane, quadrant and quarter turns (CCW in the image) of a sticker after `rot`."""
    c, rt = rot @ centre, rot @ right
    axis = int(np.argmax(np.abs(c)))
    n = np.zeros(3)
    n[axis] = np.sign(c[axis])
    p = next(i for i in range(6) if np.allclose(N3D[i], n))
    su, sv = np.sign(c @ v3(T3D[p])), np.sign(c @ v3(B3D[p]))
    q = QUADS.index((int(su), int(sv)))
    turns = next(k for k, v in enumerate((T3D[p], B3D[p], tuple(-x for x in T3D[p]), tuple(-x for x in B3D[p])))
                 if np.allclose(rt, v))
    return p, q, turns


def screens_small(faces):
    """Each screen at TWIST_MATCH_PX, for matching: [plane][quadrant] -> float array."""
    out = []
    for p in range(6):
        row = []
        for q, (su, sv) in enumerate(QUADS):
            x0 = LIM - SCREEN_OUT if su < 0 else LIM + SCREEN_IN
            y0 = LIM - SCREEN_OUT if sv > 0 else LIM + SCREEN_IN
            im = faces[p].crop((x0, y0, x0 + SCREEN, y0 + SCREEN)).convert("RGB").resize((TWIST_MATCH_PX,) * 2, Image.BILINEAR)
            row.append(np.asarray(im, dtype=np.float32))
        out.append(row)
    return out


def find_twist(before, after):
    """(side, sign) of the half turn that best explains `before` -> `after`, or None."""
    b, a = screens_small(before), screens_small(after)
    def score(rot, side):
        err = 0.0
        for p, q, centre, corners, _ in STICKERS:
            src = b[p][q]
            if rot is not None and centre @ v3(N3D[side]) > 0:
                p2, q2, k = where(centre, v3(T3D[p]), rot)
                err += float(np.abs(np.rot90(src, k) - a[p2][q2]).mean())
            else:
                err += float(np.abs(src - a[p][q]).mean())
        return err
    none = score(None, 0)
    ranked = sorted((score(rot_axis(v3(N3D[s]), sg * math.pi / 2), s), s, sg) for s in range(6) for sg in (1, -1))
    best, second = ranked[0], ranked[1]
    if best[0] > TWIST_MATCH_CLEAR * second[0] or best[0] > TWIST_MATCH_NONE * none:
        return None
    return best[1], best[2]


def cube_view_turning(faces, frame, side, ang):
    """The cube with the half on `side` turned by `ang` radians, sticker by sticker."""
    r = view_matrix(frame)
    axis = v3(N3D[side])
    turn = rot_axis(axis, ang)
    out = Image.new("RGBA", VIEW_SIZE, (0, 0, 0, 0))
    cam_cube = r.T @ v3((0, 0, -CAM))
    halves = {True: [], False: []}
    for p, q, centre, corners, box in STICKERS:
        halves[bool(centre @ axis > 0)].append((p, centre, corners, box))
    # the half on the camera's far side of the cut first
    for moving in sorted((True, False), key=lambda m: (cam_cube @ axis > 0) == m):
        m = r @ turn if moving else r
        perp = [v for v in (v3((1, 0, 0)), v3((0, 1, 0)), v3((0, 0, 1))) if abs(v @ axis) < 0.5]
        cap_n = -axis if moving else axis
        cap = [perp[0] * su + perp[1] * sv for su, sv in QUADS]
        cn = m @ cap_n
        if visible(cn, m @ (cap_n * 0.0)):
            ImageDraw.Draw(out).polygon([project(m @ c) for c in cap], fill=SEAM)
        for p, centre, corners, box in halves[moving]:
            n = m @ v3(N3D[p])
            if not visible(n, m @ centre):
                continue
            warp(out, faces[p].crop(box), [project(m @ c) for c in corners], n, outline=4)
    return out


# --- the page ------------------------------------------------------------------------------------

def rounded(d, box, r, fill, outline=None, width=2):
    d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


class Page:
    def __init__(self, cfg):
        self.cfg = cfg
        self.c = {k: hex_rgb(v) for k, v in {**COLORS, **cfg.get("colors", {})}.items()}
        ttf = cfg.get("font")
        self.f_head = font(ttf, 26, "Medium")
        self.f_title = font(ttf, 64, "Bold")
        self.f_sub = font(ttf, 30, "Regular")
        self.f_card = font(ttf, 30, "SemiBold")
        self.f_card_sub = font(ttf, 24, "Regular")
        self.f_card2 = font(ttf, 25, "SemiBold")                          # a two-line row
        self.f_card2_sub = {px: font(ttf, px, "Regular") for px in range(20, 13, -1)}
        self.f_cap = font(ttf, 38, "SemiBold")
        self.f_cap_sub = font(ttf, 26, "Regular")
        self.f_net = font(ttf, 22, "Bold")
        self.art = Art(cfg)
        self.icons = [self.icon(row.get("icon")) for row in cfg["legend"]]
        self.base = self.background()

    def icon(self, name):
        if not name:
            return None
        path = Path(name) if name.lower().endswith(".png") else Path(self.cfg["sprites"]) / f"{name}.png"
        if not path.is_file():
            print(f"  legend icon not found: {path}")
            return None
        im = Image.open(path).convert("RGBA")
        k = 54 / max(im.size)
        return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)

    def background(self):
        c = self.c
        im = Image.new("RGBA", (W, H), (*c["page"], 255))
        d = ImageDraw.Draw(im)
        rounded(d, (16, 16, 1168, H - 6), 26, c["panel"], c["panel_edge"])
        rounded(d, (1186, 16, W - 16, H - 6), 26, c["panel"], c["panel_edge"])
        d.text((38, 38), self.cfg["head3d"], font=self.f_head, fill=c["dim"])
        d.text((1208, 38), self.cfg["headNet"], font=self.f_head, fill=c["dim"])
        title = self.cfg["title"] if isinstance(self.cfg["title"], list) else [self.cfg["title"]]
        x = 1208
        for k, part in enumerate(title):
            d.text((x, 596), part, font=self.f_title, fill=c["accent"] if k % 2 else c["text"])
            x += d.textlength(part, font=self.f_title)
        d.text((1208, 672), self.cfg.get("tagline", ""), font=self.f_sub, fill=c["dim"])
        return im

    def legend_text(self, d, y, title, text):
        """One line when it fits the row; else the title over the text, the text shrunk to fit."""
        c, x, right = self.c, 1306, W - 52
        w_title = d.textlength(title, font=self.f_card)
        if x + w_title + 16 + d.textlength(text, font=self.f_card_sub) <= right:
            d.text((x, y + 8), title, font=self.f_card, fill=c["text"])
            d.text((x + w_title + 16, y + 14), text, font=self.f_card_sub, fill=c["dim"])
            return
        d.text((x, y + 4), title, font=self.f_card2, fill=c["text"])
        f = next((f for f in self.f_card2_sub.values() if x + d.textlength(text, font=f) <= right), None)
        if f is None:                                                   # too long even small: cut it
            f = list(self.f_card2_sub.values())[-1]
            while text and x + d.textlength(text + "…", font=f) > right:
                text = text[:-1]
            text += "…"
        d.text((x, y + 34), text, font=f, fill=c["dim"])

    def faces(self, frame, frames_dir):
        if "net" in frame:
            return faces_from_net(frames_dir / frame["net"], self.c["bezel"])
        return faces_from_sprites(self.art, frame, self.c["space"], self.c["bezel"])

    def compose(self, frame, faces, cube):
        c = self.c
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        im.alpha_composite(cube, (62, 92))
        cell, ox, oy = 168, 1208, 74
        for p, (i, j) in NET.items():
            im.alpha_composite(faces[p].resize((cell - 4, cell - 4), Image.LANCZOS), (ox + i * cell + 2, oy + j * cell + 2))
            d.rectangle((ox + i * cell + 1, oy + j * cell + 1, ox + (i + 1) * cell - 2, oy + (j + 1) * cell - 2), outline=c["net_edge"], width=2)
            x, y = ox + i * cell + cell // 2, oy + j * cell + cell // 2
            d.ellipse((x - 15, y - 15, x + 15, y + 15), fill=c["page"], outline=(0x70, 0x78, 0x98), width=2)
            d.text((x, y), NET_NAME[p], font=self.f_net, fill=c["text"], anchor="mm")
        y = 724
        for k, row in enumerate(self.cfg["legend"]):
            on = k == frame.get("legend", -1)
            rounded(d, (1208, y, W - 38, y + 62), 14, c["row_on"] if on else c["row"], c["accent"] if on else c["row_edge"], 3 if on else 2)
            ic = self.icons[k]
            if ic is not None:
                im.alpha_composite(ic, (1234 + (54 - ic.width) // 2, y + 4 + (54 - ic.height) // 2))
            self.legend_text(d, y, row["title"], row.get("text", ""))
            y += 70
        cap, sub = frame.get("cap", ""), frame.get("sub", "")
        if cap or sub:
            w = max(d.textlength(cap, font=self.f_cap), d.textlength(sub, font=self.f_cap_sub)) + 60
            x0 = 592 - w / 2
            rounded(d, (x0, 950, x0 + w, 1050), 20, c["caption"], c["caption_edge"], 3)
            d.text((592, 978), cap, font=self.f_cap, fill=c["text"], anchor="mm")
            d.text((592, 1024), sub, font=self.f_cap_sub, fill=c["dim"], anchor="mm")
        return im.convert("RGB")


# --- jobs ----------------------------------------------------------------------------------------

_page = None
_frames = None
_dir = None


def _init(cfg, frames, frames_dir):
    global _page, _frames, _dir
    _page, _frames, _dir = Page(cfg), frames, frames_dir


def _render(job):
    """("frame", i, path) or ("turn", i, side, ang, path): the turn is drawn on frame i - 1's screens."""
    if job[0] == "frame":
        _, i, path = job
        faces = _page.faces(_frames[i], _dir)
        cube = cube_view(faces, _frames[i])
        frame = _frames[i]
    else:
        _, i, side, ang, path = job
        faces = _page.faces(_frames[i - 1], _dir)
        frame = _frames[i - 1]
        cube = cube_view_turning(faces, frame, side, ang)
    _page.compose(frame, faces, cube).save(path, quality=92)
    return path


def ease(x):
    return x * x * (3 - 2 * x)


def plan(cfg, frames, frames_dir, every, twist_frames):
    """The jobs: every `every`-th frame, and the turn of each twist before the frame that follows it."""
    jobs = []
    page = None
    for i in range(0, len(frames), every):
        f = frames[i]
        if f.get("twist", -1) >= 0 and i > 0 and twist_frames > 0:
            if page is None:
                page = Page(cfg)
            found = find_twist(page.faces(frames[i - 1], frames_dir), page.faces(f, frames_dir))
            if found is None:
                print(f"  frame {i}: twist {f['twist']} not seen on the screens: cut")
            else:
                side, sign = found
                for k in range(1, twist_frames + 1):
                    jobs.append(("turn", i, side, sign * math.pi / 2 * ease(k / (twist_frames + 1))))
        jobs.append(("frame", i))
    return jobs


def main():
    ap = argparse.ArgumentParser(description="Render a WowCube demo video from a capture")
    ap.add_argument("config", help="demo.json: title, tagline, legend, font, paths")
    ap.add_argument("--every", type=int, default=1, help="draw every n-th frame (a quick look)")
    ap.add_argument("--still", type=int, default=None, help="only this frame, as <out>.<frame>.png")
    ap.add_argument("--out", default=None)
    ap.add_argument("--jobs", type=int, default=None, help="worker processes (default: all cores)")
    ap.add_argument("--twist-frames", type=int, default=TWIST_FRAMES)
    a = ap.parse_args()

    cfg = {**DEFAULTS, **json.loads(Path(a.config).read_text(encoding="utf-8"))}
    out = a.out or cfg.get("out") or "docs/demo/demo.mp4"
    frames_path = Path(cfg["frames"])
    frames_dir = frames_path.parent
    frames = [json.loads(line) for line in frames_path.read_text().splitlines() if line.strip()]
    mark_level(frames)

    if a.still is not None:
        _init(cfg, frames, frames_dir)
        i = next(k for k, f in enumerate(frames) if f["t"] >= a.still)
        path = str(Path(out).with_suffix(f".{a.still}.png"))
        _render(("frame", i, path))
        print(path)
        return

    jobs = plan(cfg, frames, frames_dir, a.every, a.twist_frames)
    with tempfile.TemporaryDirectory() as tmp:
        jobs = [(*j, f"{tmp}/f{k:05d}.jpg") for k, j in enumerate(jobs)]
        with mp.Pool(a.jobs, initializer=_init, initargs=(cfg, frames, frames_dir)) as pool:
            for k, _ in enumerate(pool.imap(_render, jobs, chunksize=4)):
                if k % 100 == 0:
                    print(f"  frame {k}/{len(jobs)}")
        fps = max(1, round(cfg["fps"] / a.every))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", f"{tmp}/f%05d.jpg",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(cfg["crf"]), "-preset", "medium",
                        "-movflags", "+faststart", out], check=True)
    print(out)


if __name__ == "__main__":
    main()
