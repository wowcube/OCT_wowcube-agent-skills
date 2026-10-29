"""Tests for scripts/image_providers.py — multi-provider image adapter.

No live network anywhere: every provider test monkeypatches
`image_providers.requests` with fakes and asserts request assembly +
response parsing against canned JSON.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

import image_providers as ip
import genimg


# ---------------------------------------------------------------- helpers

def _tiny_png_b64() -> str:
    """Base64 of a real 2x2 RGBA PNG (decodable by PIL)."""
    img = Image.new("RGBA", (2, 2), (10, 200, 30, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


@pytest.fixture
def no_env(monkeypatch, tmp_path):
    """Clear every resolution source: env vars gone, config path -> empty tmp."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_API", raising=False)
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "image_api.json")
    return tmp_path


@pytest.fixture
def capture_post(monkeypatch):
    """Replace requests.post with a recorder returning a canned response."""
    calls: list[dict] = []

    def install(payload: dict, status: int = 200):
        def _post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse(payload, status)
        monkeypatch.setattr(ip.requests, "post", _post)
        return calls

    return install


@pytest.fixture
def capture_get(monkeypatch):
    calls: list[dict] = []

    def install(payload: dict, status: int = 200):
        def _get(url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse(payload, status)
        monkeypatch.setattr(ip.requests, "get", _get)
        return calls

    return install


# ---------------------------------------------------------------- detection

@pytest.mark.parametrize("value,provider", [
    ("sk-or-v1-abcdef", "openrouter"),
    ("sk-proj-abcdef", "openai"),
    ("xai-abcdef", "xai"),
    ("AIzaSyAbCdEf123", "gemini"),
    ("http://127.0.0.1:7860", "sd_a1111"),
    ("https://sd.example.com", "sd_a1111"),
])
def test_detect_provider_table(value, provider):
    assert ip.detect_provider(value) == provider


def test_detect_provider_strips_whitespace():
    assert ip.detect_provider("  sk-or-key \n") == "openrouter"


def test_detect_provider_unknown_names_supported_forms():
    with pytest.raises(ip.UnknownProviderError) as ei:
        ip.detect_provider("totally-not-a-key")
    msg = str(ei.value)
    for form in ("sk-or-", "sk-", "xai-", "AIza", "http"):
        assert form in msg


# ---------------------------------------------------------------- resolution chain

def test_resolve_none_when_nothing_configured(no_env):
    assert ip.resolve_provider() is None


def test_resolve_openrouter_env_wins_over_everything(no_env, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key")
    monkeypatch.setenv("IMAGE_API", "sk-openai-key")
    ip.CONFIG_PATH.write_text(json.dumps({"provider": "xai", "key": "xai-x"}),
                              encoding="utf-8")
    cfg = ip.resolve_provider()
    assert cfg.provider == "openrouter"
    assert cfg.key == "sk-or-env-key"


def test_resolve_image_api_bare_key(no_env, monkeypatch):
    monkeypatch.setenv("IMAGE_API", "xai-abc123")
    cfg = ip.resolve_provider()
    assert cfg.provider == "xai"
    assert cfg.key == "xai-abc123"


def test_resolve_image_api_bare_url(no_env, monkeypatch):
    monkeypatch.setenv("IMAGE_API", "http://localhost:7860")
    cfg = ip.resolve_provider()
    assert cfg.provider == "sd_a1111"
    assert cfg.base_url == "http://localhost:7860"


def test_resolve_image_api_json(no_env, monkeypatch):
    monkeypatch.setenv("IMAGE_API", json.dumps(
        {"provider": "openai", "key": "sk-x", "model": "gpt-image-1"}))
    cfg = ip.resolve_provider()
    assert cfg.provider == "openai"
    assert cfg.key == "sk-x"
    assert cfg.model == "gpt-image-1"


def test_resolve_image_api_json_detects_missing_provider(no_env, monkeypatch):
    monkeypatch.setenv("IMAGE_API", json.dumps({"key": "sk-or-abc"}))
    cfg = ip.resolve_provider()
    assert cfg.provider == "openrouter"


def test_resolve_image_api_wins_over_config_file(no_env, monkeypatch):
    monkeypatch.setenv("IMAGE_API", "sk-openai")
    ip.CONFIG_PATH.write_text(json.dumps({"provider": "xai", "key": "xai-x"}),
                              encoding="utf-8")
    assert ip.resolve_provider().provider == "openai"


def test_resolve_config_file(no_env):
    ip.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ip.CONFIG_PATH.write_text(json.dumps(
        {"provider": "sd_a1111", "base_url": "http://10.0.0.5:7860"}),
        encoding="utf-8")
    cfg = ip.resolve_provider()
    assert cfg.provider == "sd_a1111"
    assert cfg.base_url == "http://10.0.0.5:7860"


# ---------------------------------------------------------------- save/load

def test_save_provider_roundtrip(no_env):
    saved = ip.save_provider("AIzaSyTest123")
    assert saved.provider == "gemini"
    assert ip.CONFIG_PATH.is_file()
    loaded = ip.resolve_provider()
    assert loaded == saved


def test_save_provider_url_roundtrip(no_env):
    saved = ip.save_provider("https://sd.lan:7860")
    assert saved.provider == "sd_a1111"
    assert saved.base_url == "https://sd.lan:7860"
    assert ip.resolve_provider() == saved


def test_save_provider_dict(no_env):
    saved = ip.save_provider({"provider": "openai", "key": "sk-z", "model": "gpt-image-1"})
    assert saved.model == "gpt-image-1"
    assert ip.resolve_provider() == saved


def test_save_provider_unknown_raises_and_writes_nothing(no_env):
    with pytest.raises(ip.UnknownProviderError):
        ip.save_provider("garbage")
    assert not ip.CONFIG_PATH.exists()


# ---------------------------------------------------------------- per-provider txt2img

def test_openrouter_request_and_parse(capture_post):
    calls = capture_post({
        "choices": [{"message": {"images": [
            {"image_url": {"url": "data:image/png;base64," + _tiny_png_b64()}},
        ]}}],
    })
    prov = ip.get_provider(ip.ProviderConfig(provider="openrouter", key="sk-or-k"))
    img = prov.generate("a red coin")
    assert img.size == (2, 2)

    call = calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-or-k"
    assert call["timeout"] == (15, 180)
    payload = json.loads(call["data"])
    assert payload["stream"] is False
    assert payload["model"] == "openai/gpt-5.4-image-2"
    assert payload["messages"][0]["content"][0] == {"type": "text", "text": "a red coin"}


def test_openrouter_reference_image(capture_post, tmp_path):
    ref = tmp_path / "ref.png"
    Image.new("RGBA", (2, 2), (1, 2, 3, 255)).save(ref)
    calls = capture_post({
        "choices": [{"message": {"images": [
            {"image_url": {"url": "data:image/png;base64," + _tiny_png_b64()}},
        ]}}],
    })
    prov = ip.get_provider(ip.ProviderConfig(provider="openrouter", key="sk-or-k"))
    prov.generate("variant", reference=ref)
    payload = json.loads(calls[0]["data"])
    content = payload["messages"][0]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openrouter_no_image_returns_none(capture_post):
    capture_post({"choices": [{"message": {"content": "sorry, no"}}]})
    prov = ip.get_provider(ip.ProviderConfig(provider="openrouter", key="sk-or-k"))
    assert prov.generate("nope") is None


def test_openai_request_and_parse(capture_post):
    calls = capture_post({"data": [{"b64_json": _tiny_png_b64()}]})
    prov = ip.get_provider(ip.ProviderConfig(provider="openai", key="sk-k"))
    img = prov.generate("a coin")
    assert img.size == (2, 2)

    call = calls[0]
    assert call["url"] == "https://api.openai.com/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-k"
    assert call["timeout"] == (15, 180)
    assert call["json"]["prompt"] == "a coin"
    assert call["json"]["model"] == "gpt-image-1"


def test_xai_request_and_parse(capture_post):
    calls = capture_post({"data": [{"b64_json": _tiny_png_b64()}]})
    prov = ip.get_provider(ip.ProviderConfig(provider="xai", key="xai-k"))
    img = prov.generate("a coin")
    assert img.size == (2, 2)

    call = calls[0]
    assert call["url"] == "https://api.x.ai/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer xai-k"
    assert call["json"]["model"] == "grok-2-image"
    assert call["json"]["response_format"] == "b64_json"


def test_gemini_request_and_parse(capture_post):
    calls = capture_post({
        "candidates": [{"content": {"parts": [
            {"text": "here you go"},
            {"inlineData": {"mimeType": "image/png", "data": _tiny_png_b64()}},
        ]}}],
    })
    prov = ip.get_provider(ip.ProviderConfig(provider="gemini", key="AIza-k"))
    img = prov.generate("a coin")
    assert img.size == (2, 2)

    call = calls[0]
    assert "generativelanguage.googleapis.com" in call["url"]
    assert ":generateContent" in call["url"]
    assert call["headers"]["x-goog-api-key"] == "AIza-k"
    assert call["json"]["contents"][0]["parts"][0]["text"] == "a coin"
    assert "IMAGE" in call["json"]["generationConfig"]["responseModalities"]


def test_gemini_parses_snake_case_inline_data(capture_post):
    capture_post({
        "candidates": [{"content": {"parts": [
            {"inline_data": {"mime_type": "image/png", "data": _tiny_png_b64()}},
        ]}}],
    })
    prov = ip.get_provider(ip.ProviderConfig(provider="gemini", key="AIza-k"))
    assert prov.generate("a coin").size == (2, 2)


def test_sd_a1111_request_and_parse(capture_post):
    calls = capture_post({"images": [_tiny_png_b64()]})
    prov = ip.get_provider(
        ip.ProviderConfig(provider="sd_a1111", base_url="http://sd.lan:7860/"))
    img = prov.generate("a coin")
    assert img.size == (2, 2)

    call = calls[0]
    assert call["url"] == "http://sd.lan:7860/sdapi/v1/txt2img"
    assert call["json"]["prompt"] == "a coin"
    assert call["timeout"] == (15, 180)


def test_model_override_from_config(capture_post):
    calls = capture_post({"data": [{"b64_json": _tiny_png_b64()}]})
    prov = ip.get_provider(
        ip.ProviderConfig(provider="openai", key="sk-k", model="gpt-image-1-mini"))
    prov.generate("x")
    assert calls[0]["json"]["model"] == "gpt-image-1-mini"


def test_get_provider_unknown_name():
    with pytest.raises(ip.UnknownProviderError):
        ip.get_provider(ip.ProviderConfig(provider="dalle-9000"))


# ---------------------------------------------------------------- retry behaviour

def test_generate_retries_then_raises(monkeypatch):
    import requests as real_requests
    attempts = []

    def _post(url, **kwargs):
        attempts.append(url)
        raise real_requests.exceptions.ConnectionError("boom")

    sleeps = []
    monkeypatch.setattr(ip.requests, "post", _post)
    monkeypatch.setattr(ip.time, "sleep", lambda s: sleeps.append(s))

    prov = ip.get_provider(ip.ProviderConfig(provider="openai", key="sk-k"))
    with pytest.raises(ip.ImageGenError, match="after retries"):
        prov.generate("x")
    assert len(attempts) == 4
    assert sleeps == [2.0, 4.0, 6.0]


def test_generate_recovers_after_transient_failure(monkeypatch):
    import requests as real_requests
    state = {"n": 0}

    def _post(url, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise real_requests.exceptions.ConnectionError("flaky")
        return FakeResponse({"data": [{"b64_json": _tiny_png_b64()}]})

    monkeypatch.setattr(ip.requests, "post", _post)
    monkeypatch.setattr(ip.time, "sleep", lambda s: None)

    prov = ip.get_provider(ip.ProviderConfig(provider="openai", key="sk-k"))
    assert prov.generate("x").size == (2, 2)
    assert state["n"] == 2


# ---------------------------------------------------------------- validate()

@pytest.mark.parametrize("provider,key,url_frag", [
    ("openrouter", "sk-or-k", "openrouter.ai/api/v1/key"),
    ("openai", "sk-k", "api.openai.com/v1/models"),
    ("xai", "xai-k", "api.x.ai/v1/models"),
    ("gemini", "AIza-k", "generativelanguage.googleapis.com/v1beta/models"),
])
def test_validate_hits_cheap_endpoint(capture_get, provider, key, url_frag):
    calls = capture_get({"data": []})
    prov = ip.get_provider(ip.ProviderConfig(provider=provider, key=key))
    prov.validate()
    assert url_frag in calls[0]["url"]


def test_validate_sd_a1111_lists_models(capture_get):
    calls = capture_get([{"title": "v1-5"}])
    prov = ip.get_provider(
        ip.ProviderConfig(provider="sd_a1111", base_url="http://sd.lan:7860"))
    prov.validate()
    assert calls[0]["url"] == "http://sd.lan:7860/sdapi/v1/sd-models"


def test_validate_failure_raises_provider_validation_error(capture_get):
    capture_get({"error": "bad key"}, status=401)
    prov = ip.get_provider(ip.ProviderConfig(provider="openai", key="sk-bad"))
    with pytest.raises(ip.ProviderValidationError):
        prov.validate()


def test_validate_network_failure_raises(monkeypatch):
    import requests as real_requests

    def _get(url, **kwargs):
        raise real_requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(ip.requests, "get", _get)
    prov = ip.get_provider(
        ip.ProviderConfig(provider="sd_a1111", base_url="http://sd.lan:7860"))
    with pytest.raises(ip.ProviderValidationError):
        prov.validate()


# ---------------------------------------------------------------- genimg facade

def test_genimg_error_is_shared():
    """`genimg.ImageGenError` and the adapter's error are the same class, so
    existing `except genimg.ImageGenError` callers catch provider failures."""
    assert genimg.ImageGenError is ip.ImageGenError
    assert issubclass(ip.ImageGenError, RuntimeError)
    assert genimg.API_KEY_ENV == "OPENROUTER_API_KEY"


def test_generate_image_no_provider_raises(no_env, tmp_path):
    with pytest.raises(genimg.ImageGenError):
        genimg.generate_image("a coin", tmp_path / "out.png")


def test_generate_image_end_to_end_openrouter(no_env, monkeypatch, capture_post, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-k")
    capture_post({
        "choices": [{"message": {"images": [
            {"image_url": {"url": "data:image/png;base64," + _tiny_png_b64()}},
        ]}}],
    })
    out = tmp_path / "sub" / "coin.png"
    result = genimg.generate_image("a coin", out, size=(8, 8))
    assert result == out
    img = Image.open(out)
    assert img.size == (8, 8)
    assert img.mode == "RGBA"


def test_generate_image_none_result_raises(no_env, monkeypatch, capture_post, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-k")
    capture_post({"choices": [{"message": {"content": "refused"}}]})
    with pytest.raises(genimg.ImageGenError, match="no image returned"):
        genimg.generate_image("a coin", tmp_path / "x.png")
