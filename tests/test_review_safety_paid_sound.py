"""Review findings (paid-API safety, credentials, sound), each with its
regression test. Nothing here reaches a network, a paid API or a real Codex:
every subprocess / HTTP seam is replaced."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import build_pipeline
import gen_sounds
import genimg
import image_providers as ip
import sound_kit
from manifest_schema import load_manifest

ART = Path(__file__).resolve().parents[1] / "skills" / "cube_art-director" / "scripts"
sys.path.insert(0, str(ART))
import art_codex  # noqa: E402


# ------------------------------------------------------------- isolation

@pytest.fixture
def no_paid_env(monkeypatch, tmp_path):
    for var in (ip.ALLOW_PAID_ENV, ip.API_KEY_ENV, ip.IMAGE_API_ENV, ip.ART_PY_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(ip.NO_CODEX_ENV, "1")
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "cfg" / "image_api.json")

    def _guard(argv, **kwargs):
        raise AssertionError(f"unexpected subprocess: {argv}")
    monkeypatch.setattr(ip, "_run", _guard)

    def _no_http(*a, **k):
        raise AssertionError("network call")
    monkeypatch.setattr(ip.requests, "post", _no_http)
    monkeypatch.setattr(ip.requests, "get", _no_http)
    ip._codex_login_cache.clear()
    yield
    ip._codex_login_cache.clear()


# ------------------------------------------------- 6. local SD is not paid

@pytest.mark.parametrize("url", ["http://localhost:7860", "http://127.0.0.1:7860", "https://127.0.0.5",
                                 "http://[::1]:7860/", "http://sd.localhost:7860"])
def test_local_stable_diffusion_needs_no_opt_in(no_paid_env, monkeypatch, url):
    monkeypatch.setenv(ip.IMAGE_API_ENV, url)
    cfg = ip.resolve_provider()
    assert cfg.provider == "sd_a1111" and cfg.base_url == url


@pytest.mark.parametrize("url", ["http://10.0.0.5:7860", "https://sd.example.com", "http://localhost.evil.com",
                                 "http://127.0.0.1.nip.io"])
def test_remote_stable_diffusion_still_needs_the_opt_in(no_paid_env, monkeypatch, url):
    monkeypatch.setenv(ip.IMAGE_API_ENV, url)
    with pytest.raises(ip.PaidProviderNotAllowed):
        ip.resolve_provider()


def test_local_sd_from_the_config_file_and_paid_keys_unchanged(no_paid_env):
    ip.CONFIG_PATH.parent.mkdir(parents=True)
    ip.CONFIG_PATH.write_text(json.dumps({"provider": "sd_a1111", "base_url": "http://127.0.0.1:7860"}),
                              encoding="utf-8")
    assert ip.resolve_provider().provider == "sd_a1111"
    ip.CONFIG_PATH.write_text(json.dumps({"provider": "openai", "key": "sk-x"}), encoding="utf-8")
    with pytest.raises(ip.PaidProviderNotAllowed):
        ip.resolve_provider()


def test_build_pipeline_generate_draws_with_local_sd_without_opt_in(no_paid_env, monkeypatch, tmp_path, capsys):
    from PIL import Image
    monkeypatch.setenv(ip.IMAGE_API_ENV, "http://127.0.0.1:7860")
    drawn = []

    def _fake(prompt, out_path, *, size=None, reference=None, cutout=False):
        drawn.append(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", tuple(size), (1, 2, 3, 255)).save(out_path)
        return out_path
    monkeypatch.setattr(genimg, "generate_image", _fake)
    mp = tmp_path / "plans" / "demo_assets.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [
        {"name": "coin", "size": [8, 8], "description": "d", "gen_prompt": "A coin."}], "sounds": []}),
        encoding="utf-8")
    rc = build_pipeline._cli(["generate", "--manifest", str(mp), "--workspace", str(tmp_path / "assets_demo")])
    assert rc == 0 and len(drawn) == 1
    out = capsys.readouterr().out
    assert "local Stable Diffusion" in out and "PAID" not in out


# ------------------------------------------------ 5. key file permissions

def test_saved_key_file_is_created_owner_only(no_paid_env, monkeypatch):
    modes = []
    real_open = os.open

    def _open(path, flags, mode=0o777, *a, **k):
        if Path(path) == ip.CONFIG_PATH:
            modes.append(mode)
        return real_open(path, flags, mode, *a, **k)
    monkeypatch.setattr(ip.os, "open", _open)
    ip.save_provider("sk-or-secret")
    assert modes == [0o600]
    assert json.loads(ip.CONFIG_PATH.read_text(encoding="utf-8"))["key"] == "sk-or-secret"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_saved_key_file_mode_is_0600_even_when_it_existed(no_paid_env):
    ip.CONFIG_PATH.parent.mkdir(parents=True)
    ip.CONFIG_PATH.write_text("{}", encoding="utf-8")
    os.chmod(ip.CONFIG_PATH, 0o644)
    ip.save_provider("sk-or-secret")
    assert stat.S_IMODE(ip.CONFIG_PATH.stat().st_mode) == 0o600
    assert stat.S_IMODE(ip.CONFIG_PATH.parent.stat().st_mode) == 0o700


# ------------------------------------------- 2. art_codex: ChatGPT login only

class _Proc:
    def __init__(self, out, rc=0):
        self.stdout, self.stderr, self.returncode = out, "", rc


@pytest.fixture
def fake_codex(monkeypatch, tmp_path):
    """art_codex with a fake CLI: records every subprocess; `codex exec` (a
    real generation) fails the test."""
    calls = []
    state = {"status": "Logged in using ChatGPT"}

    def _run(argv, **kwargs):
        calls.append(list(argv))
        if argv[1:3] == ["login", "status"]:
            return _Proc(state["status"])
        raise AssertionError(f"generation must not start: {argv}")
    monkeypatch.setattr(art_codex.subprocess, "run", _run)
    monkeypatch.setattr(art_codex, "find_codex", lambda: str(tmp_path / "codex.exe"))
    art_codex._login_ok.clear()
    yield calls, state
    art_codex._login_ok.clear()


@pytest.mark.parametrize("status", ["Logged in using an API key - sk-proj-***abcd", "Not logged in",
                                    "Logged in using ChatGPT api key mode", ""])
def test_run_refuses_to_generate_without_a_chatgpt_login(fake_codex, tmp_path, status):
    calls, state = fake_codex
    state["status"] = status
    with pytest.raises(SystemExit) as e:
        art_codex.run("hero", "draw", [], tmp_path / "hero.png", tmp_path / "logs")
    assert "codex login" in str(e.value) and "ChatGPT" in str(e.value)
    assert all(c[1:3] == ["login", "status"] for c in calls)
    assert not (tmp_path / "hero.png").exists()


def test_login_check_passes_for_chatgpt_and_is_cached(fake_codex, tmp_path):
    calls, _ = fake_codex
    art_codex.require_chatgpt_login("codex.exe")
    art_codex.require_chatgpt_login("codex.exe")
    assert calls == [["codex.exe", "login", "status"]]


def test_doctor_flags_an_api_key_login(fake_codex):
    _, state = fake_codex
    state["status"] = "Logged in using an API key - sk-***"
    rows = art_codex.doctor()
    login = [r for r in rows if r[1].startswith("login:")][0]
    assert login[0] is False and "codex login" in login[1]


def test_image_providers_rejects_an_api_key_codex_login(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "_run", lambda argv, **k: _Proc("Logged in using an API key (ChatGPT org) sk-***"))
    ip._codex_login_cache.clear()
    try:
        assert ip.codex_login_status(str(tmp_path / "codex.exe"), use_cache=False)[0] is False
    finally:
        ip._codex_login_cache.clear()


# --------------------------------------------- 3. licence classification

@pytest.mark.parametrize("text,kind", [
    ("Creative Commons Zero (CC0) http://creativecommons.org/publicdomain/zero/1.0/", "CC0"),
    ("This work is dedicated to the public domain.", "CC0"),
    ("Free for commercial and non-commercial use. CC0.", "CC0"),
    ("CC0. Attribution is not required but appreciated.", "CC0"),
    ("Licensed under CC-BY 3.0: credit Vincent Sevedge", "CC-BY"),
    ("Creative Commons Attribution 4.0 International", "CC-BY"),
    ("Attribution-ShareAlike 4.0 (CC BY-SA 4.0)", "CC-BY-SA"),
    ("Attribution-NonCommercial 4.0 International", "CC-BY-NC"),
    ("CC BY-NC-SA 3.0", "CC-BY-NC"),
    ("https://creativecommons.org/licenses/by-nd/4.0/", "CC-BY-ND"),
    ("Everything is CC0 except music.ogg, which is CC-BY 3.0", "CC-BY"),   # cc0 mentioned, still not CC0
    ("GNU General Public License v3", "GPL"),
    ("Thanks for downloading! Have fun.", "?"),
])
def test_classify_licence(text, kind):
    assert sound_kit.classify_licence(text) == kind


def _pack(tmp_path, files: dict) -> Path:
    root = tmp_path / "dl"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    (root / "boom.wav").write_bytes(b"RIFF")
    return root


def test_licences_exit_0_only_when_everything_is_cc0(tmp_path, capsys):
    root = _pack(tmp_path, {"kenney/License.txt": "CC0 1.0 Universal", "oga/readme.md": "Public domain (CC0)"})
    assert sound_kit.main(["licences", str(root)]) == 0
    assert "OK: all 2" in capsys.readouterr().out


@pytest.mark.parametrize("files", [
    {"a/License.txt": "CC0", "b/credits.txt": "CC-BY 3.0, credit Vincent Sevedge"},
    {"a/LICENSE": "Attribution-NonCommercial 4.0"},
    {"a/notes.txt": "Have fun!"},
])
def test_licences_exit_1_when_anything_is_not_cc0(tmp_path, capsys, files):
    assert sound_kit.main(["licences", str(_pack(tmp_path, files))]) == 1
    assert "NOT CLEARED" in capsys.readouterr().out


def test_licences_without_any_licence_file_is_not_cleared(tmp_path, capsys):
    root = tmp_path / "dl"
    root.mkdir()
    (root / "boom.wav").write_bytes(b"RIFF")
    assert sound_kit.main(["licences", str(root)]) == 1


@pytest.mark.parametrize("name", ["Attribution.nfo", "info.txt", "COPYRIGHT", "license.htm", "LICENSE.rtf",
                                  "credits.json", "NOTICE"])
def test_licences_scans_licence_files_the_old_filter_skipped(tmp_path, capsys, name):
    root = _pack(tmp_path, {name: "CC-BY 4.0 by Someone"})
    assert sound_kit.main(["licences", str(root)]) == 1
    out = capsys.readouterr().out
    assert f"[CC-BY] {root / name}" in out


def test_licences_reports_a_pdf_licence_as_unknown(tmp_path, capsys):
    root = _pack(tmp_path, {})
    (root / "License.pdf").write_bytes(b"%PDF-1.4 CC0")
    assert sound_kit.main(["licences", str(root)]) == 1
    assert "[?]" in capsys.readouterr().out


# -------------------------------------- 4. old placeholders are not "real"

def _sounds(tmp_manifest):
    return load_manifest(tmp_manifest({"game": "demo", "schema_version": 1, "sprites": [], "sounds": [
        {"name": "shot", "description": "s", "duration_ms": 150, "event_type": "shoot"}]}))


@pytest.fixture
def fake_encode(monkeypatch):
    calls = []

    def _fake(wav_path, assets_dir):
        wav_path, assets_dir = Path(wav_path), Path(assets_dir)
        assets_dir.mkdir(parents=True, exist_ok=True)
        out = assets_dir / (wav_path.stem + ".mp3")
        out.write_bytes(b"mp3-of:" + hashlib.md5(wav_path.read_bytes()).hexdigest().encode())
        calls.append(wav_path.stem)
        return out
    monkeypatch.setattr(gen_sounds, "encode_beta_mp3", _fake)
    return calls


def _legacy_placeholder(out: Path, m, fake=True):
    """What an older gen_sounds left behind: the WAV + its mp3, no placeholders.json."""
    snd = m.sounds[0]
    wav = gen_sounds.render_wav_bytes(group=gen_sounds._derived_group(snd), name=snd.name,
                                      event_type=snd.event_type, duration_ms=snd.duration_ms)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shot.wav").write_bytes(wav)
    (out / "assets").mkdir(exist_ok=True)
    (out / "assets" / "shot.mp3").write_bytes(b"mp3-of:" + hashlib.md5(wav).hexdigest().encode())


def test_an_old_unrecorded_placeholder_is_recognised_and_refreshed(tmp_manifest, tmp_path, fake_encode):
    m = _sounds(tmp_manifest)
    out = tmp_path / "wav"
    _legacy_placeholder(out, m)
    assert gen_sounds.classify(out, "shot") == "placeholder"
    assert not gen_sounds.is_sourced(out, "shot")
    kept: list[str] = []
    written = gen_sounds.generate(m, out, encode_mp3=True, kept=kept)
    assert kept == [] and written == [out / "shot.wav"]
    assert "shot" in json.loads((out / gen_sounds.PLACEHOLDERS_FILE).read_text(encoding="utf-8"))


def test_an_unprovable_old_placeholder_is_kept_but_not_counted(tmp_manifest, tmp_path, monkeypatch, capsys):
    m = _sounds(tmp_manifest)
    out = tmp_path / "wav"
    _legacy_placeholder(out, m)
    before = (out / "assets" / "shot.mp3").read_bytes()
    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: None)       # no ffmpeg: cannot prove it
    kept: list[str] = []
    unverified: list[str] = []
    gen_sounds.generate(m, out, kept=kept, unverified=unverified)
    assert kept == [] and unverified == ["shot"]
    assert (out / "assets" / "shot.mp3").read_bytes() == before              # never overwritten
    assert not gen_sounds.is_sourced(out, "shot")


def test_cli_warns_about_unverified_old_placeholders(tmp_path, monkeypatch, capsys):
    plans = tmp_path / "plans"
    plans.mkdir()
    mp = plans / "demo_assets.json"
    mp.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [], "sounds": [
        {"name": "shot", "description": "s", "duration_ms": 150, "event_type": "shoot"}]}), encoding="utf-8")
    out = tmp_path / "assets_demo" / "wav"
    _legacy_placeholder(out, load_manifest(mp))
    monkeypatch.setattr(gen_sounds.shutil, "which", lambda name: None)
    assert gen_sounds.main([str(mp), "--no-mp3"]) == 0
    text = capsys.readouterr().out
    assert "probably OLD placeholders" in text and "shot" in text and "kept 1 sourced" not in text


def test_a_real_recording_without_a_placeholder_wav_is_still_sourced(tmp_manifest, tmp_path, fake_encode):
    out = tmp_path / "wav"
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "shot.mp3").write_bytes(b"CC0 blast")
    assert gen_sounds.classify(out, "shot") == "sourced"
    kept: list[str] = []
    gen_sounds.generate(_sounds(tmp_manifest), out, encode_mp3=True, kept=kept)
    assert kept == ["shot"] and fake_encode == []


def test_a_recording_over_a_recorded_placeholder_stays_sourced_on_later_runs(tmp_manifest, tmp_path, fake_encode):
    m = _sounds(tmp_manifest)
    out = tmp_path / "wav"
    gen_sounds.generate(m, out, encode_mp3=True)
    (out / "assets" / "shot.mp3").write_bytes(b"layered shotgun blast")
    for _ in range(3):
        kept: list[str] = []
        unverified: list[str] = []
        gen_sounds.generate(m, out, encode_mp3=True, kept=kept, unverified=unverified)
        assert kept == ["shot"] and unverified == []
    assert (out / "assets" / "shot.mp3").read_bytes() == b"layered shotgun blast"


# ------------------------------------------- 1. docs: consent is explicit

DOCS = Path(__file__).resolve().parents[1] / "skills"


def test_run_modes_never_falls_back_to_a_paid_provider_without_opt_in():
    text = (DOCS / "cube_orchestrator" / "references" / "RUN_MODES.md").read_text(encoding="utf-8")
    assert "a configured paid provider" not in text
    assert "a paid\n   image provider if one is already configured" not in text
    assert "YOLO risk confirmation" in text and "НЕ разрешает платные API и скачивания" in text
    assert "--allow-paid" in text


def test_agent_safety_states_yolo_is_not_paid_consent():
    text = (DOCS / "cube_orchestrator" / "references" / "AGENT_SAFETY.md").read_text(encoding="utf-8")
    assert "No paid API without the user's explicit opt-in" in text and "`YOLO`" in text


def test_codex_calls_never_see_a_billable_key(monkeypatch, tmp_path):
    """A ChatGPT login is not enough if codex can still pick OPENAI_API_KEY / CODEX_API_KEY from the
    environment: every codex subprocess gets the environment without them."""
    import subprocess as sp
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "skills" / "cube_art-director" / "scripts"))
    import art_codex
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("CODEX_API_KEY", "sk-test-not-real")
    seen = []

    class R:
        returncode = 0
        stdout = "Logged in using ChatGPT"
        stderr = ""

    def fake_run(cmd, **kw):
        seen.append((cmd[1:3], kw.get("env")))
        return R()

    monkeypatch.setattr(art_codex.subprocess, "run", fake_run)
    monkeypatch.setattr(art_codex, "find_codex", lambda: "codex")
    monkeypatch.setattr(art_codex, "pick_model", lambda: ("m", "max"))
    monkeypatch.setattr(art_codex, "_login_ok", {})
    monkeypatch.setattr(art_codex.time, "sleep", lambda s: None)
    ok, _ = art_codex.run("x", "draw", [], tmp_path / "x.png", tmp_path / "logs", retries=1)
    assert not ok                                   # the fake draws nothing
    assert [c for c, _ in seen] == [["login", "status"], ["exec", "-m"]]
    for _, env in seen:
        assert env is not None and "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
