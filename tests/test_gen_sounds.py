"""Tests for gen_sounds.py — pure-Python WAV synthesis, no external encoder."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from manifest_schema import load_manifest
import gen_sounds
from gen_sounds import (
    FFMPEG_MISSING_MSG, encode_beta_mp3, generate, render_wav_bytes,
    resolve_sound_asset_names, sound_asset_name, sound_asset_name_problem,
)


# ── Sound asset names: SND_<name> must be a legal C identifier ────────
#
# The 11 WAV sources of the reference corpus (OCT_get_started) and the asset
# names the legacy toolchain shipped for them in sound/assets/*.mp3. This is
# the ground truth the rule has to reproduce.
CORPUS_SOUND_NAMES = {
    "Congratulations-007":   "congratulations_007",
    "Pat_double1_500ms":     "pat_double1_500ms",
    "StageCongratulations":  "stagecongratulations",
    "StageGreetings":        "stagegreetings",
    "StagePairing":          "stagepairing",
    "SuccessHalfTwist":      "successhalftwist",
    "SuccessSelector":       "successselector",
    "WrongAction":           "wrongaction",
    "eyes_appear":           "eyes_appear",
    "eyes_blink":            "eyes_blink",
    "selector":              "selector",
}


@pytest.mark.parametrize("stem,expected", sorted(CORPUS_SOUND_NAMES.items()))
def test_sound_asset_name_reproduces_corpus_names(stem, expected):
    assert sound_asset_name(stem) == expected


def test_corpus_names_are_all_legal_identifiers():
    for asset in CORPUS_SOUND_NAMES.values():
        assert sound_asset_name_problem(asset) is None


def test_sound_asset_name_prefixes_leading_digit():
    assert sound_asset_name("007intro") == "s_007intro"
    assert sound_asset_name("3-2-1 go") == "s_3_2_1_go"


def test_sound_asset_name_is_idempotent():
    for stem in CORPUS_SOUND_NAMES:
        once = sound_asset_name(stem)
        assert sound_asset_name(once) == once
    assert sound_asset_name(sound_asset_name("007intro")) == "s_007intro"


def test_sound_asset_name_empty_falls_back():
    assert sound_asset_name("") == "sound"
    assert sound_asset_name("!!!") == "___"


def test_sound_asset_name_strips_non_ascii():
    # isalnum() is Unicode-aware ("é".isalnum() is True), so the normaliser
    # must also require isascii() or non-ASCII letters leak straight through
    # into a SND_<name> enum member the C compiler can't tokenise.
    result = gen_sounds.sound_asset_name("café")
    assert re.match(r"^[a-z_][a-z0-9_]*$", result)
    assert result == "caf_"


@pytest.mark.parametrize("stem,fragment", [
    ("", "empty name"),
    ("Congratulations-007", "illegal character"),
    ("007intro", "starts with a digit"),
    ("café", "illegal character"),
])
def test_sound_asset_name_problem_explains(stem, fragment):
    why = sound_asset_name_problem(stem)
    assert why is not None and fragment in why


def test_sound_asset_name_problem_accepts_legal_name():
    assert sound_asset_name_problem("eyes_blink") is None


def test_resolve_sound_asset_names_maps_the_corpus():
    assert resolve_sound_asset_names(CORPUS_SOUND_NAMES) == CORPUS_SOUND_NAMES


def test_resolve_sound_asset_names_rejects_collisions():
    with pytest.raises(ValueError, match=r"collide after name normalisation"):
        resolve_sound_asset_names(["Win-Fanfare", "win fanfare"])


def test_resolve_sound_asset_names_collision_message_names_the_sources():
    with pytest.raises(ValueError) as exc:
        resolve_sound_asset_names(["Win-Fanfare", "win fanfare", "other"])
    msg = str(exc.value)
    assert "Win-Fanfare" in msg and "win fanfare" in msg
    assert "win_fanfare" in msg
    assert "other" not in msg


# ── Pure-Python WAV synthesis (no ffmpeg) ─────────────────────────────

def test_render_wav_bytes_matches_duration():
    data = render_wav_bytes(
        group="ui", name="sfx", event_type="pickup", duration_ms=300,
    )
    rate = struct.unpack_from("<I", data, 24)[0]
    data_size = struct.unpack_from("<I", data, 40)[0]
    num_samples = data_size // 2
    assert abs(num_samples / rate * 1000 - 300) <= 10


def test_render_wav_bytes_deterministic():
    a = render_wav_bytes(group="ui", name="s", event_type="pickup", duration_ms=200)
    b = render_wav_bytes(group="ui", name="s", event_type="pickup", duration_ms=200)
    assert a == b


def test_render_wav_bytes_differs_for_different_events():
    a = render_wav_bytes(group="ui", name="s", event_type="pickup", duration_ms=200)
    b = render_wav_bytes(group="ui", name="s", event_type="hit", duration_ms=200)
    assert a != b


# ── End-to-end WAV output (no external encoder) ───────────────────────

def test_generate_writes_wav_per_sound(tmp_manifest, minimal_manifest, tmp_path):
    m = load_manifest(tmp_manifest(minimal_manifest))
    out = tmp_path / "wav"
    generate(m, out)
    assert (out / "sfx_coin.wav").exists()


def test_generate_wav_is_valid_riff(tmp_manifest, minimal_manifest, tmp_path):
    m = load_manifest(tmp_manifest(minimal_manifest))
    out = tmp_path / "wav"
    generate(m, out)
    head = (out / "sfx_coin.wav").read_bytes()[:12]
    assert head[:4] == b"RIFF" and head[8:12] == b"WAVE"


def test_generate_determinism_between_runs(tmp_manifest, minimal_manifest, tmp_path):
    m = load_manifest(tmp_manifest(minimal_manifest))
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate(m, a)
    generate(m, b)
    h1 = hashlib.md5((a / "sfx_coin.wav").read_bytes()).hexdigest()
    h2 = hashlib.md5((b / "sfx_coin.wav").read_bytes()).hexdigest()
    assert h1 == h2


def _write_test_wav(path: Path) -> Path:
    """Write a tiny synthesised WAV to `path` for encoder tests."""
    data = render_wav_bytes(group="ui", name="blip", event_type="ui", duration_ms=120)
    path.write_bytes(data)
    return path


# ── Beta mp3 encoding (22050 Hz mono CBR 32k, no Xing, no metadata) ───

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_encode_beta_mp3_writes_playable_mp3(tmp_path):
    wav = tmp_path / "blip.wav"
    _write_test_wav(wav)

    out = encode_beta_mp3(wav, tmp_path / "assets")

    assert out == tmp_path / "assets" / "blip.mp3"
    assert out.exists()
    assert out.stat().st_size > 0

    if shutil.which("ffprobe") is None:
        return
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert int(stream["sample_rate"]) == 22050
    assert int(stream["channels"]) == 1


def test_encode_beta_mp3_normalises_the_output_name(tmp_path, monkeypatch):
    """An artist's WAV name becomes a legal SND_ id at encode time."""
    wav = _write_test_wav(tmp_path / "Congratulations-007.wav")
    calls: list[list[str]] = []
    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(gen_sounds.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))

    out = encode_beta_mp3(wav, tmp_path / "assets")

    assert out == tmp_path / "assets" / "congratulations_007.mp3"
    assert calls and calls[0][-1] == str(out)


