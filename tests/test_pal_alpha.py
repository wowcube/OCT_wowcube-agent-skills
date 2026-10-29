"""``.pal`` format parity: spread-with-alpha vs plain, and the ALPHA flag.

The engine reads a palette entry two incompatible ways depending on the
sprite's ``OCT_FLAG_ALPHA`` bit (``octavios/engine/oct_render.h``)::

    OCT_BLEND_opaque:   back[pix] = pal[t];              // low 16 bits = RGB565
    OCT_BLEND_alpha:    alpha = pe >> 27;                // 5 bits
                        fg    = pe & 0x07FFFFFF;         // "Already spread in
                                                         //  pallette: fg =
                                                         //  (fg | fg << 16)
                                                         //  & 0x07e0f81f"

So the two forms are *not* interchangeable, in either direction:

* a **spread** word under ``BLEND_OPAQUE`` writes ``r5<<11 | b5`` into the
  framebuffer — the green channel is gone;
* a **plain** word under ``BLEND_ALPHA`` reads the RED channel as alpha —
  white stays opaque, black disappears.

``utils.exe`` therefore keeps the two in lockstep, and so must we: a group's
``.pal`` is spread **iff** its sprites carry ``OCT_FLAG_ALPHA``.  The flag
itself is decided elsewhere (``packtxt.resolve_sprite_flags`` — per palette
group, from pooled anti-aliasing); this module only pins the byte format that
must follow it.

Ground truth is the ``OCT_get_started`` corpus: ``art/packed/*.pal`` (46
groups), the ``OCT_FLAG_ALPHA`` bit at ``art/packed/*.raw`` offset 44, and
``utils.exe``'s own ``art/!pack.log`` for the sprite→group routing of all 451
sprites.  That corpus is gitignored, so the numbers are transcribed here
rather than read at test time.
"""
from __future__ import annotations

import struct

import numpy as np
import pytest
from PIL import Image

import pack_beta
from pack_beta import (
    OCT_FLAG_ALPHA,
    PAL_ALPHA5_SHIFT,
    PAL_SPREAD_MASK,
    build_pal,
    pal_is_spread,
    pal_word_plain,
    pal_word_spread,
    read_pal,
    read_pal_rgba,
)
from pack_codec import build_auto_palette, pack_sprite, rgba_to_rgb565


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: the golden format rule
# ─────────────────────────────────────────────────────────────────────────────

# One row per palette group of the OCT_get_started corpus:
#   (bucket index == !pack.txt block index == utils.exe's "pal:N",
#    entries, the group's first glob, spread?, OCT_FLAG_ALPHA on its sprites?)
#
# `spread?` was read off `art/packed/<bucket+1>.pal` (a file is plain iff every
# 4-byte word has low16 == high16); the flag off octBmp_t offset 44 of every
# member sprite named in `art/!pack.log` (uniform within a group, as
# utils.exe decides it per group).
GOLDEN_PAL_GROUPS: list[tuple[int, int, str, bool, bool]] = [
    (0,  256, "*",                    False, False),
    (1,   16, "cubetext_xl_*",        False, False),
    # cubetext_hi_* and main* DO contain semi-transparent pixels, but not
    # enough of them (<= 15 % of the visible ones) for utils.exe to enable
    # alpha -- so their palettes stay plain.  This is why the format must
    # follow the flag and not "any non-opaque entry".
    (2,  128, "cubetext_hi_*",        False, False),
    (3,  128, "cubetext_wow_*",       False, False),
    (4,  256, "selectcube_*",         True,  True),
    (5,  256, "selectcube_orange_*",  True,  True),
    (6,   16, "bg_blue_s_*",          False, False),
    (7,   16, "bg_orange_s_*",        False, False),
    (8,   16, "main*",                False, False),
    (9,   16, "error_ind_*",          True,  True),
    (10,  16, "selector_*",           True,  True),
    (11,  16, "arrow_b*",             True,  True),
    (12,  16, "arrow_o*",             True,  True),
    (13,  16, "arrow_point_*",        True,  True),
    (14,  16, "transit_w_new_*",      True,  True),
    (15,  16, "selectcube_transit_*", False, False),
    (16,   4, "eyes_bg*",             False, False),   # all-zero palette
    (17,   4, "eyes_idle*",           False, False),
    (18, 256, "ic_tilt_*",            True,  True),
    (19, 256, "ic_halftwist_*",       False, False),
    (20, 128, "t_finalstep*",         True,  True),
    (21, 128, "t_future*",            True,  True),
    (22, 129, "t_halftwist*",         True,  True),
    (23, 128, "t_justshake*",         True,  True),
    (24, 128, "t_pat*",               True,  True),
    (25, 128, "t_scanqr*",            True,  True),
    (26, 128, "t_selectcube_1*",      True,  True),
    (27, 128, "t_selectcube_2*",      True,  True),
    (28, 128, "t_selectcube_3*",      True,  True),
    (29, 128, "t_selector*",          True,  True),
    (30, 128, "t_shake*",             True,  True),
    (31, 128, "t_tilt*",              True,  True),
    (32, 128, "t_twist*",             True,  True),
    (33, 128, "t_twistright*",        True,  True),
    (34, 128, "t_twistup*",           True,  True),
    (35, 128, "t_usehalftwist*",      True,  True),
    (36, 128, "t_welcome*",           True,  True),
    (37, 128, "t_welldone*",          True,  True),
    (38, 128, "t_pairit*",            True,  True),
    (39, 128, "t_paircube*",          True,  True),
    (40,   4, "t_hi*",                True,  True),
    (41,  16, "halftwist_p*",         True,  True),
    (42,  64, "halftwist_b*",         True,  True),
    (43,  64, "ahover*",              False, False),
    (44,  64, "ico*",                 False, False),
    # qr_code*: utils.exe wrote plain + flags:00 (a QR is hard-edged, so the
    # auto-detector finds no anti-aliasing -- see art/!pack.log line "PNG
    # qr_code palette:45 bits:4 flags:00").  The corpus on disk shows spread +
    # ALPHA because art/!pack.bat re-runs art/qr_setalpha.py afterwards, which
    # flips BOTH together -- the rule holds in either state.
    (45,  16, "qr_code*",             True,  True),
]

