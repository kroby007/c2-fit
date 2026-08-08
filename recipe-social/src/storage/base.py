"""Storage interface — turns local PNGs into public HTTPS URLs.

TikTok pulls carousel images from URLs rather than accepting uploaded bytes, so
every post needs its slides reachable over HTTPS before publishing can start.
"""
from __future__ import annotations

import os
import pathlib
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    def put(self, local_path: pathlib.Path, key: str) -> str:
        """Store the file under `key` and return its public HTTPS URL."""


def get_storage(name: str | None = None) -> Storage:
    name = (name or os.environ.get("STORAGE_BACKEND", "ghpages")).lower()
    if name == "ghpages":
        from .ghpages import GitHubPagesStorage

        return GitHubPagesStorage()
    raise ValueError(f"Unknown storage backend {name!r}")
