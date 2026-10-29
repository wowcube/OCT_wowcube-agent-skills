"""Image-generation providers for cube_asset-builder.

Resolution chain (first hit wins) — `resolve_provider()`:
  0. `codex` (the DEFAULT, no key): a Codex CLI logged in with the user's
     ChatGPT account. Found as the newest
     %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe (Windows installs are often
     not on PATH) or `codex` on PATH; `codex login status` must mention
     ChatGPT. Skipped when WOWCUBE_NO_CODEX=1 (forces the key chain below).
  1. `OPENROUTER_API_KEY` env var (backward compat, treated as OpenRouter key)
  2. `IMAGE_API` env var — JSON object or a bare key/URL
  3. config file `~/.wowcube/image_api.json` — same JSON shape
  4. nothing -> None (the caller decides: agent-drawn placeholder art, never final)

Steps 1-3 are paid (or at least external) APIs and are OPT-IN: a key that
merely sits in the environment (set for something else) is never used
silently. Without WOWCUBE_ALLOW_PAID_IMAGES=1 (or `allow_paid=True`; the
generate CLIs have `--allow-paid`), finding one raises PaidProviderNotAllowed
with the reason, instead of falling through to it. Set the opt-in only after
the user agreed to pay per image. Exception: a Stable Diffusion server on this
machine (`http://localhost`, `127.x.x.x`, `[::1]`) costs nothing and leaves no
machine, so it needs no opt-in (`is_local_url()`); any other URL does.

Codex never runs through this module's HTTP code: drawing is delegated to
cube_art-director's `art.py` (one code path for prompts, Codex quirks, chroma
keying, set fitting and colour lock). `codex_generate()` draws a whole
WowCube manifest (`art.py gen` then `art.py process`); `codex_draw()` draws
one image through a throw-away art.json (genimg one-offs).

Config JSON shape (every field optional):
    {"provider": "...", "key": "...", "base_url": "...", "model": "..."}
Missing `provider` is detected from `key`/`base_url` patterns.

Detection patterns — `detect_provider()`:
    sk-or-...     -> openrouter      sk-...    -> openai
    xai-...       -> xai             AIza...   -> gemini
    http(s)://... -> sd_a1111        else      -> UnknownProviderError

`save_provider(value)` persists a pasted key/URL (or config dict) to the
config file so the intake question never repeats. The file holds a secret: it
is created owner-only (0600, its folder 0700) on POSIX; on Windows chmod cannot
express that, so it relies on the per-user ACL of the user profile folder
(best effort, documented in cube_asset-builder/references/ART.md).

The HTTP providers are non-streaming, use `(15, 180)` (connect, read)
timeouts and the same 4-attempt retry-with-backoff loop the original genimg
used. `validate()` is the cheapest possible authenticated call per provider
(for codex: `codex login status`); failures raise ProviderValidationError.
"""
from __future__ import annotations

import base64
import glob
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from dataclasses import dataclass, asdict
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

API_KEY_ENV = 'OPENROUTER_API_KEY'
IMAGE_API_ENV = 'IMAGE_API'
CONFIG_PATH = Path.home() / '.wowcube' / 'image_api.json'

CODEX_PROVIDER = 'codex'
# '1' skips Codex detection, so the key chain (OPENROUTER_API_KEY -> IMAGE_API
# -> config file) decides even when a logged-in Codex CLI is installed.
NO_CODEX_ENV = 'WOWCUBE_NO_CODEX'
# '1' = the user agreed to pay per image: only then may the key chain
# (OPENROUTER_API_KEY -> IMAGE_API -> config file) be used.
ALLOW_PAID_ENV = 'WOWCUBE_ALLOW_PAID_IMAGES'
# Optional override for where cube_art-director's art.py lives.
ART_PY_ENV = 'WOWCUBE_ART_PY'
_ART_PY_REL = Path('skills') / 'cube_art-director' / 'scripts' / 'art.py'
# `codex login status` per CLI path, checked once per process (resolve_provider
# runs more than once per pipeline run).
_codex_login_cache: dict[str, tuple[bool, str]] = {}

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


