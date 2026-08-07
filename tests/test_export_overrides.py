"""``art/overrides/`` — committed PNGs that win over the PSD export.

A python-only CI build re-exports ``art/exported/`` from the PSDs on every
run, which is right for the 99 % case and wrong for sprites the artist's own
pipeline deliberately replaces afterwards. The reference corpus
(``OCT_get_started``) is the measured case: its ``art/!pack.bat`` copies
``qr_code_transparent.png`` over the exported ``qr_code.png`` *after* the
psd.exe run, so the PSD layer is not the artwork the app ships (mean abs
error 146/255 between the two). Nothing structural catches that — the pack
succeeds, the sizes match, the wrong picture ships.

``<art-dir>/overrides/*.png`` makes the step declarative and app-agnostic:
the packer copies them over the export by filename, and knows nothing about
QR codes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from pack import _apply_export_overrides


def _png(path: Path, color, size=(4, 4)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path)


def test_no_overrides_dir_is_a_no_op(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    _png(exported / "coin.png", (1, 2, 3, 255))
    before = (exported / "coin.png").read_bytes()

    assert _apply_export_overrides(str(art), str(exported)) == 0
    assert (exported / "coin.png").read_bytes() == before


def test_empty_overrides_dir_is_a_no_op(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    (art / "overrides").mkdir(parents=True)
    _png(exported / "coin.png", (1, 2, 3, 255))

    assert _apply_export_overrides(str(art), str(exported)) == 0


def test_override_replaces_the_exported_sprite(tmp_path: Path):
    """The corpus case: same name, different artwork, override wins."""
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    _png(exported / "qr_code.png", (10, 20, 30, 255))       # the PSD layer
    _png(art / "overrides" / "qr_code.png", (200, 0, 0, 128))  # what ships

    assert _apply_export_overrides(str(art), str(exported)) == 1
    with Image.open(exported / "qr_code.png") as img:
        assert img.convert("RGBA").getpixel((0, 0)) == (200, 0, 0, 128)


def test_override_can_add_a_sprite_no_psd_produces(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    exported.mkdir(parents=True)
    _png(art / "overrides" / "extra.png", (7, 7, 7, 255))

    assert _apply_export_overrides(str(art), str(exported)) == 1
    assert (exported / "extra.png").is_file()


def test_overrides_do_not_touch_other_sprites(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    _png(exported / "coin.png", (1, 2, 3, 255))
    _png(exported / "qr_code.png", (10, 20, 30, 255))
    keep = (exported / "coin.png").read_bytes()
    _png(art / "overrides" / "qr_code.png", (200, 0, 0, 255))

    _apply_export_overrides(str(art), str(exported))
    assert (exported / "coin.png").read_bytes() == keep


def test_non_png_files_in_overrides_are_ignored(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    exported.mkdir(parents=True)
    (art / "overrides").mkdir(parents=True)
    (art / "overrides" / "notes.txt").write_text("not artwork", encoding="utf-8")

    assert _apply_export_overrides(str(art), str(exported)) == 0
    assert not (exported / "notes.txt").exists()


def test_applying_twice_is_idempotent(tmp_path: Path):
    art, exported = tmp_path / "art", tmp_path / "art" / "exported"
    _png(exported / "qr_code.png", (10, 20, 30, 255))
    _png(art / "overrides" / "qr_code.png", (200, 0, 0, 255))

    _apply_export_overrides(str(art), str(exported))
    first = (exported / "qr_code.png").read_bytes()
    _apply_export_overrides(str(art), str(exported))
    assert (exported / "qr_code.png").read_bytes() == first
