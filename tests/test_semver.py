"""octavios dev versions apps with OCT_APP_SEMVER (engine/oct_app_version.h):
scheme byte 1 on top of major.minor.patch, and the official app layout keeps
APP_VERSION_MAJOR/MINOR/PATCH in src/app_metadata.h. The packer must read it
and repack_app must bump the patch field, not the opaque integer."""
from __future__ import annotations

from pack_beta import read_app_defines
from repack_app import bump_patch

METADATA = (
    '#pragma once\n#include "oct_app_version.h"\n'
    "#define APP_VERSION_MAJOR 0 // x-release-please-major\n"
    "#define APP_VERSION_MINOR 1 // x-release-please-minor\n"
    "#define APP_VERSION_PATCH 14 // x-release-please-patch\n"
    "#define APP_VERSION OCT_APP_SEMVER(APP_VERSION_MAJOR, APP_VERSION_MINOR, APP_VERSION_PATCH)\n"
    "#define APP_GUID1 0x0123456789ABCDEFULL\n"
    '#define APP_TITLE "Game"\n'
    "#define APP_CATEGORIES (APP_CATEGORY_GAME)\n"
    "#define APP_COLORS 0x00000000\n"
)


def _app(tmp_path, metadata=METADATA):
    (tmp_path / "app_metadata.h").write_text(metadata, encoding="utf-8")
    app_h = tmp_path / "app.h"
    app_h.write_text('#pragma once\n#include "app_metadata.h"\n#include "app_game.h"\n', encoding="utf-8")
    return app_h


def test_read_app_defines_resolves_semver_through_metadata(tmp_path):
    d = read_app_defines(_app(tmp_path))
    assert d["app_version"] == (1 << 24) | (0 << 16) | (1 << 8) | 14
    assert d["title"] == "Game"
    assert d["guid1"] == 0x0123456789ABCDEF


def test_bump_patch_bumps_metadata_patch_field(tmp_path):
    app_h = _app(tmp_path)
    assert bump_patch(app_h) == (1 << 24) | (1 << 8) | 15
    text = (tmp_path / "app_metadata.h").read_text(encoding="utf-8")
    assert "#define APP_VERSION_PATCH 15 // x-release-please-patch" in text
    assert read_app_defines(app_h)["app_version"] == (1 << 24) | (1 << 8) | 15


def test_bump_patch_literal_semver(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text("#define APP_VERSION OCT_APP_SEMVER(0, 1, 1)\n", encoding="utf-8")
    assert bump_patch(app_h) == (1 << 24) | (1 << 8) | 2
    assert "OCT_APP_SEMVER(0, 1, 2)" in app_h.read_text(encoding="utf-8")


def test_bump_patch_legacy_integer_still_works(tmp_path):
    app_h = tmp_path / "app.h"
    app_h.write_text("#define APP_VERSION 100 //v1.00\n", encoding="utf-8")
    assert bump_patch(app_h) == 101
