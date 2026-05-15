"""Load and validate plans/<game>_assets.json.

Schema version policy
---------------------
Every manifest carries an integer `schema_version`. The loader transparently
upgrades older manifests to CURRENT_SCHEMA_VERSION by running each registered
migrator in sequence, so downstream code only deals with the current shape.

To introduce a new version:
  1. Bump CURRENT_SCHEMA_VERSION.
  2. Register a migrator at SCHEMA_MIGRATORS[OLD_VERSION] that returns a dict
     with schema_version incremented and whatever field reshaping is needed.
  3. Add tests covering both the migration path and the post-migration shape.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

NAME_RE = re.compile(r"^[a-z0-9_]+$")
RESERVED_NAMES = frozenset({
    "pal", "0", "icon", "none",
    "bmp_none", "bmp_last", "bmp_0",
    "map_none", "map_last",
})
SPRITE_MAX_SIDE = 240
SOUND_MAX_DURATION_MS = 2000
SOUND_DEFAULT_DURATION_MS = 500
ANIM_FRAME_MIN = 0
ANIM_FRAME_MAX = 99  # two-digit zero-padded suffix: 00..99
ALLOWED_EVENT_TYPES = frozenset({
    "pickup", "hit", "ui", "ambient", "music", "default",
})

# Schema evolution. CURRENT_SCHEMA_VERSION is the shape this module parses
# directly; anything older is upgraded via SCHEMA_MIGRATORS before parsing.
CURRENT_SCHEMA_VERSION = 1
MIN_SUPPORTED_SCHEMA_VERSION = 1

# Each migrator upgrades a raw dict from version K to K+1. The registry is
# keyed by the SOURCE version (the one we are upgrading FROM). Example stub:
#   SCHEMA_MIGRATORS[1] = _migrate_1_to_2
# where _migrate_1_to_2(raw) returns the same dict with schema_version=2
# and any field reshaping applied.
SCHEMA_MIGRATORS: dict[int, Callable[[dict], dict]] = {
    # populated as new versions are introduced
}


class ValidationError(Exception):
    """Raised only when load_manifest is asked to enforce via `strict=True`."""


class SchemaMigrationError(ValidationError):
    """Raised when a manifest cannot be brought up to CURRENT_SCHEMA_VERSION."""


@dataclass(frozen=True)
class Flags:
    alpha: bool = True
    fullsize: bool = False
    additive: bool = False
    bg: bool = False


@dataclass(frozen=True)
class Sprite:
    name: str
    size: tuple[int, int]
    description: str
    group: str | None = None
    anim: str | None = None
    frame: int | None = None
    pivot: tuple[int, int] = (0, 0)
    flags: Flags = field(default_factory=Flags)

    def derived_group(self) -> str:
        """Explicit group wins; otherwise strip a trailing _NN suffix.

        Centralised here so generators, pipeline, and pack logic agree on the
        same grouping rule.
        """
        if self.group:
            return self.group
        n = self.name
        if len(n) >= 3 and n[-3] == "_" and n[-2:].isdigit():
            return n[:-3]
        return n


@dataclass(frozen=True)
class Sound:
    name: str
    description: str
    duration_ms: int = SOUND_DEFAULT_DURATION_MS
    event_type: str | None = None
    group: str | None = None

    def derived_group(self) -> str:
        """Explicit group wins; otherwise fall back to the sound name."""
        return self.group or self.name


@dataclass(frozen=True)
class Manifest:
    game: str
    schema_version: int
    sprites: tuple[Sprite, ...]
    sounds: tuple[Sound, ...]


def _parse_flags(raw: dict | None) -> Flags:
    raw = raw or {}
    return Flags(
        alpha=bool(raw.get("alpha", True)),
        fullsize=bool(raw.get("fullsize", False)),
        additive=bool(raw.get("additive", False)),
        bg=bool(raw.get("bg", False)),
    )


def _parse_sprite(raw: dict) -> Sprite:
    size = tuple(raw["size"])
    w, h = size
    pivot_raw = raw.get("pivot")
    pivot = tuple(pivot_raw) if pivot_raw else (w // 2, h // 2)
    return Sprite(
        name=raw["name"],
        size=(int(w), int(h)),
        description=raw["description"],
        group=raw.get("group"),
        anim=raw.get("anim"),
        frame=raw.get("frame"),
        pivot=(int(pivot[0]), int(pivot[1])),
        flags=_parse_flags(raw.get("flags")),
    )


def _parse_sound(raw: dict) -> Sound:
    return Sound(
        name=raw["name"],
        description=raw["description"],
        duration_ms=int(raw.get("duration_ms", SOUND_DEFAULT_DURATION_MS)),
        event_type=raw.get("event_type"),
        group=raw.get("group"),
    )


def _migrate_to_current(raw: dict) -> dict:
    """Walk registered migrators until raw['schema_version'] == CURRENT_SCHEMA_VERSION.

    Raises SchemaMigrationError when:
      - version is missing or not an int,
      - version is older than MIN_SUPPORTED_SCHEMA_VERSION,
      - version is newer than CURRENT_SCHEMA_VERSION (manifest from the future),
      - a migrator for an intermediate version is not registered.
    """
    try:
        v = int(raw.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise SchemaMigrationError(
            f"schema_version missing or not an integer: {raw.get('schema_version')!r}"
        ) from exc

    if v < MIN_SUPPORTED_SCHEMA_VERSION:
        raise SchemaMigrationError(
            f"schema_version {v}: older than minimum supported "
            f"({MIN_SUPPORTED_SCHEMA_VERSION})"
        )
    if v > CURRENT_SCHEMA_VERSION:
        raise SchemaMigrationError(
            f"schema_version {v}: manifest newer than this tool supports "
            f"(up to {CURRENT_SCHEMA_VERSION}); update the skill or downgrade the manifest"
        )

    while v < CURRENT_SCHEMA_VERSION:
        migrator = SCHEMA_MIGRATORS.get(v)
        if migrator is None:
            raise SchemaMigrationError(
                f"schema_version {v}: no migrator registered to upgrade to "
                f"{v + 1}"
            )
        raw = migrator(raw)
        new_v = int(raw.get("schema_version", -1))
        if new_v <= v:
            raise SchemaMigrationError(
                f"migrator for schema_version {v} did not advance version "
                f"(got {new_v})"
            )
        v = new_v
    return raw


def load_manifest(path: str | Path, strict: bool = False) -> Manifest:
    """Parse a manifest JSON file into a Manifest dataclass.

    Older manifests are transparently migrated up to CURRENT_SCHEMA_VERSION
    via SCHEMA_MIGRATORS before parsing. If `strict` is True, call validate()
    and raise on any error.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data = _migrate_to_current(data)
    m = Manifest(
        game=data["game"],
        schema_version=int(data["schema_version"]),
        sprites=tuple(_parse_sprite(s) for s in data.get("sprites", [])),
        sounds=tuple(_parse_sound(s) for s in data.get("sounds", [])),
    )
    if strict:
        errors = validate(m)
        if errors:
            raise ValidationError("\n".join(errors))
    return m


