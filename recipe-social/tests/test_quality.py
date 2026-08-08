"""Quality gate: the checks that stop a bad recipe reaching a platform."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.recipes import quality  # noqa: E402
from src.recipes.schema import Recipe  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> Recipe:
    return Recipe.from_dict(json.loads((FIXTURES / name).read_text()))


@pytest.fixture
def good() -> Recipe:
    return load("recipe_good.json")


def test_good_recipe_passes(good: Recipe) -> None:
    assert quality.check(good) == []


def test_macro_arithmetic_is_checked(good: Recipe) -> None:
    # 44p/62c/19f = 176 + 248 + 171 = 595 kcal, close to the stated 612.
    assert good.macros.computed_calories() == 595


def test_invented_macros_are_held() -> None:
    bad = load("recipe_bad_macros.json")
    reasons = quality.check(bad)
    assert any("do not add up" in r for r in reasons), reasons


def test_unearned_badges_are_dropped() -> None:
    bad = load("recipe_bad_macros.json")
    quality.check(bad)
    # Claimed all four; it is one_pot (not air_fryer) and 15 minutes total,
    # so only the badges it genuinely earns survive.
    assert "air_fryer" not in bad.series
    assert set(bad.series) == {"high_protein", "budget", "fifteen_min"}


def test_series_rules_use_real_numbers(good: Recipe) -> None:
    assert quality.earned_series(good) == ["high_protein", "budget"]

    lean = copy.deepcopy(good)
    lean.macros.protein_g = 22
    lean.macros.calories = lean.macros.computed_calories()
    assert "high_protein" not in quality.earned_series(lean)


def test_expensive_recipe_loses_budget_badge(good: Recipe) -> None:
    pricey = copy.deepcopy(good)
    pricey.cost_per_serving = 3.80
    assert "budget" not in quality.earned_series(pricey)


def test_air_fryer_badge_follows_method(good: Recipe) -> None:
    fried = copy.deepcopy(good)
    fried.method = "air_fryer"
    assert "air_fryer" in quality.earned_series(fried)


def test_undeclared_allergen_is_held(good: Recipe) -> None:
    sneaky = copy.deepcopy(good)
    sneaky.allergens = []  # soy sauce is right there in the ingredients
    reasons = quality.check(sneaky)
    assert any("soy" in r for r in reasons), reasons


def test_too_many_ingredients_is_held(good: Recipe) -> None:
    bloated = copy.deepcopy(good)
    bloated.ingredients = bloated.ingredients * 3
    assert any("ingredients, limit" in r for r in quality.check(bloated))


def test_over_time_budget_is_held(good: Recipe) -> None:
    slow = copy.deepcopy(good)
    slow.cook_minutes = 90
    assert any("minutes total" in r for r in quality.check(slow))


def test_duplicate_detection(good: Recipe) -> None:
    assert quality.is_duplicate(good, ["Chili Crisp Chicken Bowls"]) is not None
    assert quality.is_duplicate(good, ["Lemon Garlic Salmon Traybake"]) is None


def test_duplicate_ignores_filler_words(good: Recipe) -> None:
    # Shares only "easy"/"quick"-style filler, which carries no signal.
    assert quality.is_duplicate(good, ["Easy Quick Beef and Rice"]) is None


def test_caption_length_is_capped(good: Recipe) -> None:
    reasons = quality.check(good, caption="x" * 2300)
    assert any("Caption is" in r for r in reasons)


def test_hashtag_count_is_capped(good: Recipe) -> None:
    reasons = quality.check(good, hashtags=[f"#tag{i}" for i in range(40)])
    assert any("hashtags, limit" in r for r in reasons)


def test_recipe_with_no_badges_is_held(good: Recipe) -> None:
    plain = copy.deepcopy(good)
    plain.macros.protein_g = 12
    plain.macros.calories = plain.macros.computed_calories()
    plain.cost_per_serving = 3.90
    plain.cook_minutes = 20
    reasons = quality.check(plain)
    assert any("series badge" in r for r in reasons), reasons
