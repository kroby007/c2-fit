"""GitHub Pages media hosting.

Chosen over raw.githubusercontent.com for a hard reason: TikTok's photo endpoint
only accepts PULL_FROM_URL, and it will not fetch a URL whose prefix you have not
proven you own. Ownership is proven by serving a verification file at that
prefix, which is impossible on raw.githubusercontent.com but trivial on a Pages
site built from this repo. The same site supplies the website, privacy, and terms
URLs that TikTok's app registration requires.

Files land in docs/media/<date>/ and are committed; publishing therefore depends
on the commit having been pushed and Pages having rebuilt.
"""
from __future__ import annotations

import os
import pathlib
import shutil

from .. import config
from .base import Storage


class GitHubPagesStorage(Storage):
    def __init__(self, base_url: str | None = None) -> None:
        base = base_url or os.environ.get("PAGES_BASE_URL")
        if not base:
            raise RuntimeError(
                "PAGES_BASE_URL is not set. It must exactly match the URL prefix "
                "you verified in the TikTok developer portal, e.g. "
                "https://<user>.github.io/<repo>"
            )
        self.base_url = base.rstrip("/")

    def put(self, local_path: pathlib.Path, key: str) -> str:
        target = config.MEDIA_DIR / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, target)
        return f"{self.base_url}/media/{key}"
