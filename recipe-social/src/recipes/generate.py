"""Recipe generation via the Claude API.

Uses structured outputs so the response is guaranteed to match the Recipe shape —
no parsing of prose, no retry-on-malformed-JSON loop.
"""
from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from .. import config
from .schema import Ingredient, Macros, Recipe

# Recipe writing is a well-scoped structured task well inside Sonnet's range,
# and output tokens dominate the bill, so the tier matters more than anything
# else here. High effort rather than medium: it buys back most of what dropping
# from Opus costs, and this is the one call whose quality shows up on the slides.
MODEL = config.setting("RECIPE_MODEL", "claude-sonnet-5")
EFFORT = config.setting("RECIPE_EFFORT", "high")


def _rotate(key: str, exclude: list[str] | None = None) -> list[str]:
    """Values from niche.yaml[key] with recent ones removed.

    Recent choices are dropped from the enum rather than merely discouraged in
    the prompt, because structured output cannot return a value the schema does
    not offer. Asking for variety is advisory; this is not.

    The exclusion yields if it would leave too little to choose from, so a short
    list in niche.yaml degrades to a wider choice instead of an empty enum and a
    failed run.
    """
    values = list(config.niche()[key])
    remaining = [v for v in values if v not in set(exclude or ())]
    return remaining if len(remaining) >= 2 else values


def available_methods(exclude: list[str] | None = None) -> list[str]:
    """Cooking methods the next recipe may use."""
    return _rotate("methods", exclude)


def available_proteins(exclude: list[str] | None = None) -> list[str]:
    """Main proteins the next recipe may use."""
    return _rotate("proteins", exclude)


def _schema(
    exclude_methods: list[str] | None = None,
    exclude_proteins: list[str] | None = None,
) -> dict[str, Any]:
    """Build the JSON schema from config so methods and series stay in sync.

    Numeric bounds are deliberately absent — the structured-output schema does
    not support minimum/maximum, so those are enforced in quality.py instead.
    """
    brand = config.brand()
    niche = config.niche()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "title", "hook", "method", "protein", "servings", "prep_minutes", "cook_minutes",
            "ingredients", "steps", "macros", "cost_per_serving", "allergens",
            "series", "image_subject",
        ],
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "Dish name, max 40 characters so it fits the hook card. Do not "
                    "name a cooking method the recipe does not use — a one-pot "
                    "recipe called 'Chicken Skillet' is rejected. The title is the "
                    "only thing the reader sees, so it has to match the method."
                ),
            },
            "hook": {
                "type": "string",
                "description": (
                    "Scroll-stopping line with a concrete number, max 60 characters. "
                    "E.g. '42g protein for $2.80'. No emoji — the card supplies those."
                ),
            },
            "method": {"type": "string", "enum": available_methods(exclude_methods)},
            "protein": {
                "type": "string",
                "enum": available_proteins(exclude_proteins),
                "description": "The main protein the dish is built around.",
            },
            "servings": {"type": "integer"},
            "prep_minutes": {"type": "integer"},
            "cook_minutes": {"type": "integer"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["item", "qty"],
                    "properties": {
                        "item": {"type": "string", "description": "e.g. 'chicken breast'"},
                        "qty": {"type": "string", "description": "e.g. '1 lb (450g)'"},
                    },
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "string",
                    "description": "Short imperative sentence, max 18 words.",
                },
            },
            "macros": {
                "type": "object",
                "additionalProperties": False,
                "required": ["calories", "protein_g", "carbs_g", "fat_g"],
                "properties": {
                    "calories": {"type": "integer", "description": "Per serving."},
                    "protein_g": {"type": "integer"},
                    "carbs_g": {"type": "integer"},
                    "fat_g": {"type": "integer"},
                },
            },
            "cost_per_serving": {
                "type": "number",
                "description": "Realistic US grocery cost per serving, in dollars.",
            },
            "allergens": {
                "type": "array",
                "items": {"type": "string", "enum": list(niche["allergens_to_flag"])},
                "description": "Only allergens actually present in the ingredients.",
            },
            "series": {
                "type": "array",
                "items": {"type": "string", "enum": list(brand["series"])},
                "description": (
                    "Badges this recipe genuinely qualifies for. These are re-checked "
                    "against the numbers, so claiming one it does not earn is pointless."
                ),
            },
            "image_subject": {
                "type": "string",
                "description": (
                    "The plated dish described for a food photographer: what is on the "
                    "plate, how it is arranged, visible textures and garnishes. One or "
                    "two sentences. No camera or lighting direction — that is added later."
                ),
            },
        },
    }


