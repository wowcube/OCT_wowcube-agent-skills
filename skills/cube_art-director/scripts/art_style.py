"""Style lock: measure the artist's approved anchors once, then score every
generated asset against that profile so drift is caught by numbers, not only
by eye.

profile.json (written next to the anchors, <style>/profile.json):
  palette_lab      K dominant colours of the anchors (CIELAB), weights
  L_mean, L_std    lightness of the anchors
  C_mean           mean chroma (saturation-like)
  outline_dark     share of silhouette-edge pixels darker than L*35 (keyed anchors only)
  thresholds       the defaults below; with 2+ anchors they are widened to what
                   the anchors themselves need (leave-one-out), but never past
                   CAP x the default. Anchors that need more than that do not
                   share one style: split them into families (separate projects
                   or style_check:false for the odd ones) - `style` warns.

A score is a set of measured numbers and a verdict per metric:
  palette_mean   mean CIE76 distance of the asset's pixels to the nearest palette colour
  off_palette    share of pixels further than OFF_DE from every palette colour
  over_chroma    share of pixels more saturated than the anchors' 99th percentile
                 (catches "too vivid / glossy" drift)
  out_of_range   share of pixels lighter / darker than the anchors' 0.5-99.5 percentile
                 lightness band (catches lighting / contrast drift)
  outline        asset edge-dark share vs anchors (only when both are keyed sprites)
  L_mean, C_mean reported for information only: a whole-scene anchor and a single
                 sprite legitimately differ in average lightness and saturation,
                 so averages are never gated (gamut shares are).
Numbers flag drift; the final call (intended exception or real drift) is the
reviewer's, and intended departures are marked style_check:false.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from art_image import key_backdrop, kmeans, lab_to_srgb, pick_key, srgb_to_lab

OFF_DE = 25.0
DEFAULT_T = {"palette_mean": 12.0, "off_palette": 0.12, "over_chroma": 0.10, "out_of_range": 0.10,
             "outline_min_ratio": 0.5}
SAMPLE = 40000
CAP = 2.0          # calibration may widen a threshold to at most CAP x its default


def _visible_rgb(img: Image.Image, guess_key: bool = False) -> tuple[np.ndarray, np.ndarray | None]:
    """RGB of visible pixels. Images with alpha use their alpha. guess_key=True
    (anchors only: a raw generation dropped in as an anchor) keys a flat pure
    magenta/green backdrop when at least 3 corners are that exact colour;
    finished assets are never guessed at (opaque art may be green).
    Returns (rgb Nx3, rgba array or None when the image is opaque)."""
    a = np.array(img.convert("RGBA"))
    if (a[..., 3] < 255).any():
        return a[a[..., 3] > 0][:, :3], a
    if guess_key:
        rgb = a[..., :3].astype(int)
        corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
        for key, val in (("magenta", (255, 0, 255)), ("green", (0, 255, 0))):
            if (np.abs(corners - np.array(val)).sum(1) < 40).sum() >= 3:
                k = np.array(key_backdrop(img, key))
                return k[k[..., 3] > 0][:, :3], k
    return a[..., :3].reshape(-1, 3), None


def _edge_dark_share(rgba: np.ndarray) -> float | None:
    m = rgba[..., 3] > 0
    if not m.any() or m.all():
        return None
    pad = np.pad(m, 1)
    interior = pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    edge = m & ~interior
    if not edge.any():
        return None
    lab = srgb_to_lab(rgba[edge][:, :3])
    return float((lab[:, 0] < 35).mean())


def _sample(rgb: np.ndarray, n: int = SAMPLE, seed: int = 0) -> np.ndarray:
    if len(rgb) <= n:
        return rgb
    return rgb[np.random.default_rng(seed).choice(len(rgb), n, replace=False)]


def _palette(lab: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    c, n = kmeans(lab, k)
    w = n / n.sum()
    keep = w >= 0.004
    return c[keep], w[keep]


def _metrics(lab: np.ndarray, pal: np.ndarray) -> dict:
    d = np.sqrt(((lab[:, None, :] - pal[None]) ** 2).sum(-1)).min(1)
    C = np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2)
    return {"palette_mean": float(d.mean()), "palette_p95": float(np.percentile(d, 95)),
            "off_palette": float((d > OFF_DE).mean()), "L_mean": float(lab[:, 0].mean()),
            "C_mean": float(C.mean())}


def extract(anchors: list[Path], out_dir: Path, k: int = 24) -> dict:
    """Build profile.json + palette swatch from the approved anchors."""
    if not anchors:
        raise SystemExit("no style anchors: put the approved style frame(s) in the anchors list first")
    per = []
    budget = max(4000, SAMPLE // len(anchors))      # equal weight per anchor, not per pixel
    for p in anchors:
        rgb, rgba = _visible_rgb(Image.open(p), guess_key=True)
        if len(rgb) < 16:
            raise SystemExit(f"anchor {p} has no visible pixels - remove it or fix its alpha")
        per.append((p, srgb_to_lab(_sample(rgb, budget)), rgba))
    all_lab = np.concatenate([x[1] for x in per])
    pal, w = _palette(all_lab, k)
    edges = [e for e in (_edge_dark_share(x[2]) for x in per if x[2] is not None) if e is not None]
    t = dict(DEFAULT_T)
    if len(per) >= 2:
        # leave-one-out: how far each anchor sits from the palette of the others
        lo = []
        for i in range(len(per)):
            rest = np.concatenate([x[1] for j, x in enumerate(per) if j != i])
            p_rest, _ = _palette(rest, k)
            m = _metrics(per[i][1], p_rest)
            Cr = np.sqrt(rest[:, 1] ** 2 + rest[:, 2] ** 2)
            Ci = np.sqrt(per[i][1][:, 1] ** 2 + per[i][1][:, 2] ** 2)
            Li = per[i][1][:, 0]
            m["over_chroma"] = float((Ci > np.percentile(Cr, 99) + 4).mean())
            m["out_of_range"] = float(((Li > np.percentile(rest[:, 0], 99.5) + 4) |
                                       (Li < np.percentile(rest[:, 0], 0.5) - 4)).mean())
            lo.append(m)
        warnings = []
        for key in ("palette_mean", "off_palette", "over_chroma", "out_of_range"):
            need = 1.3 * max(m[key] for m in lo)
            if need > CAP * DEFAULT_T[key]:
                warnings.append(f"{key}: anchors disagree ({need:.3g} needed, capped at {CAP * DEFAULT_T[key]:.3g})")
            t[key] = round(min(max(t[key], need), CAP * DEFAULT_T[key]), 4)
        for w_ in warnings:
            print(f"WARNING style: {w_} - these anchors may not be one style; consider families", flush=True)
    C_all = np.sqrt(all_lab[:, 1] ** 2 + all_lab[:, 2] ** 2)
    prof = {
        "anchors": [str(p) for p in anchors],
        "palette_lab": pal.round(2).tolist(), "palette_weight": w.round(4).tolist(),
        "palette_hex": ["#%02x%02x%02x" % tuple(c) for c in lab_to_srgb(pal)],
        "L_mean": float(all_lab[:, 0].mean()), "L_std": float(all_lab[:, 0].std()),
        "L_lo": float(np.percentile(all_lab[:, 0], 0.5)), "L_hi": float(np.percentile(all_lab[:, 0], 99.5)),
        "C_mean": float(C_all.mean()), "C_p99": float(np.percentile(C_all, 99)),
        "outline_dark": float(np.mean(edges)) if edges else None,
        "thresholds": t,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "profile.json").write_text(json.dumps(prof, indent=2), encoding="utf-8")
    sw = 32
    swatch = Image.new("RGB", (sw * len(pal), sw + 10), (20, 20, 20))
    for i, c in enumerate(lab_to_srgb(pal)):
        swatch.paste(tuple(int(v) for v in c), (i * sw, 0, (i + 1) * sw, sw))
        bar = int(sw * min(1.0, w[i] * 8))
        swatch.paste((200, 200, 200), (i * sw, sw + 2, i * sw + bar, sw + 8))
    swatch.save(out_dir / "palette.png")
    return prof


def load_profile(style_dir: Path) -> dict | None:
    f = style_dir / "profile.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def palette_rgb(prof: dict | None) -> np.ndarray | None:
    if not prof:
        return None
    return lab_to_srgb(np.array(prof["palette_lab"]))


def score(img: Image.Image, prof: dict) -> dict:
    """Measure one asset against the profile -> metrics + verdict per metric."""
    rgb, rgba = _visible_rgb(img, guess_key=False)
    if not len(rgb):
        return {"verdict": "FAIL", "why": ["empty image"]}
    lab = srgb_to_lab(_sample(rgb))
    m = _metrics(lab, np.array(prof["palette_lab"]))
    t = {**DEFAULT_T, **prof["thresholds"]}
    C = np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2)
    m["over_chroma"] = float((C > prof["C_p99"] + 4).mean())
    m["out_of_range"] = float(((lab[:, 0] > prof["L_hi"] + 4) | (lab[:, 0] < prof["L_lo"] - 4)).mean())
    why, warn = [], []

    def gate(ok: bool, near: bool, msg: str):
        if not ok:
            why.append(msg)
        elif near:
            warn.append(msg)

    gate(m["palette_mean"] <= t["palette_mean"], m["palette_mean"] > 0.75 * t["palette_mean"],
         f"palette distance {m['palette_mean']:.1f} (max {t['palette_mean']:.1f})")
    gate(m["off_palette"] <= t["off_palette"], m["off_palette"] > 0.75 * t["off_palette"],
         f"off-palette pixels {m['off_palette']:.0%} (max {t['off_palette']:.0%})")
    gate(m["over_chroma"] <= t["over_chroma"], m["over_chroma"] > 0.75 * t["over_chroma"],
         f"more saturated than the anchors on {m['over_chroma']:.0%} of pixels (max {t['over_chroma']:.0%})")
    gate(m["out_of_range"] <= t["out_of_range"], m["out_of_range"] > 0.75 * t["out_of_range"],
         f"outside the anchors' light/dark range on {m['out_of_range']:.0%} of pixels (max {t['out_of_range']:.0%})")
    if rgba is not None and prof.get("outline_dark"):
        e = _edge_dark_share(rgba)
        if e is not None:
            m["outline_dark"] = e
            gate(e >= prof["outline_dark"] * t["outline_min_ratio"], e < prof["outline_dark"] * 0.75,
                 f"dark outline on {e:.0%} of the edge (anchors {prof['outline_dark']:.0%})")
    m["verdict"] = "FAIL" if why else ("WARN" if warn else "PASS")
    m["why"] = why + [f"near limit: {w}" for w in warn]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def suggest_key(prof: dict | None, text: str) -> str:
    return pick_key(text, palette_rgb(prof))
