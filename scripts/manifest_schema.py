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

# An asset name is used verbatim everywhere downstream: the file name in
# art/packed and sound/assets, the index.bin record (looked up by exact name,
# e.g. SND_getAssetId("catch")) and the BMP_/MAP_/SND_ enum member. It must
# start with a letter: a digit-leading sound used to be renamed ("1up" ->
# "s_1up") by the mp3 encoder, which silently broke the exact-name lookup.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NAME_RULE = "[a-z][a-z0-9_]* (lowercase letters, digits, underscores; starts with a letter)"
# octavios index.bin stores names in char[24] incl. the NUL -> 23 usable chars
# (pack_beta.ASSET_NAME_MAXLEN). Checked here so a long name fails BEFORE
# generation, not after it at pack time.
ASSET_NAME_MAX_CHARS = 23
RESERVED_NAMES = frozenset({
    # legacy packer: palette strip, placeholder sprite, launcher icon file
    "pal", "0", "icon",
    "bmp_none", "bmp_last", "bmp_0",
    "map_none", "map_last",
    # sentinels of the generated ids header (BMP_none/BMP_last, MAP_none/
    # MAP_last, SND_none/SND_last): a sprite or sound named "none"/"last"
    # duplicates one of them
    "none", "last",
    # records pack_beta.emit_beta_layout generates itself: the reserved
    # slot-0 sprite, the launcher icon sprite and the launcher maps the
    # engine looks up by name (they share art/packed/<name>.raw with sprites)
    "zero", "ico", "ico_idle", "ahover",
})
# BMFont glyph sprites the packer generates from art/font_*.fnt:
# "<font stem>_<glyph id, 5 digits>" (pack_psd.export_font_python).
GLYPH_NAME_RE = re.compile(r"^font_[a-z0-9_]*_\d{5}$")
# Animation sequences, exactly as the packer finds them
# (pack_beta._seq_frame_groups): "<base>_<2+ digits>", a sequence counts when
# its lowest frame is 0 or 1. Each one adds the ids-header aliases
# BMP_<base> (first frame) and BMP_<base>_end (last frame).
_SEQ_FRAME_RE = re.compile(r"^(.+?)_(\d{2,})$")
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
# The engine streams sounds through a small window (octavios dev, 2026-09):
# no 2 s / 64 KB cap any more, music beds and long loops are fine. The bound
# below only catches typos (a 10-minute ceiling).
SOUND_MAX_DURATION_MS = 600_000
SOUND_DEFAULT_DURATION_MS = 500
ALLOWED_EVENT_TYPES = frozenset({
    "pickup", "hit", "ui", "ambient", "music", "default",
    "shoot", "spawn", "attack", "hurt", "death", "win", "lose", "jump",
    "step", "explode", "voice", "alert", "transition",
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
    background: str | None = None   # "key" (cut-out on a chroma-key backdrop) | "opaque" (full-canvas picture)


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
        background=raw.get("background"),
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


def parse_manifest(data: dict) -> Manifest:
    """A manifest dict (already read from JSON) -> Manifest. No validation."""
    return Manifest(
        game=data["game"],
        schema_version=int(data["schema_version"]),
        sprites=tuple(_parse_sprite(s) for s in data.get("sprites", [])),
        sounds=tuple(_parse_sound(s) for s in data.get("sounds", [])),
        icon=_parse_icon(data.get("icon")),
    )


def load_manifest(path: str | Path, strict: bool = False) -> Manifest:
    """Parse a manifest JSON file into a Manifest dataclass.

    If `strict` is True, call validate() and raise on any error.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    m = parse_manifest(data)
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


def sequence_aliases(names) -> dict[str, str]:
    """{alias name: animation base} for every BMP_<base> / BMP_<base>_end
    alias the packer adds to the ids header (mirrors
    pack_beta._seq_frame_groups + generate_beta_ids_h)."""
    groups: dict[str, list[int]] = {}
    for name in names:
        m = _SEQ_FRAME_RE.match(name)
        if m:
            groups.setdefault(m.group(1), []).append(int(m.group(2)))
    out: dict[str, str] = {}
    for base, frames in groups.items():
        if min(frames) in (0, 1):
            out[base] = base
            out[f"{base}_end"] = base
    return out


def _name_errors(kind: str, name: str) -> list[str]:
    """Name rules shared by sprites and sounds."""
    errors: list[str] = []
    if not NAME_RE.match(name):
        errors.append(f"{kind} {name!r}: name must match {NAME_RULE}")
    if len(name) > ASSET_NAME_MAX_CHARS:
        errors.append(
            f"{kind} {name!r}: name longer than {ASSET_NAME_MAX_CHARS} chars "
            f"(octavios asset names are char[24] incl. NUL)"
        )
    if name in RESERVED_NAMES:
        errors.append(
            f"{kind} {name!r}: reserved name (the packer generates it or the "
            f"ids header uses it: {', '.join(sorted(RESERVED_NAMES))})"
        )
    elif GLYPH_NAME_RE.match(name):
        errors.append(
            f"{kind} {name!r}: reserved name pattern - the packer names BMFont "
            f"glyph sprites <font>_<glyph id, 5 digits>"
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

        errors.extend(_name_errors("sprite", s.name))
        if s.background is not None and s.background not in ("key", "opaque"):
            errors.append(f"sprite {s.name!r}: background must be \"key\" (cut-out drawn on a chroma-key "
                          f"backdrop) or \"opaque\" (full-canvas picture), got {s.background!r}")

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

    # A sprite named like an animation alias (BMP_<base> = first frame,
    # BMP_<base>_end = last frame) duplicates that enum member and the pack
    # fails in generate_beta_ids_h - catch it before anything is generated.
    aliases = sequence_aliases(sprite_names)
    for n in sorted(seen & set(aliases)):
        errors.append(
            f"sprite {n!r}: collides with the ids-header alias BMP_{n} of the "
            f"animation {aliases[n]!r} ({aliases[n]}_00.. frames get BMP_{aliases[n]} "
            f"and BMP_{aliases[n]}_end) - rename the sprite"
        )

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

        errors.extend(_name_errors("sound", snd.name))

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


# ─────────────────────────────────────────────────────────────────────────────
# Provider-free pipeline gate: `build_pipeline.py validate --manifest M`.
# Everything validate() checks, plus the rules Stage 2 writes and Stage 3
# depends on (background field, launcher_icon, the Codex prompt rules that a
# regex can check, _panoramas pieces). Reads one JSON file; never generates,
# never starts a subprocess, never touches the network.
# ─────────────────────────────────────────────────────────────────────────────

LAUNCHER_ICON_NAME = "launcher_icon"
STYLE_WORDS = (60, 120)

_RE_TRANSPARENT_BG = re.compile(
    r"\btransparent\s+(?:background|backdrop|bg)\b"
    r"|\b(?:background|backdrop|bg)\s+(?:is\s+|must\s+be\s+|should\s+be\s+)?transparent\b"
    r"|\balpha\s+channel\b", re.I)
_RE_TRANSPARENT = re.compile(r"\btranspar(?:ent|ency)\b", re.I)
_RE_EXACT_SIZE = re.compile(r"\b(?:exactly|precisely)\s+\d+\s*(?:[x×]\s*\d+)?", re.I)
_RE_WXH_PIXELS = re.compile(r"\b\d+\s*[x×]\s*\d+\s*(?:px|pixels?)\b", re.I)
_RE_PIXELS = re.compile(r"\b\d+\s*(?:px|pixels?)\b", re.I)
_RE_MAGENTA_KEY = re.compile(r"#\s*ff00ff\b|\bmagenta\s+(?:background|backdrop|bg)\b", re.I)
_RE_BACKDROP_COLOUR = re.compile(
    r"\b(?:white|black|grey|gray|green|blue|pink|magenta|solid|plain|flat|uniform|chroma[- ]?key|green[- ]?screen)"
    r"\s+(?:background|backdrop|bg)\b", re.I)


def _norm_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _copies_style(prompt: str, style: str, window: int = 8) -> bool:
    """True when `prompt` repeats `window` consecutive words of the _style paragraph."""
    sw = _norm_words(style)
    if len(sw) < window:
        return False
    text = " " + " ".join(_norm_words(prompt)) + " "
    return any(" " + " ".join(sw[i:i + window]) + " " in text for i in range(len(sw) - window + 1))


def prompt_findings(where: str, prompt: str, *, size: tuple[int, int] | None,
                    keyed: bool, style: str = "") -> tuple[list[str], list[str]]:
    """Codex prompt rules a regex can check (technical_prompter Step 4a,
    cube_art-director art_codex.build_prompt). Returns (errors, warnings).

    Errors: the rules that break generation every time - asking for a
    transparent background (the model cannot draw one; art.py asks for a flat
    key backdrop and keys it), pixel sizes (the model draws a 1024x1024
    canvas; fitting to `size` is processing), the magenta key colour in the
    prompt (art.py picks and records the key itself), the _style paragraph
    pasted into the prompt (art.py prepends it). Warnings: likely mistakes a
    regex cannot be sure about."""
    errors: list[str] = []
    warnings: list[str] = []
    if _RE_TRANSPARENT_BG.search(prompt):
        errors.append(f"{where}: gen_prompt asks for a transparent background - the model cannot draw "
                      f"transparency; drop it (background \"key\" makes art.py draw a flat key backdrop and key it)")
    elif _RE_TRANSPARENT.search(prompt):
        warnings.append(f"{where}: gen_prompt says 'transparent' - the model cannot draw transparency; describe "
                        f"see-through parts as dark or solid")
    own = None
    if size is not None:
        w, h = size
        own = re.compile(rf"\b{w}\s*[x×]\s*{h}\b", re.I)
    if _RE_EXACT_SIZE.search(prompt) or _RE_WXH_PIXELS.search(prompt) or (own and own.search(prompt)):
        errors.append(f"{where}: gen_prompt states a pixel size - the model draws a 1024x1024 canvas and "
                      f"processing fits it to `size`; describe proportions instead (\"a long bar, about 3:1\")")
    elif _RE_PIXELS.search(prompt):
        warnings.append(f"{where}: gen_prompt mentions pixels - pixel measures mean nothing on the 1024x1024 "
                        f"canvas; describe thickness/size relative to the subject")
    if keyed:
        if _RE_MAGENTA_KEY.search(prompt):
            errors.append(f"{where}: gen_prompt names the magenta key backdrop - art.py adds the backdrop "
                          f"itself (only #00FF00 may be written, to force a green key on a pink subject)")
        elif "#00ff00" not in prompt.lower() and _RE_BACKDROP_COLOUR.search(prompt):
            warnings.append(f"{where}: gen_prompt seems to set a backdrop colour - for background \"key\" "
                            f"art.py adds the flat key backdrop itself")
    if style and _copies_style(prompt, style):
        errors.append(f"{where}: gen_prompt repeats the _style paragraph - write the style once in `_style` "
                      f"(art.py puts it in front of every prompt)")
    return errors, warnings


def _structure_errors(data) -> list[str]:
    """Shape checks that keep parse_manifest from crashing on a broken file."""
    if not isinstance(data, dict):
        return ["manifest: top level must be a JSON object"]
    errors: list[str] = []
    if not isinstance(data.get("game"), str) or not data.get("game"):
        errors.append("manifest: `game` (non-empty string) is required")
    sv = data.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, (int, str)) or not str(sv).strip().lstrip("-").isdigit():
        errors.append("manifest: `schema_version` (integer, 1) is required")

    def _ints(v, n):
        return (isinstance(v, (list, tuple)) and len(v) == n
                and all(isinstance(x, int) and not isinstance(x, bool) for x in v))

    for key, required in (("sprites", ("name", "size", "description")), ("sounds", ("name", "description"))):
        items = data.get(key, [])
        if not isinstance(items, list):
            errors.append(f"manifest: `{key}` must be a list")
            continue
        for i, item in enumerate(items):
            label = f"{key}[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{label}: must be an object")
                continue
            if isinstance(item.get("name"), str):
                label = f"{key[:-1]} {item['name']!r}"
            for field_name in required:
                if field_name not in item:
                    errors.append(f"{label}: missing required field `{field_name}`")
            if not isinstance(item.get("name", ""), str):
                errors.append(f"{label}: `name` must be a string")
            if not isinstance(item.get("description", ""), str):
                errors.append(f"{label}: `description` must be a string")
            if key == "sprites":
                if "size" in item and not _ints(item["size"], 2):
                    errors.append(f"{label}: `size` must be [width, height] (two integers)")
                if item.get("pivot") is not None and not _ints(item["pivot"], 2):
                    errors.append(f"{label}: `pivot` must be [x, y] (two integers)")
                if item.get("flags") is not None and not isinstance(item["flags"], dict):
                    errors.append(f"{label}: `flags` must be an object")
                if item.get("frame") is not None and (isinstance(item["frame"], bool)
                                                      or not isinstance(item["frame"], int)):
                    errors.append(f"{label}: `frame` must be an integer")
            elif "duration_ms" in item and (isinstance(item["duration_ms"], bool)
                                            or not isinstance(item["duration_ms"], (int, float))):
                errors.append(f"{label}: `duration_ms` must be a number")
    if data.get("icon") is not None and not isinstance(data["icon"], dict):
        errors.append("manifest: `icon` must be an object")
    return errors


def pipeline_findings(data: dict, m: Manifest) -> tuple[list[str], list[str]]:
    """Stage 2 -> Stage 3 rules beyond validate(). Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    style = data.get("_style") if isinstance(data.get("_style"), str) else ""
    if not style.strip():
        warnings.append("_style: missing - Stage 3 writes it into style/STYLE.md as the prompt block every "
                        "generation starts with")
    else:
        n = len(style.split())
        if not (STYLE_WORDS[0] <= n <= STYLE_WORDS[1]):
            warnings.append(f"_style: {n} words (Stage 2 writes {STYLE_WORDS[0]}-{STYLE_WORDS[1]})")

    names = {s.name for s in m.sprites}
    for s in m.sprites:
        where = f"sprite {s.name!r}"
        if s.background is None:
            errors.append(f"{where}: `background` is missing - \"key\" (cut-out: characters, props, effects, UI) "
                          f"or \"opaque\" (full-canvas picture: backgrounds, tiles, panorama pieces); without it "
                          f"art.py guesses and keys pictures or leaves cut-outs boxed")
        if not (isinstance(s.gen_prompt, str) and s.gen_prompt.strip()):
            if s.gen_prompt is None:
                errors.append(f"{where}: `gen_prompt` is missing - every sprite needs one (art.py refuses a "
                              f"manifest with a prompt-less sprite)")
            continue                         # an empty one is already a validate() error
        e, w = prompt_findings(where, s.gen_prompt, size=s.size, keyed=s.background == "key", style=style)
        errors += e
        warnings += w

    icon = next((s for s in m.sprites if s.name == LAUNCHER_ICON_NAME), None)
    if icon is None:
        errors.append(f"sprite {LAUNCHER_ICON_NAME!r} is missing - the launcher badge in the game's style "
                      f"(flat-top hexagon, transparent corners); Stage 3 copies it to app_<game>/art/icon.png")
    else:
        if icon.size[0] != icon.size[1]:
            errors.append(f"sprite {LAUNCHER_ICON_NAME!r}: size {list(icon.size)} must be square (the packer "
                          f"centre-crops the icon to a square)")
        if icon.background != "key":
            warnings.append(f"sprite {LAUNCHER_ICON_NAME!r}: background should be \"key\" (the badge needs "
                            f"transparent corners)")
        if icon.color == "full":
            warnings.append(f"sprite {LAUNCHER_ICON_NAME!r}: color \"full\" has no transparency - the corners "
                            f"cannot be transparent")

    panoramas = data.get("_panoramas")
    if panoramas is not None and not isinstance(panoramas, dict):
        errors.append("_panoramas: must be an object {name: {size, grid: [cols, rows], pieces, gen_prompt}}")
        panoramas = {}
    for pname, pano in (panoramas or {}).items():
        where = f"_panoramas.{pname}"
        if not isinstance(pano, dict):
            errors.append(f"{where}: must be an object")
            continue
        pieces = pano.get("pieces")
        if not isinstance(pieces, list) or not pieces:
            errors.append(f"{where}: `pieces` (list of sprite names) is required")
            pieces = []
        for piece in pieces:
            if piece not in names:
                errors.append(f"{where}: piece {piece!r} is not a sprite in the manifest")
        grid = pano.get("grid")
        if (isinstance(grid, list) and len(grid) == 2
                and all(isinstance(g, int) and not isinstance(g, bool) and g > 0 for g in grid)):
            cols, rows = grid                  # [cols, rows], as Stage 3 splits it (ART.md "Panoramas")
            if pieces and cols * rows != len(pieces):
                errors.append(f"{where}: grid [cols, rows] = {grid} needs {cols * rows} pieces, found {len(pieces)}")
            else:
                # pieces named <pano>_r<row>c<col> (the prompter's convention) must agree with the order and
                # be listed row-major: a [rows, cols] grid would be cut into the wrong shape
                cells = [re.search(r"_r(\d+)c(\d+)$", str(p)) for p in pieces]
                if pieces and all(cells):
                    rc = [(int(c.group(1)), int(c.group(2))) for c in cells]
                    n_rows, n_cols = max(r for r, _ in rc) + 1, max(c for _, c in rc) + 1
                    if (n_cols, n_rows) != (cols, rows):
                        errors.append(f"{where}: grid is [cols, rows] = {grid}, but the piece names "
                                      f"(_r<row>c<col>) make it [{n_cols}, {n_rows}]")
                    elif rc != sorted(rc) or len(set(rc)) != len(rc):
                        errors.append(f"{where}: pieces must be listed row-major (r0c0, r0c1, ..., r1c0, ...) "
                                      f"without repeats")
        else:
            errors.append(f"{where}: `grid` must be [cols, rows] (two positive integers)")
        prompt = pano.get("gen_prompt")
        if not (isinstance(prompt, str) and prompt.strip()):
            errors.append(f"{where}: `gen_prompt` (the whole picture) is required")
        else:
            size = pano.get("size")
            size = tuple(size) if isinstance(size, list) and len(size) == 2 else None
            e, w = prompt_findings(where, prompt, size=size, keyed=False, style=style)
            errors += e
            warnings += w
    return errors, warnings


def check_manifest_file(path: str | Path) -> tuple[list[str], list[str], Manifest | None]:
    """The whole provider-free check of one manifest file: JSON, structure,
    validate(), pipeline_findings(). Returns (errors, warnings, manifest or
    None when it could not be parsed)."""
    path = Path(path)
    if not path.is_file():
        return [f"manifest not found: {path}"], [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [f"{path}: not readable JSON ({exc})"], [], None
    errors = _structure_errors(data)
    if errors:
        return errors, [], None
    try:
        m = parse_manifest(data)
    except (KeyError, TypeError, ValueError) as exc:
        return [f"{path}: cannot parse ({exc!r})"], [], None
    errors = validate(m)
    more, warnings = pipeline_findings(data, m)
    return errors + more, warnings, m
