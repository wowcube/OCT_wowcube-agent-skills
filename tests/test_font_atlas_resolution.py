"""A ``.fnt``'s embedded page name is a hint, not the truth.

Ground truth, ``OCT_ladybug``. ``art/font_3.fnt`` is a binary BMFont whose
pages block names ``font_1_0.png`` — a stale leftover from whatever tool wrote
it. The real atlas ``font_3_0.png`` sits in the same directory. The legacy
toolchain is immune because ``psd.exe`` derives the atlas from the ``.fnt``
filename stem and never reads the embedded name.

Trusting the declared name is a SILENT corruption: ``font_1_0.png`` exists, so
the "atlas not found" guard never fires. All 94 ``font_3`` glyphs were exported
as byte-exact crops of the font_1 atlas (94/94 matched the wrong sheet, 0/94
the right one). font_3 is a 25px face and font_1 a 45px one, so font_3's small
rects landed on inter-glyph padding and the glyphs came out nearly blank rather
than visibly scrambled::

    glyph                exported  crop(font_1_0)  crop(font_3_0)  legacy
    font_3_00082 'R'      1 / 120        1               97          99
    font_3_00056 '8'      8 / 143        8              101         104
    font_3_00108 'l'      8 /  48        8               47          47

Mean abs error against the shipped pack was ~123/255 with 75.7% of pixels
differing, while font_1/font_2 sat at ~1.3-1.8 (benign palette requantization).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from pack_psd import resolve_font_atlas


def _png(path: Path, color=(255, 0, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), color).save(path)


def test_convention_wins_over_a_stale_declared_page(tmp_path: Path):
    # exactly ladybug's font_3 situation: both files exist, .fnt names the wrong one
    _png(tmp_path / "font_3_0.png", (0, 255, 0, 255))
    _png(tmp_path / "font_1_0.png", (255, 0, 0, 255))
    got = resolve_font_atlas(str(tmp_path / "font_3.fnt"), 0, "font_1_0.png")
    assert got == str(tmp_path / "font_3_0.png")


def test_declared_name_is_used_when_the_conventional_file_is_absent(tmp_path: Path):
    _png(tmp_path / "atlas_custom.png")
    got = resolve_font_atlas(str(tmp_path / "font_9.fnt"), 0, "atlas_custom.png")
    assert got == str(tmp_path / "atlas_custom.png")


def test_agreeing_names_resolve_to_that_file(tmp_path: Path):
    # font_1 / font_2 already declare their conventional name; must not change
    _png(tmp_path / "font_1_0.png")
    got = resolve_font_atlas(str(tmp_path / "font_1.fnt"), 0, "font_1_0.png")
    assert got == str(tmp_path / "font_1_0.png")


def test_missing_everything_returns_none(tmp_path: Path):
    assert resolve_font_atlas(str(tmp_path / "font_1.fnt"), 0, "nope.png") is None


def test_multi_page_uses_the_page_index(tmp_path: Path):
    _png(tmp_path / "font_1_0.png")
    _png(tmp_path / "font_1_1.png")
    assert resolve_font_atlas(str(tmp_path / "font_1.fnt"), 1, "font_1_1.png") \
        == str(tmp_path / "font_1_1.png")


def test_ladybug_font_3_fnt_really_declares_the_wrong_page():
    """Regression guard against the actual shipped source file."""
    art = Path("C:/Users/igort/Desktop/wowcube_vibecode/OCT_ladybug/art")
    fnt = art / "font_3.fnt"
    if not fnt.is_file():
        import pytest
        pytest.skip("OCT_ladybug reference art not available")
    blob = fnt.read_bytes()
    assert b"font_1_0.png" in blob, "the stale page name this rule exists for"
    assert (art / "font_3_0.png").is_file(), "the atlas that should be used"
    assert resolve_font_atlas(str(fnt), 0, "font_1_0.png") \
        == str(art / "font_3_0.png")
