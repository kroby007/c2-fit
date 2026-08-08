"""Food photography prompt construction.

The style and negative direction come from brand.yaml and are identical on every
post; only the dish description changes. That consistency is what makes a grid of
AI-generated food read as one account.
"""
from __future__ import annotations

from .. import config
from ..recipes.schema import Recipe


def hero_prompt(recipe: Recipe) -> str:
    photo = config.brand()["photography"]
    subject = recipe.image_subject.strip() or recipe.title
    return "\n\n".join(
        part.strip()
        for part in (photo["style"], f"The dish: {subject}", photo["negative"])
    )


def aspect_ratio() -> str:
    return config.brand()["photography"]["aspect_ratio"]
