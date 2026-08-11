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


def _schema() -> dict[str, Any]:
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
            "title", "hook", "method", "servings", "prep_minutes", "cook_minutes",
            "ingredients", "steps", "macros", "cost_per_serving", "allergens",
            "series", "image_subject",
        ],
        "properties": {
            "title": {
                "type": "string",
                "description": "Dish name, max 40 characters so it fits the hook card.",
            },
            "hook": {
                "type": "string",
                "description": (
                    "Scroll-stopping line with a concrete number, max 60 characters. "
                    "E.g. '42g protein for $2.80'. No emoji — the card supplies those."
                ),
            },
            "method": {"type": "string", "enum": list(niche["methods"])},
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


def _prompt(exclude_titles: list[str]) -> str:
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


def generate_recipe(exclude_titles: list[str] | None = None) -> Recipe:
    """Generate one recipe matching the niche brief, avoiding recent titles."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": _schema()},
        },
        messages=[{"role": "user", "content": _prompt(exclude_titles or [])}],
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
        ingredients=[Ingredient(**i) for i in data["ingredients"]],
        steps=data["steps"],
        macros=Macros(**data["macros"]),
        cost_per_serving=data["cost_per_serving"],
        allergens=data["allergens"],
        series=data["series"],
        image_subject=data["image_subject"],
    )
