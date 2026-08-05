"""Load and validate plans/<game>_assets.json (schema_version 1).

Sprites come in three complexity tiers, selected by the per-sprite `color`
field plus `flags.fullsize`:

- Palette 120 (default, cheapest): `color: "palette"`, quantized-palette
  sprites, index 0 is transparent. Authored at HALF resolution; the engine
  upscales x2 at draw time, so the on-screen size is 2x the authored size.
  Max authored side is 120.
- Palette fullsize (middle): `color: "palette"` + `flags.fullsize`. Still
  palette-encoded, and transparency via index 0 is KEPT, but the sprite
  draws 1:1 (no 2x upscale), so it is authored at native resolution, up to
  240 per side. This is the same mode the engine's fonts use.
- Full-color fullsize (max): `color: "full"` + `flags.fullsize`. RAW565
  (RGB565, 2 bytes/texel), no palette and no transparency -- 0x0000 is
  opaque black, not transparent -- so `flags.alpha` must not be set on any
  full-color sprite. Draws 1:1 at native resolution, up to 240 per side.

`flags.fullsize` lifts the 120 cap to 240 for ANY color (the engine draws
every FULLSIZE sprite at zoom 1); the alpha ban is full-color-only. A
sprite without `flags.fullsize` -- palette or full-color -- draws at 2x
and is capped at 120.

Full-color sprites additionally accept `dither: true` -- Floyd-Steinberg
error diffusion to the RGB565 lattice during conversion (before the
lossless RLE encode). Recommended for photographic art with smooth
gradients; meaningless for palette sprites, which are quantized by the
palette codec instead, so dither+palette is a validation error.
"""
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
# Sprites are authored at HALF resolution; the engine upscales them x2 at draw
# time, so the on-screen size is 2x the authored size. A full-screen sprite is
# authored at 120x120 (-> 240x240 on screen), which is the hard maximum.
# This cap applies to every sprite WITHOUT flags.fullsize, regardless of
# color -- see SPRITE_MAX_SIDE_FULLSIZE.
SPRITE_MAX_SIDE = 120
# flags.fullsize sprites (any color) draw 1:1 (no 2x upscale), so fullsize
# art is authored at native resolution, up to 240.
SPRITE_MAX_SIDE_FULLSIZE = 240
ALLOWED_SPRITE_COLORS = frozenset({"palette", "full"})
# Launcher icon (optional top-level `icon` object). Same three tiers as
# sprites, but the icon is standalone: a palette icon gets its OWN dedicated
# .pal record instead of joining the shared sprite palette groups.
#   - palette + side 120: cheap; engine upscales x2 -> 240 on screen
#   - palette + side 240: FULLSIZE, draws 1:1
#   - full (default) + side 1..240: RAW565, FULLSIZE, optional dither
# Palette icons only ship in the two device-proven shapes (120 / 240).
ALLOWED_ICON_COLORS = frozenset({"palette", "full"})
ICON_DEFAULT_SIDE = 160
ICON_MAX_SIDE = 240
ICON_PALETTE_SIDES = (120, 240)
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
    gen_prompt: str | None = None
    group: str | None = None
    anim: str | None = None
    frame: int | None = None
    pivot: tuple[int, int] = (0, 0)
    flags: Flags = field(default_factory=Flags)
    color: str = "palette"
    dither: bool = False


@dataclass(frozen=True)
class Sound:
    name: str
    description: str
    duration_ms: int = SOUND_DEFAULT_DURATION_MS
    event_type: str | None = None
    group: str | None = None


@dataclass(frozen=True)
class Icon:
    """Launcher-icon art tier. Defaults preserve the pre-tier behaviour
    exactly: full-color RAW565 at 160x160, no dither."""
    color: str = "full"
    side: int = ICON_DEFAULT_SIDE
    dither: bool = False


@dataclass(frozen=True)
class Manifest:
    game: str
    schema_version: int
    sprites: tuple[Sprite, ...]
    sounds: tuple[Sound, ...]
    icon: Icon | None = None


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
        gen_prompt=raw.get("gen_prompt"),
        group=raw.get("group"),
        anim=raw.get("anim"),
        frame=raw.get("frame"),
        pivot=(int(pivot[0]), int(pivot[1])),
        flags=_parse_flags(raw.get("flags")),
        color=raw.get("color", "palette"),
        dither=bool(raw.get("dither", False)),
    )


def _parse_icon(raw: dict | None) -> Icon | None:
    if raw is None:
        return None
    return Icon(
        color=raw.get("color", "full"),
        side=int(raw.get("side", ICON_DEFAULT_SIDE)),
        dither=bool(raw.get("dither", False)),
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
        icon=_parse_icon(data.get("icon")),
    )
    if strict:
        errors = validate(m)
        if errors:
            raise ValidationError("\n".join(errors))
    return m


