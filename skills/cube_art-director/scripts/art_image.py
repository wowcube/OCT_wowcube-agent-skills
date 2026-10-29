"""Image processing for generated art: chroma-key removal, fitting to the
target size, shared-scale fitting of sets, colour locking, colour science
helpers (sRGB <-> CIELAB) used by the style checks.

Everything works on RGBA numpy arrays / PIL images and has no project
knowledge; art.py wires it to the asset spec.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps

KEYS = {"magenta": (255, 0, 255), "green": (0, 255, 0)}


# --------------------------------------------------------------------------- keying
def key_backdrop(img: Image.Image, key: str = "magenta", tol: int = 90) -> Image.Image:
    """Make the flat chroma-key backdrop transparent and strip its fringing.

    The prompt asks the model for a flat #FF00FF (or #00FF00) backdrop. Pixels
    close to the key, or strongly key-tinted, become transparent; edge pixels
    that kept some key tint are de-spilled towards their neutral colour.
    """
    arr = np.array(img.convert("RGBA")).astype(np.int16)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    target = KEYS[key]
    if key == "green":
        excess = g - np.maximum(r, b)
    else:
        excess = np.minimum(r, b) - g
    dist = np.abs(r - target[0]) + np.abs(g - target[1]) + np.abs(b - target[2])
    bg = (dist <= tol) | ((excess > 60) & (dist <= 2 * tol))
    arr[bg, 3] = 0
    # de-spill only the subject's rim (pixels near the removed backdrop): an
    # interior purple or green that the subject really has must stay untouched
    near = bg.copy()
    for _ in range(2):
        n = near.copy()
        n[1:, :] |= near[:-1, :]
        n[:-1, :] |= near[1:, :]
        n[:, 1:] |= near[:, :-1]
        n[:, :-1] |= near[:, 1:]
        near = n
    spill = (~bg) & near & (excess > 20)
    if key == "green":
        arr[spill, 1] = np.maximum(r[spill], b[spill])
    else:
        m = np.minimum(r, b)
        arr[spill, 0] = np.minimum(r[spill], g[spill] + (r[spill] - m[spill]))
        arr[spill, 2] = np.minimum(b[spill], g[spill] + (b[spill] - m[spill]))
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")


def key_fringe_count(a: np.ndarray, key: str | None = None) -> int:
    """Visible pixels that still read as THE generation key colour (a pink
    subject drawn on green legitimately keeps its magenta-ish pixels).
    key=None checks both (unknown provenance)."""
    rgb = a[..., :3].astype(int)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    vis = a[..., 3] > 0
    magenta = (np.minimum(r, b) - g > 80) & (r > 150) & (b > 150)
    green = (g - np.maximum(r, b) > 80) & (g > 150)
    hit = magenta if key == "magenta" else green if key == "green" else (magenta | green)
    return int((vis & hit).sum())


def pick_key(text: str, palette_rgb: np.ndarray | None = None) -> str:
    """Backdrop colour the subject does not use: green when the prompt or the
    style palette contains pink/magenta, magenta otherwise."""
    t = text.lower()
    # a prompt that already names its backdrop wins (older manifests spell it out)
    if "#00ff00" in t:
        return "green"
    if "#ff00ff" in t:
        return "magenta"
    if any(w in t for w in ("pink", "magenta", "fuchsia", "purple", "violet")):
        return "green"
    if palette_rgb is not None and len(palette_rgb):
        p = palette_rgb.astype(int)
        if (((np.minimum(p[:, 0], p[:, 2]) - p[:, 1]) > 70) & (p[:, 0] > 140)).any():
            return "green"
    return "magenta"


# --------------------------------------------------------------------------- fitting
def _box_down(canvas: Image.Image, size: tuple[int, int], binary_alpha: bool) -> Image.Image:
    """Box downscale. Pillow resizes RGBA with premultiplied alpha itself, so
    edge colours stay clean; premultiplying by hand on top of that brightened
    every half-covered rim pixel (grey 80 came out as 157)."""
    small = np.array(canvas.convert("RGBA").resize(size, Image.BOX))
    if binary_alpha:
        small[..., 3] = np.where(small[..., 3] >= 128, 255, 0).astype(np.uint8)
    small[small[..., 3] == 0, :3] = 0
    return Image.fromarray(small, "RGBA")


def fit_rgba(img: Image.Image, size: tuple[int, int], binary_alpha: bool = True) -> Image.Image:
    """Crop to the object, pad to the target aspect, downscale."""
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    tw, th = size
    w, h = img.size
    scale = min(tw / w, th / h)
    cw, ch = max(1, round(tw / scale)), max(1, round(th / scale))
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    canvas.paste(img, ((cw - w) // 2, (ch - h) // 2))
    return _box_down(canvas, size, binary_alpha)


def fit_rgba_set(imgs: list[Image.Image], size: tuple[int, int], binary_alpha=True) -> list[Image.Image]:
    """Fit frames of ONE subject in motion with one shared scale, each aligned
    on its centre of mass. Fitting frames one by one rescales each to its own
    bbox: an outstretched arm shrinks the whole body and the figure jitters."""
    tw, th = size
    arrs = [np.array(im.convert("RGBA")) for im in imgs]
    boxes, cents = [], []
    for a in arrs:
        ys, xs = np.nonzero(a[..., 3] > 0)
        if not len(xs):
            ys, xs = np.array([0, a.shape[0] - 1]), np.array([0, a.shape[1] - 1])
        boxes.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
        cents.append((xs.mean(), ys.mean()))
    half_w = max(max(c[0] - b[0], b[2] - c[0]) for b, c in zip(boxes, cents)) * 1.02
    half_h = max(max(c[1] - b[1], b[3] - c[1]) for b, c in zip(boxes, cents)) * 1.02
    if half_w / half_h < tw / th:
        half_w = half_h * tw / th
    else:
        half_h = half_w * th / tw
    # one geometry for the whole set, alpha policy per frame (bool or list of bools)
    modes = binary_alpha if isinstance(binary_alpha, (list, tuple)) else [binary_alpha] * len(arrs)
    out = []
    for a, (cx, cy), bin_a in zip(arrs, cents, modes):
        win = Image.new("RGBA", (round(2 * half_w), round(2 * half_h)), (0, 0, 0, 0))
        win.paste(Image.fromarray(a, "RGBA"), (round(half_w - cx), round(half_h - cy)))
        out.append(_box_down(win, size, bin_a))
    return out


def fit_opaque(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Cover-fit an opaque picture (backgrounds, tiles) to the target size."""
    # fractional cover crop: extreme aspect ratios never round a side to zero
    return ImageOps.fit(img.convert("RGB"), tuple(size), Image.LANCZOS).convert("RGBA")


