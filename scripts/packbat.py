#!/usr/bin/env python3
"""Read ``art/!pack.bat`` — the app's own declaration of how it is packed.

Every legacy WowCube app repo ships the artist's batch file next to the PSDs.
It is not documentation: it *is* the pack, the exact ``psd.exe``/``utils.exe``
command line the shipped ``index.bin`` was built from. Four decisions that no
filename heuristic can get right in general are stated literally in it:

  * **which PSDs are exported at all.** ``OCT_get_started`` keeps a stray
    ``art/map_18_18.psd`` that ``!pack.bat`` never mentions; the ``map_``
    prefix heuristic packs it as a ninth map the legacy container does not
    have. ``OCT_ladybug`` keeps ``ladybug-assets.psd``, the pre-split
    original of ``ladybug-assets_1/_2.psd``, which the glob-based asset
    detection re-exports on top of the real ones.
  * **which of them are ``-map`` placement documents.** ladybug runs eight
    PSDs through ``psd.exe -map`` (``splash, splash_wo_saves, countdown,
    hud, game_over, complete, win, ico``) and not one of them carries the
    ``map_`` prefix or one of the two reserved launcher names, so the
    name-based rule finds exactly one of the eight. A map PSD mistaken for
    an asset PSD exports PNGs named after sprites that already exist and
    silently overwrites them.
  * **which palette config ``utils.exe`` actually consumes.** In
    ``OCT_get_started`` that is ``!pack.txt``. In ``OCT_ladybug``
    ``!pack.bat`` first runs the app's own ``pack_palettes.py`` to expand
    ``!pack.txt`` (16 coarse buckets, used only as a lock/seed) into
    ``!pack_pal.txt`` (32 buckets) and feeds *that* to ``utils.exe``.
    Picking the config by filename gets ladybug's palettes wrong.
  * **what the generated ids header is called.** ``!pack.bat`` sets
    ``app=app`` in ladybug and ``app=app_get_started`` in get_started, so
    the header is ``src/app_ids.h`` in one and ``src/app_get_started_ids.h``
    in the other. Deriving it from the ``*.target`` marker (``app_ladybug``)
    writes a *new* header beside the stale committed one, and the ARM build
    then compiles old ids against a fresh ``index.bin``.

Parsing is deliberately shallow: expand ``set NAME=VALUE`` variables, tokenize
each line with cmd.exe double-quote rules, and look at the lines whose first
token is a ``psd.exe`` or ``utils.exe`` path. Anything else (``del``, ``mkdir``,
``xcopy``, ``python pack_palettes.py``, ``pause``) is ignored — this module
never runs the batch file, and never runs the app's own scripts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PACK_BAT_FILENAME = '!pack.bat'

_RE_SET = re.compile(r'^\s*set\s+(?:/a\s+)?([^=\s]+)\s*=(.*)$', re.I)
_RE_VAR = re.compile(r'%([^%\s]+)%')
# A batch line may be prefixed with "@" (echo off) or a label; both are dropped
# before tokenizing.
_RE_COMMENT = re.compile(r'^\s*(?:::|@?rem\b)', re.I)


@dataclass
class PackBat:
    """What ``art/!pack.bat`` declares. Paths stay as written (art-relative)."""

    path: Path
    variables: dict[str, str] = field(default_factory=dict)
    exported_dir: str | None = None
    assets: list[str] = field(default_factory=list)      # PSD stems, no -map
    maps: list[str] = field(default_factory=list)        # PSD stems, -map
    fonts: list[str] = field(default_factory=list)       # .fnt sources
    pack_config: str | None = None                       # utils.exe arg 1
    packed_dir: str | None = None                        # utils.exe arg 2
    ids_output: str | None = None                        # utils.exe arg 3

    @property
    def psd_names(self) -> list[str]:
        """Every PSD stem the batch exports, maps included."""
        return self.assets + self.maps

    @property
    def declares_export(self) -> bool:
        """True when the batch runs ``psd.exe`` at all.

        Only then can it be read as "these PSDs, and no others" — a batch
        that merely links (``utils.exe``) still tells us the palette config
        and the ids header, but says nothing about the export set.
        """
        return bool(self.assets or self.maps or self.fonts)

    @property
    def declares_link(self) -> bool:
        return bool(self.pack_config or self.ids_output)

    @property
    def declares_anything(self) -> bool:
        return self.declares_export or self.declares_link


def find_pack_bat(art_dir: str | Path) -> Path | None:
    """``<art_dir>/!pack.bat`` if it exists (case-insensitive on the stem)."""
    art = Path(art_dir)
    if not art.is_dir():
        return None
    direct = art / PACK_BAT_FILENAME
    if direct.is_file():
        return direct
    for cand in sorted(art.glob('*.bat')):
        if cand.name.lower() == PACK_BAT_FILENAME:
            return cand
    return None


def _tokenize(line: str) -> list[str]:
    """cmd.exe-ish tokenizer: whitespace splits, double quotes group.

    ``shlex`` is wrong here — it treats the backslashes in ``"..\\src\\x.h"``
    as escapes and eats them.
    """
    tokens: list[str] = []
    cur: list[str] = []
    in_quotes = False
    has_content = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            has_content = True
        elif ch.isspace() and not in_quotes:
            if has_content:
                tokens.append(''.join(cur))
                cur, has_content = [], False
        else:
            cur.append(ch)
            has_content = True
    if has_content:
        tokens.append(''.join(cur))
    return tokens


def _expand(text: str, variables: dict[str, str]) -> str:
    lowered = {k.lower(): v for k, v in variables.items()}

    def sub(m: re.Match[str]) -> str:
        return lowered.get(m.group(1).lower(), m.group(0))

    # two passes: `set app=app` then `"%app%_ids.h"` is one level, but
    # `set out=%exp%\x` inside another variable needs a second
    for _ in range(2):
        new = _RE_VAR.sub(sub, text)
        if new == text:
            break
        text = new
    return text


def _stem_of(arg: str) -> str:
    return Path(arg.replace('\\', '/')).stem


def parse_pack_bat(path: str | Path) -> PackBat:
    """Parse one ``!pack.bat``. Never raises on odd content — an unparsable
    line is simply not a declaration, and the caller falls back to its
    heuristics."""
    path = Path(path)
    result = PackBat(path=path)
    text = path.read_text(encoding='utf-8', errors='replace')

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _RE_COMMENT.match(line):
            continue
        if line.startswith('@'):
            line = line[1:].lstrip()

        m = _RE_SET.match(line)
        if m:
            result.variables[m.group(1).strip()] = \
                _expand(m.group(2).strip().strip('"'), result.variables)
            continue

        tokens = _tokenize(_expand(line, result.variables))
        if not tokens:
            continue
        exe = tokens[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
        args = tokens[1:]

        if exe in ('psd.exe', 'psd'):
            if not args:
                continue
            source = args[0]
            flags = ' '.join(args[1:]).lower()
            if result.exported_dir is None and len(args) > 1 and args[1]:
                result.exported_dir = args[1].replace('\\', '/').lstrip('./')
            if source.lower().endswith('.fnt'):
                result.fonts.append(source)
            elif source.lower().endswith('.psd'):
                stem = _stem_of(source)
                bucket = result.maps if '-map' in flags.split() else result.assets
                if stem not in bucket:
                    bucket.append(stem)

        elif exe in ('utils.exe', 'utils'):
            if len(args) >= 1 and result.pack_config is None:
                result.pack_config = args[0]
            if len(args) >= 2 and result.packed_dir is None:
                result.packed_dir = args[1]
            if len(args) >= 3 and result.ids_output is None:
                result.ids_output = args[2]

    return result


def read_pack_bat(art_dir: str | Path) -> PackBat | None:
    """:func:`find_pack_bat` + :func:`parse_pack_bat`, or None."""
    found = find_pack_bat(art_dir)
    return parse_pack_bat(found) if found is not None else None


_RE_IDS_INCLUDE = re.compile(r'#\s*include\s+"([^"]*_ids\.h)"')


def resolve_ids_header(app_dir: str | Path, app: str,
                       log=lambda _msg: None) -> Path:
    """The ids header path this app's sources actually ``#include``.

    Assuming ``src/<target>_ids.h`` is the worst kind of wrong. Ladybug's
    ``art/!pack.bat`` sets ``app=app``, so the legacy header is
    ``src/app_ids.h`` and ``src/app.h`` does ``#include "app_ids.h"`` — while
    the ``*.target`` marker says ``app_ladybug``. Writing
    ``src/app_ladybug_ids.h`` leaves the committed ``app_ids.h`` untouched and
    the ARM build then compiles STALE asset ids against a freshly generated
    ``index.bin``: every id off by an unpredictable amount, nothing crashes,
    the wrong art draws.

    Order of authority:
      1. the ``#include "..._ids.h"`` the app's own sources write — literally
         the file the compiler will open;
      2. the third argument of the ``utils.exe`` line in ``art/!pack.bat``,
         i.e. what the legacy toolchain was told to write;
      3. ``src/<app>_ids.h``, the scaffold/AI-generated convention.

    Raises ValueError when ``src/`` includes more than one distinct
    ``*_ids.h`` — the packer generates exactly one, so the app must name one.
    """
    app_dir = Path(app_dir)
    src = app_dir / "src"
    found: dict[str, set[str]] = {}
    if src.is_dir():
        for header in sorted(src.rglob("*.h")):
            try:
                text = header.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _RE_IDS_INCLUDE.finditer(text):
                found.setdefault(Path(m.group(1).replace('\\', '/')).name,
                                 set()).add(header.name)
    if len(found) > 1:
        raise ValueError(
            f"{src} includes several *_ids.h headers "
            f"({', '.join(sorted(found))}) - the packer can only generate "
            f"one; keep a single ids header")
    if len(found) == 1:
        name = next(iter(found))
        log(f"ids header from #include in "
            f"{', '.join(sorted(found[name]))}: src/{name}")
        return src / name

    declared = ids_header_name(read_pack_bat(app_dir / "art"))
    if declared:
        log(f"ids header from art/!pack.bat: src/{declared}")
        return src / declared

    return src / f"{app}_ids.h"


def ids_header_name(pack_bat: PackBat | None) -> str | None:
    """The ids header basename ``utils.exe`` was told to write, if declared.

    ``!pack.bat`` writes it either straight into ``../src`` (ladybug:
    ``..\\src\\%app%_ids.h``) or next to the PSDs and then ``xcopy``s it
    (get_started: ``%app%_ids.h``); only the basename is meaningful to us,
    because the beta container always puts the header in ``<app>/src/``.
    """
    if pack_bat is None or not pack_bat.ids_output:
        return None
    return Path(pack_bat.ids_output.replace('\\', '/')).name
