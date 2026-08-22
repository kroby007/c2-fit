"""Caption and hashtag composition."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.caption import compose  # noqa: E402
from src.recipes import quality  # noqa: E402
from src.recipes.schema import Post, Recipe  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def good() -> Recipe:
    return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))


def test_caption_carries_the_numbers(good: Recipe) -> None:
    caption = compose.build_caption(good)
    assert "44g protein" in caption
    assert "$2.90" in caption
    assert good.hook in caption
    assert config.brand()["disclaimer"] in caption


def test_allergen_warning_appears(good: Recipe) -> None:
    assert "Contains soy" in compose.build_caption(good)


def test_no_allergen_line_when_clean(good: Recipe) -> None:
    clean = copy.deepcopy(good)
    clean.allergens = []
    assert "Contains" not in compose.build_caption(clean)


def test_hashtags_respect_configured_ceilings(good: Recipe) -> None:
    draw = config.hashtags()["draw"]
    tags = compose.build_hashtags(good)
    assert len(tags) <= draw["max_total"]
    assert len(" ".join(tags)) <= draw["max_chars"]
    assert len(tags) == len(set(tags)), "hashtags must be unique"
    assert all(t.startswith("#") for t in tags)


def test_hashtags_are_deterministic_per_recipe(good: Recipe) -> None:
    # Re-running a stage must not produce a different caption.
    assert compose.build_hashtags(good) == compose.build_hashtags(good)


def test_hashtags_rotate_against_recent_use(good: Recipe) -> None:
    first = compose.build_hashtags(good)
    rotated = compose.build_hashtags(good, recent=first)
    assert rotated != first, "recently used tags should be deprioritised"


def test_hashtags_include_series_specific_tags(good: Recipe) -> None:
    tags = set(compose.build_hashtags(good))
    high_protein_pool = set(config.hashtags()["series"]["high_protein"])
    budget_pool = set(config.hashtags()["series"]["budget"])
    assert tags & (high_protein_pool | budget_pool)


def test_composed_post_passes_the_gate(good: Recipe) -> None:
    # The composer and the gate have to agree, or every post would be held.
    tags = compose.build_hashtags(good)
    caption = compose.build_caption(good)
    assert quality.check(good, caption=caption, hashtags=tags) == []


def test_full_caption_joins_body_and_tags(good: Recipe) -> None:
    post = Post(recipe=good, date="2026-07-26")
    post.caption = compose.build_caption(good)
    post.hashtags = compose.build_hashtags(good)
    assert post.full_caption.startswith(post.caption)
    assert post.full_caption.endswith(post.hashtags[-1])


# --------------------------------------------------------------------------- #
# five hashtags
# --------------------------------------------------------------------------- #

def test_the_set_is_capped_at_five(good: Recipe) -> None:
    from src import config

    recipe = good
    assert config.hashtags()["draw"]["max_total"] == 5
    assert len(compose.build_hashtags(recipe)) == 5


def test_the_cap_is_met_exactly_even_when_buckets_collide(good: Recipe) -> None:
    """At five tags one overlap is a fifth of the set, so the draw tops up.

    A recipe earning no series badge draws nothing from that bucket, and used to
    come out short rather than pulling a replacement from elsewhere.
    """
    recipe = good
    recipe.series = []
    assert len(compose.build_hashtags(recipe)) == 5


def test_the_set_still_rotates_against_recent_posts(good: Recipe) -> None:
    """A tight cap must not collapse into the same five tags every day."""
    recipe = good
    first = compose.build_hashtags(recipe)
    second = compose.build_hashtags(recipe, recent=first)
    assert len(second) == 5
    assert set(first) != set(second), "consecutive posts must not repeat the block"


def test_the_gate_enforces_the_configured_cap_not_just_the_platform_ceiling(
    good: Recipe
) -> None:
    from src.recipes import quality

    reasons = quality.check(good, hashtags=[f"#tag{i}" for i in range(6)])
    assert any("hashtags, limit is 5" in r for r in reasons)
