"""Posting history — dedupe source and hashtag-rotation memory.

Committed to the repo rather than kept on disk: GitHub Actions runners are
ephemeral, so history that is not committed does not survive to the next run,
and the generator would start repeating recipes within a week.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from .. import config

HISTORY_PATH = config.STATE_DIR / "history.json"

# How far back to look. Long enough that recipes do not visibly repeat, short
# enough that the hashtag pools do not exhaust themselves.
DEDUPE_WINDOW = 60
HASHTAG_WINDOW = 5
# How many recent cooking methods to rule out. niche.yaml lists five, so two
# still leaves three to choose from — enough that the model is not boxed into a
# bad fit, tight enough that the feed cannot become all one appliance.
METHOD_WINDOW = 2


def _load() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text())


def recent_titles(limit: int = DEDUPE_WINDOW) -> list[str]:
    return [e["title"] for e in _load()[-limit:] if e.get("title")]


def recent_hashtags(limit: int = HASHTAG_WINDOW) -> list[str]:
    tags: list[str] = []
    for entry in _load()[-limit:]:
        tags.extend(entry.get("hashtags", []))
    return tags


def recent_methods(limit: int = METHOD_WINDOW) -> list[str]:
    """Cooking methods used most recently, for the generator to avoid.

    Held posts count: the method was still spent on that day's slot as far as
    variety goes, and the point here is what the feed looks like, not what
    published.
    """
    return [m for e in _load()[-limit:] if (m := e.get("method"))]


def record(
    date: str,
    slug: str,
    title: str,
    hashtags: list[str],
    published: dict[str, Any] | None = None,
    held: bool = False,
    method: str = "",
) -> None:
    """Append one post to the history file."""
    entries = _load()
    entries.append(
        {
            "date": date,
            "slug": slug,
            "title": title,
            "method": method,
            "hashtags": hashtags,
            "published": published or {},
            "held": held,
        }
    )
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def already_posted_today(date: str) -> bool:
    """Guard against a re-run double-posting after a partial failure."""
    return any(e["date"] == date and not e.get("held") for e in _load())


def path() -> pathlib.Path:
    return HISTORY_PATH
