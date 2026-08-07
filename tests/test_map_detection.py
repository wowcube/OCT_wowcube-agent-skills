"""Which PSDs are placement maps (``_resolve_map_filter``).

Measured on the reference corpus: ``art/!pack.bat`` runs ``psd.exe -map`` on
``ico.psd`` and ``ahover.psd`` — neither carries the ``map_`` prefix. Exported
in Assets mode instead, they write PNGs whose layer names collide with real
sprites (``ahover.psd``'s 74x67 placement thumbnail is called ``ahover_00``,
while the sprite the app ships is ``ahover_src.psd``'s 144x145 layer), so the
map overwrites the sprite and nothing structural notices.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pack import _resolve_map_filter


def _args(art_dir: Path, map_filter=None) -> argparse.Namespace:
    return argparse.Namespace(art_dir=str(art_dir), map_filter=map_filter)


def _psds(art: Path, *names: str) -> None:
    art.mkdir(parents=True, exist_ok=True)
    for n in names:
        (art / f"{n}.psd").write_bytes(b"8BPS")     # only the name matters here


def test_map_prefix_is_detected(tmp_path: Path):
    _psds(tmp_path, "assets", "map_18_18")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    assert a.map_filter == "map_18_18"


def test_reserved_launcher_names_are_maps(tmp_path: Path):
    """The corpus shape: ico.psd + ahover.psd with no map_ prefix."""
    _psds(tmp_path, "assets", "ico", "ico_sprite", "ahover", "ahover_src")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    assert sorted(a.map_filter.split(",")) == ["ahover", "ico"]


def test_prefixed_and_reserved_maps_combine(tmp_path: Path):
    _psds(tmp_path, "assets", "map_18_18", "ico", "ahover")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    assert sorted(a.map_filter.split(",")) == ["ahover", "ico", "map_18_18"]


def test_source_psds_of_the_reserved_names_stay_assets(tmp_path: Path):
    """``ico_sprite``/``ahover_src`` hold the real artwork - never maps."""
    _psds(tmp_path, "assets", "ico", "ico_sprite", "ahover", "ahover_src")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    names = a.map_filter.split(",")
    assert "ico_sprite" not in names and "ahover_src" not in names


def test_no_duplicate_when_a_reserved_name_also_has_the_prefix(tmp_path: Path):
    _psds(tmp_path, "assets", "map_ico", "ico")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    assert sorted(a.map_filter.split(",")) == ["ico", "map_ico"]


def test_explicit_filter_is_never_overridden(tmp_path: Path):
    _psds(tmp_path, "assets", "ico", "ahover", "map_18_18")
    a = _args(tmp_path, map_filter="map_18_18")
    _resolve_map_filter(a)
    assert a.map_filter == "map_18_18"


def test_no_maps_leaves_the_filter_unset(tmp_path: Path):
    _psds(tmp_path, "assets", "eyes", "text")
    a = _args(tmp_path)
    _resolve_map_filter(a)
    assert a.map_filter is None


# ── !pack.bat wins over every filename heuristic ─────────────────────────────
#
# Measured on OCT_ladybug: EIGHT PSDs go through `psd.exe -map` and not one of
# them carries the `map_` prefix or a reserved launcher name, so the rules
# above find exactly one of the eight. The other seven then export in Assets
# mode, writing PNGs named after sprites the asset PSDs already exported and
# inflating the sprite count by their `$name` anchors.

def _bat(art: Path, *lines: str) -> None:
    art.mkdir(parents=True, exist_ok=True)
    body = ["@echo off", "set exp=exported",
            r"set psd=..\..\octavios\utils\psd.exe"]
    body += list(lines)
    (art / "!pack.bat").write_text("\n".join(body) + "\n", encoding="utf-8")


def _with_bat(art_dir: Path, map_filter=None):
    from pack import _resolve_pack_bat
    a = argparse.Namespace(art_dir=str(art_dir), map_filter=map_filter,
                           pack_bat=None, no_pack_bat=False)
    return a, _resolve_pack_bat(a)


def test_pack_bat_declares_maps_the_heuristics_cannot_see(tmp_path: Path):
    _psds(tmp_path, "ladybug-assets_1", "splash", "hud", "win", "ico")
    _bat(tmp_path,
         r'%psd% "ladybug-assets_1.psd" "%exp%" "" "-log"',
         r'%psd% "splash.psd" "%exp%" "" "-log -map"',
         r'%psd% "hud.psd" "%exp%" "" "-log -map"',
         r'%psd% "win.psd" "%exp%" "" "-log -map"',
         r'%psd% "ico.psd" "%exp%" "" "-log -map"')
    a, pb = _with_bat(tmp_path)
    _resolve_map_filter(a, pb)
    assert a.map_filter.split(",") == ["splash", "hud", "win", "ico"]


def test_pack_bat_keeps_an_undeclared_map_prefixed_psd_out(tmp_path: Path):
    """get_started ships art/map_18_18.psd that !pack.bat never runs."""
    _psds(tmp_path, "assets", "ico", "ahover", "map_18_18")
    _bat(tmp_path,
         r'%psd% "assets.psd" "%exp%" "" "-log"',
         r'%psd% "ico.psd" "%exp%" "" "-log -map"',
         r'%psd% "ahover.psd" "%exp%" "" "-log -map"')
    a, pb = _with_bat(tmp_path)
    _resolve_map_filter(a, pb)
    assert a.map_filter.split(",") == ["ico", "ahover"]
    assert "map_18_18" not in pb.psd_names


def test_pack_bat_with_no_map_run_means_no_maps(tmp_path: Path):
    """An explicit declaration of "none" must not fall through to the
    heuristic, which would call ico.psd a map anyway."""
    _psds(tmp_path, "assets", "ico")
    _bat(tmp_path, r'%psd% "assets.psd" "%exp%" "" "-log"',
         r'%psd% "ico.psd" "%exp%" "" "-log"')
    a, pb = _with_bat(tmp_path)
    _resolve_map_filter(a, pb)
    assert a.map_filter == ""


def test_explicit_filter_still_beats_pack_bat(tmp_path: Path):
    _psds(tmp_path, "assets", "ico", "hud")
    _bat(tmp_path, r'%psd% "hud.psd" "%exp%" "" "-log -map"')
    a, pb = _with_bat(tmp_path, map_filter="ico")
    _resolve_map_filter(a, pb)
    assert a.map_filter == "ico"


def test_no_pack_bat_flag_restores_the_heuristic(tmp_path: Path):
    _psds(tmp_path, "assets", "ico", "hud")
    _bat(tmp_path, r'%psd% "hud.psd" "%exp%" "" "-log -map"')
    from pack import _resolve_pack_bat
    a = argparse.Namespace(art_dir=str(tmp_path), map_filter=None,
                           pack_bat=None, no_pack_bat=True)
    pb = _resolve_pack_bat(a)
    assert pb is None
    _resolve_map_filter(a, pb)
    assert a.map_filter == "ico"
