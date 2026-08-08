"""Config loading and the handful of paths everything else resolves against."""
from __future__ import annotations

import functools
import os
import pathlib
import shutil

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
OUT_DIR = pathlib.Path(os.environ.get("RECIPE_OUT_DIR", ROOT / "out"))
STATE_DIR = ROOT / "state"

# GitHub Pages doubles as the TikTok-verified media host; see README.
DOCS_DIR = ROOT.parent / "docs"
MEDIA_DIR = DOCS_DIR / "media"


@functools.lru_cache(maxsize=None)
def load(name: str) -> dict:
    """Load config/<name>.yaml. Cached — configs do not change mid-run."""
    return yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text())


def brand() -> dict:
    return load("brand")


def niche() -> dict:
    return load("niche")


def hashtags() -> dict:
    return load("hashtags")


# Ordered by how likely each is to be the real binary in a given environment:
# the dev container ships Playwright's Chromium, Actions runners ship Chrome,
# and a developer machine usually has one of the distro names on PATH.
#
# The Windows entries matter more than they look: Chrome's installer does not
# put chrome.exe on PATH, so the shutil.which() fallback below never finds it
# and these absolute paths are the only thing that does.
_CHROME_CANDIDATES = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)


def chrome_binary() -> str:
    """Locate a Chromium/Chrome binary for slide rendering.

    CHROME_BINARY wins if set, which is what the Actions workflow uses. The
    existing build-pdf.py in this repo hardcodes a container-specific path;
    that would break on a runner, so we search instead.
    """
    explicit = os.environ.get("CHROME_BINARY")
    if explicit:
        return explicit
    for candidate in _CHROME_CANDIDATES:
        if pathlib.Path(candidate).is_file():
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(
        "No Chromium/Chrome binary found for slide rendering. "
        "Set CHROME_BINARY to its path, or install Chrome."
    )
