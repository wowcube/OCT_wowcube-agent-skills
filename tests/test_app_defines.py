"""``read_app_defines`` — the pack-header defines an app.h really carries.

The old parser handled a bare integer and an OR of ``APP_CATEGORY_*`` macros,
which covers scaffolded apps but not the two real ones in the corpus: both
``OCT_get_started`` and ``app_seabattle`` write

    #define APP_VER(ma, mi, pa)  (((ma) << 16) | ((mi) << 8) | (pa))
    #define APP_VERSION          APP_VER(0, 1, 3)

and the .oct assembly died on it with "unknown token 'APP_VER 0, 1, 3'".
Function-like macros defined in the same header are now expanded first, and
the result is evaluated through an AST whitelist of C integer operators.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pack_beta import read_app_defines


def _app_h(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "app.h"
    p.write_text(body, encoding="utf-8")
    return p


def test_plain_integer_version(tmp_path: Path):
    h = _app_h(tmp_path, "#define APP_VERSION 102\n")
    assert read_app_defines(h)["app_version"] == 102


def test_leading_zero_decimal_is_not_octal(tmp_path: Path):
    """`001` means v0.01, not an octal literal (and int('001', 0) raises)."""
    h = _app_h(tmp_path, "#define APP_VERSION 001\n")
    assert read_app_defines(h)["app_version"] == 1


def test_hex_and_suffixed_literals(tmp_path: Path):
    h = _app_h(tmp_path, "#define APP_GUID1 0xDF00112233445566ULL\n")
    assert read_app_defines(h)["guid1"] == 0xDF00112233445566


def test_app_ver_macro_from_the_corpus(tmp_path: Path):
    h = _app_h(tmp_path,
               "#define APP_VER(ma, mi, pa)  (((ma) << 16) | ((mi) << 8) | (pa))\n"
               "#define APP_VERSION          APP_VER(0, 1, 3)\n")
    assert read_app_defines(h)["app_version"] == (0 << 16) | (1 << 8) | 3


def test_app_ver_macro_with_nontrivial_components(tmp_path: Path):
    h = _app_h(tmp_path,
               "#define APP_VER(ma, mi, pa)  (((ma) << 16) | ((mi) << 8) | (pa))\n"
               "#define APP_VERSION APP_VER(2, 10, 255)\n")
    assert read_app_defines(h)["app_version"] == (2 << 16) | (10 << 8) | 255


def test_category_macro_or_still_works(tmp_path: Path):
    from pack_beta import _CATEGORY_MACROS
    name_a, name_b = sorted(_CATEGORY_MACROS)[:2]
    h = _app_h(tmp_path, f"#define APP_CATEGORIES ({name_a} | {name_b})\n")
    want = _CATEGORY_MACROS[name_a] | _CATEGORY_MACROS[name_b]
    assert read_app_defines(h)["categories"] == want


def test_trailing_comment_is_stripped(tmp_path: Path):
    h = _app_h(tmp_path,
               "#define APP_VER(ma, mi, pa) (((ma) << 16) | ((mi) << 8) | (pa)) // helper\n"
               "#define APP_VERSION APP_VER(1, 2, 3)  // v1.2.3\n")
    assert read_app_defines(h)["app_version"] == (1 << 16) | (2 << 8) | 3


def test_unknown_identifier_still_raises(tmp_path: Path):
    h = _app_h(tmp_path, "#define APP_VERSION SOME_OTHER_HEADERS_MACRO\n")
    with pytest.raises(ValueError, match="unknown token"):
        read_app_defines(h)


def test_function_call_shaped_garbage_is_rejected(tmp_path: Path):
    """No macro named `whatever` exists, so the call must not evaluate."""
    h = _app_h(tmp_path, "#define APP_VERSION whatever(1, 2)\n")
    with pytest.raises(ValueError):
        read_app_defines(h)


def test_title_and_version_together(tmp_path: Path):
    h = _app_h(tmp_path,
               '#define APP_TITLE "Get Started"\n'
               "#define APP_VER(ma, mi, pa) (((ma) << 16) | ((mi) << 8) | (pa))\n"
               "#define APP_VERSION APP_VER(0, 1, 3)\n")
    got = read_app_defines(h)
    assert got["title"] == "Get Started"
    assert got["app_version"] == 259
