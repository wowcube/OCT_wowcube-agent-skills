#!/usr/bin/env python3
"""cube_art-director CLI: style-locked asset generation with Codex.

  python art.py doctor   <spec>                     setup check: python deps, Codex CLI, ChatGPT login, model
  python art.py init     <dir>                      new project: art.json, style/STYLE.md, style/anchors/, refs/, drawn/
  python art.py candidates <spec> --subject "<what to draw>" [--n 3]
                                                    first style frames from the artist's refs/ (before any lock)
  python art.py style    <spec>                     profile the approved anchors -> style/profile.json + palette.png
  python art.py anchor   <spec> --only a,b          promote approved assets to style anchors (profile rebuilt)
  python art.py gen      <spec> [--only a,b] [--set s] [--force] [--jobs 3]
                                                    Codex draws every asset that has no raw image yet
  python art.py process  <spec> [--only a,b]        key + fit (sets share scale) -> final images; with --only,
                                                    an incomplete set fits the members that have a raw image
                                                    together (warning "partial set": family leaders first),
                                                    a complete set is always refitted whole
  python art.py qa       <spec> [--only a,b] [--set s]   checks + style scores; exit 1 on hard failures
  python art.py review   <spec>                     <workspace>/review.html for the artist
  python art.py feedback <spec> --file fb.json      fold the page's "Copy feedback" JSON into fixes.json
  python art.py all      <spec> [gen options]       gen -> process -> qa -> review

<spec> is an art.json project file or a WowCube manifest plans/<game>_assets.json
(then the workspace defaults to assets_<game>/ and final images go to its art/
folder, where the WowCube pack stage reads them). --workspace overrides.

Project layout (art.json kind):
  <project>/art.json, refs/ (artist references), drawn/ (artist drawings),
  style/STYLE.md + style/anchors/ + style/profile.json + style/candidates/,
  <workspace>/raw/ (model output, keys.json, prompts.json, logs/),
  <workspace>/final/ (exact-size images), <workspace>/qa/, <workspace>/review.html, <workspace>/fixes.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import art_codex  # noqa: E402
import art_qa  # noqa: E402
import art_review  # noqa: E402
import art_style  # noqa: E402
from art_image import fit_opaque, fit_rgba, fit_rgba_set, key_backdrop, match_colours, pick_key  # noqa: E402
from art_spec import (apply_meta, colour_ref, dependency_order, fix_for, load_fixes,  # noqa: E402
                      load_project, validate)

HERE = Path(__file__).resolve().parent


def style_dir(p) -> Path:
    """One stable style folder per project (anchors may live anywhere)."""
    return p.workspace / "style" if p.kind == "cube-manifest" else p.root / "style"


def final_dir(p) -> Path:
    return p.workspace / ("art" if p.kind == "cube-manifest" else "final")


_WARNED: set = set()


def prompt_block(p) -> str:
    """The '## Prompt block' section of STYLE.md: the operational style
    paragraph injected into every prompt. A WowCube manifest's `_style` seeds
    it when STYLE.md has none; when both exist and differ, STYLE.md wins and a
    warning says so (the two must not drift apart silently)."""
    block = ""
    if p.bible and p.bible.exists():
        text = p.bible.read_text(encoding="utf-8")
        m = re.search(r"^##\s*Prompt block\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
        if m:
            block = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()
            if block.startswith("<") and block.endswith(">"):
                block = ""                      # untouched template placeholder
    style = getattr(p, "style_text", None)
    if not block and style:
        return style
    if block and style and " ".join(block.split()) != " ".join(style.split()) and "style" not in _WARNED:
        _WARNED.add("style")
        print("WARNING: STYLE.md Prompt block differs from the manifest's _style - STYLE.md is used; "
              "update _style (Stage 2) or STYLE.md so they agree", file=sys.stderr)
    return block


def load(args):
    p = load_project(args.spec, args.workspace)
    fixes = load_fixes(p.workspace)
    apply_meta(p, fixes)
    errs = validate(p)
    if errs:
        print("spec problems:\n  " + "\n  ".join(errs), file=sys.stderr)
        raise SystemExit(2)
    return p, fixes


def pick(p, only: str | None, set_name: str | None):
    names = set(only.split(",")) if only else None
    out = [a for a in p.assets if (names is None or a.name in names) and (set_name is None or a.set == set_name)]
    if names and names - {a.name for a in out}:
        raise SystemExit(f"unknown asset(s): {sorted(names - {a.name for a in out})}")
    return out


def cmd_line(args, *extra: str) -> str:
    """A copy-pasteable command for the current interpreter, script, spec and workspace."""
    parts = [sys.executable, str(Path(__file__).resolve()), *extra[:1], str(Path(args.spec).resolve())]
    if args.workspace:
        parts += ["--workspace", str(Path(args.workspace).resolve())]
    parts += list(extra[1:])
    if sys.platform == "win32":
        return " ".join(f'"{x}"' if (" " in x or "\\" in x) else x for x in parts)
    return " ".join(shlex.quote(x) for x in parts)


def resolve_ref(p, ref: str) -> Path:
    """An image reference that is not an asset name: absolute, or relative to
    the workspace (fixes.json refs such as raw/<frame>.png), or to the project
    root (art.json paths such as drawn/pose.png) - first one that exists."""
    r = Path(ref)
    if r.is_absolute():
        return r
    for base in (p.workspace, p.root):
        if (base / r).exists():
            return base / r
    return p.workspace / r


def keys_file(p) -> Path:
    return p.workspace / "raw" / "keys.json"


def load_keys(p) -> dict:
    f = keys_file(p)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def key_of(p, a, keys: dict, prof=None) -> str:
    """The backdrop colour an asset was DRAWN on: recorded at generation time, so
    adding anchors later can never flip how an existing raw image is keyed."""
    if a.key != "auto":
        return a.key
    if a.name in keys:
        return keys[a.name]
    return pick_key(a.prompt)      # legacy raw without a record: prompt only, deterministic


# --------------------------------------------------------------------------- commands
def cmd_doctor(args) -> int:
    ok = True
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        print(f"ok   python {sys.version.split()[0]}, pillow {PIL.__version__}, numpy {numpy.__version__}")
    except ImportError as e:
        ok = False
        print(f"FAIL python deps: {e} (pip install pillow numpy)")
    for good, msg in art_codex.doctor():
        ok &= good
        print(("ok   " if good else "FAIL ") + msg)
    if args.spec and Path(args.spec).exists() and Path(args.spec).is_file():
        try:
            p, _ = load(args)
            print(f"ok   spec: {len(p.assets)} assets, {len(p.anchors)} anchor(s), workspace {p.workspace}")
            if not p.anchors:
                print("note no style anchors yet: run `candidates`, get the artist's pick, then `style`")
        except SystemExit:
            ok = False
    return 0 if ok else 1


def cmd_init(args) -> int:
    d = Path(args.spec)
    for sub in ("style/anchors", "style/candidates", "refs", "drawn"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    bible = d / "style" / "STYLE.md"
    if not bible.exists():
        shutil.copyfile(HERE.parent / "references" / "STYLE_TEMPLATE.md", bible)
    spec = d / "art.json"
    if not spec.exists():
        spec.write_text(json.dumps({
            "project": d.name, "workspace": "art_work",
            "style": {"bible": "style/STYLE.md", "anchors": []},
            "defaults": {"background": "key", "key": "auto", "alpha": "binary"},
            "assets": [{"name": "example_00", "size": [40, 40], "set": "example", "motion": True,
                        "colour_lock": True, "prompt": "describe the subject, pose and colours here"}],
        }, indent=2), encoding="utf-8")
    print(f"project ready: {spec}\n- artist references -> {d / 'refs'}, drawings -> {d / 'drawn'}"
          f"\n- write the style bible {bible}\n- approved style frames go to {d / 'style' / 'anchors'} "
          f"and art.json style.anchors")
    return 0


def cmd_candidates(args) -> int:
    """Style frames BEFORE the lock: the artist's refs/ (and drawn/) are attached
    as style references; the artist picks one -> it becomes the first anchor."""
    p, fixes = load(args)
    refs = sorted([*(p.root / "refs").glob("*.png"), *(p.root / "refs").glob("*.jpg"),
                   *(p.root / "drawn").glob("*.png")])[:6]
    if not refs:
        raise SystemExit(f"no references in {p.root / 'refs'} or {p.root / 'drawn'}")
    if not args.subject:
        raise SystemExit('candidates needs --subject "a representative character/prop/scene in this game"')
    out = style_dir(p) / "candidates"
    body = "\n\n".join(x for x in (prompt_block(p), args.subject) if x)
    ok_all = True
    for i in range(args.n):
        name = f"candidate_{i + 1:02d}"
        prompt = art_codex.build_prompt(name, body + f"\n\n(Variation {i + 1} of {args.n}: interpret the "
                                        "references faithfully; vary only composition details.)",
                                        n_anchors=0, subject=False, sketch=False, background="opaque",
                                        key="magenta", n_style_refs=len(refs))
        ok, info = art_codex.run(name, prompt, refs, out / f"{name}.png", out / "logs")
        ok_all &= ok
        print(f"  {'ok ' if ok else 'ERR'} {name}: {info}")
    print(f"candidates in {out}: show them to the artist; copy the approved one to style/anchors/, list it in "
          f"art.json and run: {cmd_line(args, 'style')}")
    return 0 if ok_all else 1


def cmd_style(args) -> int:
    p, _ = load(args)
    prof = art_style.extract(p.anchors, style_dir(p), k=args.k)
    print(f"profile: {style_dir(p) / 'profile.json'}  palette: {', '.join(prof['palette_hex'][:12])}"
          f"{' ...' if len(prof['palette_hex']) > 12 else ''}\nthresholds: {prof['thresholds']}"
          + ("" if len(p.anchors) > 1 else "\nnote: one anchor -> default thresholds (no self-calibration)"))
    return 0


def _approved_look(p, a, keys: dict) -> Image.Image:
    """The asset as approved, at raw resolution: keyed, and colour-matched the
    same way processing matched it (so an anchor never differs from the final)."""
    raw = p.workspace / "raw"
    img = Image.open(raw / f"{a.name}.png")
    if a.background != "key":
        return img.convert("RGBA")
    img = key_backdrop(img, key_of(p, a, keys))
    members = [m for m in p.assets if m.set == a.set and tuple(m.size) == tuple(a.size)] if a.set else [a]
    i = members.index(a)
    j = colour_ref(members, i)
    if j != i and (raw / f"{members[j].name}.png").exists():
        ref = key_backdrop(Image.open(raw / f"{members[j].name}.png"), key_of(p, members[j], keys))
        img = match_colours(img, ref)
    return img


def cmd_anchor(args) -> int:
    """Promote approved assets to style anchors (the style lock grows with
    every approval: the first approved character becomes the reference for
    every later character)."""
    p, _ = load(args)
    if not args.only:
        raise SystemExit("anchor needs --only name1,name2 (the approved assets to promote)")
    sdir = style_dir(p) / "anchors"
    sdir.mkdir(parents=True, exist_ok=True)
    keys = load_keys(p)
    added = []
    for a in pick(p, args.only, None):
        if not (p.workspace / "raw" / f"{a.name}.png").exists():
            raise SystemExit(f"{a.name}: no raw image to promote")
        dst = sdir / f"{a.name}.png"
        _approved_look(p, a, keys).save(dst)
        added.append(dst)
    if p.kind == "art":
        spec = Path(args.spec)
        data = json.loads(spec.read_text(encoding="utf-8"))
        anchors = data.setdefault("style", {}).setdefault("anchors", [])
        for dst in added:
            try:
                rel = dst.resolve().relative_to(p.root.resolve()).as_posix()
            except ValueError:
                rel = str(dst.resolve())
            if rel not in anchors:
                anchors.append(rel)
        spec.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    p2, _ = load(args)
    art_style.extract(p2.anchors, style_dir(p2), k=args.k)
    print(f"anchors now: {', '.join(x.name for x in p2.anchors)} (profile rebuilt)")
    return 0


def full_prompt(p, a, fixes: dict, block: str) -> str:
    parts = []
    if block:
        parts.append(block)
    if a.view:
        parts.append(f"Viewpoint: {a.view}.")
    parts.append(a.prompt.strip())
    g, _ = fix_for(fixes, "*")
    t, _ = fix_for(fixes, a.name)
    parts += [x for x in (g, t) if x]
    return "\n\n".join(parts)


def cmd_gen(args) -> int:
    p, fixes = load(args)
    raw = p.workspace / "raw"
    logs = raw / "logs"
    raw.mkdir(parents=True, exist_ok=True)
    prof = art_style.load_profile(style_dir(p))
    block = prompt_block(p)
    todo = [a for a in pick(p, args.only, args.set) if args.force or not (raw / f"{a.name}.png").exists()]
    prompts_f = raw / "prompts.json"
    prompts = json.loads(prompts_f.read_text(encoding="utf-8")) if prompts_f.exists() else {}
    keys = load_keys(p)
    names = {a.name for a in p.assets}
    failed: set[str] = set()

    def refs_for(a):
        anchors = [x for x in p.anchors if x.exists()]
        _, fix_ref = fix_for(fixes, a.name)
        subj = fix_ref or a.subject_ref
        subj_path = None
        if subj:
            subj_path = (raw / f"{subj}.png") if subj in names else resolve_ref(p, subj)
        sk = (p.root / a.sketch) if a.sketch else None
        return anchors, subj, subj_path, sk

    def job(a):
        if a.source:
            shutil.copyfile(p.root / a.source, raw / f"{a.name}.png")
            return a.name, True, "artist source copied"
        anchors, subj, subj_path, sk = refs_for(a)
        if subj in failed:
            return a.name, False, f"skipped: its subject reference {subj} failed"
        if subj_path is not None and not subj_path.exists():
            return a.name, False, f"subject reference {subj_path} does not exist"
        body = full_prompt(p, a, fixes, block)
        key = a.key if a.key != "auto" else art_style.suggest_key(prof, a.prompt)
        prompt = art_codex.build_prompt(a.name, body, n_anchors=len(anchors), subject=subj_path is not None,
                                        sketch=sk is not None, background=a.background, key=key)
        refs = anchors + ([subj_path] if subj_path is not None else []) + ([sk] if sk is not None else [])
        ok, info = art_codex.run(a.name, prompt, refs, raw / f"{a.name}.png", logs)
        if ok:
            prompts[a.name] = body
            keys[a.name] = key
        return a.name, ok, info

    # Panoramas (cube manifests): ONE picture per `_panoramas` entry, drawn once and cut into its
    # row-major pieces (grid [cols, rows]); the pieces are never drawn one by one.
    piece_of = {pc: pn for pn, pv in p.panoramas.items() for pc in pv.get("pieces", [])}
    wanted = {piece_of[a.name] for a in todo if a.name in piece_of}
    for pname in sorted(wanted):
        pv = p.panoramas[pname]
        ok, info = draw_panorama(p, pname, pv, block, fixes, raw, logs)
        print(f"  {'ok ' if ok else 'ERR'} panorama {pname} -> {', '.join(pv.get('pieces', []))}: {info}", flush=True)
        if ok:
            for pc in pv.get("pieces", []):
                prompts[pc] = f"(cut from panorama {pname})"
                keys[pc] = "opaque"
        else:
            failed.update(pv.get("pieces", []))
    todo = [a for a in todo if a.name not in piece_of]
    if wanted:
        prompts_f.write_text(json.dumps(prompts, indent=1, ensure_ascii=False), encoding="utf-8")
        keys_file(p).write_text(json.dumps(keys, indent=1), encoding="utf-8")

    for batch in dependency_order(todo, fixes, names):
        with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            for f in cf.as_completed([pool.submit(job, a) for a in batch]):
                name, ok, info = f.result()
                print(f"  {'ok ' if ok else 'ERR'} {name}: {info}", flush=True)
                if not ok:
                    failed.add(name)
        prompts_f.write_text(json.dumps(prompts, indent=1, ensure_ascii=False), encoding="utf-8")
        keys_file(p).write_text(json.dumps(keys, indent=1), encoding="utf-8")
    print(f"gen: {len(todo) - len(failed)}/{len(todo)} drawn" + (f"; failed: {','.join(sorted(failed))}" if failed else ""))
    if failed:
        print(f"retry: {cmd_line(args, 'gen', '--only', ','.join(sorted(failed)), '--force')}")
    return 1 if failed else 0


def draw_panorama(p, pname: str, pv: dict, block: str, fixes: dict, raw: Path, logs: Path) -> tuple[bool, str]:
    """Draw one panorama with Codex (opaque, anchors attached) and cut it into the pieces' raw images."""
    pieces = pv.get("pieces", [])
    cols, rows = (pv.get("grid") or [2, 2])[:2]
    if len(pieces) != cols * rows:
        return False, f"grid {cols}x{rows} does not match {len(pieces)} pieces"
    extra, _ = fix_for(fixes, pname)
    body = "\n\n".join(x for x in (
        block, pv.get("gen_prompt", ""),
        f"One continuous picture that will be cut into a {cols}x{rows} grid of equal screens: no focal object on "
        "the cut lines; the left and right edges join seamlessly (it repeats around the cube).", extra) if x)
    # "anchors": [asset names] in the _panoramas entry picks the style anchors to attach (scenery anchors, not a
    # character that would leak into the landscape); without the field every anchor goes, an empty list sends none
    want = pv.get("anchors")                # absent = every anchor, [] = none
    anchors = [x for x in p.anchors if x.exists() and (want is None or x.stem in set(want))]
    prompt = art_codex.build_prompt(f"_pano_{pname}", body, n_anchors=len(anchors), subject=False, sketch=False,
                                    background="opaque", key="magenta")
    src = raw / f"_pano_{pname}.png"
    ok, info = art_codex.run(f"_pano_{pname}", prompt, anchors, src, logs)
    if not ok:
        return False, info
    img = Image.open(src).convert("RGB")
    w, h = img.width // cols, img.height // rows
    for i, piece in enumerate(pieces):
        r, c = divmod(i, cols)
        img.crop((c * w, r * h, (c + 1) * w, (r + 1) * h)).save(raw / f"{piece}.png")
    return True, info


