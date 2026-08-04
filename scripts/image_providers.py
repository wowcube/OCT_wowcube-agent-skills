"""Multi-provider image-generation adapter (design spec 2026-08-04 §4).

One interface, five providers, auto-detected from whatever key/URL the user
has. `genimg.generate_image()` stays the single entry point for callers; this
module supplies the provider underneath it.

Resolution chain (first hit wins) — `resolve_provider()`:
  1. `OPENROUTER_API_KEY` env var (backward compat, treated as OpenRouter key)
  2. `IMAGE_API` env var — JSON object or a bare key/URL
  3. config file `~/.wowcube/image_api.json` — same JSON shape
  4. nothing -> None (the caller decides: intake question / placeholder art)

Config JSON shape (every field optional):
    {"provider": "...", "key": "...", "base_url": "...", "model": "..."}
Missing `provider` is detected from `key`/`base_url` patterns.

Detection patterns — `detect_provider()`:
    sk-or-...     -> openrouter      sk-...    -> openai
    xai-...       -> xai             AIza...   -> gemini
    http(s)://... -> sd_a1111        else      -> UnknownProviderError

`save_provider(value)` persists a pasted key/URL (or config dict) to the
config file so the intake question never repeats.

All providers are non-streaming, use `(15, 180)` (connect, read) timeouts and
the same 4-attempt retry-with-backoff loop the original genimg used.
`validate()` is the cheapest possible authenticated call per provider (see
each class); failures raise ProviderValidationError.
"""
from __future__ import annotations

import base64
import json
import os
import time

from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

API_KEY_ENV = 'OPENROUTER_API_KEY'
IMAGE_API_ENV = 'IMAGE_API'
CONFIG_PATH = Path.home() / '.wowcube' / 'image_api.json'

# (connect timeout, read timeout) — without this a stalled socket hangs
# forever and the retry loop never triggers.
TIMEOUT = (15, 180)

_SUPPORTED_FORMS = (
    'supported forms: OpenRouter key (sk-or-...), OpenAI key (sk-...), '
    'xAI key (xai-...), Google Gemini key (AIza...), or a local Stable '
    'Diffusion URL (http://... / https://...)'
)


class ImageGenError(RuntimeError):
    """Raised when the API call fails or returns no image."""


class UnknownProviderError(ImageGenError):
    """Raised when a pasted key/URL matches no known provider pattern."""


class ProviderValidationError(ImageGenError):
    """Raised when the cheap `validate()` call fails (bad key, endpoint down)."""


@dataclass
class ProviderConfig:
    provider: str
    key: str | None = None
    base_url: str | None = None
    model: str | None = None


def detect_provider(value: str) -> str:
    """Map a pasted key/URL to a provider name (spec §4 detection table)."""
    v = value.strip()
    if v.startswith('sk-or-'):
        return 'openrouter'
    if v.startswith('sk-'):
        return 'openai'
    if v.startswith('xai-'):
        return 'xai'
    if v.startswith('AIza'):
        return 'gemini'
    if v.startswith('http://') or v.startswith('https://'):
        return 'sd_a1111'
    raise UnknownProviderError(
        f'cannot identify an image provider from {v[:12]!r}...; {_SUPPORTED_FORMS}'
    )


def _config_from_value(value: str) -> ProviderConfig:
    """Build a ProviderConfig from a bare key or URL."""
    v = value.strip()
    provider = detect_provider(v)
    if provider == 'sd_a1111':
        return ProviderConfig(provider=provider, base_url=v)
    return ProviderConfig(provider=provider, key=v)


def _config_from_dict(d: dict) -> ProviderConfig:
    """Build a ProviderConfig from a JSON object; detect provider if missing."""
    provider = d.get('provider')
    if not provider:
        seed = d.get('key') or d.get('base_url')
        if not seed:
            raise UnknownProviderError(
                f'image API config has neither "provider" nor a detectable '
                f'"key"/"base_url"; {_SUPPORTED_FORMS}'
            )
        provider = detect_provider(seed)
    return ProviderConfig(
        provider=provider,
        key=d.get('key'),
        base_url=d.get('base_url'),
        model=d.get('model'),
    )


def _parse_config_text(text: str) -> ProviderConfig:
    """Parse IMAGE_API / config-file content: JSON object or bare key/URL."""
    text = text.strip()
    if text.startswith('{'):
        return _config_from_dict(json.loads(text))
    return _config_from_value(text)


def resolve_provider() -> ProviderConfig | None:
    """Walk the resolution chain (spec §4); None means nothing is configured."""
    key = os.environ.get(API_KEY_ENV)
    if key:
        return ProviderConfig(provider='openrouter', key=key)

    image_api = os.environ.get(IMAGE_API_ENV)
    if image_api and image_api.strip():
        return _parse_config_text(image_api)

    if CONFIG_PATH.is_file():
        return _parse_config_text(CONFIG_PATH.read_text(encoding='utf-8'))

    return None


