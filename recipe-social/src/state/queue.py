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
# Proteins and cuisines rule out further back: eleven of each, and they are what
# make two posts feel like the same dinner. Six of eleven still leaves five to
# choose from, while guaranteeing a protein cannot come back inside a week.
PROTEIN_WINDOW = 6
CUISINE_WINDOW = 6
# The look of the slide, not the food. Six themes and eight surfaces, so ruling
# out the last three of each still leaves a real choice while guaranteeing
# neither repeats inside half a week.
THEME_WINDOW = 3
SURFACE_WINDOW = 3


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


def recent_proteins(limit: int = PROTEIN_WINDOW) -> list[str]:
    """Main proteins used most recently, for the generator to avoid."""
    return [p for e in _load()[-limit:] if (p := e.get("protein"))]


def recent_cuisines(limit: int = CUISINE_WINDOW) -> list[str]:
    """Flavour directions used most recently, for the generator to avoid."""
    return [c for e in _load()[-limit:] if (c := e.get("cuisine"))]


def recent_themes(limit: int = THEME_WINDOW) -> list[str]:
    """Slide colour themes used most recently, for the next post to avoid."""
    return [t for e in _load()[-limit:] if (t := e.get("theme"))]


def recent_surfaces(limit: int = SURFACE_WINDOW) -> list[str]:
    """Photo surfaces used most recently, for the next post to avoid."""
    return [s for e in _load()[-limit:] if (s := e.get("surface"))]


def all_slugs() -> set[str]:
    """Every slug ever posted.

    Unbounded on purpose, unlike the other windows: those trade recency against
    a pool that would otherwise exhaust itself, but an exact repeat is never
    acceptable no matter how long ago it ran.
    """
    return {s for e in _load() if (s := e.get("slug"))}


def record(
    date: str,
    slug: str,
    title: str,
    hashtags: list[str],
    published: dict[str, Any] | None = None,
    held: bool = False,
    method: str = "",
    protein: str = "",
    cuisine: str = "",
    theme: str = "",
    surface: str = "",
) -> None:
    """Record this post, replacing any earlier entry for the same date and slug.

    More than one stage records: staging is the moment a post goes public in
    manual mode, publishing is that moment when the API is in use, and either
    can be re-run. Appending made the history depend on how many times a stage
    happened to run, so this upserts instead. The entry moves to the end, which
    is what the recency windows want.
    """
    entries = [
        e for e in _load() if not (e["date"] == date and e.get("slug") == slug)
    ]
    entries.append(
        {
            "date": date,
            "slug": slug,
            "title": title,
            "method": method,
            "protein": protein,
            "cuisine": cuisine,
            "theme": theme,
            "surface": surface,
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
