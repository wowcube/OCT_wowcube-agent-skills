"""`build_pipeline.py validate` - the provider-free manifest gate - and the
manifest name rules it shares with `generate` (manifest_schema.validate).

validate must never generate, never resolve an image provider, never start a
subprocess: every test here runs with subprocess.run and the provider chain
booby-trapped.
"""
from __future__ import annotations

import copy
import json
import subprocess

import pytest

import image_providers
import manifest_schema
from build_pipeline import _cli
from manifest_schema import check_manifest_file, load_manifest, sequence_aliases, validate

STYLE = ("Calm magical night-garden game art seen from straight above. Clean digital illustration with simple bold "
         "shapes, two or three flat tone steps per material, a thin dark navy outline around every object. Deep "
         "indigo and navy ground, dark slate-teal stone; warm gold only on the basket; cyan-white light only on "
         "orbs and stars. Glows are drawn as crisp concentric bands of lighter colour, never as soft gradients. "
         "Big readable shapes, very little fine detail.")

GOOD = {
    "game": "orb", "schema_version": 1, "_style": STYLE,
    "sprites": [
        {"name": "launcher_icon", "size": [160, 160], "color": "palette", "flags": {"fullsize": True},
         "background": "key", "group": "icon", "description": "badge",
         "gen_prompt": "An app launcher badge: a flat-top hexagon with a thick dark outline, a golden basket inside."},
        {"name": "basket", "size": [60, 60], "background": "key", "group": "basket", "description": "basket",
         "gen_prompt": "A round woven basket seen from directly above. Single subject, fills most of the canvas."},
        {"name": "hero_walk_00", "size": [40, 40], "background": "key", "group": "hero", "anim": "hero_walk",
         "frame": 0, "description": "f0", "gen_prompt": "A small knight, frame 0 of a 2-frame walk loop."},
        {"name": "hero_walk_01", "size": [40, 40], "background": "key", "group": "hero", "anim": "hero_walk",
         "frame": 1, "description": "f1", "gen_prompt": "The same knight, frame 1: the other foot forward."},
        {"name": "sky_r0c0", "size": [120, 120], "background": "opaque", "color": "full",
         "flags": {"alpha": False, "bg": True}, "description": "piece", "gen_prompt": "Upper-left quarter."},
        {"name": "sky_r0c1", "size": [120, 120], "background": "opaque", "color": "full",
         "flags": {"alpha": False, "bg": True}, "description": "piece", "gen_prompt": "Upper-right quarter."},
    ],
    "_panoramas": {"sky": {"size": [240, 120], "grid": [2, 1], "pieces": ["sky_r0c0", "sky_r0c1"],
                           "gen_prompt": "A night sky over dark hills seen from the front."}},
    "sounds": [{"name": "catch", "description": "ding", "duration_ms": 400, "event_type": "pickup"}],
}