def _hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def cmd_process(args) -> int:
    p, fixes = load(args)
    raw, out = p.workspace / "raw", final_dir(p)
    out.mkdir(parents=True, exist_ok=True)
    if p.kind == "cube-manifest":
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(out / "0.png")   # packer sentinel
    keys = load_keys(p)
    selected = {a.name for a in pick(p, args.only, None)}
    groups: dict[tuple, list] = {}
    for a in p.assets:
        if a.background == "key" and a.set:
            groups.setdefault(("set", a.set, tuple(a.size)), []).append(a)
        else:
            groups.setdefault(("one", a.name), []).append(a)
    provenance_f = p.workspace / "qa" / "provenance.json"
    provenance = json.loads(provenance_f.read_text(encoding="utf-8")) if provenance_f.exists() else {}
    problems = []
    written: list[str] = []
    for members in groups.values():
        if not any(m.name in selected for m in members):
            continue          # a set is always re-fitted whole, even when --only names one member
        missing = [m.name for m in members if not (raw / f"{m.name}.png").exists()]
        partial = False
        if missing:
            present = [m for m in members if m.name not in missing]
            if not args.only or not present or len(members) == 1:
                # a full run never fits part of a set: the shared scale would no longer match
                problems.append(f"set {'+'.join(m.name for m in members)}: no raw image for {','.join(missing)}")
                continue
            # --only <family leaders> before the rest of the family is drawn: fit the members that have a raw
            # image TOGETHER (shared scale among them) so the leaders can be reviewed; the whole set is refitted
            # (one shared scale for every member) as soon as the family is complete
            print(f"  WARNING: partial set: refit when the family is complete - fitting "
                  f"{'+'.join(m.name for m in present)} without {','.join(missing)}", file=sys.stderr)
            members, partial = present, True
        first = members[0]
        if first.background == "opaque":
            outs = [fit_opaque(Image.open(raw / f"{first.name}.png"), tuple(first.size))]
        else:
            keyed = [key_backdrop(Image.open(raw / f"{m.name}.png"), key_of(p, m, keys)) for m in members]
            matched = list(keyed)
            for i in range(len(members)):         # colour lock is independent of motion
                j = colour_ref(members, i)
                if j != i:
                    matched[i] = match_colours(keyed[i], keyed[j])
            if any(m.motion for m in members):
                outs = fit_rgba_set(matched, tuple(first.size), [m.alpha == "binary" for m in members])
            else:
                outs = [fit_rgba(k, tuple(m.size), m.alpha == "binary") for m, k in zip(members, matched)]
        for m, o in zip(members, outs):
            o.save(out / f"{m.name}.png")
            provenance[m.name] = {"raw": _hash(raw / f"{m.name}.png"), "final": _hash(out / f"{m.name}.png")}
            if partial:
                provenance[m.name]["partial_set"] = True    # cleared by the next whole-set fit
        print(f"  {'+'.join(m.name for m in members)} -> {first.size[0]}x{first.size[1]}"
              + (" (partial set)" if partial else ""))
        written.extend(m.name for m in members)
    post = fixes.get("@post")
    if post and written:
        # a reviewer's processing fix that no option expresses (outline, crop, chroma clamp) lives in one workspace
        # script, re-applied on every process run instead of being silently undone by it
        script = (p.workspace / post).resolve()
        if not script.is_file():
            problems.append(f"@post: {script} not found (fixes.json)")
        else:
            rc = subprocess.run([sys.executable, str(script), str(out), *written], cwd=str(p.workspace)).returncode
            print(f"  @post {post} on {len(written)} final(s): exit {rc}")
            if rc != 0:
                problems.append(f"@post {post} failed (exit {rc}): the finals of this run are unfinished")
            for n in written:
                if (out / f"{n}.png").exists():
                    provenance[n]["final"] = _hash(out / f"{n}.png")
                    provenance[n]["post"] = post
    provenance_f.parent.mkdir(parents=True, exist_ok=True)
    provenance_f.write_text(json.dumps(provenance, indent=1), encoding="utf-8")
    for pr in problems:
        print(pr, file=sys.stderr)
    return 1 if problems else 0


