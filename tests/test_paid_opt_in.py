"""Paid image APIs are opt-in (the e2e friction log: OPENROUTER_API_KEY sat in
the user's environment for something else, and the provider chain fell
through to it whenever Codex was unavailable).

Codex (ChatGPT subscription) first; a key from OPENROUTER_API_KEY, IMAGE_API
or ~/.wowcube/image_api.json is used only with WOWCUBE_ALLOW_PAID_IMAGES=1 or
`--allow-paid`; otherwise generation stops with a clear message. The host
environment never leaks in: every source is cleared or redirected here.
"""
from __future__ import annotations

import json

import pytest

import build_pipeline
import genimg
import gen_sprites
import image_providers as ip


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for var in (ip.ALLOW_PAID_ENV, ip.API_KEY_ENV, ip.IMAGE_API_ENV, ip.ART_PY_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(ip.NO_CODEX_ENV, "1")                 # no Codex on this "machine"
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "cfg" / "image_api.json")

    def _guard(argv, **kwargs):
        raise AssertionError(f"unexpected subprocess: {argv}")
    monkeypatch.setattr(ip, "_run", _guard)

    def _no_paid_call(*a, **k):
        raise AssertionError("a paid image API was called")
    monkeypatch.setattr(genimg, "generate_image", _no_paid_call)
    ip._codex_login_cache.clear()
    yield
    ip._codex_login_cache.clear()


@pytest.mark.parametrize("source", ["openrouter_env", "image_api_env", "config_file"])
def test_an_inherited_key_is_never_used_without_the_opt_in(monkeypatch, source):
    if source == "openrouter_env":
        monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-inherited")
    elif source == "image_api_env":
        monkeypatch.setenv(ip.IMAGE_API_ENV, "sk-openai-inherited")
    else:
        ip.CONFIG_PATH.parent.mkdir(parents=True)
        ip.CONFIG_PATH.write_text(json.dumps({"provider": "xai", "key": "xai-x"}), encoding="utf-8")
    with pytest.raises(ip.PaidProviderNotAllowed) as e:
        ip.resolve_provider()
    msg = str(e.value)
    assert ip.ALLOW_PAID_ENV in msg and "--allow-paid" in msg and "codex login" in msg


def test_the_opt_in_env_and_kwarg_enable_the_key_chain(monkeypatch):
    monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-key")
    assert ip.resolve_provider(allow_paid=True).provider == "openrouter"
    monkeypatch.setenv(ip.ALLOW_PAID_ENV, "1")
    assert ip.resolve_provider().provider == "openrouter"
    with pytest.raises(ip.PaidProviderNotAllowed):
        ip.resolve_provider(allow_paid=False)                  # an explicit False wins over the env


@pytest.mark.parametrize("value,allowed", [("1", True), ("true", True), ("yes", True), ("0", False),
                                           ("", False), ("no", False)])
def test_opt_in_values(monkeypatch, value, allowed):
    monkeypatch.setenv(ip.ALLOW_PAID_ENV, value)
    assert ip.paid_allowed() is allowed


def test_nothing_configured_is_still_none():
    assert ip.resolve_provider() is None


def test_codex_needs_no_opt_in(monkeypatch):
    monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-key")
    monkeypatch.setattr(ip, "detect_codex", lambda: ip.ProviderConfig(provider="codex", cli="codex.exe"))
    assert ip.resolve_provider().provider == "codex"


# ── build_pipeline generate / gen_sprites / genimg ───────────────────────────

def _manifest(tmp_path):
    p = tmp_path / "plans" / "demo_assets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"game": "demo", "schema_version": 1, "sprites": [
        {"name": "coin", "size": [8, 8], "description": "d", "gen_prompt": "A coin."}], "sounds": []}),
        encoding="utf-8")
    return p


def test_generate_stops_instead_of_paying(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-inherited")
    rc = build_pipeline._cli(["generate", "--manifest", str(_manifest(tmp_path)),
                              "--workspace", str(tmp_path / "assets_demo")])
    assert rc == 3
    err = capsys.readouterr().err
    assert "PAID/external API" in err and ip.ALLOW_PAID_ENV in err
    assert not (tmp_path / "assets_demo" / "art").exists()


def test_generate_allow_paid_flag_opts_in_for_this_run_only(tmp_path, monkeypatch, capsys):
    from PIL import Image
    monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-key")
    drawn = []

    def _fake(prompt, out_path, *, size=None, reference=None, cutout=False):
        drawn.append(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", tuple(size), (1, 2, 3, 255)).save(out_path)
        return out_path
    monkeypatch.setattr(genimg, "generate_image", _fake)
    rc = build_pipeline._cli(["generate", "--manifest", str(_manifest(tmp_path)),
                              "--workspace", str(tmp_path / "assets_demo"), "--allow-paid"])
    assert rc == 0 and len(drawn) == 1
    assert "PAID openrouter API" in capsys.readouterr().out
    assert not ip.paid_allowed()                               # restored after the run


def test_gen_sprites_cli_stops_without_the_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(ip.IMAGE_API_ENV, "xai-inherited")
    assert gen_sprites.main([str(_manifest(tmp_path))]) == 1
    assert ip.ALLOW_PAID_ENV in capsys.readouterr().err


def test_genimg_without_provider_argument_respects_the_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(genimg, "generate_image", genimg.__dict__["generate_image"])
    monkeypatch.undo()                                         # the real generate_image, still isolated below
    for var in (ip.ALLOW_PAID_ENV, ip.IMAGE_API_ENV, ip.ART_PY_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(ip.NO_CODEX_ENV, "1")
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "none.json")
    monkeypatch.setenv(ip.API_KEY_ENV, "sk-or-inherited")
    monkeypatch.setattr(ip, "get_provider", lambda cfg: (_ for _ in ()).throw(AssertionError("paid call")))
    with pytest.raises(ip.PaidProviderNotAllowed):
        genimg.generate_image("a coin", tmp_path / "coin.png", size=(8, 8))
