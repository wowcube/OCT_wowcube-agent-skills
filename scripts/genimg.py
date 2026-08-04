#!/usr/bin/env python3
"""Image-generation client for cube_asset-builder.

Exposes `generate_image(prompt, out_path, size=..., reference=..., cutout=...)`
so the pipeline can turn each sprite's `gen_prompt` into a PNG, and keeps a
small CLI for one-off generation.

The actual HTTP work lives in `image_providers.py` (multi-provider adapter:
OpenRouter, OpenAI, xAI, Gemini, local Stable Diffusion). Which provider is
used is resolved per call from, in order: the `OPENROUTER_API_KEY` env var,
the `IMAGE_API` env var, or `~/.wowcube/image_api.json`. No key is ever
hardcoded. Backward-compatible quick start:

    export OPENROUTER_API_KEY=sk-or-...
"""

import argparse
import datetime

from pathlib import Path

import numpy as np
from collections import deque
from PIL import Image

import image_providers
from image_providers import (  # noqa: F401 — re-exported for callers
    API_KEY_ENV,
    ImageGenError,
    base64_to_image,
    png_image_to_base64,
)


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


def generate_image(prompt, out_path, *, size=None, reference=None, cutout=False,
                   provider=None):
    '''Generate one image from `prompt` and save it as a PNG at `out_path`.

    If `cutout` is True, the solid backdrop is removed (made transparent) at
    full resolution before resizing, so object sprites end up with a clean
    transparent background regardless of what the model paints. Leave it False
    for sprites that must fill their frame (tiles, backgrounds).

    If `size` is given as (w, h), the result is resized to exactly those
    dimensions (the model rarely returns the requested pixel size). Alpha is
    preserved so transparent-background sprites stay transparent.

    `provider` is an optional `image_providers.ProviderConfig`; when omitted
    the provider is resolved from the environment / config file chain
    (`image_providers.resolve_provider`).

    Raises ImageGenError if no provider is configured, the API call fails
    after retries, or the API returns no image.
    '''
    config = provider or image_providers.resolve_provider()
    if config is None:
        raise ImageGenError(
            f'no image provider configured. Set {API_KEY_ENV} (OpenRouter), '
            f'or IMAGE_API (any supported key/URL), or create '
            f'{image_providers.CONFIG_PATH}.'
        )

    # Retries/backoff for transient network failures live inside the provider
    # (`ImageProvider.generate`). A None result (e.g. a content refusal) is
    # NOT a transient error, so it is not retried there either.
    image = image_providers.get_provider(config).generate(prompt,
                                                          reference=reference)
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
        description='Generate an image from a text prompt via the configured '
                    'image provider.')
    parser.add_argument('prompt', type=str, help='The text prompt to generate the image from.')
    parser.add_argument('-i', '--image', type=str, default=None,
                        help='Reference image file (optional; OpenRouter only).')
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