GOLDEN_GROUP_COUNT = 46
GOLDEN_SPRITE_COUNT = 451


def test_golden_pal_format_follows_the_alpha_flag():
    """spread ⟺ OCT_FLAG_ALPHA, on all 46 corpus groups."""
    assert len(GOLDEN_PAL_GROUPS) == GOLDEN_GROUP_COUNT
    for index, _n, glob, spread, alpha in GOLDEN_PAL_GROUPS:
        if index == 16:
            continue        # all-zero palette: the two forms are identical
        assert spread == alpha, f"group {index} ({glob}) breaks the rule"


def test_golden_plain_groups_are_exactly_the_non_alpha_ones():
    plain = sorted(i for i, _n, _g, spread, _a in GOLDEN_PAL_GROUPS if not spread)
    assert plain == [0, 1, 2, 3, 6, 7, 8, 15, 16, 17, 19, 43, 44]


# ── the bit layout itself, pinned on real golden words ───────────────────────

# art/packed/5.pal (group 4, selectcube_*, spread): the first opaque entry, a
# semi-transparent one, and the alpha5 the engine reads back.
GOLDEN_SPREAD_WORDS: list[tuple[int, int, int]] = [
    # (word, rgb565, alpha5)
    (0xFF80F81F, 0xFF9F, 31),
    (0x10200001, 0x0021,  2),
    (0xF880701F, 0x709F, 31),
    (0x24209818, 0x9C38,  4),
    (0xF9A0400E, 0x41AE, 31),
]

# art/packed/1.pal (group 0, the "*" catch-all, plain)
GOLDEN_PLAIN_WORDS: list[tuple[int, int]] = [
    (0x70F370F3, 0x70F3),
    (0x08220822, 0x0822),
    (0x30CA30CA, 0x30CA),
    (0x51305130, 0x5130),
]


def test_spread_layout_constants_match_the_engine():
    # oct_render.h: `alpha = pe >> 27`, `fg = pe & 0x07FFFFFF`, and the
    # SPREAD_MASK the comment names for the already-spread RGB.
    assert PAL_ALPHA5_SHIFT == 27
    assert PAL_SPREAD_MASK == 0x07E0F81F
    # the two fields must not overlap: 5 alpha bits above the spread RGB
    assert PAL_SPREAD_MASK & (0x1F << PAL_ALPHA5_SHIFT) == 0


