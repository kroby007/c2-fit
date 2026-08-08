"""Image provider interface.

Swapping providers is an env-var change, not a rewrite — every provider takes a
prompt and an aspect ratio and returns PNG/JPEG bytes.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, aspect_ratio: str) -> bytes:
        """Return raw image bytes for `prompt`, or raise if generation failed."""


def get_provider(name: str | None = None) -> ImageProvider:
    """Resolve the configured provider. Set IMAGE_PROVIDER to override."""
    name = (name or os.environ.get("IMAGE_PROVIDER", "gemini")).lower()
    if name == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider()
    raise ValueError(
        f"Unknown image provider {name!r}. Implement it as an ImageProvider "
        f"subclass in src/images/ and register it here."
    )
