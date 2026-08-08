"""Vision sanity check on the generated hero image.

Image models occasionally return something that is technically an image but not
an appetizing plate of the dish requested — a raw ingredient pile, a mangled
composition, or stray text baked into the pixels. Slide 1 is the thumbnail that
decides whether anyone stops scrolling, so it is worth one cheap look before the
post goes anywhere.
"""
from __future__ import annotations

import base64
import json
import os

import anthropic

from ..recipes.schema import Recipe

MODEL = os.environ.get("RECIPE_MODEL", "claude-opus-5")

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_food", "matches_dish", "appetizing", "has_text", "problem"],
    "properties": {
        "is_food": {"type": "boolean", "description": "Is this a photograph of prepared food?"},
        "matches_dish": {"type": "boolean", "description": "Does it plausibly show the named dish?"},
        "appetizing": {
            "type": "boolean",
            "description": "Would this stop a scroll? False for grey, mushy, or unappealing food.",
        },
        "has_text": {
            "type": "boolean",
            "description": "Any rendered words, letters, logos, or watermarks in the image?",
        },
        "problem": {
            "type": "string",
            "description": "One short sentence naming the issue, or empty if the image is fine.",
        },
    },
}


def check_hero(recipe: Recipe, image_bytes: bytes) -> list[str]:
    """Return hold reasons for the hero image. Empty means it passed."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        # A short visual judgement; deep reasoning adds cost without accuracy here.
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(image_bytes).decode(),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"This image is meant to be the hero shot for a recipe called "
                            f"{recipe.title!r} — {recipe.image_subject} "
                            f"Judge it as the thumbnail of a food post."
                        ),
                    },
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        return ["Image sanity check was refused; review the hero image by hand."]

    verdict = json.loads(next(b.text for b in response.content if b.type == "text"))
    problem = verdict.get("problem", "").strip()
    suffix = f" ({problem})" if problem else ""

    reasons = []
    if not verdict["is_food"]:
        reasons.append(f"Hero image does not show food{suffix}.")
    elif not verdict["matches_dish"]:
        reasons.append(f"Hero image does not match the dish{suffix}.")
    elif not verdict["appetizing"]:
        reasons.append(f"Hero image is not appetizing enough to use{suffix}.")
    if verdict["has_text"]:
        reasons.append(f"Hero image has text baked into it{suffix}.")
    return reasons