def test_encode_beta_mp3_leaves_a_legal_name_alone(tmp_path, monkeypatch):
    wav = _write_test_wav(tmp_path / "eyes_blink.wav")
    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(gen_sounds.subprocess, "run", lambda cmd, **kw: None)

    assert encode_beta_mp3(wav, tmp_path / "assets") == \
        tmp_path / "assets" / "eyes_blink.mp3"


def test_encode_beta_mp3_missing_ffmpeg_raises(tmp_path, monkeypatch):
    wav = tmp_path / "blip.wav"
    _write_test_wav(wav)

    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match=r"ffmpeg is required"):
        encode_beta_mp3(wav, tmp_path / "assets")


def test_generate_wav_only_does_not_require_ffmpeg(tmp_manifest, minimal_manifest, tmp_path, monkeypatch):
    """encode_mp3=False (the default) must never touch ffmpeg."""
    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: None)

    def _boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called when encode_mp3=False")
    monkeypatch.setattr(gen_sounds.subprocess, "run", _boom)

    m = load_manifest(tmp_manifest(minimal_manifest))
    out = tmp_path / "wav"
    written = generate(m, out)
    assert (out / "sfx_coin.wav").exists()
    assert written == [out / "sfx_coin.wav"]
    assert not (out / "assets").exists()


