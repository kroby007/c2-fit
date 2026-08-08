"""Post manifest round-tripping and slide rendering."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.caption import compose  # noqa: E402
from src.recipes.schema import Post, Recipe, slugify  # noqa: E402
from src.render import slides as slides_mod  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def good() -> Recipe:
    return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))


def test_slugify() -> None:
    assert slugify("Chili Crisp Chicken Bowls!") == "chili-crisp-chicken-bowls"
    assert slugify("") == "recipe"


def test_total_minutes(good: Recipe) -> None:
    assert good.total_minutes == good.prep_minutes + good.cook_minutes == 22


def test_post_round_trips_through_json(tmp_path: pathlib.Path, good: Recipe) -> None:
    post = Post(recipe=good, date="2026-07-26")
    post.caption = compose.build_caption(good)
    post.hashtags = compose.build_hashtags(good)
    post.slide_urls = ["https://example.com/slide1.png"]

    path = post.save(tmp_path / "post.json")
    restored = Post.load(path)

    assert restored.recipe.title == good.title
    assert restored.recipe.macros.protein_g == good.macros.protein_g
    assert restored.recipe.ingredients[0].item == good.ingredients[0].item
    assert restored.full_caption == post.full_caption
    assert restored.slide_urls == post.slide_urls


def test_title_size_shrinks_for_long_titles() -> None:
    sizes = [slides_mod._title_size("Egg Fried Rice"), slides_mod._title_size("Sheet Pan Harissa Chicken and Chickpeas")]
    assert sizes[0] > sizes[1], "a long title must get a smaller headline"


def test_list_metrics_shrink_with_row_count() -> None:
    small, _ = slides_mod._list_metrics(4, 30)
    large, _ = slides_mod._list_metrics(11, 30)
    assert small > large


def _chrome_available() -> bool:
    try:
        config.chrome_binary()
        return True
    except RuntimeError:
        return False


@pytest.mark.skipif(not _chrome_available(), reason="No Chromium/Chrome available")
def test_slides_render_at_canvas_size(tmp_path: pathlib.Path, good: Recipe) -> None:
    hero = _placeholder_hero(tmp_path)
    paths = slides_mod.render_slides(good, hero, tmp_path / "slides")

    canvas = config.brand()["canvas"]
    assert len(paths) == 3
    for path in paths:
        assert slides_mod.png_dimensions(path) == (canvas["width"], canvas["height"])
        # A blank render would compress to almost nothing; real slides do not.
        assert path.stat().st_size > 20_000


@pytest.mark.skipif(not _chrome_available(), reason="No Chromium/Chrome available")
def test_long_content_still_renders(tmp_path: pathlib.Path, good: Recipe) -> None:
    """Overflow is the most likely visual bug, so push every list to its limit."""
    from src.recipes.schema import Ingredient

    good.title = "Sheet Pan Harissa Chicken With Chickpeas and Lemon"
    good.ingredients = [
        Ingredient(item=f"a fairly long ingredient name number {n}", qty="2 tbsp (30g)")
        for n in range(10)
    ]
    good.steps = [
        f"Step {n}: a deliberately long instruction that runs to about eighteen words "
        f"so it wraps across two full lines." for n in range(8)
    ]
    paths = slides_mod.render_slides(good, _placeholder_hero(tmp_path), tmp_path / "long")
    canvas = config.brand()["canvas"]
    for path in paths:
        assert slides_mod.png_dimensions(path) == (canvas["width"], canvas["height"])


def _placeholder_hero(tmp_path: pathlib.Path) -> bytes:
    """Render a stand-in hero with Chromium so the test needs no image API."""
    html_path = tmp_path / "hero.html"
    png_path = tmp_path / "hero.png"
    html_path.write_text(
        "<!doctype html><html><head><style>html,body{margin:0;width:1080px;"
        "height:1440px;overflow:hidden}body{background:linear-gradient("
        "150deg,#C8541F 0%,#4E6B22 60%,#14110F 100%)}</style></head><body></body></html>"
    )
    subprocess.run(
        [
            config.chrome_binary(), "--headless=new", "--no-sandbox", "--disable-gpu",
            "--hide-scrollbars", "--window-size=1080,1440",
            f"--screenshot={png_path}", f"file://{html_path}",
        ],
        capture_output=True, timeout=120,
    )
    return png_path.read_bytes()
