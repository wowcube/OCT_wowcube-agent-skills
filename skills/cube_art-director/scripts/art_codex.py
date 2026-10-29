"""Run the local Codex CLI (logged in with a ChatGPT subscription) to draw one
image with its built-in image generation tool.

No API key is involved: Codex bills the user's ChatGPT plan - but only when it
is logged in WITH ChatGPT. A Codex CLI logged in with an OpenAI API key bills
that key per call, so `run()` first requires `codex login status` to report a
ChatGPT login (checked once per process) and otherwise stops with a message:
the user runs `codex login` themselves. Model choice
follows the standing rule "strongest model, maximum reasoning effort": the
top visible model in ~/.codex/models_cache.json (lowest priority value) at
its highest supported effort below "ultra" (ultra = max + auto-delegation,
not deeper). Override with ART_CODEX_MODEL / ART_CODEX_EFFORT.

Lessons baked in (each one cost a broken batch once):
- parallel runs share ~/.codex/generated_images; Codex's own "copy the newest
  PNG" step grabs a sibling's picture -> take the image from THIS run's
  session folder (session id parsed from the CLI output);
- long working-directory paths break the CLI on Windows -> short temp dir;
- "model is at capacity" is transient -> retry with back-off;
- references are attached with -i and kept OUT of the work dir, so they can
  never be mistaken for the output.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

EFFORT_ORDER = ["minimal", "low", "medium", "high", "xhigh", "max"]


def find_codex() -> str:
    found = sorted(glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe")),
                   key=os.path.getmtime, reverse=True)
    if found:
        return found[0]
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    raise SystemExit("codex not found: install the Codex CLI and run `codex login` with a ChatGPT account")


# `codex login status` verdict per CLI path, once per process (a batch draws
# dozens of images; the login does not change mid-run).
_login_ok: dict[str, tuple[bool, str]] = {}


def login_status(exe: str) -> tuple[bool, str]:
    """(logged in with ChatGPT?, first line of `codex login status`).
    An API-key login ("Logged in using an API key") is NOT ok: it bills the
    key instead of the subscription."""
    try:
        r = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"`codex login status` failed: {e}"
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    out = out.strip()
    low = out.lower()
    ok = (r.returncode == 0 and "chatgpt" in low and "not logged in" not in low
          and "api key" not in low and "api_key" not in low)
    first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "no output")
    return ok, first


def require_chatgpt_login(exe: str) -> None:
    """Stop (SystemExit) unless `exe` is logged in with ChatGPT. Never logs in
    or types credentials. Only a positive verdict is cached."""
    if exe in _login_ok and _login_ok[exe][0]:
        return
    ok, info = login_status(exe)
    if ok:
        _login_ok[exe] = (ok, info)
        return
    raise SystemExit(
        f"codex is not logged in with a ChatGPT account ({info}). Nothing was generated: a Codex CLI logged in "
        f"with an OpenAI API key (or not at all) would bill that key or fail. Ask the user to run `codex login` "
        f"and sign in with ChatGPT, then rerun.")


def pick_model() -> tuple[str, str]:
    """(model, effort) per the strongest-model rule; env vars override."""
    model, effort = os.environ.get("ART_CODEX_MODEL"), os.environ.get("ART_CODEX_EFFORT")
    if model and effort:
        return model, effort
    cache = Path.home() / ".codex" / "models_cache.json"
    best = None
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        models = [m for m in data.get("models", []) if m.get("visibility") == "list"]
        best = min(models, key=lambda m: m.get("priority", 999)) if models else None
    except (OSError, ValueError):
        pass
    if best is None:
        return model or "gpt-6.1-sol", effort or "max"
    levels = [lv.get("effort") for lv in best.get("supported_reasoning_levels", []) if isinstance(lv, dict)]
    ranked = [e for e in EFFORT_ORDER if e in levels]
    return model or best["slug"], effort or (ranked[-1] if ranked else "high")


def build_prompt(name: str, body: str, *, n_anchors: int, subject: bool, sketch: bool,
                 background: str, key: str, n_style_refs: int = 0) -> str:
    refs = ""
    if n_style_refs:
        refs += (f"The first {n_style_refs} attached image(s) are the ARTIST'S STYLE REFERENCES (not yet a locked "
                 "style): render the subject so it would sit naturally among them - same rendering technique, "
                 "palette family, outline and detail level. Copy only the style, never their content. ")
    if n_anchors:
        refs += (f"The first {n_anchors} attached image(s) are the APPROVED STYLE ANCHORS. Pass them to the image "
                 "tool as style references and match their rendering exactly: pixel size, outline colour and "
                 "weight, shading steps, light direction, palette, level of detail. Copy ONLY the style, never "
                 "their content, characters, composition or background. ")
    idx = n_style_refs + n_anchors + 1
    if subject:
        refs += (f"Attached image #{idx} is the SUBJECT REFERENCE: keep that exact character/object (same design, "
                 "proportions, colours, scale, costume details) and change only what the prompt asks for. ")
        idx += 1
    if sketch:
        refs += (f"Attached image #{idx} is the ARTIST'S SKETCH: follow its pose, composition and proportions "
                 "precisely and render it in the anchors' style. ")
    if refs:
        refs += "Never edit, return or paste a reference image itself. "
    if background == "key":
        hexkey = "#00FF00 pure green" if key == "green" else "#FF00FF pure magenta"
        bg = (f"Background: one flat uniform {hexkey} colour filling the whole canvas, no gradient, no floor, "
              "no cast shadow, no vignette; the subject must not use that colour anywhere. Single subject "
              "centred with a clear margin, nothing touching the canvas edge. ")
    else:
        bg = "The picture fills the whole canvas edge to edge (opaque, no border, no frame). "
    return (
        "Use your built-in image generation tool exactly once to create this image. "
        f"{refs}Canvas: square 1024x1024. {bg}No text, watermark, signature, border or UI unless the prompt asks "
        "for text.\n\nImage prompt (use it verbatim):\n\n"
        f"{body.strip()}\n\n"
        f"Save the generated PNG into the current directory as {name}.png (copy it from wherever the tool stores "
        "it). Do not edit the image yourself. Reply with the saved absolute path only."
    )


def doctor() -> list[tuple[bool, str]]:
    """Setup check for the artist: binary, ChatGPT login, model choice."""
    out = []
    try:
        exe = find_codex()
        out.append((True, f"codex CLI: {exe}"))
    except SystemExit as e:
        return [(False, str(e))]
    ok, info = login_status(exe)
    out.append((ok, "login: " + info +
                ("" if ok else " (run `codex login` and sign in with the ChatGPT account, not an API key)")))
    m, e = pick_model()
    out.append((True, f"model: {m} at effort {e}"))
    return out


def run(name: str, prompt: str, refs: list[Path], out_png: Path, log_dir: Path,
        retries: int = 3, timeout: int = 900) -> tuple[bool, str]:
    codex = find_codex()
    require_chatgpt_login(codex)          # before anything can be billed
    model, effort = pick_model()
    base = Path(tempfile.gettempdir()) / "artgen"
    base.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    last = ""
    for attempt in range(1, retries + 1):
        # unique short dir per call: two projects drawing "hero" at once must not share it
        work = Path(tempfile.mkdtemp(prefix="g", dir=base))
        cmd = [codex, "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
               "--skip-git-repo-check", "-C", str(work), "-s", "workspace-write", "--ephemeral"]
        for r in refs:
            cmd += ["-i", str(r)]
        cmd.append("-")
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
            out = proc.stdout + "\n--- stderr ---\n" + proc.stderr
        except subprocess.TimeoutExpired as e:
            out = f"timeout after {timeout}s\n{e.stdout or ''}"
            proc = None
        (log_dir / f"{name}.log").write_text(f"model={model} effort={effort} attempt={attempt}\n"
                                              f"--- prompt ---\n{prompt}\n--- output ---\n{out}", encoding="utf-8")
        pngs = []
        sid = re.search(r"session id:\s*([0-9a-f-]{36})", out)
        if sid:
            own = Path.home() / ".codex" / "generated_images" / sid.group(1)
            pngs = sorted(own.glob("*.png"), key=os.path.getmtime)
        if not pngs:
            pngs = sorted(work.glob("*.png"), key=os.path.getmtime)
        if pngs:
            out_png.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pngs[-1], out_png)
            shutil.rmtree(work, ignore_errors=True)
            return True, f"{time.time() - t0:.0f}s ({model}/{effort})"
        shutil.rmtree(work, ignore_errors=True)
        last = f"no PNG (rc={proc.returncode if proc else 'timeout'})"
        if "capacity" in out.lower() or "rate limit" in out.lower() or "429" in out:
            time.sleep(30 * attempt)
            continue
        if attempt < retries:
            time.sleep(5)
    return False, last
