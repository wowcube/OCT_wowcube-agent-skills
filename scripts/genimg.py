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
import time
import base64
import argparse
import datetime

from io import BytesIO
from pathlib import Path

import requests
import numpy as np
from collections import deque
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
        'stream': False,
    }

    # (connect timeout, read timeout) — without this a stalled socket hangs
    # forever and the retry logic in generate_image never triggers.
    response = requests.post(
        url=API_URL,
        headers={
            'Authorization': f'Bearer {_api_key()}',
            'Content-Type': 'application/json',
        },
        data=json.dumps(payload),
        timeout=(15, 180),
    )
    response.raise_for_status()

    # This model returns the generated image in the final assistant message
    # (choices[0].message.images), not in streaming deltas. Read it directly.
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


def remove_background(image, tol=48):
    '''Make the solid backdrop transparent by flood-filling from the edges.

    The image models often ignore "transparent background" and paint a fill.
    We sample the backdrop color from the four corners and clear the alpha of
    every pixel that (a) is within `tol` color distance of ANY corner color AND
    (b) is connected to an image edge. Matching any corner (not just the median)
    handles two-tone or lightly graded backdrops. Connectivity from the border
    means interior regions that happen to share the backdrop color (e.g. eye
    whites) are kept. Works on the full-resolution image so edges stay clean
    after downscaling.
    '''
    image = image.convert('RGBA')
    arr = np.array(image)
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    alpha = arr[:, :, 3]

    corner_colors = [
        arr[0, 0, :3], arr[0, w - 1, :3], arr[h - 1, 0, :3], arr[h - 1, w - 1, :3],
    ]

    # Candidate background: already transparent, or close to ANY corner color.
    candidate = (alpha == 0)
    for c in corner_colors:
        dist = np.abs(rgb - c.astype(np.int16)).sum(axis=2)
        candidate = candidate | (dist <= tol)

    # Flood fill from all border pixels that are candidates.
    visited = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        if candidate[0, x]:
            dq.append((0, x))
        if candidate[h - 1, x]:
            dq.append((h - 1, x))
    for y in range(h):
        if candidate[y, 0]:
            dq.append((y, 0))
        if candidate[y, w - 1]:
            dq.append((y, w - 1))

    while dq:
        y, x = dq.popleft()
        if visited[y, x]:
            continue
        visited[y, x] = True
        if y > 0 and not visited[y - 1, x] and candidate[y - 1, x]:
            dq.append((y - 1, x))
        if y < h - 1 and not visited[y + 1, x] and candidate[y + 1, x]:
            dq.append((y + 1, x))
        if x > 0 and not visited[y, x - 1] and candidate[y, x - 1]:
            dq.append((y, x - 1))
        if x < w - 1 and not visited[y, x + 1] and candidate[y, x + 1]:
            dq.append((y, x + 1))

    arr[visited, 3] = 0
    return Image.fromarray(arr, 'RGBA')


def generate_image(prompt, out_path, *, size=None, reference=None, cutout=False):
    '''Generate one image from `prompt` and save it as a PNG at `out_path`.

    If `cutout` is True, the solid backdrop is removed (made transparent) at
    full resolution before resizing, so object sprites end up with a clean
    transparent background regardless of what the model paints. Leave it False
    for sprites that must fill their frame (tiles, backgrounds).

    If `size` is given as (w, h), the result is resized to exactly those
    dimensions (the model rarely returns the requested pixel size). Alpha is
    preserved so transparent-background sprites stay transparent.

    Raises ImageGenError if the API returns no image.
    '''
    # Transient network failures (premature close, chunked-encoding error,
    # timeouts) are common on the slow image endpoint. Retry a few times with
    # backoff before giving up. A None result (e.g. a content refusal) is NOT a
    # transient error, so it is not retried here.
    image = None
    last_err = None
    for attempt in range(4):
        try:
            image = _request_image(prompt, reference=reference)
            break
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 3:
                time.sleep(2.0 * (attempt + 1))
    else:
        raise ImageGenError(f'OpenRouter request failed after retries: {last_err}') from last_err

    if image is None:
        raise ImageGenError(f'no image returned for prompt: {prompt!r}')

    image = image.convert('RGBA')
    if cutout:
        image = remove_background(image)
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