def save_provider(value: str | dict) -> ProviderConfig:
    """Persist a pasted key/URL (or a config dict) to the config file.

    Used by the orchestrator intake flow: the user pastes a key once, it is
    detected, written to `~/.wowcube/image_api.json`, and every later run
    resolves it from there. Raises UnknownProviderError (before writing
    anything) if the value matches no known pattern.
    """
    if isinstance(value, dict):
        config = _config_from_dict(value)
    else:
        config = _config_from_value(value)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in asdict(config).items() if v is not None}
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return config


# --------------------------------------------------------------------------
# Image helpers (moved from genimg.py)
# --------------------------------------------------------------------------

def base64_to_image(base64_string):
    """Decode a base64 encoded PNG/JPEG string into a PIL Image object."""
    try:
        for prefix in ('data:image/png;base64,', 'data:image/jpeg;base64,'):
            if base64_string.startswith(prefix):
                base64_string = base64_string[len(prefix):]
                break

        image_data = base64.b64decode(base64_string)
        return Image.open(BytesIO(image_data))
    except Exception as e:
        print(f'Error decoding base64: {e}')
        return None


def png_image_to_base64(filename):
    """Encode an image file into a base64 encoded PNG data URI."""
    try:
        image = Image.open(filename)
        buffered = BytesIO()
        image.save(buffered, format='PNG')
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return f'data:image/png;base64,{img_str}'
    except Exception as e:
        print(f'Error encoding image to base64: {e}')
        return None


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class ImageProvider:
    """Base class: shared retry loop + auth header; subclasses implement
    `_request(prompt, reference)` (one HTTP call -> PIL Image or None) and
    `validate()` (cheapest authenticated call)."""

    #: default model, overridable via ProviderConfig.model
    default_model = None

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.model = config.model or self.default_model

    @property
    def name(self) -> str:
        return self.config.provider

    def generate(self, prompt: str, *, reference=None):
        """Call the provider and return a PIL Image, or None if the model
        answered without an image (e.g. a content refusal — NOT retried).

        Transient network failures (premature close, chunked-encoding error,
        timeouts) are common on slow image endpoints, so each request is
        retried up to 4 times with linear backoff — the exact behaviour of the
        original genimg OpenRouter client.
        """
        last_err = None
        for attempt in range(4):
            try:
                return self._request(prompt, reference=reference)
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt < 3:
                    time.sleep(2.0 * (attempt + 1))
        raise ImageGenError(
            f'{self.name} request failed after retries: {last_err}') from last_err

    def _auth_headers(self) -> dict:
        return {
            'Authorization': f'Bearer {self.config.key}',
            'Content-Type': 'application/json',
        }

    def _request(self, prompt, *, reference=None):
        raise NotImplementedError

    def validate(self) -> None:
        raise NotImplementedError

    def _validated_get(self, url, **kwargs):
        """GET that converts any failure into ProviderValidationError."""
        try:
            response = requests.get(url, timeout=(15, 30), **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise ProviderValidationError(
                f'{self.name} validation failed ({url}): {e}') from e


class OpenRouterProvider(ImageProvider):
    """OpenRouter chat-completions image generation (the original genimg code).

    Endpoint: POST https://openrouter.ai/api/v1/chat/completions
    The model returns the generated image in the final assistant message
    (choices[0].message.images), not in streaming deltas.
    """

    API_URL = 'https://openrouter.ai/api/v1/chat/completions'
    default_model = 'openai/gpt-5.4-image-2'

    def _request(self, prompt, *, reference=None):
        content = [{'type': 'text', 'text': prompt}]
        if reference:
            content.append({
                'type': 'image_url',
                'image_url': {'url': png_image_to_base64(str(reference))},
            })

        payload = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': content}],
            'stream': False,
        }

        response = requests.post(
            url=self.API_URL,
            headers=self._auth_headers(),
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        data = response.json()
        choices = data.get('choices') or []
        if not choices:
            return None

        message = choices[0].get('message') or {}
        images = message.get('images') or []
        if images:
            base64_url = images[0]['image_url']['url']
            return base64_to_image(base64_url)

        return None

    def validate(self) -> None:
        # GET /api/v1/key returns the key's own metadata (limits/usage) —
        # authenticated, free, no model invocation.
        self._validated_get('https://openrouter.ai/api/v1/key',
                            headers={'Authorization': f'Bearer {self.config.key}'})


class OpenAIProvider(ImageProvider):
    """OpenAI Images API.

    Endpoint: POST https://api.openai.com/v1/images/generations
    gpt-image-* models return the image as base64 in data[0].b64_json.
    Reference images are not sent (that needs the multipart /images/edits
    endpoint); the reference argument is ignored here.
    """

    API_URL = 'https://api.openai.com/v1/images/generations'
    default_model = 'gpt-image-1'

    def _request(self, prompt, *, reference=None):
        payload = {'model': self.model, 'prompt': prompt}
        response = requests.post(
            url=self.API_URL,
            headers=self._auth_headers(),
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        data = (response.json().get('data') or [])
        if data and data[0].get('b64_json'):
            return base64_to_image(data[0]['b64_json'])
        return None

    def validate(self) -> None:
        # GET /v1/models — cheapest authenticated call (no generation billed).
        self._validated_get('https://api.openai.com/v1/models',
                            headers={'Authorization': f'Bearer {self.config.key}'})


class XAIProvider(ImageProvider):
    """xAI (Grok) image generation — OpenAI-compatible images endpoint.

    Endpoint: POST https://api.x.ai/v1/images/generations
    `response_format: "b64_json"` puts the image bytes in data[0].b64_json.
    Reference images are not supported; the argument is ignored.
    """

    API_URL = 'https://api.x.ai/v1/images/generations'
    default_model = 'grok-2-image'

    def _request(self, prompt, *, reference=None):
        payload = {
            'model': self.model,
            'prompt': prompt,
            'response_format': 'b64_json',
        }
        response = requests.post(
            url=self.API_URL,
            headers=self._auth_headers(),
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        data = (response.json().get('data') or [])
        if data and data[0].get('b64_json'):
            return base64_to_image(data[0]['b64_json'])
        return None

    def validate(self) -> None:
        # GET /v1/models — cheapest authenticated call.
        self._validated_get('https://api.x.ai/v1/models',
                            headers={'Authorization': f'Bearer {self.config.key}'})


class GeminiProvider(ImageProvider):
    """Google Gemini image generation ("nano banana").

    Endpoint: POST https://generativelanguage.googleapis.com/v1beta/models/
              {model}:generateContent   (header x-goog-api-key)
    Image comes back as a base64 inlineData part inside the first candidate.
    Reference images are not sent; the argument is ignored.
    """

    API_BASE = 'https://generativelanguage.googleapis.com/v1beta'
    default_model = 'gemini-2.5-flash-image'

    def _request(self, prompt, *, reference=None):
        payload = {
            'contents': [{'parts': [{'text': prompt}]}],
            # ask for an image back explicitly — text-only is the default
            'generationConfig': {'responseModalities': ['TEXT', 'IMAGE']},
        }
        response = requests.post(
            url=f'{self.API_BASE}/models/{self.model}:generateContent',
            headers={'x-goog-api-key': self.config.key,
                     'Content-Type': 'application/json'},
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        candidates = response.json().get('candidates') or []
        if not candidates:
            return None
        parts = (candidates[0].get('content') or {}).get('parts') or []
        for part in parts:
            # REST responses use camelCase; some client shims emit snake_case
            inline = part.get('inlineData') or part.get('inline_data')
            if inline and inline.get('data'):
                return base64_to_image(inline['data'])
        return None

    def validate(self) -> None:
        # GET /v1beta/models — cheapest authenticated call (lists models).
        self._validated_get(f'{self.API_BASE}/models',
                            headers={'x-goog-api-key': self.config.key})


class SDA1111Provider(ImageProvider):
    """Local/self-hosted Stable Diffusion, Automatic1111-compatible API.

    Endpoint: POST {base_url}/sdapi/v1/txt2img
    Response: {"images": ["<base64 png>", ...]} — no auth by default.
    Reference images are not sent (img2img is a different endpoint); the
    argument is ignored.
    """

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self.base_url = (config.base_url or '').rstrip('/')

    def _request(self, prompt, *, reference=None):
        payload = {'prompt': prompt}
        if self.model:
            # A1111 selects the checkpoint via an override, not a 'model' field
            payload['override_settings'] = {'sd_model_checkpoint': self.model}
        response = requests.post(
            url=f'{self.base_url}/sdapi/v1/txt2img',
            json=payload,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

        images = response.json().get('images') or []
        if images:
            return base64_to_image(images[0])
        return None

    def validate(self) -> None:
        # GET /sdapi/v1/sd-models — cheapest call proving the server is an
        # A1111-compatible endpoint that is up and has checkpoints loaded.
        self._validated_get(f'{self.base_url}/sdapi/v1/sd-models')


PROVIDERS = {
    'openrouter': OpenRouterProvider,
    'openai': OpenAIProvider,
    'xai': XAIProvider,
    'gemini': GeminiProvider,
    'sd_a1111': SDA1111Provider,
}


def get_provider(config: ProviderConfig) -> ImageProvider:
    """Instantiate the provider implementation for `config`."""
    cls = PROVIDERS.get(config.provider)
    if cls is None:
        raise UnknownProviderError(
            f'unknown image provider {config.provider!r}; '
            f'known: {", ".join(sorted(PROVIDERS))}'
        )
    return cls(config)


def validate(config: ProviderConfig) -> None:
    """Cheapest possible authenticated call for `config`'s provider.

    Raises ProviderValidationError on any failure (bad key, endpoint down).
    """
    get_provider(config).validate()