def match_colours(img: Image.Image, ref: Image.Image) -> Image.Image:
    """Shift `img`'s opaque pixels to the per-channel mean/std of `ref`'s, so
    separately generated frames of one character read as the same colours."""
    a = np.array(img.convert("RGBA")).astype(np.float32)
    r = np.array(ref.convert("RGBA")).astype(np.float32)
    ma, mr = a[..., 3] > 0, r[..., 3] > 0
    if not ma.any() or not mr.any():
        return img
    src, dst = a[ma][:, :3], r[mr][:, :3]
    s_mean, s_std = src.mean(0), src.std(0) + 1e-6
    d_mean, d_std = dst.mean(0), dst.std(0)
    a[ma, :3] = ((src - s_mean) / s_std * d_std + d_mean).clip(0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


# --------------------------------------------------------------------------- measures
def mask_stats(a: np.ndarray):
    """(mask, bbox, centroid, area, mean_rgb) of the visible pixels."""
    m = a[..., 3] > 0
    ys, xs = np.nonzero(m)
    if not len(xs):
        return m, None, None, 0, None
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return m, bbox, (float(xs.mean()), float(ys.mean())), int(m.sum()), a[m][:, :3].astype(float).mean(0)


# --------------------------------------------------------------------------- colour science
def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(N,3) uint8/float sRGB -> (N,3) CIELAB (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[:, 1] - 16
    a = 500 * (f[:, 0] - f[:, 1])
    b = 200 * (f[:, 1] - f[:, 2])
    return np.stack([L, a, b], axis=1)


def kmeans(x: np.ndarray, k: int, iters: int = 20, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Plain k-means (k-means++ init). Returns (centres, counts)."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=np.float64)
    k = max(1, min(k, len(x)))
    centres = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = np.min(((x[:, None, :] - np.array(centres)[None]) ** 2).sum(-1), axis=1)
        p = d / d.sum() if d.sum() > 0 else None
        centres.append(x[rng.choice(len(x), p=p)])
    c = np.array(centres)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([x[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
        if np.allclose(new, c):
            break
        c = new
    lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
    counts = np.bincount(lab, minlength=k)
    order = np.argsort(-counts)
    return c[order], counts[order]


def lab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """(N,3) CIELAB -> (N,3) uint8 sRGB (clipped)."""
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[:, 0] + 16) / 116
    fx = fy + lab[:, 1] / 500
    fz = fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], axis=1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27))
    xyz *= np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314],
                  [-0.9692660, 1.8760108, 0.0415560],
                  [0.0556434, -0.2040259, 1.0572252]])
    c = xyz @ m.T
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 0, None) ** (1 / 2.4) - 0.055)
    return (c.clip(0, 1) * 255).round().astype(np.uint8)
