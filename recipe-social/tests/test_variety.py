"""Why the feed stops being all one appliance.

The first three posts were all skillets — 'Chicken, Black Bean & Rice Skillet',
'Chipotle Chicken Burrito Bowl Skillet', 'Chipotle Chicken & Black Bean Skillet'
— and nothing caught it. Two independent causes, both covered here:

1. The history file was only ever written by the publish stage, so running in
   manual mode left it permanently empty. Every dedup mechanism reads that file,
   so every one of them was inert: the generator saw no recent titles, the gate
   had nothing to compare against, hashtags never rotated.

2. Nothing rotated the cooking method. niche.yaml called the list "rotated", but
   the model was free to pick the same one forever, and it did.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.recipes import generate as gen  # noqa: E402
from src.recipes.quality import is_duplicate  # noqa: E402
from src.recipes.schema import Macros, Recipe  # noqa: E402
from src.state import queue  # noqa: E402

# The three titles that actually went out, in order.
SHIPPED = [
    "Chicken, Black Bean & Rice Skillet",
    "Chipotle Chicken Burrito Bowl Skillet",
    "Chipotle Chicken & Black Bean Skillet",
]


@pytest.fixture
def history(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    path = tmp_path / "history.json"
    monkeypatch.setattr(queue, "HISTORY_PATH", path)
    return path


def _recipe(title: str, method: str = "skillet", protein: str = "chicken") -> Recipe:
    return Recipe(
        title=title, hook="x", method=method, protein=protein, servings=4,
        prep_minutes=5, cook_minutes=15, ingredients=[], steps=[],
        macros=Macros(500, 40, 50, 15), cost_per_serving=2.5,
    )


# --------------------------------------------------------------------------- #
# cause 1: the history was never written
# --------------------------------------------------------------------------- #

def test_the_gate_would_have_caught_the_third_skillet(history: pathlib.Path) -> None:
    """The duplicate check was never broken — it was fed an empty list.

    This is the whole bug in one assertion: the machinery worked, and the third
    post still went out, because nothing had recorded the first two.
    """
    third = _recipe(SHIPPED[2])
    assert is_duplicate(third, SHIPPED[:2]) == SHIPPED[0]
    assert is_duplicate(third, []) is None


def test_recording_a_post_makes_it_visible_to_the_next_run(history: pathlib.Path) -> None:
    queue.record("2026-08-08", "s", SHIPPED[0], ["#foodtok"], method="skillet")

    assert queue.recent_titles() == [SHIPPED[0]]
    assert queue.recent_methods() == ["skillet"]
    assert queue.recent_hashtags() == ["#foodtok"]
    assert queue.already_posted_today("2026-08-08")


def test_history_entries_written_before_methods_existed_are_skipped(
    history: pathlib.Path
) -> None:
    """Old entries have no 'method' key, and must not become an empty exclusion."""
    history.write_text(json.dumps([
        {"date": "2026-08-08", "slug": "a", "title": "A", "hashtags": []},
        {"date": "2026-08-09", "slug": "b", "title": "B", "hashtags": [],
         "method": "air_fryer"},
    ]))
    assert queue.recent_methods() == ["air_fryer"]
    assert "" not in gen.available_methods(queue.recent_methods())


# --------------------------------------------------------------------------- #
# cause 2: nothing rotated the method
# --------------------------------------------------------------------------- #

def test_recent_methods_are_removed_from_the_schema_enum() -> None:
    """A prompt can be ignored; an enum the model never sees cannot be picked."""
    all_methods = list(config.niche()["methods"])
    assert "skillet" in all_methods, "fixture assumption"

    offered = gen.available_methods(["skillet"])
    assert "skillet" not in offered
    assert set(offered) == set(all_methods) - {"skillet"}

    schema = gen._schema(["skillet"])
    assert "skillet" not in schema["properties"]["method"]["enum"]


def test_the_backfilled_history_rules_skillet_out_of_the_next_run(
    history: pathlib.Path
) -> None:
    """End to end on the real data: three skillets in, no skillet possible out."""
    for i, title in enumerate(SHIPPED):
        queue.record(f"2026-08-0{i + 8}", "s", title, [], method="skillet")

    schema = gen._schema(queue.recent_methods())
    assert "skillet" not in schema["properties"]["method"]["enum"]


def test_exclusion_yields_rather_than_emptying_the_enum() -> None:
    """A structured output with no legal value is a failed run, not a varied one.

    niche.yaml is user-editable, so a short methods list plus a wide exclusion
    window has to degrade to a wider choice instead of an empty enum.
    """
    every = list(config.niche()["methods"])
    assert gen.available_methods(every) == every
    assert len(gen.available_methods(every[:-1])) >= 2


# --------------------------------------------------------------------------- #
# the part that is actually visible
# --------------------------------------------------------------------------- #

def test_a_rotated_method_cannot_keep_the_old_name_in_the_title() -> None:
    """method is never rendered — the title is the only thing anyone reads.

    So rotating the method to one_pot achieves nothing if the dish is still
    called a Skillet, and nothing else in the pipeline prevents that.
    """
    from src.recipes.quality import mislabelled_method

    assert mislabelled_method(_recipe("Chicken & Bean Skillet", "one_pot")) == "skillet"
    assert mislabelled_method(_recipe("Air Fryer Chicken", "sheet_pan")) == "air_fryer"
    assert mislabelled_method(_recipe("Sheet-Pan Salmon", "skillet")) == "sheet_pan"

    # A title naming the method it actually uses is the normal, good case.
    assert mislabelled_method(_recipe("Chicken & Bean Skillet", "skillet")) is None
    assert mislabelled_method(_recipe("Air Fryer Chicken", "air_fryer")) is None


def test_the_gate_holds_a_title_that_contradicts_its_method() -> None:
    from src.recipes import quality

    reasons = quality.check(_recipe("Chicken & Bean Skillet", "one_pot"))
    assert any("Title says skillet" in r and "recipe is one pot" in r for r in reasons)

    honest = quality.check(_recipe("Chicken & Bean Skillet", "skillet"))
    assert not any("Title says" in r for r in honest)


@pytest.mark.parametrize(
    "title", ["Baked Chicken Thighs", "Pan-Seared Salmon Bowls", "Crispy Potato Hash"]
)
def test_ordinary_cooking_words_are_not_treated_as_method_claims(title: str) -> None:
    """'baked' and 'pan' appear in honest titles; holding those would be worse."""
    from src.recipes.quality import mislabelled_method

    assert mislabelled_method(_recipe(title, "sheet_pan")) is None


def test_the_prompt_explains_the_missing_option() -> None:
    """Without this the model writes a skillet recipe and calls it one_pot."""
    prompt = gen._prompt([], ["skillet", "sheet_pan"])
    assert "skillet, sheet_pan" in prompt
    assert "not the same technique renamed" in prompt

    assert "Pick a genuinely different" not in gen._prompt([], [])


# --------------------------------------------------------------------------- #
# the protein axis
#
# The stronger of the two. Chicken cooked four different ways is still chicken
# four days running, which is how the feed actually started out — every one of
# the three shipped posts was chicken and black beans.
# --------------------------------------------------------------------------- #

def test_recent_proteins_are_removed_from_the_schema_enum() -> None:
    every = list(config.niche()["proteins"])
    assert "chicken" in every, "fixture assumption"

    offered = gen.available_proteins(["chicken"])
    assert "chicken" not in offered
    assert gen._schema(None, ["chicken"])["properties"]["protein"]["enum"] == offered


def test_the_protein_rotates_further_back_than_the_method() -> None:
    """One pan repeating is a smaller tell than one protein repeating."""
    assert queue.PROTEIN_WINDOW > queue.METHOD_WINDOW


def test_three_chicken_posts_rule_chicken_out_of_the_next_one(
    history: pathlib.Path
) -> None:
    """End to end on the real data that prompted this."""
    for i, title in enumerate(SHIPPED):
        queue.record(f"2026-08-0{i + 8}", "s", title, [],
                     method="skillet", protein="chicken")

    schema = gen._schema(queue.recent_methods(), queue.recent_proteins())
    assert "chicken" not in schema["properties"]["protein"]["enum"]
    assert "skillet" not in schema["properties"]["method"]["enum"]


def test_the_protein_exclusion_also_yields_rather_than_emptying() -> None:
    every = list(config.niche()["proteins"])
    assert gen.available_proteins(every) == every


def test_the_prompt_names_the_excluded_proteins() -> None:
    prompt = gen._prompt([], None, ["chicken", "salmon"])
    assert "chicken, salmon" in prompt
    # Swapping the protein while keeping the rest is the obvious way to comply
    # with the letter of the instruction and still post the same dinner.
    assert "same beans and the same sauce under a new protein" in prompt


# --------------------------------------------------------------------------- #
# never repeat
# --------------------------------------------------------------------------- #

def test_a_slug_that_has_run_before_is_refused_outright(history: pathlib.Path) -> None:
    """Unbounded, unlike the similarity window: an exact repeat is never fine."""
    from src.recipes.quality import repeat_reason

    queue.record("2020-01-01", "chicken-black-bean-rice-skillet", SHIPPED[0], [])

    again = _recipe(SHIPPED[0])
    assert again.slug == "chicken-black-bean-rice-skillet", "slug derives from title"
    assert "has been posted before" in repeat_reason(again, [], queue.all_slugs())

    # Nothing in common with it, years later, is still fine.
    assert repeat_reason(_recipe("Sheet-Pan Salmon"), [], queue.all_slugs()) is None


def test_the_gate_still_catches_a_repeat_the_generator_let_through() -> None:
    """repeat_reason is one definition used in both places, not two that drift."""
    from src.recipes import quality

    reasons = quality.check(
        _recipe(SHIPPED[0]), past_slugs={"chicken-black-bean-rice-skillet"}
    )
    assert any("has been posted before" in r for r in reasons)
