"""The quality gate.

Two jobs:

1. **Correct** what can be corrected silently — a series badge the recipe does
   not actually earn is dropped rather than held.
2. **Hold** anything that would embarrass the account if it went out: macro
   arithmetic that does not describe real food, unlabeled allergens, a recipe
   too close to one already posted, or content over a platform limit.

Held posts never reach a publisher; they land in out/held/ for review.
"""
from __future__ import annotations

import re

from .. import config
from .schema import Recipe

# Stated calories may differ from the 4/4/9 computation by this much before we
# treat the numbers as invented. Real recipes drift a little (rounding, fiber,
# alcohol); a 40% gap means the model made the figures up.
MACRO_TOLERANCE = 0.15

# Both platforms cap captions at 2200 characters.
MAX_CAPTION_CHARS = 2200
# Instagram rejects a post outright above 30 hashtags.
MAX_HASHTAGS = 30


def _recipe_field(recipe: Recipe, field: str):
    if field == "total_minutes":
        return recipe.total_minutes
    if hasattr(recipe.macros, field):
        return getattr(recipe.macros, field)
    return getattr(recipe, field)


def _passes(recipe: Recipe, rule: dict) -> bool:
    actual = _recipe_field(recipe, rule["field"])
    expected, op = rule["value"], rule["op"]
    if op == ">=":
        return actual >= expected
    if op == "<=":
        return actual <= expected
    if op == "==":
        return actual == expected
    raise ValueError(f"Unsupported rule op: {op!r}")


def earned_series(recipe: Recipe) -> list[str]:
    """Series badges the recipe genuinely qualifies for, in config order."""
    series = config.brand()["series"]
    return [key for key, spec in series.items() if _passes(recipe, spec["rule"])]


_WORD_RE = re.compile(r"[a-z]+")


def _title_tokens(title: str) -> set[str]:
    # Words that appear in half the titles in this niche carry no signal for
    # similarity, so they are excluded from the overlap comparison.
    stop = {"and", "the", "with", "in", "a", "of", "for", "minute", "min", "easy", "quick"}
    return {w for w in _WORD_RE.findall(title.lower()) if w not in stop and len(w) > 2}


# What each method is called when it turns up in a dish name. Deliberately just
# the method's own names — nothing like "baked" or "pan", which appear in plenty
# of honest titles and would hold good posts for no reason.
METHOD_WORDS = {
    "skillet": ("skillet",),
    "sheet_pan": ("sheet pan", "sheet-pan", "tray bake", "traybake"),
    "air_fryer": ("air fryer", "air-fryer", "air fried", "air-fried"),
    "one_pot": ("one pot", "one-pot"),
    "no_cook": ("no cook", "no-cook"),
}


def mislabelled_method(recipe: Recipe) -> str | None:
    """Return the method the title claims, if the recipe does not actually use it.

    The method field is never rendered anywhere — the reader only ever sees the
    title. So rotating the method away from skillet achieves nothing on its own
    if the title still says Skillet, which nothing otherwise prevents.
    """
    title = recipe.title.lower()
    for method, words in METHOD_WORDS.items():
        if method == recipe.method:
            continue
        if any(word in title for word in words):
            return method
    return None


def is_duplicate(recipe: Recipe, past_titles: list[str], threshold: float = 0.6) -> str | None:
    """Return the matching past title if this recipe is too similar to one."""
    tokens = _title_tokens(recipe.title)
    if not tokens:
        return None
    for past in past_titles:
        past_tokens = _title_tokens(past)
        if not past_tokens:
            continue
        overlap = len(tokens & past_tokens) / min(len(tokens), len(past_tokens))
        if overlap >= threshold:
            return past
    return None


