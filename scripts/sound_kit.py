#!/usr/bin/env python3
"""Sound kit: real recorded sounds -> punchy game SFX and music loops in the
exact format the OctaviOS engine plays (22050 Hz mono CBR 32 kbps mp3, no
Xing header, no tags).

Why this exists: pure synthesis (gen_sounds.py) gives placeholder beeps that
players hate. What worked on a shipped game (Shotgun Princess): CC0 recordings
(OpenGameArt, Kenney, Freesound CC0 - downloaded only after the user approves
the list), layered and mastered per a recipe, plus a synthetic sub thump where
recordings lack low end. Everything is analysed by numbers - never played out
loud on the user's machine.

  python scripts/sound_kit.py inspect <audio...>              duration, peak/mean dB, band energy, envelope
                                                              (wildcards like src/*.mp3 are expanded by the
                                                              script, so PowerShell works too)
  python scripts/sound_kit.py loop <music> --out <dir> [--name music_loop] [--min 8 --max 30]
                                                              cut the most self-similar loop, start on a beat
  python scripts/sound_kit.py licences <source folders...>     licence/readme files inside the downloads, flags non-CC0
  python scripts/sound_kit.py build <recipes.json> --out <sound/assets>
                                                              layer + master + encode every recipe

Recipe file (paths relative to the recipe file):
{
  "sources": {
    "crack": {"file": "src/shotty.wav", "trim": 0.02, "end": 0.62, "hp": 160, "decay": 0.22},
    "meat":  {"file": "src/impact_meat02.flac", "trim": 0.05},
    "growl": {"file": "src/zombie-17.wav", "end": 1.3}
  },
  "synth": {
    "sub":  {"type": "thump", "from_hz": 130, "to_hz": 45, "decay": 0.09, "len": 0.35},
    "body": {"type": "noise", "lp": 1400, "decay": 0.035, "len": 0.16}
  },
  "sounds": {
    "shotgun_hit": {"layers": [["crack", 0, 1.0], ["sub", 0, 0.9], ["body", 0, 0.45], ["meat", 0.03, 0.9]],
                    "drive": 2.2},
    "tank_growl":  {"layers": [["growl", 0, 1.0, {"pitch": -5}]], "drive": 1.8, "max_len": 1.6}
  }
}
Source options: trim (silence threshold to cut the lead-in), start/end (s), hp/lp (Hz, 1-pole),
decay (s, exponential fade), gain, pitch (semitones, resample). Layer = [source, offset_s, gain, {opts}].
Sound options: drive (tanh saturation = loud and punchy without clipping), max_len (s), fade_out (s).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 22050


# ------------------------------------------------------------------------- io
def need_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg is required (Windows: winget install Gyan.FFmpeg)")
    return exe


def load(path: Path, sr: int = SR) -> np.ndarray:
    r = subprocess.run([need_ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                        "-f", "s16le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768


def save(a: np.ndarray, wav: Path, mp3: Path | None) -> None:
    """WAV (for inspection) + the engine mp3: 22050 Hz mono CBR 32k, no Xing, no tags.
    The mp3 starts with ~50 ms of LAME encoder delay that cannot be signalled
    without the Xing/LAME gapless header the engine format omits."""
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
    wav.parent.mkdir(parents=True, exist_ok=True)
    ff = need_ffmpeg()
    subprocess.run([ff, "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", str(wav)],
                   input=pcm, check=True)
    if mp3 is not None:
        mp3.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-v", "error", "-y", "-i", str(wav), "-ar", str(SR), "-ac", "1", "-c:a", "libmp3lame",
                        "-b:a", "32k", "-write_xing", "0", "-id3v2_version", "0", "-write_id3v1", "0",
                        "-map_metadata", "-1", str(mp3)], check=True)


# ------------------------------------------------------------------------- dsp
def hp(a: np.ndarray, fc: float) -> np.ndarray:
    rc = 1 / (2 * np.pi * fc)
    al = rc / (rc + 1 / SR)
    y = np.zeros_like(a)
    p = px = 0.0
    for i, x in enumerate(a):
        p = al * (p + x - px)
        px = x
        y[i] = p
    return y


def lp(a: np.ndarray, fc: float) -> np.ndarray:
    al = (1 / SR) / (1 / (2 * np.pi * fc) + 1 / SR)
    y = np.zeros_like(a)
    p = 0.0
    for i, x in enumerate(a):
        p += al * (x - p)
        y[i] = p
    return y


def pitch(a: np.ndarray, semis: float) -> np.ndarray:
    f = 2 ** (semis / 12)
    idx = np.arange(0, len(a) - 1, f)
    return np.interp(idx, np.arange(len(a)), a).astype(np.float32)


def trim_lead(a: np.ndarray, thr: float) -> np.ndarray:
    i = int(np.argmax(np.abs(a) > thr)) if (np.abs(a) > thr).any() else 0
    return a[max(0, i - int(0.004 * SR)):]


def fade(a: np.ndarray, fin: float = 0.003, fout: float = 0.04) -> np.ndarray:
    a = a.copy()
    n1, n2 = int(fin * SR), min(len(a), int(fout * SR))
    if n1:
        a[:n1] *= np.linspace(0, 1, n1)
    if n2:
        a[-n2:] *= np.linspace(1, 0, n2) ** 2
    return a


def master(a: np.ndarray, drive: float = 1.0, peak: float = 0.97) -> np.ndarray:
    if drive > 0:
        a = np.tanh(a * drive) / np.tanh(drive)
    return (a / (np.abs(a).max() + 1e-9) * peak).astype(np.float32)


def shape(a: np.ndarray, o: dict) -> np.ndarray:
    if "trim" in o:
        a = trim_lead(a, float(o["trim"]))
    s, e = o.get("start"), o.get("end")
    if s is not None or e is not None:
        a = a[int((s or 0) * SR):(int(e * SR) if e is not None else None)]
    if o.get("hp"):
        a = hp(a, float(o["hp"]))
    if o.get("lp"):
        a = lp(a, float(o["lp"]))
    if o.get("pitch"):
        a = pitch(a, float(o["pitch"]))
    if o.get("decay"):
        a = a * np.exp(-np.arange(len(a)) / SR / float(o["decay"]))
    if o.get("gain"):
        a = a * float(o["gain"])
    return a.astype(np.float32)


def synth(o: dict, seed: int = 7) -> np.ndarray:
    n = int(float(o.get("len", 0.3)) * SR)
    t = np.arange(n) / SR
    if o["type"] == "thump":       # pitch-dropping sine: chest punch under a gunshot / impact
        f0, f1, d = float(o.get("from_hz", 130)), float(o.get("to_hz", 45)), float(o.get("decay", 0.09))
        freq = f1 + (f0 - f1) * np.exp(-t / 0.035)
        return (np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / d)).astype(np.float32)
    if o["type"] == "noise":       # filtered noise burst: body / air of a blast
        x = np.random.default_rng(seed).standard_normal(n).astype(np.float32)
        if o.get("lp"):
            x = lp(x, float(o["lp"]))
        if o.get("hp"):
            x = hp(x, float(o["hp"]))
        return (x * np.exp(-t / float(o.get("decay", 0.04)))).astype(np.float32)
    raise SystemExit(f"unknown synth type {o['type']!r}")


def mix(layers: list[tuple[np.ndarray, float, float]]) -> np.ndarray:
    n = max(int(off * SR) + len(s) for s, off, g in layers)
    y = np.zeros(n, np.float32)
    for s, off, g in layers:
        k = int(off * SR)
        y[k:k + len(s)] += s * g
    return y


# ------------------------------------------------------------------------- analysis
def describe(a: np.ndarray) -> str:
    dur = len(a) / SR
    peak = 20 * np.log10(np.abs(a).max() + 1e-9)
    rms = 20 * np.log10(np.sqrt((a ** 2).mean()) + 1e-9)
    sp = np.abs(np.fft.rfft(a[:SR * 4]))
    fq = np.fft.rfftfreq(min(len(a), SR * 4), 1 / SR)
    tot = sp.sum() + 1e-9
    bands = [(0, 150), (150, 500), (500, 2000), (2000, 6000), (6000, 11025)]
    share = " ".join(f"{lo}-{hi}:{sp[(fq >= lo) & (fq < hi)].sum() / tot:.0%}" for lo, hi in bands)
    hop = max(1, len(a) // 40)
    env = [np.abs(a[i:i + hop]).max() for i in range(0, len(a), hop)][:40]
    bars = " .:-=+*#%@"
    line = "".join(bars[min(9, int(e * 9.99))] for e in env)
    return f"{dur:6.2f}s peak {peak:5.1f} dB rms {rms:5.1f} dB | {share} | [{line}]"


def find_loop(m: np.ndarray, lmin: float, lmax: float) -> tuple[float, float, float]:
    """Most self-similar (start, length) by onset-envelope correlation, then
    the start snapped to the strongest onset nearby.

    The onset envelope (5 ms frames) of an 8 s window starting at s is
    correlated (Pearson) with the window starting at s + L for every loop
    length L in [lmin, lmax] at once (np.correlate over the sliding windows,
    rolling mean/std from cumulative sums), for starts every 50 ms."""
    hop = 55                      # 5 ms at 11025 Hz
    x = m[::2] if SR == 22050 else m
    n = (len(x) - hop) // hop
    if n <= 0:
        raise SystemExit("audio too short to search for a loop")
    frames = x[:n * hop].reshape(n, hop)
    env = np.sqrt((frames ** 2).mean(axis=1))
    on = np.maximum(0, np.diff(np.log(env + 1e-4))).astype(np.float64)
    W = int(8 / 0.005)
    l0, l1 = int(lmin / 0.005), int(lmax / 0.005)
    first = int(1 / 0.005)
    last = len(on) - W - l1
    if last <= first:
        raise SystemExit(f"audio too short for loops up to {lmax}s (need about {lmax + 9:.0f}s)")
    c1 = np.concatenate([[0.0], np.cumsum(on)])
    c2 = np.concatenate([[0.0], np.cumsum(on * on)])
    starts = np.arange(len(on) - W + 1)
    mean_w = (c1[starts + W] - c1[starts]) / W
    std_w = np.sqrt(np.maximum((c2[starts + W] - c2[starts]) / W - mean_w ** 2, 0)) + 1e-9
    best = (-1.0, 0, 0)
    for s in range(first, last, 10):
        a = on[s:s + W]
        a = (a - a.mean()) / (a.std() + 1e-9)
        seg = on[s + l0:s + l1 + W]
        dots = np.correlate(seg, a, "valid")          # sum(a * b) for b at every L in [l0, l1]
        idx = s + l0 + np.arange(len(dots))
        corr = (dots / W - a.mean() * mean_w[idx]) / std_w[idx]   # a.mean() == 0 after z-scoring
        k = int(np.argmax(corr))
        if corr[k] > best[0]:
            best = (float(corr[k]), s, l0 + k)
    c, s, L = best
    s_samples = int(s * 0.005 * SR)
    win = np.abs(m[s_samples:s_samples + int(0.3 * SR)])
    s_samples += int(np.argmax(np.convolve(win, np.ones(64), "same"))) - int(0.01 * SR)
    return max(0, s_samples) / SR, L * 0.005, c


# ------------------------------------------------------------------------- commands
LICENCE_HINTS = ("licen", "copying", "readme", "credit", "creativecommons", "attribution", "source")


def cmd_licences(args) -> int:
    """Print every licence/readme/credits file inside the given source folders
    (or next to the given files) and flag attribution licences. A store page can
    say CC0 while the archive ships a CC-BY notice (it happened): the file in
    the archive is what the proposal must quote."""
    seen, flagged = set(), 0
    for f in args.files:
        root = Path(f)
        root = root if root.is_dir() else root.parent
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p in seen or p.suffix.lower() not in (".txt", ".md", ".html", ""):
                continue
            if not any(h in p.name.lower() for h in LICENCE_HINTS):
                continue
            seen.add(p)
            text = p.read_text(encoding="utf-8", errors="replace")
            low = text.lower()
            kind = ("CC0" if ("cc0" in low or "publicdomain/zero" in low) else
                    "CC-BY-SA" if ("by-sa" in low or "sharealike" in low) else
                    "CC-BY" if ("attribution" in low or "/by/" in low) else
                    "GPL" if "gpl" in low else "?")
            if kind != "CC0":
                flagged += 1
            head = " ".join(text.split())[:220]
            print(f"[{kind}] {p}")
            print(f"      {head}")
    if not seen:
        print("no licence/readme files found next to the sources: quote the store page and keep its URL")
    elif flagged:
        print(f"{flagged} file(s) are not CC0: attribution (or more) required - put it in sound/CREDITS.md "
              f"and tell the user before using these sounds")
    return 0


def cmd_inspect(args) -> int:
    for f in args.files:
        print(f"{Path(f).name:28s} {describe(load(Path(f)))}")
    return 0


def cmd_loop(args) -> int:
    m = load(Path(args.files[0]))
    start, length, corr = find_loop(m, args.min, args.max)
    s, L = int(start * SR), int(length * SR)
    loop = m[s:s + L].copy()
    xf = int(0.03 * SR)
    if s + L + xf <= len(m):      # fold the next bar's head into the tail: smoother wrap on retrigger
        loop[-xf:] = loop[-xf:] * np.linspace(1, 0, xf) + m[s + L:s + L + xf] * np.linspace(0, 1, xf)
    loop = loop / (np.abs(loop).max() + 1e-9) * 0.9
    out = Path(args.out)
    save(loop.astype(np.float32), Path(args.wav_dir or out.parent / "_wav") / f"{args.name}.wav", out / f"{args.name}.mp3")
    ticks = round(length * 20)
    print(f"loop {args.name}: start {start:.3f}s length {length:.3f}s (self-similarity {corr:.2f}) "
          f"-> retrigger every {ticks} ticks at 20 Hz; {describe(loop)}")
    return 0


def cmd_build(args) -> int:
    rf = Path(args.files[0]).resolve()
    rec = json.loads(rf.read_text(encoding="utf-8"))
    base = rf.parent
    src = {k: shape(load(base / v["file"]), v) for k, v in rec.get("sources", {}).items()}
    src.update({k: synth(v) for k, v in rec.get("synth", {}).items()})
    out = Path(args.out)
    for name, s in rec["sounds"].items():
        layers = []
        for lay in s["layers"]:
            nm, off, g = lay[0], float(lay[1]), float(lay[2])
            a = src[nm]
            if len(lay) > 3:
                a = shape(a, lay[3])
            layers.append((a, off, g))
        y = mix(layers)
        if s.get("max_len"):
            y = y[:int(float(s["max_len"]) * SR)]
        y = fade(master(y, float(s.get("drive", 1.0))), fout=float(s.get("fade_out", 0.04)))
        mp3 = out / f"{name}.mp3"
        save(y, Path(args.wav_dir or out.parent / "_wav") / f"{name}.wav", mp3)
        print(f"{name:16s} {describe(y)}  {mp3.stat().st_size} B")
    return 0


_GLOB_CHARS = set("*?[")


def expand_files(patterns: list[str]) -> list[str]:
    """Expand wildcards ourselves: PowerShell and cmd hand `*.mp3` to python
    literally (only POSIX shells expand it). A path that exists as written is
    kept as is (so 'take [1].wav' is never treated as a pattern); a pattern
    expands to its matches in sorted order; a pattern matching nothing is an
    error, never silently dropped."""
    import glob
    out: list[str] = []
    for pat in patterns:
        if Path(pat).exists() or not (_GLOB_CHARS & set(pat)):
            out.append(pat)
            continue
        hits = sorted(glob.glob(pat, recursive=True))
        if not hits:
            raise SystemExit(f"no file matches {pat!r}")
        out += hits
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["inspect", "loop", "build", "licences"])
    ap.add_argument("files", nargs="+", help="audio files (or a recipe for build); wildcards such as "
                                             "src/*.mp3 are expanded here, on every shell")
    ap.add_argument("--out", default="sound/assets")
    ap.add_argument("--wav-dir", default=None, help="where the inspection WAVs go (default <out>/../_wav, kept out of the pack)")
    ap.add_argument("--name", default="music_loop")
    ap.add_argument("--min", type=float, default=8.0)
    ap.add_argument("--max", type=float, default=30.0)
    args = ap.parse_args(argv)
    args.files = expand_files(args.files)
    return {"inspect": cmd_inspect, "loop": cmd_loop, "build": cmd_build, "licences": cmd_licences}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
