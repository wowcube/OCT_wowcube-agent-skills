"""Measurable QA for a generated asset set (rules: references/QA_RULES.md).

Per asset: exact size, a real cut-out for keyed assets (transparent pixels
exist unless the asset is declared to fill its canvas), clean key (no pixels
of the colour it was keyed on), alpha mode, canvas fill, style score against
the anchors' profile.
Per set (same `set` and size): one character in motion must not pump in
scale (area/height vs the first frame of the same anim) or jitter (centroid
drift), and colour-locked frames must keep the colours of the frame they are
locked to (the same reference processing used: art_spec.colour_ref).

Writes <ws>/qa/report.txt, report.json, all.png (every final in manifest order,
at the size the cube draws it), sets.png (frames x4 + onion skin per anim; only
when the manifest has sets) and one flipbook GIF per anim (frames in frame
order). Returns the
number of hard failures. Empty frames are failures, never references.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from art_image import key_fringe_count, mask_stats
from art_spec import colour_ref, safe_name
from art_style import score as style_score

CENTROID_JITTER_PX = 1.0
AREA_RATIO = (0.85, 1.15)
HEIGHT_RATIO = (0.93, 1.07)
COLOUR_DRIFT = 10.0


def run(project, final_dir: Path, prof: dict | None, keys: dict | None = None,
        scope: set[str] | None = None) -> tuple[int, dict]:
    keys = keys or {}
    qa = project.workspace / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    lines, fails = [], 0
    results: dict[str, dict] = {}
    in_scope = (lambda n: True) if scope is None else (lambda n: n in scope)

    def check(name: str, ok: bool, msg: str, hard: bool = True):
        nonlocal fails
        tag = "PASS" if ok else ("FAIL" if hard else "WARN")
        lines.append(f"{tag} {name}: {msg}")
        results.setdefault(name, {"checks": []})["checks"].append({"ok": ok, "hard": hard, "msg": msg})
        if not ok and hard:
            fails += 1

    arrs: dict[str, np.ndarray] = {}
    empty: set[str] = set()
    for a in project.assets:
        if not in_scope(a.name):
            continue
        f = final_dir / f"{a.name}.png"
        if not f.exists():
            check(a.name, False, "missing final image (run process)")
            continue
        arr = np.array(Image.open(f).convert("RGBA"))
        arrs[a.name] = arr
        check(a.name, tuple(arr.shape[1::-1]) == tuple(a.size),
              f"size {arr.shape[1]}x{arr.shape[0]} (spec {a.size[0]}x{a.size[1]})")
        _, bbox, _, area, _ = mask_stats(arr)
        if bbox is None:
            empty.add(a.name)
            check(a.name, False, "fully transparent")
            continue
        if a.background == "key":
            transparent = int((arr[..., 3] == 0).sum())
            full_canvas = a.fill is not None and a.fill >= 0.999
            check(a.name, transparent > 0 or full_canvas,
                  f"cut-out has {transparent} transparent pixels" + ("" if transparent else
                  " - the backdrop was not removed (or declare fill: 1.0 for a full-canvas asset)"))
            key = a.key if a.key != "auto" else keys.get(a.name)
            fr = key_fringe_count(arr, key)
            check(a.name, fr == 0, f"{key or 'key'}-colour pixels left: {fr}")
            if a.alpha == "binary":
                semi = int(((arr[..., 3] > 0) & (arr[..., 3] < 255)).sum())
                check(a.name, semi == 0, f"semi-transparent pixels: {semi}")
            if a.fill:
                fw, fh = (bbox[2] - bbox[0]) / a.size[0], (bbox[3] - bbox[1]) / a.size[1]
                check(a.name, min(fw, fh) >= a.fill, f"fills {fw:.0%} x {fh:.0%} of the canvas (min {a.fill:.0%})")
        else:
            check(a.name, bool((arr[..., 3] == 255).all()), "opaque everywhere")
        if not a.style_check:
            lines.append(f"INFO {a.name}: style check off (approved exception)")
        elif prof is None:
            results.setdefault(a.name, {"checks": []})["style"] = {"verdict": "UNCHECKED", "why": ["no style profile"]}
        else:
            s = style_score(Image.fromarray(arr, "RGBA"), prof)
            results[a.name]["style"] = s
            check(a.name, s["verdict"] != "FAIL",
                  f"style {s['verdict']}" + (f" - {'; '.join(s['why'])}" if s["why"] else ""))

    rows = []
    groups: dict[tuple, list] = {}
    for a in project.assets:
        if a.set and a.background == "key":
            groups.setdefault((a.set, tuple(a.size)), []).append(a)
    for (sname, size), members in groups.items():
        live = [m for m in members if m.name in arrs and m.name not in empty]
        if len(live) < 2 or not any(in_scope(m.name) for m in members):
            continue
        st = {m.name: mask_stats(arrs[m.name]) for m in live}
        first = live[0]
        for i, m in enumerate(live):
            if i == 0 or not in_scope(m.name):
                continue
            _, bb, c, area, col = st[m.name]
            c0 = st[first.name][2]
            jit = float(np.hypot(c[0] - c0[0], c[1] - c0[1]))
            ref = next((o for o in live[:i] if o.anim == m.anim), None)
            if m.motion:
                # one character (colour-locked) must not pump or jitter: hard rules.
                # Other motion sets (effects, a fading blast) change shape on purpose:
                # the same numbers are reported as warnings for the reviewer.
                hard = m.colour_lock
                check(m.name, jit <= CENTROID_JITTER_PX, f"centroid jitter {jit:.2f}px vs {first.name} (max {CENTROID_JITTER_PX})", hard)
                hard = hard and not m.pose_free
                if ref is not None:
                    _, bb_r, _, area_r, _ = st[ref.name]
                    ar = area / max(area_r, 1)
                    hr = (bb[3] - bb[1]) / max(bb_r[3] - bb_r[1], 1)
                    check(m.name, AREA_RATIO[0] <= ar <= AREA_RATIO[1], f"area ratio {ar:.2f} vs {ref.name}", hard)
                    check(m.name, HEIGHT_RATIO[0] <= hr <= HEIGHT_RATIO[1], f"height ratio {hr:.2f} vs {ref.name}", hard)
            j = colour_ref(members, members.index(m))
            refm = members[j]
            if j != members.index(m) and refm.name in st:
                dc = float(np.abs(col - st[refm.name][4]).sum())
                check(m.name, dc <= COLOUR_DRIFT, f"colour drift {dc:.1f} vs {refm.name} (max {COLOUR_DRIFT})")
        anims: dict[str, list] = {}
        for m in live:
            anims.setdefault(m.anim or m.name, []).append(m)
        for anim, frames in anims.items():
            frames.sort(key=lambda m: (m.frame if m.frame is not None else 1 << 30, live.index(m)))
            if len(frames) >= 2:
                _flipbook(qa / f"{safe_name(sname)}_{safe_name(anim)}.gif", [arrs[m.name] for m in frames], size)
        rows.append((f"{sname} {size[0]}x{size[1]}", [arrs[m.name] for m in live], [m.name for m in live]))
    if rows:
        _sheet(qa / "sets.png", rows)
    if arrs:
        _all_sheet(qa / "all.png", [(a.name, arrs[a.name], a.fullsize or max(a.size) > 120) for a in project.assets if a.name in arrs])
    lines.append(f"\n{fails} hard failure(s)")
    (qa / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    (qa / "report.json").write_text(json.dumps({"fails": fails, "profile": bool(prof), "assets": results}, indent=1),
                                    encoding="utf-8")
    return fails, results


BG = (70, 52, 40, 255)


def _scaled(a: np.ndarray, size) -> Image.Image:
    k = max(2, min(6, 160 // max(size)))
    return Image.fromarray(a, "RGBA").resize((size[0] * k, size[1] * k), Image.NEAREST)


def _flipbook(path: Path, frames: list[np.ndarray], size) -> None:
    gif = []
    for a in frames:
        f = _scaled(a, size)
        bg = Image.new("RGBA", f.size, BG)
        bg.alpha_composite(f)
        gif.append(bg.convert("P", palette=Image.ADAPTIVE))
    gif[0].save(path, save_all=True, append_images=gif[1:], duration=200, loop=0)


def _onion(frames: list[Image.Image]) -> Image.Image:
    onion = Image.new("RGBA", frames[0].size, BG)
    tints = [(255, 120, 120), (120, 200, 255), (160, 255, 140), (255, 230, 120)]
    for i, f in enumerate(frames):
        t = np.array(f).astype(np.float32)
        t[..., 3] *= 0.55
        t[..., :3] = t[..., :3] * 0.4 + np.array(tints[i % 4]) * 0.6
        onion.alpha_composite(Image.fromarray(t.clip(0, 255).astype(np.uint8), "RGBA"))
    return onion


def _all_sheet(path: Path, items) -> None:
    """Every final on one sheet at device scale (x2; x1 for fullsize art), labelled."""
    tiles = []
    for name, a, fullsize in items:
        im = Image.fromarray(a, "RGBA")
        k = 1 if fullsize else 2
        im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        bg = Image.new("RGBA", im.size, BG)
        bg.alpha_composite(im)
        tiles.append((name, bg.convert("RGB")))
    rows, row, w = [], [], 0
    for t in tiles:
        if row and w + t[1].width + 8 > 1200:
            rows.append(row)
            row, w = [], 0
        row.append(t)
        w += t[1].width + 8
    rows.append(row)
    W = max(sum(t[1].width + 8 for t in r) for r in rows) + 8
    H = sum(max(t[1].height for t in r) + 22 for r in rows) + 4
    sheet = Image.new("RGB", (W, H), (25, 22, 19))
    d = ImageDraw.Draw(sheet)
    y = 4
    for r in rows:
        x = 4
        for name, im in r:
            d.text((x, y), name[:max(4, im.width // 6)], fill=(230, 220, 200))
            sheet.paste(im, (x, y + 16))
            x += im.width + 8
        y += max(t[1].height for t in r) + 22
    sheet.save(path)


def _sheet(path: Path, rows) -> None:
    built = []
    for title, arrs, names in rows:
        size = arrs[0].shape[1::-1]
        frames = [_scaled(a, size) for a in arrs]
        built.append((title, frames, _onion(frames)))
    W = max(sum(f.size[0] + 8 for f in fr) + on.size[0] + 24 for _, fr, on in built)
    H = sum(on.size[1] + 22 for _, _, on in built)
    sheet = Image.new("RGB", (W, H), (25, 22, 19))
    d = ImageDraw.Draw(sheet)
    y = 0
    for title, frames, onion in built:
        d.text((4, y + 2), title + "   (frames | onion skin)", fill=(230, 220, 200))
        x = 4
        for f in frames:
            bg = Image.new("RGBA", f.size, BG)
            bg.alpha_composite(f)
            sheet.paste(bg.convert("RGB"), (x, y + 18))
            x += f.size[0] + 8
        sheet.paste(onion.convert("RGB"), (x + 16, y + 18))
        y += onion.size[1] + 22
    sheet.save(path)
