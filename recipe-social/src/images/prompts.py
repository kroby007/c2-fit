"""Food photography prompt construction.

The style and negative direction come from brand.yaml and are identical on every
post; only the dish description changes. That consistency is what makes a grid of
AI-generated food read as one account.
"""
from __future__ import annotations

from .. import config
from ..recipes.schema import Recipe


def hero_prompt(recipe: Recipe, problem: str = "") -> str:
    """The photography brief for this dish.

    `problem` carries what the vision check disliked about the previous attempt.
    Re-rolling the identical prompt tends to reproduce the same mistake, so the
    correction is stated explicitly and last, where it outranks the rest.
    """
    photo = config.brand()["photography"]
    subject = recipe.image_subject.strip() or recipe.title
    parts = [photo["style"], f"The dish: {subject}", photo["negative"]]
    if problem:
        parts.append(
            f"A previous attempt was rejected: {problem} Fix that specifically. "
            f"The main ingredient is {recipe.protein.replace('_', ' ') or recipe.title} "
            f"and it must be clearly recognisable as such."
        )
    return "\n\n".join(part.strip() for part in parts)


def aspect_ratio() -> str:
    return config.brand()["photography"]["aspect_ratio"]
