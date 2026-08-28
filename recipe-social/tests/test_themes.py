"""The look rotates, and every theme in the config is actually usable.

Slides used to come out the same orange every day. The accent was the recipe's
first earned series colour, which sounds varied and is not: high_protein is
first in brand.yaml and nearly every recipe earns it. The photo surface was a
fixed phrase in the prompt, so every dish was shot on the same charcoal stone.

Both now rotate against history. These tests cover the rotation and, just as
importantly, the colours themselves — a theme is hand-written YAML, and a typo
in a hex value is invisible until it renders.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.recipes import generate as gen  # noqa: E402
from src.recipes.schema import Macros, Post, Recipe  # noqa: E402
from src.render import slides  # noqa: E402
from src.state import queue  # noqa: E402

HEX = re.compile(r"#[0-9A-Fa-f]{6}$")
SWATCHES = ("accent", "bg", "surface", "surface_alt", "text", "text_muted", "hairline")


@pytest.fixture
def history(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    path = tmp_path / "history.json"
    monkeypatch.setattr(queue, "HISTORY_PATH", path)
    return path


def _recipe() -> Recipe:
    return Recipe(
        title="Korean Gochujang Pork Bites", hook="34g protein for $2.12",
        method="air_fryer", protein="pork", cuisine="korean", servings=4,
        prep_minutes=7, cook_minutes=15, ingredients=[], steps=[],
        macros=Macros(230, 34, 10, 6), cost_per_serving=2.12,
        series=["high_protein", "budget"],
    )


def _luminance(hex_colour: str) -> float:
    """WCAG relative luminance."""
    channels = []
    for i in (1, 3, 5):
        c = int(hex_colour[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)))
    return (lb + 0.05) / (la + 0.05)


THEMES = sorted(config.brand()["themes"])


# --------------------------------------------------------------------------- #
# the colours themselves
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", THEMES)
def test_every_theme_is_complete_and_well_formed(name: str) -> None:
    """Two of these were written as 8-digit values by hand and rendered as
    nothing at all. YAML will not catch that; this does."""
    theme = config.brand()["themes"][name]
    assert set(theme) == set(SWATCHES), f"{name} is missing or has extra keys"
    for key, value in theme.items():
        assert HEX.match(str(value)), f"{name}.{key} is not a 6-digit hex colour: {value!r}"


@pytest.mark.parametrize("name", THEMES)
def test_every_theme_stays_readable(name: str) -> None:
    """Vibrancy is the point, but not at the cost of a slide nobody can read."""
    theme = config.brand()["themes"][name]
    assert _contrast(theme["text"], theme["bg"]) >= 12, "body text must be plainly legible"
    assert _contrast(theme["accent"], theme["bg"]) >= 4.5, "the accent carries real text"
    assert _contrast(theme["text_muted"], theme["bg"]) >= 4.5


@pytest.mark.parametrize("name", THEMES)
def test_every_theme_keeps_the_background_dark(name: str) -> None:
    """The food is the colour on the slide; a bright panel would fight it, and
    the photo's own fade assumes it is fading into something near-black."""
    assert _luminance(config.brand()["themes"][name]["bg"]) < 0.02


def test_the_accents_are_actually_different_from_each_other() -> None:
    accents = [config.brand()["themes"][n]["accent"] for n in THEMES]
    assert len(set(accents)) == len(accents)
    for i, a in enumerate(accents):
        for b in accents[i + 1:]:
            assert _contrast(a, b) > 1.15 or a != b, "two themes read as the same colour"


# --------------------------------------------------------------------------- #
# the accent no longer comes from the badge
# --------------------------------------------------------------------------- #

def test_the_accent_is_the_theme_not_the_first_series_badge() -> None:
    """The original bug. high_protein is first in the config and nearly every
    recipe earns it, so deriving the accent from it produced one colour."""
    series_colour = config.brand()["series"]["high_protein"]["color"]
    off_brand = [n for n in THEMES if config.brand()["themes"][n]["accent"] != series_colour]
    assert off_brand, "fixture assumption: some theme differs from the badge colour"
    for name in off_brand:
        assert slides.palette_for(name)["accent"] != series_colour


def test_an_unknown_theme_falls_back_rather_than_failing() -> None:
    """Posts written before themes existed carry no theme name."""
    for name in ("", "no-such-theme"):
        palette = slides.palette_for(name)
        assert set(SWATCHES) <= set(palette)
        assert HEX.match(palette["accent"])


# --------------------------------------------------------------------------- #
# rotation
# --------------------------------------------------------------------------- #

def test_recent_themes_and_surfaces_are_withheld(history: pathlib.Path) -> None:
    queue.record("2026-08-27", "a", "A", [], theme="ember",
                 surface="a warm charcoal stone surface")
    queue.record("2026-08-28", "b", "B", [], theme="lime",
                 surface="a dark walnut wood board with visible grain")

    assert queue.recent_themes() == ["ember", "lime"]
    offered = gen.available_themes(queue.recent_themes())
    assert "ember" not in offered and "lime" not in offered

    surfaces = gen.available_surfaces(queue.recent_surfaces())
    assert "a warm charcoal stone surface" not in surfaces


def test_rotation_yields_rather_than_running_out() -> None:
    every = list(config.brand()["themes"])
    assert gen.available_themes(every) == every
    all_surfaces = list(config.brand()["photography"]["surfaces"])
    assert gen.available_surfaces(all_surfaces) == all_surfaces


def test_the_surface_reaches_the_photo_prompt() -> None:
    from src.images import prompts

    prompt = prompts.hero_prompt(
        _recipe(), surface="a dark oxidised copper surface with muted patina",
        plate="a black cast-iron skillet used as the serving vessel")
    assert "dark oxidised copper" in prompt
    assert "cast-iron skillet" in prompt
    # The old fixed phrase must be gone, or every photo still gets the same table.
    assert prompt.count("charcoal stone") == 0


def test_the_look_survives_a_round_trip_through_post_json(tmp_path: pathlib.Path) -> None:
    """render reads it back from disk, and stage records it from there."""
    post = Post(recipe=_recipe(), date="2026-08-28")
    post.theme, post.surface, post.plate = "jade", "a weathered dark terracotta tile", "a rustic speckled ceramic plate in deep grey"
    path = post.save(tmp_path / "post.json")

    loaded = Post.load(path)
    assert (loaded.theme, loaded.surface, loaded.plate) == (post.theme, post.surface, post.plate)
