#!/usr/bin/env python3
"""
``!pack.txt`` — the legacy ``utils.exe`` palette-bucket configuration
====================================================================

An app's ``art/!pack.txt`` is what the legacy toolchain feeds to
``utils.exe``: it declares one palette per block, the exact number of
palette entries that palette gets, optional per-block flag tags, and the
filename globs that route exported sprites into it.

File format
-----------

::

    exported            <- line 1: the folder holding the exported PNGs
                        <- blank line
    256                 <- block: palette entry count (INCLUDING index 0)
    *                     glob(s); a plain name matches exactly
                        <- blank line separates blocks
    256
    <ALPHA><FULLSIZE>   <- optional tag line(s), several tags may share a line
    selectcube_*
    selectcube_orange_*   several globs may share a block

* Blocks are separated by blank lines (``utils.exe`` aborts with
  "Expected empty line in conf" otherwise).
* The first line of a block is the palette size. It is *not* rounded to a
  power of two — the reference corpus contains a 129-entry palette.
* Every following line is either a tag line (starts with ``<``) or a glob.
* A sprite is routed into the **last** block whose globs match it, so the
  usual layout is a ``*`` catch-all first and increasingly specific blocks
  after it (``selectcube_*`` then ``selectcube_transit_*``).
* A sprite matching no block at all is not skipped by this toolchain: it is
  packed into palette group 0, or group 1 when its name contains "font",
  with the default 8-bit symbol bitness (it does not inherit any bucket's
  reduced bitness). ``utils.exe`` itself instead skips such a sprite
  ("Unmatched palette %s, skipped").

Symbol bitness is ``ceil(log2(size))`` — verified against ``utils.exe`` for
sizes 2, 3, 4, 5, 16, 17, 127, 128, 129, 255, 256.

Tags
----

The tag vocabulary and the flag bit each one sets were read out of
``utils.exe`` and confirmed by packing a probe sprite with every tag and
reading octBmp_t offset 44 back:

===============  =====================================
``<FULLSIZE>``   ``SpriteFlag.FULLSIZE`` (0x02)
``<ADD>``        ``SpriteFlag.ADDITIVE`` (0x04)
``<BG>``         ``SpriteFlag.BG``       (0x08)
``<BUMP>``       ``SpriteFlag.BUMP``     (0x10)
``<DUDV>``       ``SpriteFlag.DUDV``     (0x20)
``<REFL>``       ``SpriteFlag.REFL``     (0x40)
``<ALPHA>``      forces ``SpriteFlag.ALPHA`` **on**
``<OPAQUE>``     forces ``SpriteFlag.ALPHA`` **off**
===============  =====================================

``<FULLSIZE>`` is load-bearing twice over: besides the flag bit, it halves
the pivot scale (see :func:`pack_codec.compute_psd_marker_pivot`), so a
dropped tag both scales and mis-anchors the sprite.

Auto-detected ALPHA
-------------------

Without ``<ALPHA>``/``<OPAQUE>``, ``utils.exe`` decides per palette group
from the share of anti-aliased pixels, printing either

  ``Alpha enabled: 24108/140544 (17.2%) semi-transparent pixels`` or
  ``AA-tolerance: 5535/39906 (13.9%) semi-transparent pixels forced opaque``

The three constants below were pinned by binary-searching the real
``utils.exe`` with synthetic sprites (see the module constants), and they
reproduce the ALPHA decision for all 46 palette groups of the
``OCT_get_started`` corpus, matching both counters exactly.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from config import (
    PACK_TXT_ALPHA_ENABLE_RATIO,
    PACK_TXT_FILENAME,
    PACK_TXT_OPAQUE_MIN_ALPHA,
    PACK_TXT_TAG_ALPHA,
    PACK_TXT_TAG_FLAGS,
    PACK_TXT_TAG_OPAQUE,
    PACK_TXT_TRANSPARENT_MAX_ALPHA,
    SpriteFlag,
)

_TAG_RE = re.compile(r'<[^<>]*>')


class PackTxtError(ValueError):
    """``!pack.txt`` is malformed."""


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PackBucket:
    """One palette block of ``!pack.txt``."""

    index: int                      # 0-based; == the Pidx utils.exe writes
    max_colors: int                 # palette entries INCLUDING index 0
    patterns: tuple[str, ...]
    tags: tuple[str, ...]
    line: int                       # 1-based line of the size, for messages

    @property
    def base_flags(self) -> int:
        """Flag bits the tags set, excluding the ALPHA decision."""
        flags = 0
        for tag in self.tags:
            flags |= int(PACK_TXT_TAG_FLAGS.get(tag, 0))
        return flags

    @property
    def alpha_override(self) -> bool | None:
        """True for ``<ALPHA>``, False for ``<OPAQUE>``, None for auto."""
        if PACK_TXT_TAG_OPAQUE in self.tags:
            return False
        if PACK_TXT_TAG_ALPHA in self.tags:
            return True
        return None

    @property
    def unknown_tags(self) -> tuple[str, ...]:
        known = set(PACK_TXT_TAG_FLAGS) | {PACK_TXT_TAG_ALPHA, PACK_TXT_TAG_OPAQUE}
        return tuple(t for t in self.tags if t not in known)

    def matches(self, sprite_name: str) -> bool:
        return any(fnmatch.fnmatchcase(sprite_name, p) for p in self.patterns)


@dataclass(frozen=True)
class PackConfig:
    """A parsed ``!pack.txt``."""

    exported_dir: str
    buckets: tuple[PackBucket, ...]
    path: Path | None = None

    # ── routing ──────────────────────────────────────────────────────────
    def bucket_for(self, sprite_name: str) -> PackBucket | None:
        """The **last** matching block wins, so later masks beat earlier ones."""
        found: PackBucket | None = None
        for bucket in self.buckets:
            if bucket.matches(sprite_name):
                found = bucket
        return found

    def assign(self, sprite_name: str) -> tuple[int, int, int] | None:
        """``(palette_group_id, max_colors, flags)`` or None when unmatched.

        ``flags`` carries only what the tags decide; the auto-detected ALPHA
        bit is added by :func:`resolve_sprite_flags`, which needs the pixels.
        """
        bucket = self.bucket_for(sprite_name)
        if bucket is None:
            return None
        flags = bucket.base_flags
        if bucket.alpha_override:
            flags |= int(SpriteFlag.ALPHA)
        return bucket.index, bucket.max_colors, flags

    def group_sprites(self, sprite_names) -> tuple[dict[int, list[str]], list[str]]:
        """Split names into ``{bucket_index: [names]}`` plus the unmatched."""
        groups: dict[int, list[str]] = {b.index: [] for b in self.buckets}
        unmatched: list[str] = []
        for name in sprite_names:
            bucket = self.bucket_for(name)
            if bucket is None:
                unmatched.append(name)
            else:
                groups[bucket.index].append(name)
        return groups, unmatched


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_pack_txt(path: str | Path) -> PackConfig:
    """Parse ``!pack.txt`` into a :class:`PackConfig`."""
    path = Path(path)
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    return parse_pack_txt_text(text, path=path)


def parse_pack_txt_text(text: str, path: Path | None = None) -> PackConfig:
    """Parse ``!pack.txt`` contents (CRLF and a BOM are both tolerated)."""
    lines = [line.strip() for line in text.replace('\r\n', '\n')
             .replace('\r', '\n').split('\n')]

    exported_dir = None
    header_idx = 0
    for i, line in enumerate(lines):
        if line:
            exported_dir, header_idx = line, i
            break
    if exported_dir is None:
        raise PackTxtError(f"{path or '<text>'}: empty config")
    if exported_dir.isdigit():
        raise PackTxtError(
            f"{path or '<text>'}:{header_idx + 1}: expected the exported-folder "
            f"name on the first line, got the number {exported_dir!r}")

    buckets: list[PackBucket] = []
    size: int | None = None
    tags: list[str] = []
    globs: list[str] = []
    size_line = 0

    def flush() -> None:
        nonlocal size, tags, globs
        if size is None:
            return
        if not globs:
            raise PackTxtError(
                f"{path or '<text>'}:{size_line}: palette block of {size} "
                f"colors has no filename mask")
        buckets.append(PackBucket(index=len(buckets), max_colors=size,
                                  patterns=tuple(globs), tags=tuple(tags),
                                  line=size_line))
        size, tags, globs = None, [], []

    for lineno, line in enumerate(lines[header_idx + 1:], start=header_idx + 2):
        if not line:
            flush()
            continue
        if size is None:
            # First line of a block is always the palette size. A bare number
            # further down a block is a sprite name (the reserved 0.png), which
            # is why blocks are delimited by blank lines and nothing else.
            try:
                size = int(line)
            except ValueError:
                raise PackTxtError(
                    f"{path or '<text>'}:{lineno}: expected a palette size, "
                    f"got {line!r} (blocks must be separated by a blank line)"
                ) from None
            if size < 1:
                raise PackTxtError(
                    f"{path or '<text>'}:{lineno}: palette size must be >= 1")
            size_line = lineno
            continue
        if line.startswith('<'):
            found = _TAG_RE.findall(line)
            if ''.join(found) != line:
                raise PackTxtError(
                    f"{path or '<text>'}:{lineno}: malformed tag line {line!r}")
            tags.extend(t.upper() for t in found)
            continue
        globs.append(line)
    flush()

    return PackConfig(exported_dir=exported_dir, buckets=tuple(buckets),
                      path=path)


def find_pack_txt(art_dir: str | Path) -> Path | None:
    """``<art_dir>/!pack.txt`` if it exists, else None."""
    candidate = Path(art_dir) / PACK_TXT_FILENAME
    return candidate if candidate.is_file() else None


# ─────────────────────────────────────────────────────────────────────────────
# ALPHA auto-detection (utils.exe parity)
# ─────────────────────────────────────────────────────────────────────────────

def sprite_alpha_counts(png_path: str | Path) -> tuple[int, int]:
    """``(semi_transparent_px, visible_px)`` under utils.exe's thresholds.

    Pixels at or below :data:`config.PACK_TXT_TRANSPARENT_MAX_ALPHA` are not
    visible at all and count for neither total; pixels at or above
    :data:`config.PACK_TXT_OPAQUE_MIN_ALPHA` are visible but not
    anti-aliased.
    """
    import numpy as np
    from PIL import Image

    with Image.open(png_path) as img:
        alpha = np.asarray(img.convert('RGBA'))[:, :, 3]
    visible = alpha > PACK_TXT_TRANSPARENT_MAX_ALPHA
    semi = visible & (alpha < PACK_TXT_OPAQUE_MIN_ALPHA)
    return int(semi.sum()), int(visible.sum())


def group_alpha_enabled(semi_px: int, visible_px: int) -> bool:
    """utils.exe's rule: alpha iff ``semi / visible`` is *strictly* above
    :data:`config.PACK_TXT_ALPHA_ENABLE_RATIO`."""
    if visible_px <= 0:
        return False
    return (semi_px / visible_px) > PACK_TXT_ALPHA_ENABLE_RATIO


def resolve_sprite_flags(
    config: PackConfig,
    exported_dir: str | Path,
    sprite_names,
) -> dict[str, int]:
    """Per-sprite octBmp_t flag bytes implied by ``!pack.txt``.

    Tags apply per palette group; the ALPHA bit is decided per group too —
    forced by ``<ALPHA>``/``<OPAQUE>``, otherwise auto-detected from the
    group's pooled anti-aliasing. Every sprite of a group therefore ends up
    with the same flags, exactly as ``utils.exe`` does it.
    """
    exported_dir = Path(exported_dir)
    groups, _unmatched = config.group_sprites(sprite_names)
    flags: dict[str, int] = {}

    for bucket in config.buckets:
        members = groups.get(bucket.index, [])
        if not members:
            continue
        alpha = bucket.alpha_override
        if alpha is None:
            semi = visible = 0
            for name in members:
                png = exported_dir / f'{name}.png'
                if not png.is_file():
                    continue
                s, v = sprite_alpha_counts(png)
                semi += s
                visible += v
            alpha = group_alpha_enabled(semi, visible)
        value = bucket.base_flags | (int(SpriteFlag.ALPHA) if alpha else 0)
        for name in members:
            flags[name] = value
    return flags
