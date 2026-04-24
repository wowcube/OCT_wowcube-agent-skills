"""Deterministic MP3 placeholder generator for cube_asset-builder.

Synthesises short audio clips with numpy, encodes to MP3 via ffmpeg with
bitexact flags so the same manifest produces the same bytes across runs.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from manifest_schema import Manifest, Sound, load_manifest

SAMPLE_RATE = 22050
BITRATE = "96k"
WAVEFORMS = ("sine", "square", "triangle", "sawtooth")

EVENT_PRESETS = {
    "pickup":  {"freq_scale": (1.0, 2.0), "attack_ms": 5,  "release_ms": 80,  "style": "rising"},
    "hit":     {"freq_scale": (0.7, 0.3), "attack_ms": 2,  "release_ms": 40,  "style": "noise_thump"},
    "ui":      {"freq_scale": (1.0, 1.0), "attack_ms": 1,  "release_ms": 20,  "style": "click"},
    "ambient": {"freq_scale": (1.0, 1.0), "attack_ms": 60, "release_ms": 200, "style": "pad"},
    "music":   {"freq_scale": (1.0, 1.0), "attack_ms": 5,  "release_ms": 80,  "style": "arpeggio"},
    "default": {"freq_scale": (1.0, 1.0), "attack_ms": 10, "release_ms": 60,  "style": "pad"},
}


def _md5_seed(label: str) -> int:
    return int(hashlib.md5(label.encode("utf-8")).hexdigest()[:8], 16)


def _waveform(wf: str, freq: np.ndarray) -> np.ndarray:
    phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    if wf == "sine":
        return np.sin(phase)
    if wf == "square":
        return np.sign(np.sin(phase))
    if wf == "triangle":
        return 2.0 / np.pi * np.arcsin(np.sin(phase))
    if wf == "sawtooth":
        return 2.0 * (phase / (2 * np.pi) - np.floor(0.5 + phase / (2 * np.pi)))
    raise ValueError(f"unknown waveform {wf!r}")


def _ar_envelope(n: int, attack_ms: int, release_ms: int) -> np.ndarray:
    """Attack-Release envelope (no decay/sustain).

    Linear fade-in over `attack_ms`, unity gain, linear fade-out over
    `release_ms`. Not a full ADSR — the name reflects that.
    """
    env = np.ones(n, dtype=np.float32)
    a = max(1, int(SAMPLE_RATE * attack_ms / 1000))
    r = max(1, int(SAMPLE_RATE * release_ms / 1000))
    a = min(a, n // 2)
    r = min(r, n - a)
    env[:a] = np.linspace(0.0, 1.0, a)
    env[n - r:] = np.linspace(1.0, 0.0, r)
    return env


def render_wav_bytes(
    *, group: str, name: str, event_type: str | None, duration_ms: int,
) -> bytes:
    """Synthesise a mono PCM16 WAV clip and return its byte representation."""
    event = event_type or "default"
    preset = EVENT_PRESETS.get(event, EVENT_PRESETS["default"])

    group_seed = _md5_seed(group)
    name_seed = _md5_seed(f"{group}:{name}")
    base_freq = 200.0 + (group_seed % 1800)
    wf = WAVEFORMS[group_seed % len(WAVEFORMS)]

    n = max(1, int(SAMPLE_RATE * duration_ms / 1000))

    freq_a, freq_b = preset["freq_scale"]
    sweep = np.linspace(base_freq * freq_a, base_freq * freq_b, n, dtype=np.float32)

    style = preset["style"]
    if style == "noise_thump":
        rng = np.random.default_rng(name_seed & 0xFFFFFFFF)
        noise = rng.standard_normal(n).astype(np.float32) * 0.4
        thump = _waveform("sine", sweep * 0.5)
        signal = noise + thump * 0.7
    elif style == "click":
        signal = _waveform("square", np.full_like(sweep, base_freq))
    elif style == "arpeggio":
        notes = [1.0, 1.25, 1.5, 2.0]
        signal = np.zeros(n, dtype=np.float32)
        seg = max(1, n // len(notes))
        for i, mult in enumerate(notes):
            start = i * seg
            end = min(n, start + seg)
            freq_seg = np.full(end - start, base_freq * mult, dtype=np.float32)
            signal[start:end] = _waveform(wf, freq_seg)
    else:
        # pad / rising / default: sweep over the full duration.
        signal = _waveform(wf, sweep)

    env = _ar_envelope(n, preset["attack_ms"], preset["release_ms"])
    signal *= env

    peak = float(np.max(np.abs(signal))) or 1.0
    signal = (signal / peak) * 0.707

    pcm = (signal * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _encode_mp3(wav_bytes: bytes, out_path: Path) -> None:
    """Invoke ffmpeg with bit-exact flags so the same input produces the same MP3 bytes."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error",
        "-f", "wav", "-i", "-",
        "-b:a", BITRATE,
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        "-flags", "+bitexact",
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=wav_bytes, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {proc.stderr.decode(errors='replace')}"
        )


def generate(manifest: Manifest, out_dir: Path, *, group: str | None = None) -> list[Path]:
    """Generate MP3s for every sound in `manifest` to `out_dir`.

    If `group` is given, only sounds whose derived/explicit group matches
    are regenerated. The caller is responsible for ensuring `ffmpeg` is on
    PATH (build_pipeline._check_deps does this upstream); invocations that
    bypass the pipeline will surface a normal FileNotFoundError from subprocess.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for snd in manifest.sounds:
        grp = snd.derived_group()
        if group is not None and grp != group:
            continue
        wav_bytes = render_wav_bytes(
            group=grp, name=snd.name, event_type=snd.event_type,
            duration_ms=snd.duration_ms,
        )
        target = out_dir / f"{snd.name}.mp3"
        _encode_mp3(wav_bytes, target)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate placeholder MP3s from an asset manifest.")
    p.add_argument("manifest", help="Path to <game>_assets.json")
    p.add_argument("--out", default="assets/mp3", help="Output directory (default: assets/mp3)")
    p.add_argument("--group", default=None, help="Regenerate only this group")
    args = p.parse_args(argv)

    m = load_manifest(args.manifest)
    written = generate(m, Path(args.out), group=args.group)
    print(f"gen_sounds: wrote {len(written)} MP3(s) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