class PaidProviderNotAllowed(ImageGenError):
    """Codex is not available and the only provider found is a paid/external
    API that was not opted in (WOWCUBE_ALLOW_PAID_IMAGES=1 / --allow-paid)."""


@dataclass
class ProviderConfig:
    provider: str
    key: str | None = None
    base_url: str | None = None
    model: str | None = None
    cli: str | None = None          # codex: path of the Codex CLI binary


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


# --------------------------------------------------------------------------
# Codex CLI (ChatGPT subscription): detection
# --------------------------------------------------------------------------

def _run(argv, **kwargs):
    """The one subprocess seam of this module (Codex login check, art.py).
    Tests replace it; nothing in the test suite ever reaches a real Codex."""
    return subprocess.run(argv, **kwargs)


def find_codex_cli() -> str | None:
    """Newest %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe, else `codex` on
    PATH, else None (same discovery as cube_art-director's art_codex.py)."""
    local = os.environ.get('LOCALAPPDATA')
    if local:
        found = glob.glob(os.path.join(local, 'OpenAI', 'Codex', 'bin', '*', 'codex.exe'))
        if found:
            return max(found, key=os.path.getmtime)
    return shutil.which('codex')


def codex_login_status(exe: str, *, use_cache: bool = True) -> tuple[bool, str]:
    """(logged in with ChatGPT?, first line of `codex login status`).

    An API-key login does not count: the pipeline only uses Codex on the
    user's ChatGPT subscription. Never logs in or types credentials; when this
    is False the user runs `codex login` themselves."""
    if use_cache and exe in _codex_login_cache:
        return _codex_login_cache[exe]
    try:
        r = _run([exe, 'login', 'status'], capture_output=True, text=True,
                 encoding='utf-8', errors='replace', timeout=60)
        out = f'{r.stdout or ""}\n{r.stderr or ""}'.strip()
        low = out.lower()
        ok = (r.returncode == 0 and 'chatgpt' in low and 'not logged in' not in low
              and 'api key' not in low and 'api_key' not in low)
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), 'no output')
        result = (ok, first)
    except (OSError, subprocess.TimeoutExpired) as e:
        result = (False, f'`codex login status` failed: {e}')
    _codex_login_cache[exe] = result
    return result


def detect_codex() -> ProviderConfig | None:
    """The codex step of the chain: a ProviderConfig when a Codex CLI is
    installed and logged in with ChatGPT (and WOWCUBE_NO_CODEX is not set)."""
    if os.environ.get(NO_CODEX_ENV, '').strip().lower() not in ('', '0', 'false', 'no'):
        return None
    exe = find_codex_cli()
    if not exe:
        return None
    ok, _ = codex_login_status(exe)
    return ProviderConfig(provider=CODEX_PROVIDER, cli=exe) if ok else None


