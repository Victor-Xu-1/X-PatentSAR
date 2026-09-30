"""OpenAI-compatible vision adapter for activity-table review."""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

import requests


logger = logging.getLogger(__name__)


def call_vlm_image(
    image_path: str,
    prompt: str,
    api_url: str,
    api_key: str,
    model: str,
    *,
    timeout_s: int = 120,
    max_attempts: int = 3,
) -> str:
    """Submit one image with bounded exponential-backoff retries."""

    image = Path(image_path)
    if not image.is_file():
        raise FileNotFoundError(f"VLM image does not exist: {image}")
    if not api_url or not api_key or not model:
        raise ValueError("VLM endpoint, API key and model are required")
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    },
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    attempts = max(1, min(int(max_attempts), 5))
    endpoint = f"{api_url.rstrip('/')}/chat/completions"
    for attempt in range(attempts):
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout_s)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("VLM response content is not text")
            return content
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("VLM attempt %s/%s failed: %s", attempt + 1, attempts, exc)
            if attempt + 1 >= attempts:
                return ""
            time.sleep(2**attempt)
    return ""
