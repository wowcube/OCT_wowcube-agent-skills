"""``art/!pack.bat`` is the app's own declaration of the pack (:mod:`packbat`).

Three real corpus shapes drive these cases:

  * ``OCT_get_started``: ``app=app_get_started``, nine PSDs of which two are
    ``-map``, ``utils.exe "!pack.txt" "packed" "%app%_ids.h"``, and a stray
    ``art/map_18_18.psd`` the batch never mentions.
  * ``OCT_ladybug``: ``app=app``, three ``.fnt`` + three asset PSDs + EIGHT
    ``-map`` PSDs, a ``pack_palettes.py`` step that writes ``!pack_pal.txt``,
    ``utils.exe "!pack_pal.txt" "packed" "..\\src\\%app%_ids.h"``, and a
    ``ladybug-assets.psd`` that is the pre-split original of the two the
    batch does export.
  * apps with no ``!pack.bat`` at all (AI-generated), where every caller must
    fall back to its filename heuristic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from packbat import (
    find_pack_bat,
    ids_header_name,
    parse_pack_bat,
    read_pack_bat,
    resolve_ids_header,
)

LADYBUG_BAT = r"""@echo off
set exp=exported
set app=app
set psd=..\..\octavios\utils\psd.exe
set utils=..\..\octavios\utils\utils.exe

del /Q "%app%_ids.h"
del /Q ".\packed\*.png"
mkdir ".\%exp%"
xcopy "0.png" ".\%exp%" /Y

echo ===== Exporting... =====
%psd% "font_1.fnt" "%exp%" "" "-font-log"
%psd% "font_2.fnt" "%exp%" "" "-font-log"
%psd% "ladybug-assets_1.psd" "%exp%" "" "-log"
%psd% "ladybug-assets_2.psd" "%exp%" "" "-log"
%psd% "splash.psd" "%exp%" "" "-log -map"
%psd% "hud.psd" "%exp%" "" "-log -map"
%psd% "ico-idle.psd" "%exp%" "" "-log"
%psd% "ico.psd" "%exp%" "" "-log -map"

python pack_palettes.py -i exported -o !pack_pal.txt --lock !pack.txt

echo ===== Linking... =====
%utils% "!pack_pal.txt" "packed" "..\src\%app%_ids.h" "-hq"
pause
"""

GET_STARTED_BAT = r"""@echo off
set exp=exported
set app=app_get_started
set psd=..\..\octavios\utils\psd.exe
set utils=..\..\octavios\utils\utils.exe

echo ===== Exporting... =====
 %psd% "assets.psd" "%exp%" "" "-log"
 %psd% "ico.psd" "%exp%" "" "-log -map"
 %psd% "ahover.psd" "%exp%" "" "-log -map"

::python pack_palettes.py -i exported -o !pack_pal.txt

echo ===== Linking... =====
 %utils% "!pack.txt" "packed" "%app%_ids.h" "-hq-log"