def paid_allowed() -> bool:
    """True when the user opted in to paid image APIs (WOWCUBE_ALLOW_PAID_IMAGES=1)."""
    return os.environ.get(ALLOW_PAID_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def paid_chain() -> tuple[ProviderConfig, str] | None:
    """The key chain alone (steps 1-3): (config, where it came from) or None.
    Never checks the opt-in - resolve_provider() does."""
    key = os.environ.get(API_KEY_ENV)
    if key:
        return ProviderConfig(provider='openrouter', key=key), f'the {API_KEY_ENV} environment variable'

    image_api = os.environ.get(IMAGE_API_ENV)
    if image_api and image_api.strip():
        return _parse_config_text(image_api), f'the {IMAGE_API_ENV} environment variable'

    if CONFIG_PATH.is_file():
        return _parse_config_text(CONFIG_PATH.read_text(encoding='utf-8')), str(CONFIG_PATH)

    return None


def is_local_url(url: str | None) -> bool:
    """True for an http(s) URL whose host is this machine: `localhost` (or
    `*.localhost`), any 127.0.0.0/8 address or `::1`. A LAN or hosted URL is
    False (someone else's server, possibly billed)."""
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ('http', 'https') or not host:
        return False
    host = host.rstrip('.').lower()
    if host == 'localhost' or host.endswith('.localhost'):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_free_local(config: ProviderConfig) -> bool:
    """A local Stable Diffusion server: no paid opt-in needed."""
    return config.provider == 'sd_a1111' and is_local_url(config.base_url)


def resolve_provider(*, allow_paid: bool | None = None) -> ProviderConfig | None:
    """Walk the resolution chain (module docstring); None means nothing is
    configured. Codex comes first: a logged-in CLI needs no key.

    A paid/external provider from the key chain is returned only when
    `allow_paid` is True, or (when it is None) WOWCUBE_ALLOW_PAID_IMAGES=1;
    otherwise PaidProviderNotAllowed explains what was found and how to
    proceed - an inherited key is never used silently."""
    codex = detect_codex()
    if codex is not None:
        return codex

    found = paid_chain()
    if found is None:
        return None
    config, source = found
    if is_free_local(config):
        return config
    if allow_paid is None:
        allow_paid = paid_allowed()
    if not allow_paid:
        raise PaidProviderNotAllowed(
            f'no Codex CLI logged in with ChatGPT (the default, free on the subscription), and the only image '
            f'provider found is a PAID/external API ({config.provider}, from {source}). It is never used '
            f'silently: either the user runs `codex login`, or - only after the user agreed to pay per image - '
            f'set {ALLOW_PAID_ENV}=1 (build_pipeline.py generate / gen_sprites.py: --allow-paid). Without '
            f'either, the asset builder falls back to agent-drawn placeholder art (never final).')
    return config


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

    data = {k: v for k, v in asdict(config).items() if v is not None}
    _write_private(CONFIG_PATH, json.dumps(data, indent=2))
    return config


def _write_private(path: Path, text: str) -> None:
    """Write a secret readable by the owner only: the folder 0700 and the
    file created 0600 (no window where it is world-readable), then chmod'ed
    0600 again in case it already existed with wider bits. On Windows the
    mode bits only toggle read-only; the file then relies on the per-user ACL
    of the profile folder it lives in (best effort)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    if os.name != 'nt':
        os.chmod(path, 0o600)


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
# Codex drawing: delegated to cube_art-director's art.py
# --------------------------------------------------------------------------

def find_art_py() -> Path:
    """cube_art-director's art.py: $WOWCUBE_ART_PY, else
    skills/cube_art-director/scripts/art.py next to this scripts/ folder (or
    in any ancestor, for the packaged plugin layout)."""
    env = os.environ.get(ART_PY_ENV)
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise ImageGenError(f'{ART_PY_ENV}={env} does not exist')
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        cand = base / _ART_PY_REL
        if cand.is_file():
            return cand
    raise ImageGenError(f'cube_art-director art.py not found (looked for {_ART_PY_REL.as_posix()} '
                        f'above {here}); set {ART_PY_ENV}')


def run_art(cmd: str, spec, *, workspace=None, extra=()) -> int:
    """Run one art.py command (`gen`, `process`, `qa`, ...) on a spec (a
    WowCube manifest or an art.json); output streams to the console so the
    agent sees Codex progress and the copy-pasteable retry commands."""
    argv = [sys.executable, str(find_art_py()), cmd, str(spec)]
    if workspace is not None:
        argv += ['--workspace', str(workspace)]
    argv += [str(x) for x in extra]
    print('  $ ' + ' '.join(argv), flush=True)
    return _run(argv).returncode


def codex_generate(manifest_path, workspace, *, only=None, force=False, jobs=None) -> None:
    """Draw a WowCube manifest with Codex through cube_art-director.

    `art.py gen` draws every sprite without a raw image (style anchors and the
    STYLE.md Prompt block attached, the sprite's flat chroma-key backdrop or
    opaque canvas, subject references from <workspace>/fixes.json, dependency
    order), then `art.py process` keys and fits them into
    <workspace>/art/<name>.png (shared scale + centroid alignment per
    animation set, colour lock per fixes.json). `process` also runs after a
    partial `gen` failure: it never refits a set with a missing member, so the
    finished sprites are ready for QA while the failed ones are retried.
    Raises ImageGenError naming the failed step(s)."""
    sel = ['--only', ','.join(only)] if only else []
    gen_extra = sel + (['--force'] if force else []) + (['--jobs', str(int(jobs))] if jobs else [])
    rc_gen = run_art('gen', manifest_path, workspace=workspace, extra=gen_extra)
    rc_process = run_art('process', manifest_path, workspace=workspace, extra=sel)
    failed = [step for step, rc in (('gen', rc_gen), ('process', rc_process)) if rc != 0]
    if failed:
        raise ImageGenError(
            f'art.py {" + ".join(failed)} failed (exit {rc_gen}/{rc_process}); the lines above name the '
            f'sprites and print the retry command (a rerun of `gen` only draws what is still missing)')


def codex_draw(prompt, *, size=None, reference=None, background='opaque', key='auto') -> Image.Image:
    """One image with Codex, through a throw-away art.json run by art.py
    (`gen` + `process`): `background` "key" = drawn on a flat chroma-key
    backdrop and cut out (binary alpha), "opaque" = full-canvas picture;
    `size` (w, h) = final size (default: the 1024x1024 canvas); `reference` =
    an image to keep as the subject. For a whole manifest use codex_generate()
    (sets, anchors and colour lock only exist there)."""
    w, h = (int(size[0]), int(size[1])) if size else (1024, 1024)
    work = Path(tempfile.mkdtemp(prefix='wcx'))     # short path: long ones break Codex on Windows
    try:
        asset = {'name': 'image', 'size': [w, h], 'prompt': str(prompt), 'background': background,
                 'key': key, 'alpha': 'binary'}
        if reference:
            asset['subject_ref'] = str(Path(reference).resolve())
        spec = work / 'art.json'
        spec.write_text(json.dumps({'project': 'genimg', 'workspace': 'ws', 'assets': [asset]}, indent=1),
                        encoding='utf-8')
        if run_art('gen', spec) != 0:
            raise ImageGenError('codex drew no image (see the art.py output above)')
        if run_art('process', spec) != 0:
            raise ImageGenError('art.py process failed on the codex image')
        out = work / 'ws' / 'final' / 'image.png'
        if not out.is_file():
            raise ImageGenError(f'art.py produced no {out.name}')
        with Image.open(out) as im:
            im.load()
            return im.copy()
    finally:
        shutil.rmtree(work, ignore_errors=True)


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


class CodexProvider(ImageProvider):
    """Codex CLI on the user's ChatGPT subscription: no key, nothing billed
    per call, the strongest model at maximum effort (cube_art-director's
    art_codex.py picks it). Drawing goes through art.py (codex_draw /
    codex_generate), never through HTTP."""

    def generate(self, prompt, *, reference=None):
        return codex_draw(prompt, reference=reference)

    def validate(self) -> None:
        exe = self.config.cli or find_codex_cli()
        if not exe:
            raise ProviderValidationError(
                'codex CLI not found: install the Codex CLI and run `codex login` with the ChatGPT account')
        ok, info = codex_login_status(exe, use_cache=False)
        if not ok:
            raise ProviderValidationError(
                f'codex is not logged in with ChatGPT ({info}): the user runs `codex login` themselves')


PROVIDERS = {
    CODEX_PROVIDER: CodexProvider,
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