def test_generate_normalises_a_leading_digit_name(tmp_manifest, tmp_path):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [{"name": "007intro", "description": "b", "duration_ms": 150}],
    }
    m = load_manifest(tmp_manifest(data))
    out = tmp_path / "wav"
    written = generate(m, out)
    assert written == [out / "s_007intro.wav"]
    assert not (out / "007intro.wav").exists()


def test_generate_rejects_colliding_sound_names(tmp_manifest, tmp_path):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [
            {"name": "007go", "description": "b", "duration_ms": 150},
            {"name": "s_007go", "description": "b", "duration_ms": 150},
        ],
    }
    m = load_manifest(tmp_manifest(data))
    with pytest.raises(ValueError, match=r"collide after name normalisation"):
        generate(m, tmp_path / "wav")


def test_generate_group_filter(tmp_manifest, tmp_path):
    data = {
        "game": "demo", "schema_version": 1, "sprites": [],
        "sounds": [
            {"name": "sfx_coin", "description": "b", "duration_ms": 150, "group": "ui"},
            {"name": "sfx_hit", "description": "t", "duration_ms": 150, "group": "combat"},
        ],
    }
    m = load_manifest(tmp_manifest(data))
    out = tmp_path / "wav"
    generate(m, out)
    before = (out / "sfx_hit.wav").read_bytes()
    (out / "sfx_coin.wav").unlink()
    generate(m, out, group="ui")
    assert (out / "sfx_coin.wav").exists()
    assert (out / "sfx_hit.wav").read_bytes() == before


# ── pre-encoded mp3s committed in sound/ (not sound/assets/) ─────────────────
#
# OCT_ladybug's shape: twelve ready mp3s in sound/ itself, no WAV sources, no
# sound/assets/ at all - and twelve KIND_SOUND records in its legacy
# container. A build that only scans sound/assets/ ships a silent app whose
# every SND_getAssetId() returns -1.

LADYBUG_MP3S = ["berry_eaten", "berry_eaten2", "countdown", "game_over",
                "idle_001", "idle_002", "idle_003", "idle_004", "idle_005",
                "intro", "poison", "starting"]


def test_plan_mp3_adoption_covers_the_ladybug_set():
    from gen_sounds import plan_mp3_adoption
    plan = plan_mp3_adoption([Path(f"sound/{n}.mp3") for n in LADYBUG_MP3S])
    assert [asset for _src, asset in plan] == sorted(LADYBUG_MP3S)


def test_plan_mp3_adoption_normalises_the_asset_name():
    from gen_sounds import plan_mp3_adoption
    plan = plan_mp3_adoption([Path("sound/Win-Fanfare.mp3")])
    assert plan == [(Path("sound/Win-Fanfare.mp3"), "win_fanfare")]


def test_plan_mp3_adoption_rejects_colliding_sources():
    from gen_sounds import plan_mp3_adoption
    with pytest.raises(ValueError, match=r"collide after name normalisation"):
        plan_mp3_adoption([Path("a/Win-Fanfare.mp3"), Path("a/win fanfare.mp3")])


def test_plan_mp3_adoption_leaves_committed_assets_alone():
    from gen_sounds import plan_mp3_adoption
    plan = plan_mp3_adoption([Path("sound/intro.mp3"), Path("sound/poison.mp3")],
                             committed={"intro"})
    assert [asset for _src, asset in plan] == ["poison"]


def test_plan_mp3_adoption_of_nothing_is_empty():
    from gen_sounds import plan_mp3_adoption
    assert plan_mp3_adoption([]) == []