@pytest.fixture(autouse=True)
def _no_provider_no_subprocess(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("validate must not start a subprocess or resolve an image provider")
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(image_providers, "resolve_provider", _boom)


def _write(tmp_path, data, name="orb_assets.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _with(**changes):
    d = copy.deepcopy(GOOD)
    for k, v in changes.items():
        d[k] = v
    return d


def _sprite(d, name):
    return next(s for s in d["sprites"] if s["name"] == name)


# ── the CLI ───────────────────────────────────────────────────────────────────

def test_valid_manifest_exit_0(tmp_path, capsys):
    assert _cli(["validate", "--manifest", str(_write(tmp_path, GOOD))]) == 0
    out = capsys.readouterr().out
    assert "OK: manifest valid" in out and "WARNING" not in out


def test_invalid_manifest_exit_2_and_lists_every_error(tmp_path, capsys):
    d = copy.deepcopy(GOOD)
    _sprite(d, "basket")["name"] = "1basket"
    del _sprite(d, "hero_walk_00")["background"]
    assert _cli(["validate", "--manifest", str(_write(tmp_path, d))]) == 2
    out = capsys.readouterr().out
    assert "INVALID" in out and "1basket" in out and "`background` is missing" in out


def test_missing_and_broken_files_exit_2(tmp_path, capsys):
    assert _cli(["validate", "--manifest", str(tmp_path / "nope.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert _cli(["validate", "--manifest", str(bad)]) == 2
    assert "not readable JSON" in capsys.readouterr().out


def test_structural_problems_are_reported_not_raised(tmp_path):
    d = copy.deepcopy(GOOD)
    del d["sprites"][1]["description"]
    d["sprites"][2]["size"] = [40]
    d["sounds"][0] = "catch"
    errors, _w, m = check_manifest_file(_write(tmp_path, d))
    assert m is None
    assert any("missing required field `description`" in e for e in errors)
    assert any("`size` must be" in e for e in errors)
    assert any("sounds[0]: must be an object" in e for e in errors)


# ── pipeline rules ────────────────────────────────────────────────────────────

def test_launcher_icon_is_required_and_square(tmp_path):
    d = copy.deepcopy(GOOD)
    d["sprites"] = [s for s in d["sprites"] if s["name"] != "launcher_icon"]
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("'launcher_icon' is missing" in e for e in errors)
    d = copy.deepcopy(GOOD)
    _sprite(d, "launcher_icon")["size"] = [160, 120]
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("must be square" in e for e in errors)


def test_launcher_icon_tier_warnings(tmp_path):
    d = copy.deepcopy(GOOD)
    _sprite(d, "launcher_icon").update({"background": "opaque", "color": "full", "flags": {"alpha": False,
                                                                                           "fullsize": True}})
    errors, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert errors == []
    assert any("should be \"key\"" in w for w in warnings) and any("no transparency" in w for w in warnings)


def test_gen_prompt_is_required(tmp_path):
    d = copy.deepcopy(GOOD)
    del _sprite(d, "basket")["gen_prompt"]
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("`gen_prompt` is missing" in e for e in errors)


@pytest.mark.parametrize("prompt,needle", [
    ("A coin on a transparent background.", "transparent background"),
    ("A coin, transparent bg.", "transparent background"),
    ("A coin. Background must be transparent.", "transparent background"),
    ("A coin, exactly 60x60 pixels.", "pixel size"),
    ("A coin, 60x60.", "pixel size"),
    ("A coin, 32 x 32 px.", "pixel size"),
    ("A coin on a flat #FF00FF backdrop.", "magenta key"),
    ("A coin on a magenta background.", "magenta key"),
])
def test_codex_prompt_errors(tmp_path, prompt, needle):
    d = copy.deepcopy(GOOD)
    _sprite(d, "basket")["gen_prompt"] = prompt
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any(needle in e for e in errors), errors


@pytest.mark.parametrize("prompt,needle", [
    ("A glass bottle, slightly transparent.", "transparent"),
    ("A coin with a 1 px outline.", "pixels"),
    ("A coin on a white background.", "backdrop colour"),
])
def test_codex_prompt_warnings(tmp_path, prompt, needle):
    d = copy.deepcopy(GOOD)
    _sprite(d, "basket")["gen_prompt"] = prompt
    errors, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert errors == [] and any(needle in w for w in warnings), (errors, warnings)


def test_green_key_may_be_forced_and_cell_grids_are_not_sizes(tmp_path):
    d = copy.deepcopy(GOOD)
    _sprite(d, "basket")["gen_prompt"] = "A pink flamingo on a flat #00FF00 green background."
    _sprite(d, "sky_r0c0")["gen_prompt"] = "Wooden floor planks; a darker joint line splits it into 2x2 equal cells."
    errors, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert errors == [] and warnings == []


def test_backdrop_rules_only_apply_to_key_sprites(tmp_path):
    d = copy.deepcopy(GOOD)
    _sprite(d, "sky_r0c0")["gen_prompt"] = "A black background of night sky with stars."
    errors, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert errors == [] and warnings == []


def test_style_paragraph_must_not_be_pasted_into_prompts(tmp_path):
    d = copy.deepcopy(GOOD)
    _sprite(d, "basket")["gen_prompt"] = "A basket. " + STYLE[:200]
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("repeats the _style paragraph" in e for e in errors)


def test_style_warnings(tmp_path):
    _e, warnings, _m = check_manifest_file(_write(tmp_path, _with(_style="Pixel art.")))
    assert any("_style: 2 words" in w for w in warnings)
    d = copy.deepcopy(GOOD)
    del d["_style"]
    _e, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert any("_style: missing" in w for w in warnings)


def test_panorama_pieces_and_grid(tmp_path):
    d = copy.deepcopy(GOOD)
    d["_panoramas"]["sky"]["pieces"].append("sky_r9c9")
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("'sky_r9c9' is not a sprite" in e for e in errors)
    assert any("grid [cols, rows] = [2, 1] needs 2 pieces, found 3" in e for e in errors)


def test_panorama_grid_is_cols_rows(tmp_path):
    """ART.md and art.py's draw_panorama read grid as [cols, rows] and cut row-major; the piece names
    (<pano>_r<row>c<col>) prove which order the manifest meant."""
    d = copy.deepcopy(GOOD)
    d["_panoramas"]["sky"]["grid"] = [1, 2]                    # [rows, cols] by mistake: 1 col x 2 rows
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("grid is [cols, rows] = [1, 2], but the piece names" in e and "[2, 1]" in e for e in errors)
    d = copy.deepcopy(GOOD)
    d["_panoramas"]["sky"]["pieces"] = ["sky_r0c1", "sky_r0c0"]   # not row-major
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("row-major" in e for e in errors)
    d = copy.deepcopy(GOOD)
    d["_panoramas"]["sky"]["grid"] = [2, 0]
    errors, _w, _m = check_manifest_file(_write(tmp_path, d))
    assert any("`grid` must be [cols, rows]" in e for e in errors)


def test_the_real_e2e_shape_has_no_findings(tmp_path):
    """The orb_catch manifest the e2e run wrote from the current prompter rules (abridged): no false positives."""
    d = copy.deepcopy(GOOD)
    _sprite(d, "launcher_icon")["gen_prompt"] = (
        "An app launcher badge: a flat-top hexagon (horizontal top and bottom edges, points at the left and right) "
        "with a thick dark navy outline, filled edge to edge with a dark indigo night background. Reads at half "
        "size. No text.")
    _sprite(d, "basket")["gen_prompt"] = (
        "A thin circle of cyan light seen from above: one crisp bright cyan ring line about a twentieth of the "
        "canvas thick, completely empty inside. No characters, no objects, only the ring.")
    errors, warnings, _m = check_manifest_file(_write(tmp_path, d))
    assert errors == [] and warnings == []


# ── name rules (manifest_schema.validate: generate and validate share them) ──

def _names_manifest(tmp_path, sprite_names=(), sound_names=()):
    data = {"game": "demo", "schema_version": 1,
            "sprites": [{"name": n, "size": [8, 8], "description": "d"} for n in sprite_names],
            "sounds": [{"name": n, "description": "d"} for n in sound_names]}
    return load_manifest(_write(tmp_path, data, "names.json"))


@pytest.mark.parametrize("name", ["1up", "0coin", "_hidden", "9"])
def test_names_must_start_with_a_letter(tmp_path, name):
    errors = validate(_names_manifest(tmp_path, [name], [name]))
    assert sum("starts with a letter" in e for e in errors) == 2


@pytest.mark.parametrize("name", ["none", "last", "ico", "ico_idle", "ahover", "zero"])
def test_generated_and_sentinel_names_are_reserved(tmp_path, name):
    errors = validate(_names_manifest(tmp_path, [name], [name]))
    assert sum("reserved name" in e for e in errors) == 2


def test_bmfont_glyph_names_are_reserved(tmp_path):
    errors = validate(_names_manifest(tmp_path, ["font_1_00065"]))
    assert any("BMFont glyph" in e for e in errors)
    assert validate(_names_manifest(tmp_path, ["font_title"])) == []


@pytest.mark.parametrize("clash", ["coin", "coin_end"])
def test_sprite_colliding_with_an_animation_alias(tmp_path, clash):
    errors = validate(_names_manifest(tmp_path, ["coin_00", "coin_01", clash]))
    assert any(f"BMP_{clash}" in e for e in errors)


def test_alias_rule_matches_the_packer(tmp_path):
    """sequence_aliases must flag exactly what pack_beta.generate_beta_ids_h refuses."""
    pack_beta = pytest.importorskip("pack_beta")
    cases = [["coin_00", "coin_01", "coin"], ["coin_00", "coin_01", "coin_end"], ["boom_05", "boom"],
             ["lvl_01", "lvl"], ["a_00", "b_end"], ["x_01_02", "x_01"]]
    for names in cases:
        records = [(pack_beta.KIND_SPRITE, "zero")] + [(pack_beta.KIND_SPRITE, n) for n in names]
        try:
            pack_beta.generate_beta_ids_h(records)
            packer_refuses = False
        except ValueError:
            packer_refuses = True
        assert bool(set(names) & set(sequence_aliases(names))) == packer_refuses, names


def test_valid_names_still_pass(tmp_path):
    assert validate(_names_manifest(tmp_path, ["hero_walk_00", "hero_walk_01", "s1_up", "font_bg"],
                                    ["catch_2", "music_loop"])) == []


def test_reserved_list_covers_what_pack_beta_generates():
    pack_beta = pytest.importorskip("pack_beta")
    assert set(pack_beta.RESERVED_LAUNCHER_MAPS) <= manifest_schema.RESERVED_NAMES
    assert {"zero", "ico_idle", "none", "last"} <= manifest_schema.RESERVED_NAMES
