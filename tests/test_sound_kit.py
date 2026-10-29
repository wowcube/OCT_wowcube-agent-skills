"""sound_kit: the parts that need no ffmpeg (synthesis, layering, mastering,
loop search on a synthetic beat)."""
from __future__ import annotations

import numpy as np

import sound_kit as sk


def test_thump_is_a_decaying_low_tone():
    t = sk.synth({"type": "thump", "from_hz": 130, "to_hz": 45, "decay": 0.09, "len": 0.35})
    assert len(t) == int(0.35 * sk.SR)
    first, last = np.abs(t[:2000]).max(), np.abs(t[-2000:]).max()
    assert first > 0.5 and last < 0.1 * first


def test_mix_offsets_and_master_never_clips():
    a = np.ones(100, np.float32)
    y = sk.mix([(a, 0.0, 1.0), (a, 50 / sk.SR, 1.0)])
    assert len(y) == 150 and y[60] == 2.0
    m = sk.master(y * 10, drive=2.2)
    assert np.abs(m).max() <= 0.97 + 1e-6


def test_find_loop_recovers_a_bar_length():
    sr = sk.SR
    bar = 2.5                                   # seconds per pattern repeat
    t = np.arange(int(60 * sr)) / sr
    clicks = np.zeros_like(t, dtype=np.float32)
    for k, off in enumerate((0.0, 0.6, 1.1, 1.9)):   # an irregular pattern so only the bar matches
        idx = ((np.arange(0, 60, bar) + off) * sr).astype(int)
        clicks[idx[idx < len(t)]] = 1.0 - 0.15 * k
    env = np.exp(-np.arange(int(0.05 * sr)) / (0.01 * sr))
    sig = np.convolve(clicks, env)[:len(t)].astype(np.float32) * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    start, length, corr = sk.find_loop(sig, 2.0, 6.0)
    assert min(abs(length - n * bar) for n in (1, 2)) < 0.05
    assert corr > 0.5