@pytest.mark.parametrize("word,rgb565,alpha5", GOLDEN_SPREAD_WORDS)
def test_spread_word_reproduces_golden(word, rgb565, alpha5):
    alpha8 = (alpha5 << 3) | (alpha5 >> 2)
    assert pal_word_spread(rgb565, alpha8) == word
    # ...and the engine's own decode gets the inputs back
    assert word >> PAL_ALPHA5_SHIFT == alpha5
    fg = word & 0x07FFFFFF
    assert fg == ((rgb565 | rgb565 << 16) & PAL_SPREAD_MASK)


@pytest.mark.parametrize("word,rgb565", GOLDEN_PLAIN_WORDS)
def test_plain_word_reproduces_golden(word, rgb565):
    assert pal_word_plain(rgb565) == word
    assert word & 0xFFFF == rgb565          # OCT_BLEND_opaque reads this half


def test_a_spread_word_is_never_mistaken_for_a_plain_one():
    words = [w for w, _c, _a in GOLDEN_SPREAD_WORDS]
    assert pal_is_spread([0] + words)
    assert not pal_is_spread([0] + [w for w, _c in GOLDEN_PLAIN_WORDS])
    # an all-zero palette (corpus group 16, eyes_bg*) is indistinguishable and
    # is treated as plain
    assert not pal_is_spread([0, 0, 0, 0])


# ─────────────────────────────────────────────────────────────────────────────
# build_pal / read_pal
# ─────────────────────────────────────────────────────────────────────────────

def test_build_pal_without_alphas_stays_plain():
    """The no-alpha call is byte-for-byte what it always was."""
    colors = [0x0000, 0x70F3, 0x0822, 0x30CA]
    assert build_pal(colors) == b"".join(struct.pack("<HH", c, c) for c in colors)


def test_build_pal_with_alphas_is_spread():
    colors = [0x0000, 0xFF9F, 0x0021]
    alphas = [0, 255, 0x11]                 # 0x11 >> 3 == 2
    blob = build_pal(colors, alphas)
    words = [struct.unpack_from("<I", blob, o)[0] for o in range(0, len(blob), 4)]
    assert words == [0x00000000, 0xFF80F81F, 0x10200001]


def test_index_zero_is_transparent_in_both_formats():
    # index 0 is the keyed-out slot (`if (t == 0) continue` in every blend
    # routine); it must never carry a colour or an alpha
    assert build_pal([0x0000, 0xFFFF])[:4] == b"\x00\x00\x00\x00"
    assert build_pal([0x0000, 0xFFFF], [0, 255])[:4] == b"\x00\x00\x00\x00"
    # ...even if a caller hands us junk in slot 0 of a spread palette
    assert build_pal([0xFFFF, 0xFFFF], [255, 255])[:4] == b"\x00\x00\x00\x00"


def test_build_pal_rejects_mismatched_alpha_length():
    with pytest.raises(ValueError):
        build_pal([0x0000, 0xFFFF], [0])


def test_read_pal_reads_both_formats(tmp_path):
    colors = [0x0000, 0xFF9F, 0x0021, 0x709F]
    alphas = [0, 255, 0x11, 255]

    plain = tmp_path / "plain.pal"
    plain.write_bytes(build_pal(colors))
    assert read_pal(plain) == colors
    # a plain palette carries no alpha: everything but the keyed-out slot 0
    # reads back opaque
    assert read_pal_rgba(plain) == [(0x0000, 0)] + [(c, 255) for c in colors[1:]]

    spread = tmp_path / "spread.pal"
    spread.write_bytes(build_pal(colors, alphas))
    assert read_pal(spread) == colors       # RGB565 survives the round trip
    got = read_pal_rgba(spread)
    assert [a for _c, a in got] == [0, 255, 0x10, 255]   # a5 -> a8, 2 -> 0x10


def test_read_pal_still_rejects_a_truncated_file(tmp_path):
    bad = tmp_path / "bad.pal"
    bad.write_bytes(b"\x01\x02\x03")
    with pytest.raises(ValueError):
        read_pal(bad)


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: round trip on an antialiased sprite
# ─────────────────────────────────────────────────────────────────────────────

def _soft_circle(path, side: int = 48) -> Image.Image:
    """A red disc with a wide antialiased rim: alpha ramps 0 -> 255."""
    yy, xx = np.mgrid[0:side, 0:side]
    r = np.hypot(yy - (side - 1) / 2, xx - (side - 1) / 2)
    # 6-pixel feather so plenty of distinct intermediate alphas exist
    a = np.clip((side / 2 - 2 - r) / 6.0, 0.0, 1.0) * 255.0
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[:, :, 0] = 220
    rgba[:, :, 1] = 40
    rgba[:, :, 2] = 60
    rgba[:, :, 3] = a.astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    img.save(path)
    return img


