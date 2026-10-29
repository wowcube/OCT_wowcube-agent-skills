"""The asset spec: what to draw, at which size, in which set.

Two input formats, one in-memory model:

1. The art-director project file `art.json` (artists use this one):

    {
      "project": "shotgun_princess",
      "style":   {"bible": "style/STYLE.md", "anchors": ["style/anchors/frame.png"]},
      "defaults": {"background": "key", "alpha": "binary"},
      "assets": [
        {"name": "hero_idle_00", "size": [40, 40], "set": "hero", "motion": true,
         "colour_lock": true, "prompt": "the princess standing, facing down ..."},
        {"name": "hero_walk_00", "size": [40, 40], "set": "hero", "motion": true,
         "colour_lock": true, "subject_ref": "hero_idle_00", "prompt": "..."},
        {"name": "floor", "size": [120, 120], "background": "opaque", "prompt": "..."},
        {"name": "logo", "size": [110, 60], "source": "drawn/logo.png"}
      ]
    }

   Asset fields: name (a-z0-9_), size [w,h] final pixels, prompt (what to
   draw), set (assets that must read as one family), motion (true: frames of
   one subject in motion -> shared scale + centroid alignment), colour_lock
   (match colours to the set's first asset), subject_ref (asset name or image
   path attached as the SUBJECT reference: keep that exact design), sketch
   (artist's drawing to follow for pose/composition), source (artist-made
   finished image: no generation, only processing + QA), background ("key" =
   transparent result via chroma key, "opaque" = full-frame picture), key
   ("magenta" | "green" | "auto"), alpha ("binary" | "soft"), fill (minimum
   share of the canvas the object must cover, e.g. 0.8 for blocking tiles),
   view (e.g. "top-down"), notes (free text for the reviewer).

2. A WowCube pipeline manifest `plans/<game>_assets.json` (schema_version 1):
   sprites[] with name/size/gen_prompt/group/anim/frame/color/flags. Adapted
   automatically: gen_prompt -> prompt, group (or anim base) -> set, anim ->
   motion, color "full" or flags.bg -> background "opaque".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9_]+$")
SAFE_RE = re.compile(r"[^a-z0-9_]+")
WIN_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
# WowCube manifests (same rules as scripts/manifest_schema.py): names start with a letter and avoid what the
# packer generates itself (slot-0 "zero", the launcher's ico/ico_idle/ahover) or the ids header already uses
# (BMP_none/BMP_last, SND_none/SND_last ...)
CUBE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CUBE_RESERVED = {"pal", "0", "icon", "bmp_none", "bmp_last", "bmp_0", "map_none", "map_last",
                 "none", "last", "zero", "ico", "ico_idle", "ahover"}
CUBE_NAME_MAX = 23      # octavios asset names: char[24] incl. NUL


@dataclass
class Asset:
    name: str
    size: tuple[int, int]
    prompt: str = ""
    set: str | None = None
    motion: bool = False
    colour_lock: bool = False
    subject_ref: str | None = None
    sketch: str | None = None
    source: str | None = None
    background: str = "key"          # key | opaque
    key: str = "auto"                # auto | magenta | green
    alpha: str = "binary"            # binary | soft
    fill: float | None = None
    view: str | None = None
    anim: str | None = None          # animation id inside a set (pose rules compare within one anim)
    frame: int | None = None         # frame index inside its anim (flipbook order)
    colour_exempt: bool = False      # intended colour change inside a colour-locked set (wounded, broken)
    style_check: bool = True         # false: deliberate departure from the style palette (sky, UI, logo)
    pose_free: bool = False          # true: pose change is the point (attack lunge) -> scale rules only warn
    fullsize: bool = False           # cube manifests: flags.fullsize = drawn 1:1 (else x2) - only the QA sheet scale
    notes: str = ""


@dataclass
class Project:
    root: Path
    name: str
    bible: Path | None
    anchors: list[Path]
    assets: list[Asset]
    kind: str                        # "art" | "cube-manifest"
    workspace: Path = field(default=None)
    panoramas: dict = field(default_factory=dict)   # {name: {size, grid: [cols, rows], pieces, gen_prompt}}
    style_text: str | None = None    # cube manifest `_style`: seeds STYLE.md's Prompt block

    def get(self, name: str) -> Asset:
        for a in self.assets:
            if a.name == name:
                return a
        raise KeyError(name)

    def sets(self) -> dict[str, list[Asset]]:
        out: dict[str, list[Asset]] = {}
        for a in self.assets:
            if a.set:
                out.setdefault(a.set, []).append(a)
        return out


def _anim_base(name: str) -> str:
    return re.sub(r"_\d+$", "", name)


def load_project(path: str | Path, workspace: str | Path | None = None) -> Project:
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if "sprites" in data:
        return _from_cube_manifest(path, data, workspace)
    root = path.parent
    style = data.get("style", {})
    d = data.get("defaults", {})
    assets = []
    for raw in data.get("assets", []):
        a = Asset(name=raw["name"], size=tuple(raw["size"]))
        for k, v in raw.items():
            if k in ("name", "size"):
                continue
            if hasattr(a, k):
                setattr(a, k, v)
        for k in ("background", "key", "alpha", "view"):
            if k not in raw and k in d:
                setattr(a, k, d[k])
        if a.motion and a.anim is None:
            a.anim = _anim_base(a.name)
        assets.append(a)
    ws = Path(workspace) if workspace else root / data.get("workspace", "art_work")
    return Project(root=root, name=data.get("project", root.name),
                   bible=(root / style["bible"]) if style.get("bible") else None,
                   anchors=[root / p for p in style.get("anchors", [])],
                   assets=assets, kind="art", workspace=ws.resolve())


def _from_cube_manifest(path: Path, data: dict, workspace) -> Project:
    """plans/<game>_assets.json -> Project. Style lives next to the workspace
    (<workspace>/style/STYLE.md, anchors in <workspace>/style/anchors/)."""
    game = data.get("game", path.stem.replace("_assets", ""))
    root = path.parent.parent if path.parent.name == "plans" else path.parent
    ws = Path(workspace).resolve() if workspace else (root / f"assets_{game}").resolve()
    assets = []
    for s in data["sprites"]:
        flags = s.get("flags", {}) or {}
        prompt = s.get("gen_prompt", "") or ""
        # full-colour and bg sprites are pictures; so is a palette sprite whose prompt never asked for a key
        # backdrop (a full-canvas sky or forest strip) - only #FF00FF / #00FF00 prompts are cut-outs
        keyed = any(k in prompt.upper() for k in ("#FF00FF", "#00FF00", "CHROMA", "KEY BACKDROP", "MAGENTA BACKGROUND",
                                                   "GREEN BACKGROUND"))
        bg = s.get("background")                    # explicit manifest field wins: "key" | "opaque"
        if bg in ("key", "opaque"):
            opaque = bg == "opaque"
        else:                                       # older manifests: infer (see above)
            opaque = s.get("color") == "full" or bool(flags.get("bg")) or not keyed
        anim = s.get("anim")
        a = Asset(name=s["name"], size=tuple(s["size"]), prompt=s.get("gen_prompt", ""),
                  set=s.get("group") or (anim if anim else None), motion=bool(anim),
                  background="opaque" if opaque else "key", anim=anim, frame=s.get("frame"),
                  fullsize=bool(flags.get("fullsize")))
        assets.append(a)
    style_dir = ws / "style"
    anchors = sorted(style_dir.glob("anchors/*.png")) if style_dir.is_dir() else []
    bible = style_dir / "STYLE.md"
    panos = data.get("_panoramas") or {}
    return Project(root=root, name=game, bible=bible if bible.exists() else None,
                   anchors=anchors, assets=assets, kind="cube-manifest", workspace=ws,
                   panoramas=panos if isinstance(panos, dict) else {},
                   style_text=(data.get("_style") or "").strip() or None)


def validate(p: Project) -> list[str]:
    errs = []
    seen = set()
    names = {a.name for a in p.assets}
    for a in p.assets:
        if not NAME_RE.match(a.name):
            errs.append(f"{a.name}: name must match [a-z0-9_]+")
        if a.name in WIN_RESERVED:
            errs.append(f"{a.name}: reserved file name on Windows")
        if p.kind == "cube-manifest" and (len(a.name) > CUBE_NAME_MAX or a.name in CUBE_RESERVED
                                          or not CUBE_NAME_RE.match(a.name)):
            errs.append(f"{a.name}: WowCube asset names start with a letter, are <= {CUBE_NAME_MAX} chars and "
                        f"not reserved ({', '.join(sorted(CUBE_RESERVED))})")
        if a.name in seen:
            errs.append(f"{a.name}: duplicate name")
        seen.add(a.name)
        if (len(a.size) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) for v in a.size)
                or min(a.size) < 1 or max(a.size) > 4096):
            errs.append(f"{a.name}: size must be two whole numbers 1..4096, got {a.size}")
        if not a.source and not str(a.prompt).strip():
            errs.append(f"{a.name}: needs a prompt (or a source image)")
        if a.background not in ("key", "opaque"):
            errs.append(f"{a.name}: background must be key|opaque")
        if a.key not in ("auto", "magenta", "green"):
            errs.append(f"{a.name}: key must be auto|magenta|green")
        if a.alpha not in ("binary", "soft"):
            errs.append(f"{a.name}: alpha must be binary|soft")
        if a.fill is not None and not (0 < float(a.fill) <= 1):
            errs.append(f"{a.name}: fill must be in (0, 1]")
        for label, path in (("source", a.source), ("sketch", a.sketch)):
            if path and not (p.root / path).exists():
                errs.append(f"{a.name}: {label} image not found: {p.root / path}")
        if (a.subject_ref and a.subject_ref not in names and not Path(a.subject_ref).is_absolute()
                and not (p.root / a.subject_ref).exists() and not (p.workspace / a.subject_ref).exists()):
            errs.append(f"{a.name}: subject_ref {a.subject_ref!r} is neither an asset nor an existing image")
    for anc in p.anchors:
        if not anc.exists():
            errs.append(f"style anchor missing: {anc}")
    return errs


def safe_name(text: str) -> str:
    """File-name-safe slug for presentation files (set GIFs)."""
    return SAFE_RE.sub("_", str(text).lower()).strip("_") or "set"


def colour_ref(members: list, i: int) -> int:
    """Index of the frame member i is colour-matched to (shared by processing
    and QA so they never disagree). Only colour-locked members take part; an
    intended change (colour_exempt: wounded, broken) is matched to the first
    exempt locked member, everything else to the first non-exempt locked one.
    Returns i itself when i is its own reference (or is not locked)."""
    m = members[i]
    if not m.colour_lock:
        return i
    for j, o in enumerate(members):
        if o.colour_lock and o.colour_exempt == m.colour_exempt:
            return j
    return i


def dependency_order(assets: list, fixes: dict, names: set[str]) -> list[list]:
    """Topological batches: an asset whose subject reference (spec subject_ref
    or a fixes.json ref) is another asset being drawn waits for it. Raises on
    a cycle. Image-path references are not dependencies."""
    todo = {a.name: a for a in assets}

    def dep(a):
        _, ref = fix_for(fixes, a.name)
        r = ref or a.subject_ref
        return r if r in names and r in todo else None

    batches, done = [], set()
    while len(done) < len(todo):
        ready = [a for n, a in todo.items() if n not in done and (dep(a) is None or dep(a) in done)]
        if not ready:
            cyc = sorted(n for n in todo if n not in done)
            raise SystemExit(f"subject_ref cycle among: {', '.join(cyc)}")
        batches.append(ready)
        done |= {a.name for a in ready}
    return batches


def load_fixes(ws: Path) -> dict:
    """<workspace>/fixes.json: reviewer corrections that are appended to the
    prompts on regeneration. {"*": "global note", "<name>": "note" |
    {"text": "...", "ref": "<path or asset>"}}. Kept in a file so a regen
    reproduces every fix (never fix things ad hoc in the chat only).

    Meta keys (mostly for cube manifests, which carry no art-direction fields):
      "@colour_lock":   [name prefixes]  -> colour_lock on those assets
      "@colour_exempt": [name substrings] -> intended colour change (wounded, broken)
      "@fill":          {"prefix": 0.8}  -> minimum canvas coverage
      "@post":          "post_process.py" -> workspace script `art.py process` runs after every run as
                        `python <script> <final dir> <names processed>` (processing fixes no option expresses)
    The older till_dawn file name prompt_overrides.json (keys @colour_match,
    @colour_match_exclude, @fill_cell) is read as a fallback."""
    f = ws / "fixes.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    legacy = ws / "prompt_overrides.json"
    if not legacy.exists():
        return {}
    d = json.loads(legacy.read_text(encoding="utf-8"))
    d["@colour_lock"] = d.pop("@colour_match", [])
    d["@colour_exempt"] = d.pop("@colour_match_exclude", [])
    d["@fill"] = {p: 0.8 for p in d.pop("@fill_cell", [])}
    return d


def apply_meta(p: Project, fixes: dict) -> None:
    """Fold the fixes.json meta keys into the assets."""
    lock = tuple(fixes.get("@colour_lock", []))
    exempt = tuple(fixes.get("@colour_exempt", []))
    fill = fixes.get("@fill", {})
    no_style = tuple(fixes.get("@style_exempt", []))
    pose = tuple(fixes.get("@pose_exempt", []))
    for a in p.assets:
        if no_style and a.name.startswith(no_style):
            a.style_check = False
        if pose and any(t in a.name for t in pose):
            a.pose_free = True
        if lock and a.name.startswith(lock):
            a.colour_lock = True
            a.motion = True
            if a.anim is None:
                a.anim = _anim_base(a.name)
        if exempt and any(t in a.name for t in exempt):
            a.colour_exempt = True
        for prefix, v in fill.items():
            if a.name.startswith(prefix):
                a.fill = float(v)


def fix_for(fixes: dict, name: str) -> tuple[str, str | None]:
    v = fixes.get(name, "")
    if isinstance(v, str):
        return v, None
    return v.get("text", ""), v.get("ref")
