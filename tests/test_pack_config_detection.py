"""Which palette config drives the pack, and where the APP_* defines live.

Two measured shapes:

  * ``OCT_get_started``: ``!pack.bat`` passes ``!pack.txt`` straight to
    ``utils.exe`` - the filename heuristic happens to be right.
  * ``OCT_ladybug``: ``!pack.bat`` first runs the app's own
    ``pack_palettes.py -o !pack_pal.txt --lock !pack.txt`` and passes
    ``!pack_pal.txt``. Here ``!pack.txt`` is only the lock/seed: 16 coarse
    buckets against the 32 the shipped container was built from. Picking by
    filename silently repacks every sprite against the wrong palette.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pack import _declared_pack_config, _resolve_pack_bat, _resolve_pack_config

PACK_TXT = "exported\n\n256\n<FULLSIZE>\n*\n"


def _art(tmp_path: Path, bat: str, *configs: str) -> Path:
    art = tmp_path / "art"
    art.mkdir(parents=True, exist_ok=True)
    (art / "!pack.bat").write_text(bat, encoding="utf-8")
    for c in configs:
        (art / c).write_text(PACK_TXT, encoding="utf-8")
    return art


def _args(art: Path, **over):
    a = argparse.Namespace(art_dir=str(art), pack_bat=None, no_pack_bat=False,
                           pack_config=None, no_pack_config=False,
                           manifest=None)
    for k, v in over.items():
        setattr(a, k, v)
    return a


LADY = ('@echo off\nset app=app\nset utils=..\\..\\octavios\\utils\\utils.exe\n'
        'python pack_palettes.py -i exported -o !pack_pal.txt --lock !pack.txt\n'
        '%utils% "!pack_pal.txt" "packed" "..\\src\\%app%_ids.h" "-hq"\n')
GS = ('@echo off\nset app=app_get_started\nset utils=..\\..\\octavios\\utils\\utils.exe\n'
      '%utils% "!pack.txt" "packed" "%app%_ids.h" "-hq-log"\n')


def test_generated_config_wins_over_the_filename(tmp_path: Path):
    art = _art(tmp_path, LADY, "!pack.txt", "!pack_pal.txt")
    a = _args(art)
    assert _declared_pack_config(a, _resolve_pack_bat(a)).name == "!pack_pal.txt"


def test_pack_txt_is_used_when_that_is_what_utils_gets(tmp_path: Path):
    art = _art(tmp_path, GS, "!pack.txt")
    a = _args(art)
    assert _declared_pack_config(a, _resolve_pack_bat(a)).name == "!pack.txt"


def test_uncommitted_generated_config_falls_back(tmp_path: Path, capsys):
    """We never run the app's pack_palettes.py; if its output was not
    committed, say so and use the seed rather than guess."""
    art = _art(tmp_path, LADY, "!pack.txt")          # no !pack_pal.txt
    a = _args(art)
    assert _declared_pack_config(a, _resolve_pack_bat(a)) is None
    assert "not committed" in capsys.readouterr().out
    assert _resolve_pack_config(a, _resolve_pack_bat(a)).path.name == "!pack.txt"


def test_resolved_config_is_the_declared_one(tmp_path: Path):
    art = _art(tmp_path, LADY, "!pack.txt", "!pack_pal.txt")
    a = _args(art)
    assert _resolve_pack_config(a, _resolve_pack_bat(a)).path.name \
        == "!pack_pal.txt"


def test_explicit_pack_config_still_wins(tmp_path: Path):
    art = _art(tmp_path, LADY, "!pack.txt", "!pack_pal.txt")
    a = _args(art, pack_config=str(art / "!pack.txt"))
    assert _resolve_pack_config(a, _resolve_pack_bat(a)).path.name == "!pack.txt"


def test_no_pack_config_still_opts_out(tmp_path: Path):
    art = _art(tmp_path, LADY, "!pack.txt", "!pack_pal.txt")
    a = _args(art, no_pack_config=True)
    assert _resolve_pack_config(a, _resolve_pack_bat(a)) is None


def test_manifest_still_beats_the_declared_config(tmp_path: Path, capsys):
    art = _art(tmp_path, LADY, "!pack.txt", "!pack_pal.txt")
    a = _args(art, manifest="plans/x_assets.json")
    assert _resolve_pack_config(a, _resolve_pack_bat(a)) is None
    out = capsys.readouterr().out
    assert "!pack_pal.txt ignored - the manifest" in out


def test_without_a_pack_bat_the_filename_heuristic_applies(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "!pack.txt").write_text(PACK_TXT, encoding="utf-8")
    a = _args(art)
    assert _resolve_pack_config(a, None).path.name == "!pack.txt"


# ── APP_* defines can live in an included header ─────────────────────────────

def test_app_defines_follow_a_local_include(tmp_path: Path):
    """OCT_ladybug keeps APP_GUID1/APP_VERSION/APP_TITLE/APP_CATEGORIES in
    src/config.h; reading app.h alone made every .oct build fail with
    "no APP_GUID1"."""
    from pack_beta import read_app_defines
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.h").write_text(
        '#pragma once\n#include "oct_api.h"\n#include "config.h"\n',
        encoding="utf-8")
    (src / "config.h").write_text(
        '#define APP_VER(ma, mi, pa) (((ma) << 16) | ((mi) << 8) | (pa))\n'
        '#define APP_VERSION APP_VER(0, 1, 5)\n'
        '#define APP_GUID1   0x339B89AD25393998ULL\n'
        '#define APP_TITLE   "Ladybug"\n'
        '#define APP_CATEGORIES (APP_CATEGORY_SYSTEM)\n',
        encoding="utf-8")
    d = read_app_defines(src / "app.h")
    assert d["title"] == "Ladybug"
    assert d["guid1"] == 0x339B89AD25393998
    assert d["app_version"] == 0x000105
    assert d["categories"] == 1 << 3


def test_app_defines_in_app_h_still_win_the_lookup(tmp_path: Path):
    from pack_beta import read_app_defines
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.h").write_text('#define APP_GUID1 0x11ULL\n', encoding="utf-8")
    assert read_app_defines(src / "app.h")["guid1"] == 0x11


def test_missing_includes_are_not_fatal(tmp_path: Path):
    from pack_beta import read_app_defines
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.h").write_text(
        '#include "nope.h"\n#include <oct_api.h>\n#define APP_GUID1 0x22ULL\n',
        encoding="utf-8")
    assert read_app_defines(src / "app.h")["guid1"] == 0x22


def test_include_cycles_terminate(tmp_path: Path):
    from pack_beta import read_app_defines
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.h").write_text('#include "b.h"\n', encoding="utf-8")
    (src / "b.h").write_text('#include "app.h"\n#define APP_GUID1 0x33ULL\n',
                             encoding="utf-8")
    assert read_app_defines(src / "app.h")["guid1"] == 0x33
