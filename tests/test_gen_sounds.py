"""Tests for gen_sounds.py — pure-Python WAV synthesis, no external encoder."""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from manifest_schema import load_manifest
import gen_sounds
from gen_sounds import FFMPEG_MISSING_MSG, encode_beta_mp3, generate, render_wav_bytes


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