def _prompt(
    exclude_titles: list[str],
    exclude_methods: list[str] | None = None,
    exclude_proteins: list[str] | None = None,
) -> str:
    niche = config.niche()
    brand = config.brand()
    c = niche["constraints"]

    series_lines = "\n".join(
        f"- {key} ({s['label']}): qualifies when {s['rule']}"
        for key, s in brand["series"].items()
    )
    requirements = "\n".join(f"- {r}" for r in niche["require"])
    avoid = "\n".join(f"- {a}" for a in niche["avoid"])
    recent = (
        "\n\nDo not create anything similar to these recent posts:\n"
        + "\n".join(f"- {t}" for t in exclude_titles)
        if exclude_titles
        else ""
    )
    # The schema already withholds these, so this only explains why the usual
    # choice is missing — otherwise the model works around the gap by writing a
    # skillet recipe and labelling it one_pot.
    if exclude_methods:
        recent += (
            "\n\nThe last posts used " + ", ".join(exclude_methods) + ". Pick a "
            "genuinely different way of cooking, not the same technique renamed — "
            "the feed should not look like one appliance."
        )
    if exclude_proteins:
        recent += (
            "\n\nThe last posts were built on " + ", ".join(exclude_proteins) + ". "
            "Build this one on something else, and change the supporting cast too: "
            "the same beans and the same sauce under a new protein still reads as "
            "the same dinner."
        )

    return f"""Create one recipe for a short-form video account.

POSITIONING
{niche["positioning"]}

AUDIENCE
{niche["audience"]}

HARD CONSTRAINTS
- At most {c["max_ingredients"]} ingredients.
- At most {c["max_total_minutes"]} minutes total (prep + cook).
- {c["min_servings"]}-{c["max_servings"]} servings.
- At most ${c["max_cost_per_serving"]:.2f} per serving.
- Must qualify for at least {c["min_series_tags"]} of the series badges below.

SERIES BADGES
{series_lines}

REQUIREMENTS
{requirements}

AVOID
{avoid}

The macros must describe the recipe as written: calories should be consistent with
protein, carbs, and fat at 4/4/9 kcal per gram. A recipe with plausible-looking but
internally inconsistent numbers is worse than a simpler recipe with honest ones.{recent}"""


def generate_recipe(
    exclude_titles: list[str] | None = None,
    exclude_methods: list[str] | None = None,
    exclude_proteins: list[str] | None = None,
) -> Recipe:
    """Generate one recipe matching the niche brief, avoiding recent work."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={
            "effort": EFFORT,
            "format": {
                "type": "json_schema",
                "schema": _schema(exclude_methods, exclude_proteins),
            },
        },
        messages=[
            {
                "role": "user",
                "content": _prompt(
                    exclude_titles or [], exclude_methods, exclude_proteins
                ),
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Recipe generation refused: {response.stop_details}")

    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return Recipe(
        title=data["title"],
        hook=data["hook"],
        method=data["method"],
        servings=data["servings"],
        prep_minutes=data["prep_minutes"],
        cook_minutes=data["cook_minutes"],
        protein=data["protein"],
        ingredients=[Ingredient(**i) for i in data["ingredients"]],
        steps=data["steps"],
        macros=Macros(**data["macros"]),
        cost_per_serving=data["cost_per_serving"],
        allergens=data["allergens"],
        series=data["series"],
        image_subject=data["image_subject"],
    )