def cmd_qa(args) -> int:
    p, _ = load(args)
    prof = art_style.load_profile(style_dir(p))
    if prof is None:
        print("NOTE: no style profile yet (run `style` once anchors are approved) - style scores are UNCHECKED",
              file=sys.stderr)
    scope = {a.name for a in pick(p, args.only, args.set)} if (args.only or args.set) else None
    fails, _ = art_qa.run(p, final_dir(p), prof, keys=load_keys(p), scope=scope)
    report = (p.workspace / "qa" / "report.txt").read_text(encoding="utf-8")
    print("\n".join(line for line in report.splitlines() if not line.startswith("PASS")))
    return 1 if fails else 0


def cmd_review(args) -> int:
    p, _ = load(args)
    rj = p.workspace / "qa" / "report.json"
    report = json.loads(rj.read_text(encoding="utf-8")) if rj.exists() else {}
    pj = p.workspace / "raw" / "prompts.json"
    prompts = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
    out = art_review.build(p, final_dir(p), p.workspace / "raw", report, prompts, style_dir(p))
    print(f"review page: {out}")
    return 0


def cmd_feedback(args) -> int:
    """Fold the review page's 'Copy feedback' JSON into fixes.json. Every asset
    marked Fix gets its note added once (re-importing the same feedback is a
    no-op); unrelated fields of an existing fix entry are kept."""
    p, fixes = load(args)
    src = Path(args.file) if args.file else None
    if src is None or not src.exists():
        raise SystemExit("feedback needs --file <json pasted from the review page>")
    data = json.loads(src.read_text(encoding="utf-8"))
    if data.get("project") not in (None, p.name):
        raise SystemExit(f"this feedback is for project {data.get('project')!r}, not {p.name!r}")
    fb = data.get("review", {})
    names = {a.name for a in p.assets}
    to_fix, ok, unmarked = [], [], []
    for name, v in fb.items():
        if name not in names:
            print(f"  skip unknown asset {name}", file=sys.stderr)
            continue
        status, note = v.get("status"), (v.get("note") or "").strip()
        if status == "fix":
            to_fix.append(name)
            if note:
                cur = fixes.get(name, "")
                entry = {"text": cur} if isinstance(cur, str) else dict(cur)
                notes = entry.setdefault("notes", [])
                if note not in notes:
                    notes.append(note)
                    entry["text"] = " ".join(x for x in (entry.get("text", ""), note) if x).strip()
                fixes[name] = entry
        elif status == "ok":
            ok.append(name)
        elif note:
            unmarked.append(name)
    p.workspace.mkdir(parents=True, exist_ok=True)
    (p.workspace / "fixes.json").write_text(json.dumps(fixes, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"approved: {', '.join(ok) or '-'}\nto fix: {', '.join(to_fix) or '-'}")
    if unmarked:
        print(f"notes without OK/Fix (ignored, ask the artist): {', '.join(unmarked)}")
    if to_fix:
        print(f"next: {cmd_line(args, 'all', '--only', ','.join(to_fix), '--force')}")
    return 0


def cmd_all(args) -> int:
    rc = cmd_gen(args)
    rc |= cmd_process(argparse.Namespace(**{**vars(args), "only": None}))
    rc |= cmd_qa(argparse.Namespace(**{**vars(args), "only": None, "set": None}))
    cmd_review(args)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["doctor", "init", "candidates", "style", "anchor", "gen", "process", "qa",
                                    "review", "feedback", "all"])
    ap.add_argument("spec", nargs="?", default="")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--set", default=None)
    ap.add_argument("--force", action="store_true", help="redraw even if a raw image exists")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--k", type=int, default=24, help="palette size for `style`")
    ap.add_argument("--file", default=None, help="feedback JSON for `feedback`")
    ap.add_argument("--subject", default=None, help="what the style candidates show")
    ap.add_argument("--n", type=int, default=3, help="number of style candidates")
    args = ap.parse_args(argv)
    if args.cmd != "doctor" and not args.spec:
        ap.error("spec is required")
    return {"doctor": cmd_doctor, "init": cmd_init, "candidates": cmd_candidates, "style": cmd_style,
            "anchor": cmd_anchor, "gen": cmd_gen, "process": cmd_process, "qa": cmd_qa, "review": cmd_review,
            "feedback": cmd_feedback, "all": cmd_all}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
