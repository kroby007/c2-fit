"""End-to-end pipeline orchestration.

Only the two calls that need credentials are stubbed — recipe generation and
image generation. Everything else runs for real: caption composition, Chromium
rendering, the quality gate, the hold path, and staging to public URLs. This is
the `run --no-publish` path a first-time user executes.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import cli, config  # noqa: E402
from src.images.provider import ImageProvider  # noqa: E402
from src.recipes.schema import Post, Recipe  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
DATE = "2026-07-26"


def _chrome_available() -> bool:
    try:
        config.chrome_binary()
        return True
    except RuntimeError:
        return False


pytestmark = pytest.mark.skipif(not _chrome_available(), reason="No Chromium/Chrome available")


class _StubImageProvider(ImageProvider):
    """Renders a gradient with Chromium so no image API key is needed."""

    def generate(self, prompt: str, aspect_ratio: str) -> bytes:
        assert "The dish:" in prompt, "prompt must carry the dish description"
        assert aspect_ratio == config.brand()["photography"]["aspect_ratio"]
        tmp = pathlib.Path(config.OUT_DIR) / "_stub_hero"
        tmp.mkdir(parents=True, exist_ok=True)
        html_path, png_path = tmp / "h.html", tmp / "h.png"
        html_path.write_text(
            "<!doctype html><html><head><style>html,body{margin:0;width:1080px;"
            "height:1440px;overflow:hidden}body{background:linear-gradient("
            "150deg,#C8541F,#4E6B22 60%,#14110F)}</style></head><body></body></html>"
        )
        subprocess.run(
            [config.chrome_binary(), "--headless=new", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--window-size=1080,1440",
             f"--screenshot={png_path}", f"file://{html_path}"],
            capture_output=True, timeout=120,
        )
        return png_path.read_bytes()


@pytest.fixture
def wired(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect all writable paths into tmp and stub the two credentialed calls."""
    monkeypatch.setattr(config, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "docs" / "media")
    monkeypatch.setenv("PAGES_BASE_URL", "https://example.github.io/c2-fit")

    from src.state import queue

    monkeypatch.setattr(queue, "HISTORY_PATH", tmp_path / "state" / "history.json")

    def fake_generate(exclude_titles=None):
        return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))

    monkeypatch.setattr("src.recipes.generate.generate_recipe", fake_generate)
    monkeypatch.setattr("src.images.provider.get_provider", lambda name=None: _StubImageProvider())
    return tmp_path


def _run(*argv: str) -> None:
    cli.main(["--date", DATE, *argv])


def test_run_no_publish_produces_postable_assets(wired: pathlib.Path) -> None:
    _run("run", "--no-publish", "--no-check-image")

    post_dir = config.OUT_DIR / DATE
    for name in ("slide1.png", "slide2.png", "slide3.png", "hero.png", "caption.txt", "post.json"):
        assert (post_dir / name).exists(), f"{name} missing"

    caption = (post_dir / "caption.txt").read_text()
    assert "44g protein" in caption
    assert "#" in caption, "hashtags should be appended to the caption file"

    post = Post.load(post_dir / "post.json")
    assert not post.held
    assert post.recipe.series == ["high_protein", "budget"]
    assert len(post.slide_paths) == 3


def test_stage_produces_verified_prefix_urls(wired: pathlib.Path) -> None:
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert len(post.slide_urls) == 3
    for i, url in enumerate(post.slide_urls, 1):
        assert url == f"https://example.github.io/c2-fit/media/{DATE}/slide{i}.png"
        # The file has to actually be in the published directory, not just named.
        assert (config.MEDIA_DIR / DATE / f"slide{i}.png").exists()


def test_bad_recipe_is_held_and_never_published(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def bad_generate(exclude_titles=None):
        return Recipe.from_dict(json.loads((FIXTURES / "recipe_bad_macros.json").read_text()))

    monkeypatch.setattr("src.recipes.generate.generate_recipe", bad_generate)
    _run("run", "--no-publish", "--no-check-image")

    assert not (config.OUT_DIR / DATE).exists(), "held post must be moved out of the live folder"
    held_dir = config.OUT_DIR / "held" / DATE
    assert held_dir.exists()

    post = Post.load(held_dir / "post.json")
    assert post.held
    assert any("do not add up" in r for r in post.hold_reasons)
    assert "POST HELD" in capsys.readouterr().out


def test_second_run_is_blocked_by_the_already_posted_guard(
    wired: pathlib.Path, capsys: pytest.CaptureFixture
) -> None:
    from src.state import queue

    queue.record(DATE, "chili-crisp-chicken-bowls", "Chili Crisp Chicken Bowls", ["#foodtok"])
    _run("run", "--no-publish", "--no-check-image")
    assert "Already posted" in capsys.readouterr().out


def test_dry_run_publish_sends_nothing_and_records_nothing(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TIKTOK_POST_MODE", "MEDIA_UPLOAD")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run", "--platforms", "tiktok")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.published["tiktok"]["ok"]
    assert "DRY RUN" in post.published["tiktok"]["message"]

    from src.state import queue

    assert queue.recent_titles() == [], "a dry run must not enter the posting history"


def test_publish_defaults_to_tiktok_only(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta must not be touched by a default run while TikTok is being proven out."""
    monkeypatch.setenv("TIKTOK_POST_MODE", "MEDIA_UPLOAD")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run")  # no --platforms

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert set(post.published) == {"tiktok"}
    assert cli.DEFAULT_PLATFORMS == ("tiktok",)


def test_meta_publishers_are_dormant_not_broken(
    wired: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming them explicitly still works, so turning them on later is a flag."""
    monkeypatch.setenv("IG_USER_ID", "fake")
    monkeypatch.setenv("META_ACCESS_TOKEN", "fake")
    monkeypatch.setenv("FB_PAGE_ID", "fake")
    _run("run", "--no-publish", "--no-check-image")
    _run("stage")
    _run("publish", "--dry-run", "--platforms", "instagram,facebook")

    post = Post.load(config.OUT_DIR / DATE / "post.json")
    assert post.published["instagram"]["ok"]
    assert post.published["facebook"]["ok"]
    assert "tiktok" not in post.published


def test_slides_carry_the_configured_handle(wired: pathlib.Path) -> None:
    """The handle is burned into every slide, so a stale brand config is silent."""
    from src.render import slides as slides_mod

    handle = config.brand()["account"]["handle"]
    assert handle == "@c2_fit_"

    recipe = Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))
    css = slides_mod._base_css(recipe, 94, 33, 16)
    markup = slides_mod._fill(
        (slides_mod.TEMPLATE_DIR / "slide1.html").read_text(),
        {"BASE_CSS": css, "HERO": "", "HANDLE": handle, "BADGES": "",
         "TITLE": recipe.title, "HOOK": recipe.hook},
    )
    assert handle in markup
