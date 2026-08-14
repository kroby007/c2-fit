"""The Recipe model and the Post manifest that carries work between stages.

Every stage reads a manifest, adds to it, and writes it back, so any stage can
be re-run standalone against a previous stage's output.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "recipe"


@dataclass
class Ingredient:
    item: str
    qty: str

    def display(self) -> str:
        return f"{self.qty} {self.item}".strip()


@dataclass
class Macros:
    calories: int
    protein_g: int
    carbs_g: int
    fat_g: int

    def computed_calories(self) -> int:
        """Calories implied by the macros using 4/4/9.

        The quality gate compares this against the stated calorie figure; a
        large gap means the model invented numbers that do not describe a real
        plate of food.
        """
        return round(self.protein_g * 4 + self.carbs_g * 4 + self.fat_g * 9)


@dataclass
class Recipe:
    title: str
    hook: str
    method: str
    servings: int
    prep_minutes: int
    cook_minutes: int
    ingredients: list[Ingredient]
    steps: list[str]
    macros: Macros
    cost_per_serving: float
    # The main protein. Rotated like method, and the stronger variety signal of
    # the two — defaults to empty so recipes saved before it existed still load.
    protein: str = ""
    # Flavour direction. The axis that stops two different proteins arriving as
    # the same dinner; empty default so older saved recipes still load.
    cuisine: str = ""
    allergens: list[str] = field(default_factory=list)
    series: list[str] = field(default_factory=list)
    # Short plated-dish description used to build the food photography prompt.
    image_subject: str = ""
    slug: str = ""

    def __post_init__(self) -> None:
        # Always derived, never trusted from the input. The slug is what the
        # never-repeat check keys on, and the README tells you to fix a long
        # title by editing post.json — which would otherwise leave the old slug
        # behind, silently identifying the recipe as one it no longer is.
        self.slug = slugify(self.title)

    @property
    def total_minutes(self) -> int:
        return self.prep_minutes + self.cook_minutes

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipe":
        data = dict(data)
        data["ingredients"] = [
            Ingredient(**i) if isinstance(i, dict) else i for i in data.get("ingredients", [])
        ]
        macros = data.get("macros")
        data["macros"] = Macros(**macros) if isinstance(macros, dict) else macros
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Post:
    """One post moving through generate -> render -> stage -> gate -> publish."""

    recipe: Recipe
    date: str
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    # Local PNG paths, in carousel order.
    slide_paths: list[str] = field(default_factory=list)
    # Public HTTPS URLs after staging — what TikTok and Meta actually fetch.
    slide_urls: list[str] = field(default_factory=list)
    hero_image_path: str = ""
    held: bool = False
    hold_reasons: list[str] = field(default_factory=list)
    # Platform -> result detail, filled in by the publishers.
    published: dict[str, Any] = field(default_factory=dict)

    @property
    def full_caption(self) -> str:
        """Caption body plus the hashtag block, as sent to the platforms."""
        tags = " ".join(self.hashtags)
        return f"{self.caption}\n\n{tags}".strip() if tags else self.caption

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["recipe"] = self.recipe.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Post":
        data = dict(data)
        data["recipe"] = Recipe.from_dict(data["recipe"])
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: pathlib.Path) -> pathlib.Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        return path

    @classmethod
    def load(cls, path: pathlib.Path) -> "Post":
        return cls.from_dict(json.loads(pathlib.Path(path).read_text()))
