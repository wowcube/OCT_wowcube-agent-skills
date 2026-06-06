#!/usr/bin/env python3
"""OpenRouter image-generation client for cube_asset-builder.

Exposes `generate_image(prompt, out_path, size=..., reference=...)` so the
pipeline can turn each sprite's `gen_prompt` into a PNG, and keeps a small CLI
for one-off generation.

The API key is read from the OPENROUTER_API_KEY environment variable — it is
never hardcoded. Set it before running:

    export OPENROUTER_API_KEY=sk-or-...
"""

import os
import json
import base64
import argparse
import datetime

from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

API_URL = 'https://openrouter.ai/api/v1/chat/completions'
MODEL = 'openai/gpt-5.4-image-2'
API_KEY_ENV = 'OPENROUTER_API_KEY'


class ImageGenError(RuntimeError):
    """Raised when the API call fails or returns no image."""


def _api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise ImageGenError(
            f'{API_KEY_ENV} is not set. Export your OpenRouter key first: '
            f'`export {API_KEY_ENV}=sk-or-...`'
        )
    return key


def base64_to_image(base64_string):
    '''Decodes a base64 encoded PNG/JPEG string into a PIL Image object.'''
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
    '''Encodes an image file into a base64 encoded PNG string.'''
    try:
        image = Image.open(filename)
        buffered = BytesIO()
        image.save(buffered, format='PNG')
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return f'data:image/png;base64,{img_str}'
    except Exception as e:
        print(f'Error encoding image to base64: {e}')
        return None


def _request_image(prompt, reference=None):
    '''Call the model and return the first PIL Image it emits, or None.'''
    content = [{'type': 'text', 'text': prompt}]
    if reference:
        content.append({
            'type': 'image_url',
            'image_url': {'url': png_image_to_base64(str(reference))},
        })

    payload = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': content}],
        'stream': True,
    }

    response = requests.post(
        url=API_URL,
        headers={
            'Authorization': f'Bearer {_api_key()}',
            'Content-Type': 'application/json',
        },
        data=json.dumps(payload),
        stream=True,
    )
    response.raise_for_status()

    image = None
    for chunk_b in response.iter_lines():
        chunk = chunk_b.decode('utf-8')
        if not chunk.startswith('data: '):
            continue

        msg_s = chunk.removeprefix('data: ')
        if msg_s == '[DONE]':
            break

        try:
            msg = json.loads(msg_s)
        except json.JSONDecodeError:
            continue

        if not msg.get('choices'):
            continue

        delta = msg['choices'][0].get('delta', {})
        if 'images' in delta and delta['images']:
            base64_url = delta['images'][0]['image_url']['url']
            image = base64_to_image(base64_url)

    return image


def generate_image(prompt, out_path, *, size=None, reference=None):
    '''Generate one image from `prompt` and save it as a PNG at `out_path`.

    If `size` is given as (w, h), the result is resized to exactly those
    dimensions (the model rarely returns the requested pixel size). Alpha is
    preserved so transparent-background sprites stay transparent.

    Raises ImageGenError if the API returns no image.
    '''
    try:
        image = _request_image(prompt, reference=reference)
    except requests.exceptions.RequestException as e:
        raise ImageGenError(f'OpenRouter request failed: {e}') from e

    if image is None:
        raise ImageGenError(f'no image returned for prompt: {prompt!r}')

    image = image.convert('RGBA')
    if size is not None:
        image = image.resize((int(size[0]), int(size[1])), Image.LANCZOS)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, format='PNG')
    return out_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate an image using OpenRouter AI from a text prompt.')
    parser.add_argument('prompt', type=str, help='The text prompt to generate the image from.')
    parser.add_argument('-i', '--image', type=str, default=None,
                        help='Reference image file (optional).')
    parser.add_argument('-o', '--output', type=str, default=None,
                        help='Output PNG path (default: <timestamp>.png).')
    parser.add_argument('-s', '--size', type=str, default=None,
                        help='Resize output to WxH, e.g. 64x64 (optional).')

    args = parser.parse_args()

    output = args.output
    if output is None:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output = f'{timestamp}.png'

    size = None
    if args.size:
        w, h = args.size.lower().split('x')
        size = (int(w), int(h))

    path = generate_image(args.prompt, output, size=size, reference=args.image)
    print(f'Image successfully saved to {path}')
