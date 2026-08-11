"""Google Gemini image generation — the default provider."""
from __future__ import annotations

import os
import time

from .. import config
from .provider import ImageProvider

# A 503 from Gemini ("experiencing high demand") cost a whole day's post on
# 2026-08-10: one transient upstream blip, no image, no page, nothing to post,
# and the schedule does not retry a missed day. Spend a couple of minutes
# retrying rather than losing the run — image generation is the single point
# with no fallback, since every later stage needs the photo.
_RETRY_DELAYS = (20, 60, 120)
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# gemini-2.5-flash-image ("Nano Banana") is the cost/quality default at roughly
# $0.03/image. gemini-3-pro-image is markedly better at fine detail and costs
# more; switch with GEMINI_IMAGE_MODEL if the food shots need it.
MODEL = config.setting("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


class GeminiProvider(ImageProvider):
    def __init__(self) -> None:
        from google import genai

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get one free at https://aistudio.google.com/apikey"
            )
        self._client = genai.Client(api_key=api_key)

    def _generate_once(self, prompt: str, aspect_ratio: str):
        from google.genai import types

        return self._client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )

    def generate(self, prompt: str, aspect_ratio: str) -> bytes:
        from google.genai import errors

        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                response = self._generate_once(prompt, aspect_ratio)
                break
            except errors.APIError as exc:
                # Only transient server-side conditions are worth waiting out; a
                # 400 or a quota exhaustion will fail identically every time.
                if getattr(exc, "code", None) not in _RETRYABLE_STATUS or delay is None:
                    raise
                print(
                    f"  Gemini returned {exc.code} (attempt {attempt}); "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)

        candidates = response.candidates or []
        if not candidates:
            raise RuntimeError(f"Gemini returned no candidates (prompt: {prompt[:80]}...)")

        # Responses can interleave text with the image depending on the model, so
        # take the first part that actually carries image bytes.
        for part in candidates[0].content.parts or []:
            blob = part.inline_data
            if blob is not None and blob.data:
                return blob.data

        raise RuntimeError(
            f"Gemini response contained no image data "
            f"(finish_reason={getattr(candidates[0], 'finish_reason', None)})"
        )
