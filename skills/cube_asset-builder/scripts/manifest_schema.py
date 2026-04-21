"""Load and validate plans/<game>_assets.json (schema_version 1)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9_]+$")
RESERVED_NAMES = frozenset({
    "pal", "0", "icon",
    "bmp_none", "bmp_last", "bmp_0",
    "map_none", "map_last",
})
SPRITE_MAX_SIDE = 240
SOUND_MAX_DURATION_MS = 2000
SOUND_DEFAULT_DURATION_MS = 500
ALLOWED_EVENT_TYPES = frozenset({
    "pickup", "hit", "ui", "ambient", "music", "default",
})


class ValidationError(Exception):
    """Raised only when load_manifest is asked to enforce via `strict=True`."""


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


@dataclass(frozen=True)
class Sound:
    name: str
    description: str
    duration_ms: int = SOUND_DEFAULT_DURATION_MS
    event_type: str | None = None
    group: str | None = None


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


def load_manifest(path: str | Path, strict: bool = False) -> Manifest:
    """Parse a manifest JSON file into a Manifest dataclass.

    If `strict` is True, call validate() and raise on any error.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
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

    if m.schema_version != 1:
        errors.append(f"schema_version: unsupported value {m.schema_version!r} (expected 1)")

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
