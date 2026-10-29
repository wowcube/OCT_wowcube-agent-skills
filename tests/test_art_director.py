"""cube_art-director scripts: the processing / QA / spec behaviours that a
Codex review found broken and that are now fixed. No Codex calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ART = Path(__file__).resolve().parents[1] / "skills" / "cube_art-director" / "scripts"
sys.path.insert(0, str(ART))

import art  # noqa: E402
import art_qa  # noqa: E402
import art_style  # noqa: E402
from art_image import _box_down, fit_opaque, key_backdrop, key_fringe_count  # noqa: E402
from art_spec import Asset, Project, colour_ref, dependency_order, validate  # noqa: E402


def _rgba(a):
    return Image.fromarray(np.asarray(a, np.uint8), "RGBA")


def test_downscale_keeps_true_edge_colour():
    a = np.zeros((4, 4, 4), np.uint8)
    a[:, :1] = (80, 80, 80, 255)                       # a quarter-covered output pixel
    out = np.array(_box_down(_rgba(a), (2, 2), binary_alpha=False))
    assert abs(int(out[0, 0, 0]) - 80) <= 2            # was brightened to ~157 by double premultiplication


def test_despill_leaves_interior_purple_alone():
    b = np.zeros((20, 20, 3), np.uint8)
    b[:] = (255, 0, 255)
    b[5:15, 5:15] = (60, 60, 60)
    b[9:11, 9:11] = (180, 40, 180)                     # a purple detail inside the subject
    k = np.array(key_backdrop(Image.fromarray(b, "RGB"), "magenta"))
    assert tuple(k[10, 10]) == (180, 40, 180, 255)
    assert k[0, 0, 3] == 0


def test_key_fringe_only_counts_the_generation_key():
    a = np.zeros((2, 2, 4), np.uint8)
    a[0, 0] = (255, 40, 220, 255)                      # pink subject pixel, drawn on GREEN
    assert key_fringe_count(a, "green") == 0
    assert key_fringe_count(a, "magenta") == 1


def test_fit_opaque_extreme_aspect_is_not_black():
    out = np.array(fit_opaque(Image.new("RGB", (2, 2), (255, 0, 0)), (1, 100)))
    assert tuple(out[50, 0]) == (255, 0, 0, 255)


def test_colour_ref_shared_rule():
    m = [Asset("a", (4, 4), colour_lock=False), Asset("b", (4, 4), colour_lock=True),
         Asset("c", (4, 4), colour_lock=True), Asset("d", (4, 4), colour_lock=True, colour_exempt=True),
         Asset("e", (4, 4), colour_lock=True, colour_exempt=True)]
    assert colour_ref(m, 0) == 0           # not locked
    assert colour_ref(m, 2) == 1           # first locked, non-exempt (never the unlocked 'a')
    assert colour_ref(m, 4) == 3           # wounded state matched to the first wounded frame


def test_dependency_order_chains_and_cycles():
    a, b, c = Asset("a", (4, 4), prompt="p"), Asset("b", (4, 4), prompt="p", subject_ref="a"), \
        Asset("c", (4, 4), prompt="p", subject_ref="b")
    batches = dependency_order([c, b, a], {}, {"a", "b", "c"})
    assert [[x.name for x in bt] for bt in batches] == [["a"], ["b"], ["c"]]
    with pytest.raises(SystemExit):
        dependency_order([Asset("x", (4, 4), prompt="p", subject_ref="y"),
                          Asset("y", (4, 4), prompt="p", subject_ref="x")], {}, {"x", "y"})


def test_validate_rejects_bad_types(tmp_path):
    p = Project(root=tmp_path, name="t", bible=None, anchors=[], kind="art", workspace=tmp_path / "ws",
                assets=[Asset("ok", (10.5, 10), prompt="p"), Asset("b", (8, 8), prompt="p", alpha="half")])
    errs = validate(p)
    assert any("whole numbers" in e for e in errs) and any("alpha" in e for e in errs)


def test_empty_anchor_is_rejected(tmp_path):
    f = tmp_path / "empty.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(f)
    with pytest.raises(SystemExit):
        art_style.extract([f], tmp_path / "style")


def test_calibration_is_capped(tmp_path):
    a, b = tmp_path / "black.png", tmp_path / "red.png"
    Image.new("RGB", (32, 32), (5, 5, 5)).save(a)
    Image.new("RGB", (32, 32), (230, 10, 10)).save(b)
    prof = art_style.extract([a, b], tmp_path / "style")
    for key, default in art_style.DEFAULT_T.items():
        assert prof["thresholds"][key] <= art_style.CAP * default + 1e-9


def _project(tmp_path, assets):
    ws = tmp_path / "ws"
    (ws / "final").mkdir(parents=True)
    return Project(root=tmp_path, name="t", bible=None, anchors=[], kind="art", workspace=ws, assets=assets)


def test_qa_fails_opaque_rectangle_declared_as_cutout(tmp_path):
    p = _project(tmp_path, [Asset("prop", (8, 8), prompt="p", background="key")])
    Image.new("RGBA", (8, 8), (90, 90, 90, 255)).save(p.workspace / "final" / "prop.png")
    fails, _ = art_qa.run(p, p.workspace / "final", None)
    assert fails >= 1


def test_qa_writes_an_all_assets_sheet_even_without_sets(tmp_path):
    """The consistency reviewer needs a sheet of every final; sets.png exists only for sets of 2+."""
    p = _project(tmp_path, [Asset("prop", (8, 8), prompt="p", background="key"),
                            Asset("sky", (130, 20), prompt="p", background="opaque")])
    a = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    a.paste((200, 40, 40, 255), (2, 2, 6, 6))
    a.save(p.workspace / "final" / "prop.png")
    Image.new("RGBA", (130, 20), (20, 30, 90, 255)).save(p.workspace / "final" / "sky.png")
    art_qa.run(p, p.workspace / "final", None)
    sheet = p.workspace / "qa" / "all.png"
    assert sheet.is_file() and not (p.workspace / "qa" / "sets.png").exists()
    w, h = Image.open(sheet).size
    assert w >= 130 + 16 and h >= 20 + 16      # the 130 px picture drawn x1 (fullsize), the prop x2


def test_feedback_import_is_idempotent(tmp_path):
    spec = tmp_path / "art.json"
    spec.write_text(json.dumps({"project": "t", "assets": [{"name": "hero", "size": [8, 8], "prompt": "p"}]}),
                    encoding="utf-8")
    fb = tmp_path / "fb.json"
    fb.write_text(json.dumps({"project": "t", "review": {"hero": {"status": "fix", "note": "thicker outline"}}}),
                  encoding="utf-8")
    for _ in range(2):
        assert art.main(["feedback", str(spec), "--file", str(fb)]) == 0
    fixes = json.loads((tmp_path / "art_work" / "fixes.json").read_text(encoding="utf-8"))
    assert fixes["hero"]["text"].count("thicker outline") == 1


def test_panorama_drawn_once_and_cut_into_pieces(tmp_path, monkeypatch):
    m = {"game": "g", "schema_version": 1,
         "_style": "Dark pixel art from above.",
         "_panoramas": {"sky": {"size": [240, 240], "grid": [2, 2], "gen_prompt": "night sky",
                                "pieces": ["sky_r0c0", "sky_r0c1", "sky_r1c0", "sky_r1c1"]}},
         "sprites": [{"name": n, "size": [120, 120], "description": "d", "gen_prompt": "quarter",
                      "color": "full", "background": "opaque"}
                     for n in ("sky_r0c0", "sky_r0c1", "sky_r1c0", "sky_r1c1")]}
    spec = tmp_path / "plans" / "g_assets.json"
    spec.parent.mkdir()
    spec.write_text(json.dumps(m), encoding="utf-8")
    calls = []

    def fake_run(name, prompt, refs, out_png, log_dir, **kw):
        calls.append((name, prompt))
        img = Image.new("RGB", (64, 64))
        for x, col in ((0, (255, 0, 0)), (32, (0, 255, 0))):
            img.paste(col, (x, 0, x + 32, 32))
        img.paste((0, 0, 255), (0, 32, 32, 64))
        img.paste((255, 255, 0), (32, 32, 64, 64))
        out_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_png)
        return True, "fake"

    monkeypatch.setattr(art.art_codex, "run", fake_run)
    assert art.main(["gen", str(spec), "--workspace", str(tmp_path / "ws")]) == 0
    assert [c[0] for c in calls] == ["_pano_sky"]                      # one Codex call, not four
    assert "Dark pixel art from above." in calls[0][1]                  # _style seeded the prompt block
    raw = tmp_path / "ws" / "raw"
    assert Image.open(raw / "sky_r0c1.png").getpixel((5, 5)) == (0, 255, 0)
    assert Image.open(raw / "sky_r1c0.png").getpixel((5, 5)) == (0, 0, 255)
    assert json.loads((raw / "prompts.json").read_text(encoding="utf-8"))["sky_r0c0"].startswith("(cut from")


@pytest.mark.parametrize("anchors_field, expected", [(None, ["hero", "ground"]), (["ground"], ["ground"]), ([], [])],
                         ids=["absent-all", "listed", "empty-none"])
def test_panorama_attaches_the_listed_anchors(tmp_path, monkeypatch, anchors_field, expected):
    pano = {"size": [240, 240], "grid": [2, 2], "gen_prompt": "night sky",
            "pieces": ["sky_r0c0", "sky_r0c1", "sky_r1c0", "sky_r1c1"]}
    if anchors_field is not None:
        pano["anchors"] = anchors_field
    m = {"game": "g", "schema_version": 1, "_style": "Dark pixel art from above.", "_panoramas": {"sky": pano},
         "sprites": [{"name": n, "size": [120, 120], "description": "d", "gen_prompt": "quarter",
                      "color": "full", "background": "opaque"} for n in pano["pieces"]]}
    spec = tmp_path / "plans" / "g_assets.json"
    spec.parent.mkdir()
    spec.write_text(json.dumps(m), encoding="utf-8")
    anchors = tmp_path / "ws" / "style" / "anchors"
    anchors.mkdir(parents=True)
    for n in ("hero", "ground"):
        Image.new("RGB", (8, 8), (9, 9, 9)).save(anchors / f"{n}.png")
    seen = []

    def fake_run(name, prompt, refs, out_png, log_dir, **kw):
        seen.append(sorted(Path(r).stem for r in refs))
        out_png.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (1, 2, 3)).save(out_png)
        return True, "fake"

    monkeypatch.setattr(art.art_codex, "run", fake_run)
    assert art.main(["gen", str(spec), "--workspace", str(tmp_path / "ws")]) == 0
    assert seen == [sorted(expected)]


def test_all_sheet_uses_the_fullsize_flag_not_the_size(tmp_path):
    from art_spec import load_project
    m = {"game": "g", "schema_version": 1, "sprites": [
        {"name": "badge", "size": [64, 64], "description": "d", "gen_prompt": "a badge", "background": "key",
         "flags": {"fullsize": True}},
        {"name": "coin", "size": [64, 64], "description": "d", "gen_prompt": "a coin", "background": "key"}]}
    spec = tmp_path / "plans" / "g_assets.json"
    spec.parent.mkdir()
    spec.write_text(json.dumps(m), encoding="utf-8")
    p = load_project(spec, tmp_path / "ws")
    assert {a.name: a.fullsize for a in p.assets} == {"badge": True, "coin": False}