def _decode_indices(blob: bytes) -> np.ndarray:
    """Decode a legacy packed-sprite blob back into its palette indices."""
    from unpack import BitReader, OctBmp

    bmp = OctBmp(blob)
    trims = list(blob[OctBmp.HEADER_SIZE:OctBmp.HEADER_SIZE + bmp.h])
    texels = OctBmp.HEADER_SIZE + ((bmp.h + 3) // 4) * 4
    reader = BitReader(blob, texels)
    out = np.zeros((bmp.h, bmp.w), dtype=np.int32)
    off = 0
    for y in range(bmp.h):
        line = reader.decode_line(off, bmp.symbol_bitness, bmp.w)
        out[y, :len(line)] = line[:bmp.w]
        off += trims[y]
    return out


@pytest.fixture
def antialiased_pack(tmp_path):
    """Pack one soft-edged sprite through the real palette codec + emit layer."""
    png = tmp_path / "soft.png"
    src = _soft_circle(png)

    pal, _size, _sym, colors_rgba = build_auto_palette([str(png)], max_colors=64)
    blob = pack_sprite(str(png), pal, pidx=0, flags=OCT_FLAG_ALPHA)

    app = tmp_path / "app_soft"
    pack_beta.emit_beta_layout(
        app, "app_soft",
        palettes={0: [(0x0000 if c[3] == 0 else rgba_to_rgb565(*c[:3]), c[3])
                      for c in colors_rgba]},
        palette_sprites=[("soft", blob)],
    )
    return src, blob, app / "art" / "packed" / "1.pal"


def test_antialiased_pal_is_spread(antialiased_pack):
    _src, _blob, pal_path = antialiased_pack
    words = [struct.unpack_from("<I", pal_path.read_bytes(), o)
             for o in range(0, pal_path.stat().st_size, 4)]
    assert pal_is_spread([w[0] for w in words])


def test_antialiased_alpha_gradient_survives(antialiased_pack):
    """The rim must stay a ramp, not collapse to opaque/transparent."""
    src, blob, pal_path = antialiased_pack
    entries = read_pal_rgba(pal_path)
    alphas = np.array([a for _c, a in entries], dtype=np.int32)

    # the palette itself has to hold intermediate alphas
    mid = alphas[(alphas > 16) & (alphas < 239)]
    assert len(mid) >= 8, f"only {len(mid)} intermediate alphas: {sorted(set(alphas.tolist()))}"

    # and every pixel must decode back to roughly its source alpha
    idx = _decode_indices(blob)
    got = alphas[idx]
    want = np.asarray(src)[:, :, 3].astype(np.int32)
    assert got.shape == want.shape
    # a5 quantisation costs up to 8 levels; the palette search a little more
    assert np.abs(got - want).mean() < 12.0
    # the ramp is a ramp: the decoded rim spans many distinct alpha levels
    rim = got[(want > 16) & (want < 239)]
    assert len(np.unique(rim)) >= 8


def test_opaque_sprite_keeps_the_plain_format(tmp_path):
    """No ALPHA flag on the sprites -> plain .pal, exactly as utils.exe does."""
    png = tmp_path / "block.png"
    Image.new("RGBA", (16, 16), (10, 200, 60, 255)).save(png)

    pal, _size, _sym, colors_rgba = build_auto_palette([str(png)], max_colors=16)
    blob = pack_sprite(str(png), pal, pidx=0, flags=0)

    app = tmp_path / "app_flat"
    pack_beta.emit_beta_layout(
        app, "app_flat",
        palettes={0: [(0x0000 if c[3] == 0 else rgba_to_rgb565(*c[:3]), c[3])
                      for c in colors_rgba]},
        palette_sprites=[("block", blob)],
    )
    words_blob = (app / "art" / "packed" / "1.pal").read_bytes()
    words = [struct.unpack_from("<I", words_blob, o)[0]
             for o in range(0, len(words_blob), 4)]
    assert not pal_is_spread(words)
    # ...and the green channel is intact in the half OCT_BLEND_opaque reads
    assert any((w & 0xFFFF) >> 5 & 0x3F for w in words)