def validate(m: Manifest) -> list[str]:
    """Return a list of human-readable error messages. Empty list = valid."""
    errors: list[str] = []

    if m.schema_version != CURRENT_SCHEMA_VERSION:
        errors.append(
            f"schema_version: unsupported value {m.schema_version!r} "
            f"(expected {CURRENT_SCHEMA_VERSION}); migration should have handled this"
        )

    sprite_names: list[str] = []
    anim_frames: dict[str, list[tuple[int, str]]] = {}

    for s in m.sprites:
        sprite_names.append(s.name)

        if not NAME_RE.match(s.name):
            errors.append(
                f"sprite {s.name!r}: name must match [a-z0-9_]+"
            )
        if s.name in RESERVED_NAMES:
            errors.append(f"sprite {s.name!r}: reserved name")

        w, h = s.size
        if not (1 <= w <= SPRITE_MAX_SIDE) or not (1 <= h <= SPRITE_MAX_SIDE):
            errors.append(
                f"sprite {s.name!r}: size {s.size} out of range "
                f"(must be 1..{SPRITE_MAX_SIDE} per axis)"
            )

        if (s.anim is None) != (s.frame is None):
            errors.append(
                f"sprite {s.name!r}: anim and frame must be set together"
            )
        if s.anim is not None:
            # Enforce two-digit frame range: 00..99 only.
            if not (ANIM_FRAME_MIN <= s.frame <= ANIM_FRAME_MAX):
                errors.append(
                    f"sprite {s.name!r}: frame {s.frame} out of range "
                    f"({ANIM_FRAME_MIN}..{ANIM_FRAME_MAX}); two-digit suffix required"
                )
            anim_frames.setdefault(s.anim, []).append((s.frame, s.name))

    seen: set[str] = set()
    for n in sprite_names:
        if n in seen:
            errors.append(f"sprite {n!r}: duplicate name")
        seen.add(n)

    for anim, members in anim_frames.items():
        frames = sorted(f for f, _ in members)
        if frames[0] != 0:
            errors.append(
                f"anim {anim!r}: sequence must start at frame 0 "
                f"(named _00 in file) — found first frame {frames[0]}"
            )
        if frames != list(range(frames[0], frames[-1] + 1)):
            errors.append(
                f"anim {anim!r}: frames must be contiguous, found {frames}"
            )
        for f, n in members:
            expected = f"{anim}_{f:02d}"
            if n != expected:
                errors.append(
                    f"anim {anim!r} frame {f}: expected name {expected!r}, got {n!r}"
                )

    sound_names: list[str] = []
    for snd in m.sounds:
        sound_names.append(snd.name)

        if not NAME_RE.match(snd.name):
            errors.append(f"sound {snd.name!r}: name must match [a-z0-9_]+")
        if snd.name in RESERVED_NAMES:
            errors.append(f"sound {snd.name!r}: reserved name")

        if snd.duration_ms <= 0 or snd.duration_ms > SOUND_MAX_DURATION_MS:
            errors.append(
                f"sound {snd.name!r}: duration_ms {snd.duration_ms} "
                f"out of range (1..{SOUND_MAX_DURATION_MS})"
            )
        if snd.event_type is not None and snd.event_type not in ALLOWED_EVENT_TYPES:
            errors.append(
                f"sound {snd.name!r}: unknown event_type {snd.event_type!r} "
                f"(allowed: {sorted(ALLOWED_EVENT_TYPES)})"
            )

    seen = set()
    for n in sound_names:
        if n in seen:
            errors.append(f"sound {n!r}: duplicate name")
        seen.add(n)

    return errors
