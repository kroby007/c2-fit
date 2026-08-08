"""Caption and hashtag composition.

Hashtags are drawn per-bucket and rotated against recent history — repeating an
identical block post after post gets suppressed on both TikTok and Instagram.
The draw is seeded by the recipe slug so a given recipe always produces the same
caption (re-running a stage is idempotent) while consecutive posts differ.
"""
from __future__ import annotations

import random

from .. import config
from ..recipes.schema import Recipe

_SERIES_EMOJI_FALLBACK = "🍽️"


def _series_line(recipe: Recipe) -> str:
    series = config.brand()["series"]
    parts = [
        f"{series[key]['emoji']} {series[key]['label'].title()}"
        for key in recipe.series
        if key in series
    ]
    return "  ".join(parts)


def build_hashtags(recipe: Recipe, recent: list[str] | None = None) -> list[str]:
    """Pick a rotated hashtag set for this recipe.

    `recent` is a flat list of tags used in recent posts; they are deprioritised
    rather than banned, so a small pool never runs dry.
    """
    cfg = config.hashtags()
    draw = cfg["draw"]
    recent_set = set(recent or [])
    rng = random.Random(recipe.slug)

    def pick(pool: list[str], n: int) -> list[str]:
        fresh = [t for t in pool if t not in recent_set]
        stale = [t for t in pool if t in recent_set]
        rng.shuffle(fresh)
        rng.shuffle(stale)
        return (fresh + stale)[:n]

    series_pool: list[str] = []
    for key in recipe.series:
        series_pool.extend(cfg["series"].get(key, []))

    tags: list[str] = []
    for bucket, pool in (
        ("broad", cfg["broad"]),
        ("core", cfg["core"]),
        ("series", series_pool),
        ("discovery", cfg["discovery"]),
    ):
        for tag in pick(pool, draw[bucket]):
            if tag not in tags:
                tags.append(tag)

    # Trim to whichever ceiling bites first.
    tags = tags[: draw["max_total"]]
    while tags and len(" ".join(tags)) > draw["max_chars"]:
        tags.pop()
    return tags


def build_caption(recipe: Recipe) -> str:
    brand = config.brand()
    account = brand["account"]
    m = recipe.macros

    lines = [
        f"🔥 {recipe.hook}",
        "",
        f"{recipe.title} — {recipe.servings} servings, {recipe.total_minutes} minutes, "
        f"{len(recipe.ingredients)} ingredients.",
        "",
        f"💪 {m.protein_g}g protein  ·  🔥 {m.calories} cal  ·  "
        f"🍞 {m.carbs_g}g carbs  ·  🥑 {m.fat_g}g fat",
        f"💵 About ${recipe.cost_per_serving:.2f} a serving",
    ]

    series_line = _series_line(recipe)
    if series_line:
        lines.append(series_line)

    lines += ["", "👆 Full ingredients and steps in the slides", "🔖 Save this one for later"]

    if recipe.allergens:
        lines.append(f"⚠️ Contains {', '.join(sorted(recipe.allergens))}")

    lines += ["", f"{account['cta']} {account['handle']}", brand["disclaimer"]]
    return "\n".join(lines)