def repeat_reason(
    recipe: Recipe,
    past_titles: list[str] | None = None,
    past_slugs: set[str] | None = None,
) -> str | None:
    """Why this recipe repeats an earlier post, or None if it is new.

    Two tiers. A slug that has run before is an exact repeat and is refused
    outright, however long ago it was. Short of that, a title sharing most of
    its words with a recent one is the same dinner wearing a different name.

    Split out from check() so the generator can ask the same question before
    anything expensive happens, and simply write another recipe.
    """
    if recipe.slug and recipe.slug in (past_slugs or set()):
        return f"{recipe.title!r} has been posted before."
    match = is_duplicate(recipe, past_titles or [])
    if match:
        return f"Too similar to a previous post: {match!r}."
    return None


def check(
    recipe: Recipe,
    past_titles: list[str] | None = None,
    caption: str = "",
    hashtags: list[str] | None = None,
    past_slugs: set[str] | None = None,
) -> list[str]:
    """Return hold reasons. Empty list means the post is clear to publish.

    Mutates `recipe.series` to the badges actually earned — that is a correction,
    not a failure, so it does not produce a hold reason on its own.
    """
    reasons: list[str] = []
    niche = config.niche()
    c = niche["constraints"]
    hashtags = hashtags or []

    recipe.series = earned_series(recipe)
    if len(recipe.series) < c["min_series_tags"]:
        reasons.append(
            f"Earns {len(recipe.series)} series badge(s), needs at least "
            f"{c['min_series_tags']} — the recipe is not fast, cheap, or high-protein enough."
        )

    computed = recipe.macros.computed_calories()
    stated = recipe.macros.calories
    if stated <= 0:
        reasons.append("Calories are zero or negative.")
    else:
        drift = abs(computed - stated) / stated
        if drift > MACRO_TOLERANCE:
            reasons.append(
                f"Macros do not add up: {recipe.macros.protein_g}p/"
                f"{recipe.macros.carbs_g}c/{recipe.macros.fat_g}f implies {computed} kcal "
                f"but {stated} kcal is stated ({drift:.0%} off)."
            )

    if any(v < 0 for v in (recipe.macros.protein_g, recipe.macros.carbs_g, recipe.macros.fat_g)):
        reasons.append("Negative macro value.")

    if len(recipe.ingredients) > c["max_ingredients"]:
        reasons.append(
            f"{len(recipe.ingredients)} ingredients, limit is {c['max_ingredients']}."
        )
    if recipe.total_minutes > c["max_total_minutes"]:
        reasons.append(
            f"{recipe.total_minutes} minutes total, limit is {c['max_total_minutes']}."
        )
    if recipe.cost_per_serving > c["max_cost_per_serving"]:
        reasons.append(
            f"${recipe.cost_per_serving:.2f} per serving, limit is "
            f"${c['max_cost_per_serving']:.2f}."
        )
    if not (c["min_servings"] <= recipe.servings <= c["max_servings"]):
        reasons.append(f"{recipe.servings} servings is outside the allowed range.")
    if not recipe.steps:
        reasons.append("No steps.")
    if not recipe.ingredients:
        reasons.append("No ingredients.")

    # An allergen present in the ingredients but missing from the declared list
    # means the caption warning would be wrong — worth a human look.
    ingredient_text = " ".join(i.display().lower() for i in recipe.ingredients)
    for allergen in niche["allergens_to_flag"]:
        if allergen in ingredient_text and allergen not in recipe.allergens:
            reasons.append(f"Ingredients mention '{allergen}' but it is not declared.")

    claimed = mislabelled_method(recipe)
    if claimed:
        reasons.append(
            f"Title says {claimed.replace('_', ' ')} but the recipe is {recipe.method.replace('_', ' ')}: "
            f"{recipe.title!r}."
        )

    repeat = repeat_reason(recipe, past_titles, past_slugs)
    if repeat:
        reasons.append(repeat)

    full = f"{caption}\n\n{' '.join(hashtags)}".strip()
    if len(full) > MAX_CAPTION_CHARS:
        reasons.append(f"Caption is {len(full)} chars, limit is {MAX_CAPTION_CHARS}.")
    if len(hashtags) > MAX_HASHTAGS:
        reasons.append(f"{len(hashtags)} hashtags, limit is {MAX_HASHTAGS}.")

    return reasons