"""


def _art(tmp_path: Path, body: str) -> Path:
    art = tmp_path / "art"
    art.mkdir(parents=True, exist_ok=True)
    (art / "!pack.bat").write_text(body, encoding="utf-8")
    return art


# ── the -map declaration (gap 2) ─────────────────────────────────────────────

def test_ladybug_declares_eight_maps(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert pb.maps == ["splash", "hud", "ico"]
    assert pb.assets == ["ladybug-assets_1", "ladybug-assets_2", "ico-idle"]


def test_map_flag_is_read_from_the_flags_argument_not_the_name(tmp_path: Path):
    """None of ladybug's map PSDs carries the ``map_`` prefix or a reserved
    launcher name - only the ``-map`` flag distinguishes them."""
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert "splash" in pb.maps and "hud" in pb.maps
    assert not any(n.startswith("map_") for n in pb.maps)


def test_fonts_are_declared_separately(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert pb.fonts == ["font_1.fnt", "font_2.fnt"]
    assert "font_1" not in pb.assets and "font_1" not in pb.maps


def test_undeclared_psds_are_simply_absent(tmp_path: Path):
    """get_started's art/map_18_18.psd is never mentioned - the ``map_``
    prefix heuristic would pack it as a map the legacy container lacks."""
    pb = read_pack_bat(_art(tmp_path, GET_STARTED_BAT))
    assert "map_18_18" not in pb.psd_names
    assert pb.maps == ["ico", "ahover"]


# ── the utils.exe arguments (gaps 4 and 5) ───────────────────────────────────

def test_ladybug_feeds_the_generated_palette_config(tmp_path: Path):
    """!pack.txt is only the --lock seed here; utils.exe consumes
    !pack_pal.txt."""
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert pb.pack_config == "!pack_pal.txt"


def test_get_started_feeds_pack_txt_directly(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, GET_STARTED_BAT))
    assert pb.pack_config == "!pack.txt"


def test_ids_output_expands_the_app_variable(tmp_path: Path):
    lady = read_pack_bat(_art(tmp_path / "a", LADYBUG_BAT))
    gs = read_pack_bat(_art(tmp_path / "b", GET_STARTED_BAT))
    assert lady.ids_output == r"..\src\app_ids.h"
    assert ids_header_name(lady) == "app_ids.h"
    assert ids_header_name(gs) == "app_get_started_ids.h"


def test_commented_out_lines_are_ignored(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, GET_STARTED_BAT))
    # the `::python pack_palettes.py ...` line must not make !pack_pal.txt
    # look like the config
    assert pb.pack_config == "!pack.txt"


def test_backslashes_in_quoted_args_survive(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert "\\" in pb.ids_output   # shlex would have eaten these


def test_variables_are_collected(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, LADYBUG_BAT))
    assert pb.variables["app"] == "app"
    assert pb.exported_dir == "exported"


def test_no_pack_bat_returns_none(tmp_path: Path):
    (tmp_path / "art").mkdir()
    assert find_pack_bat(tmp_path / "art") is None
    assert read_pack_bat(tmp_path / "art") is None
    assert ids_header_name(None) is None


def test_a_batch_with_no_tool_runs_declares_nothing(tmp_path: Path):
    pb = read_pack_bat(_art(tmp_path, "@echo off\npause\n"))
    assert not pb.declares_export


# ── ids header resolution (gap 4) ────────────────────────────────────────────

def _app(tmp_path: Path, *, include: str | None, bat: str | None = None) -> Path:
    app = tmp_path / "app_ladybug"
    (app / "src").mkdir(parents=True)
    if include is not None:
        (app / "src" / "app.h").write_text(
            f'#pragma once\n#include "oct_api.h"\n#include "{include}"\n',
            encoding="utf-8")
    if bat is not None:
        _art(app, bat)
    return app


def test_ids_header_follows_the_include(tmp_path: Path):
    """The ladybug shape: target app_ladybug, header app_ids.h."""
    app = _app(tmp_path, include="app_ids.h", bat=LADYBUG_BAT)
    assert resolve_ids_header(app, "app_ladybug") == app / "src" / "app_ids.h"


def test_ids_header_falls_back_to_pack_bat(tmp_path: Path):
    app = _app(tmp_path, include=None, bat=LADYBUG_BAT)
    assert resolve_ids_header(app, "app_ladybug") == app / "src" / "app_ids.h"


def test_ids_header_falls_back_to_the_target_name(tmp_path: Path):
    """The scaffold/AI shape: nothing declares anything."""
    app = _app(tmp_path, include=None)
    assert resolve_ids_header(app, "app_mygame") == \
        app / "src" / "app_mygame_ids.h"


def test_ids_header_include_wins_over_pack_bat(tmp_path: Path):
    app = _app(tmp_path, include="renamed_ids.h", bat=LADYBUG_BAT)
    assert resolve_ids_header(app, "app_ladybug").name == "renamed_ids.h"


def test_two_different_ids_includes_are_an_error(tmp_path: Path):
    app = _app(tmp_path, include="app_ids.h")
    (app / "src" / "other.h").write_text('#include "other_ids.h"\n',
                                         encoding="utf-8")
    with pytest.raises(ValueError, match="several"):
        resolve_ids_header(app, "app_ladybug")


def test_repeating_the_same_include_is_fine(tmp_path: Path):
    app = _app(tmp_path, include="app_ids.h")
    (app / "src" / "other.h").write_text('#include "app_ids.h"\n',
                                         encoding="utf-8")
    assert resolve_ids_header(app, "app_ladybug").name == "app_ids.h"


def test_parse_pack_bat_on_a_path(tmp_path: Path):
    art = _art(tmp_path, GET_STARTED_BAT)
    assert parse_pack_bat(art / "!pack.bat").maps == ["ico", "ahover"]