def validate_icon(icon: Icon) -> list[str]:
    """Validate one launcher-icon config. Empty list = valid.

    Shared by validate() (manifest `icon` object) and pack.py (the icon
    config after --icon-color/--icon-side/--icon-dither overrides, which can
    produce combinations no manifest ever held).
    """
    errors: list[str] = []

    if icon.color not in ALLOWED_ICON_COLORS:
        errors.append(
            f"icon: color {icon.color!r} invalid "
            f"(allowed: {sorted(ALLOWED_ICON_COLORS)})"
        )
        return errors   # the remaining checks are per-color

    if icon.color == "palette":
        if icon.dither:
            errors.append(
                "icon: dither is only for color 'full' icons (Floyd-Steinberg "
                "dithering to the RGB565 lattice) -- a palette icon is "
                "quantized by the palette codec instead, so drop dither or "
                "set color 'full'"
            )
        if icon.side not in ICON_PALETTE_SIDES:
            errors.append(
                f"icon: palette icons must be side 120 (engine upscales x2 -> "
                f"240 on screen) or 240 (fullsize, draws 1:1) -- side "
                f"{icon.side} is not one of the proven shapes; use 120 or "
                f"240, or color 'full' for arbitrary sides up to "
                f"{ICON_MAX_SIDE}"
            )
    else:  # full
        if not (1 <= icon.side <= ICON_MAX_SIDE):
            errors.append(
                f"icon: side {icon.side} out of range "
                f"(full-color icons allow 1..{ICON_MAX_SIDE})"
            )

    return errors


def validate(m: Manifest) -> list[str]:
    """Return a list of human-readable error messages. Empty list = valid."""
    errors: list[str] = []

    if m.icon is not None:
        errors.extend(validate_icon(m.icon))

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

        if s.color not in ALLOWED_SPRITE_COLORS:
            errors.append(
                f"sprite {s.name!r}: color {s.color!r} invalid "
                f"(allowed: {sorted(ALLOWED_SPRITE_COLORS)})"
            )

        if s.color == "full" and s.flags.alpha:
            errors.append(
                f"sprite {s.name!r}: color 'full' (RAW565) sprites have no "
                f"transparency (0x0000 is opaque black, not transparent) -- "
                f"clear flags.alpha, or use color 'palette' for transparency"
            )

        if s.dither and s.color != "full":
            errors.append(
                f"sprite {s.name!r}: dither is only for color 'full' sprites "
                f"(Floyd-Steinberg dithering to the RGB565 lattice) -- "
                f"palette sprites are quantized by the palette codec instead, "
                f"so drop dither or set color 'full'"
            )

        w, h = s.size
        is_native_fullsize = s.flags.fullsize
        max_side = SPRITE_MAX_SIDE_FULLSIZE if is_native_fullsize else SPRITE_MAX_SIDE
        if not (1 <= w <= max_side) or not (1 <= h <= max_side):
            if not s.flags.fullsize and (
                w > SPRITE_MAX_SIDE or h > SPRITE_MAX_SIDE
            ):
                errors.append(
                    f"sprite {s.name!r}: size {s.size} out of range -- "
                    f"sides over {SPRITE_MAX_SIDE} need flags.fullsize "
                    f"(draws 1:1, works for any color)"
                )
            else:
                errors.append(
                    f"sprite {s.name!r}: size {s.size} out of range "
                    f"(must be 1..{max_side} per axis)"
                )

        if s.gen_prompt is not None and not (
            isinstance(s.gen_prompt, str) and s.gen_prompt.strip()
        ):
            errors.append(
                f"sprite {s.name!r}: gen_prompt, when present, must be a "
                f"non-empty string"
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
        if frames[0] not in (0, 1):
            errors.append(
                f"anim {anim!r}: sequence must start at frame 0 or 1 "
                f"(named _00../_01.. in file) — found first frame {frames[0]}"
            )
        if frames != list(range(frames[0], frames[-1] + 1)):
            errors.append(
                f"anim {anim!r}: frames must be contiguous, found {frames}"
            )

        # Name must be "<anim>_<digits>" with the digits parsing back to the
        # declared frame number, using 2 or more digits — the packer's
        # _seq_frame_groups (pack_beta.py) only recognizes a 2+ digit _NN..
        # suffix as an animation frame, so a shorter or malformed suffix
        # would silently fail to chain at pack time even though it validates
        # here otherwise. Width (2-digit vs 3-digit) must stay consistent
        # across the whole sequence.
        name_re = re.compile(rf"^{re.escape(anim)}_(\d{{2,}})$")
        widths: set[int] = set()
        for f, n in members:
            name_match = name_re.match(n)
            if not name_match or int(name_match.group(1)) != f:
                errors.append(
                    f"anim {anim!r} frame {f}: name {n!r} must be "
                    f"'{anim}_' followed by the frame number zero-padded "
                    f"to 2 or more digits (e.g. {anim}_{f:02d}) — the "
                    f"packer only chains frame suffixes of 2+ digits"
                )
                continue
            widths.add(len(name_match.group(1)))
        if len(widths) > 1:
            errors.append(
                f"anim {anim!r}: frame suffix digit width must be "
                f"consistent across the sequence, found widths {sorted(widths)}"
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
